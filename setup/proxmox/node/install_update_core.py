#!/usr/bin/env python3
"""Install the repo's update_core.sh on a Proxmox node, keeping the node's fleet config.

Why this exists
---------------
The deploy runs the copy in the node's home directory, not the repo file: the deploy env
config says ``{"node1-vpt": {"ssh": "proxmox", "cmd": "bash update_core.sh"}}``, and that
relative path resolves to ``~/update_core.sh`` on the node. So a change to
``setup/proxmox/node/update_core.sh`` in the repo reaches the fleet ONLY after it has been
installed on every node that runs it. A fix that lives in the repo alone changes nothing
on the hosts - that is exactly how the "the deploy pushed new host code but did not
restart vpt-host" bug (BUG-0728, 2026-10-20) survived its own deploy.

The two copies drift on purpose: the repo file is the template (default targets for a
fresh node), the node's copy carries that node's own fleet targets. A blind ``scp``
overwrites the node's targets with the template's, and the node then deploys to the wrong
VMs - silently, and worse than the drift it was meant to fix.

This installer merges instead of overwriting: the repo's script with the node's config
values, then backs the old copy up and syntax-checks the result before it goes live.

The stale-checkout guard
------------------------
The script this installer reads is the one in the checkout it runs from. A checkout that is
behind origin/main holds the OLD script, and installing from it pushes that old script onto
the node - undoing the fixes main already carries, on the very node the fixes are for. That
is the same failure this installer exists to prevent, coming from the other side: the node
would then be behind the repo while the installer reports "installed" (2026-10-25: a checkout
113 commits behind would have reinstalled the script that was missing the mirror fix and the
stale-service report).

So the installer compares the local copy with origin/main's copy of the same file. A local
copy that is behind origin/main's (the checkout is an ancestor of origin/main and the file
was changed upstream since) is refused on --install, and --check reports the node against
origin/main rather than against the stale local copy. Work in progress - a branch whose own
changes to the script are not merged yet - is not stale and installs as it is.

Usage
-----
  install_update_core.py --node proxmox --check          # report the drift, change nothing
  install_update_core.py --node proxmox --install        # install (backup + bash -n)
  install_update_core.py --node proxmox --install --dry-run
  install_update_core.py --print-merged <node-copy>      # merge locally, print the result

Exit codes: 0 ok / in sync, 1 drift (with --check), a stale checkout (with --install) or a
failed install, 2 usage error.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
DEFAULT_REPO_SCRIPT = f"{HERE}/update_core.sh"
DEFAULT_REMOTE_PATH = "~/update_core.sh"

# A single-line config assignment, e.g. SERVER_IP="192.168.0.103" or HOST_IPS="a,b"  # note
ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=")

# The fleet targets the repo's script reads from the environment (its config block). Their node
# value has to be merged as a VALUE, not as a whole line: the repo's line is env-driven
# ('HOST_IPS="${HOST_IPS:-a,b}"') while the node's line is plain ('HOST_IPS="a,b"'), and copying
# the node's line over the repo's would drop the env override on exactly the keys that matter.
# The merged line keeps the repo's shape with the node's fleet as the default:
# 'HOST_IPS="${HOST_IPS:-a,b}"' - the node's fleet wins, the environment can still override it.
# Every other key keeps the old line-merge (the node's whole line wins).
FLEET_KEYS = ("SERVER_IP", "FRONTEND_IP", "HOST_IPS", "RUNNER_IPS", "HOST_WINDOWS_IPS", "DOCKER_IPS")

# An env-driven config line: KEY="${KEY:-default}", with an optional trailing comment.
ENV_DRIVEN_RE = re.compile(
    r'(?P<key>[A-Z][A-Z0-9_]*)="\$\{(?P=key):-(?P<default>[^"}]*)\}"(?P<tail>\s+#.*)?'
)

# A config line whose right-hand side is a plain literal: a quoted string without any expansion,
# or a bare token. A value with a '$', a backtick, a backslash or a '}' in it is not a plain
# value: it cannot be moved into "${KEY:-...}" without changing what it means.
PLAIN_VALUE_RES = (
    re.compile(r'"(?P<value>[^"`$\\}]*)"(?P<tail>\s+#.*)?'),
    re.compile(r"'(?P<value>[^'$`\\}]*)'(?P<tail>\s+#.*)?"),
    re.compile(r"(?P<value>[A-Za-z0-9_.,:/@+-]*)(?P<tail>\s+#.*)?"),
)


def split_script(text: str) -> tuple[list[str], list[str], list[str]]:
    """Split a script into (preamble, config block, rest).

    The config block is the leading run of blank lines, comments and single-line
    assignments - the fleet targets and the internal config. The rest is the deploy
    logic, identical on every node.
    """
    lines = text.splitlines(keepends=True)
    idx = 0
    preamble: list[str] = []
    while idx < len(lines) and (lines[idx].startswith("#!") or lines[idx].startswith("set ")):
        preamble.append(lines[idx])
        idx += 1
    config: list[str] = []
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#") or ASSIGNMENT_RE.match(line):
            config.append(line)
            idx += 1
            continue
        break
    return preamble, config, lines[idx:]


def config_values(config_lines: list[str]) -> dict[str, str]:
    """Map config key -> the whole assignment line (value plus its trailing comment)."""
    out: dict[str, str] = {}
    for line in config_lines:
        match = ASSIGNMENT_RE.match(line)
        if match:
            out[match.group(1)] = line.rstrip("\n")
    return out


def plain_value(line: str) -> str | None:
    """The literal value of a config line, or None when the line does not hold a plain value.

    'HOST_IPS="a,b"' -> 'a,b'; 'HOST_IPS="${HOST_IPS:-a,b}"' -> 'a,b' (already env-driven: its
    default IS the value); 'HOST_IPS="$OTHER"' -> None, because an expansion is not a value that
    can be moved into "${HOST_IPS:-...}" without changing what it means.
    """
    env_driven = ENV_DRIVEN_RE.fullmatch(line.strip())
    if env_driven:
        return env_driven.group("default")
    _, _, rhs = line.partition("=")
    for pattern in PLAIN_VALUE_RES:
        match = pattern.fullmatch(rhs.strip())
        if match:
            return match.group("value")
    return None


def merged_fleet_line(key: str, repo_line: str, node_line: str) -> str:
    """The repo's env-driven line with the node's fleet as its default.

    'HOST_IPS="${HOST_IPS:-a,b}"' + the node's 'HOST_IPS="c,d"' -> 'HOST_IPS="${HOST_IPS:-c,d}"'.
    A node line that does not hold a plain value is kept verbatim: guessing what an expansion
    means would change the node's fleet.
    """
    value = plain_value(node_line)
    if value is None:
        return node_line
    env_driven = ENV_DRIVEN_RE.fullmatch(repo_line.strip())
    tail = (env_driven.group("tail") or "") if env_driven else ""
    return f'{key}="${{{key}:-{value}}}"{tail}'


def merge_config(repo_text: str, node_text: str) -> str:
    """The repo's script with the node's config values.

    The node wins for every config key it sets (its fleet targets), the repo wins for
    every key the node does not set (a new option added upstream). The deploy logic
    always comes from the repo.

    A fleet target is merged by value, not by line: the repo's env-driven line stays
    env-driven and the node's fleet becomes its default, so the node keeps its own targets
    and a deploy can still point somewhere else through the environment.
    """
    r_pre, r_cfg, r_rest = split_script(repo_text)
    _, n_cfg, _ = split_script(node_text)

    repo_values = config_values(r_cfg)
    node_values = config_values(n_cfg)

    merged: list[str] = []
    taken: set[str] = set()
    for line in r_cfg:
        match = ASSIGNMENT_RE.match(line)
        if match:
            key = match.group(1)
            if key in node_values:
                if key in FLEET_KEYS:
                    newline = merged_fleet_line(key, repo_values.get(key, line), node_values[key])
                else:
                    newline = node_values[key]
                merged.append(newline if newline.endswith("\n") else newline + "\n")
                taken.add(key)
                continue
        merged.append(line)

    # A config key only the node knows (a locally added option) stays in the block.
    for key, line in node_values.items():
        if key in repo_values or key in taken:
            continue
        merged.append(line if line.endswith("\n") else line + "\n")

    return "".join(r_pre) + "".join(merged) + "".join(r_rest)


def logic_diff(repo_text: str, node_text: str) -> str:
    """Unified diff of the deploy logic, with the config block reduced to a placeholder."""
    _, r_cfg, r_rest = split_script(repo_text)
    _, n_cfg, n_rest = split_script(node_text)
    r_norm = ["<config block>\n"] + r_rest
    n_norm = ["<config block>\n"] + n_rest
    return "".join(
        difflib.unified_diff(n_norm, r_norm, fromfile="node copy", tofile="repo script", n=3)
    )


def config_diff(repo_text: str, node_text: str) -> str:
    """Unified diff of the config block only (what the install would change)."""
    _, r_cfg, _ = split_script(repo_text)
    _, n_cfg, _ = split_script(node_text)
    return "".join(
        difflib.unified_diff(n_cfg, r_cfg, fromfile="node config", tofile="repo config", n=1)
    )


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, text=True, **kwargs)


def git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", repo_root, *args], capture_output=True)


def repo_root_of(path: str) -> str | None:
    """The git checkout that holds `path`, or None when the path is not in one."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    res = run(["git", "-C", directory, "rev-parse", "--show-toplevel"], capture_output=True)
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def git_file_text(repo_root: str, rel_path: str, ref: str) -> str | None:
    """A file's content at a ref, or None when that ref does not have it."""
    res = git(repo_root, "show", f"{ref}:{rel_path}")
    return res.stdout if res.returncode == 0 else None


def local_is_stale(repo_script: str, local_text: str) -> tuple[bool, str, str | None]:
    """Is the local copy of the script an OLDER version than origin/main's?

    The installer reads the script from the checkout it runs in. When that checkout is behind
    origin/main, the local copy is the older script, and installing it pushes the older script
    onto the node - the same regression the installer exists to prevent, from the other side.

    "Older" means: the local file is untouched (it still is the version at HEAD), and origin/main
    has commits for that file that the checkout does not have. A branch with its own changes to
    the script is work in progress, not staleness, and installs as it is.

    Returns (stale, reason, origin_main_text). The reason says why the answer is what it is,
    so a refusal can explain itself.
    """
    repo_root = repo_root_of(repo_script)
    if not repo_root:
        return False, "the script is not in a git checkout", None

    rel_path = os.path.relpath(os.path.abspath(repo_script), repo_root)
    origin_text = git_file_text(repo_root, rel_path, "origin/main")
    if origin_text is None:
        return False, "origin/main does not have this file (or origin/main is not fetched)", None
    if origin_text == local_text:
        return False, "the local copy is origin/main's", origin_text

    head_text = git_file_text(repo_root, rel_path, "HEAD")
    if head_text is None:
        return False, "the file is not tracked at HEAD", origin_text
    if head_text != local_text:
        return False, "the local copy has uncommitted changes", origin_text

    # Commits for this file that main has and the checkout does not, and the other way round.
    main_only = git(repo_root, "rev-list", "--count", "HEAD..origin/main", "--", rel_path)
    branch_only = git(repo_root, "rev-list", "--count", "origin/main..HEAD", "--", rel_path)
    if main_only.returncode != 0 or branch_only.returncode != 0:
        return False, "the commit history for this file could not be compared", origin_text
    main_count = int(main_only.stdout.strip() or "0")
    branch_count = int(branch_only.stdout.strip() or "0")

    if main_count == 0:
        return False, "the checkout has every commit origin/main has for this file", origin_text
    if branch_count > 0:
        # The branch changed the file itself: deliberate work in progress, not a stale checkout.
        return False, (
            f"the branch has {branch_count} commit(s) of its own for this file "
            f"(and misses {main_count} from origin/main)"
        ), origin_text
    return True, (
        f"the checkout misses {main_count} commit(s) origin/main has for this file"
    ), origin_text


def ssh(node: str, remote_cmd: str, stdin_text: str | None = None) -> subprocess.CompletedProcess:
    return run(["ssh", node, remote_cmd], input=stdin_text, capture_output=True)


def read_remote(node: str, remote_path: str) -> str:
    res = ssh(node, f"cat {remote_path}")
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit(f"cannot read {remote_path} on {node}")
    return res.stdout


def install_remote(node: str, remote_path: str, content: str) -> str:
    """Back up the node's copy, write the merged script, syntax-check it, then swap it in."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = f"{remote_path}.bak-{stamp}"
    remote = (
        f"set -e; "
        f"cat > {remote_path}.new; "
        f"bash -n {remote_path}.new; "
        f"cp -a {remote_path} {backup}; "
        f"mv {remote_path}.new {remote_path}; "
        f"chmod +x {remote_path}; "
        f"echo BACKUP={backup}"
    )
    res = ssh(node, remote, stdin_text=content)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit(f"install on {node} failed - the old copy is untouched")
    return res.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--node", help="ssh target of the Proxmox node (e.g. proxmox)")
    parser.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH, help="path of the live copy on the node")
    parser.add_argument("--repo-script", default=DEFAULT_REPO_SCRIPT, help="the repo copy to install")
    parser.add_argument("--check", action="store_true", help="report the drift, change nothing")
    parser.add_argument("--install", action="store_true", help="install the repo copy on the node")
    parser.add_argument("--dry-run", action="store_true", help="with --install: show the result, write nothing")
    parser.add_argument("--force", action="store_true", help="with --install: install even when the local copy is stale")
    parser.add_argument("--print-merged", metavar="NODE_COPY", help="merge a local node copy and print the result")
    args = parser.parse_args(argv)

    with open(args.repo_script, encoding="utf-8") as handle:
        repo_text = handle.read()

    if args.print_merged:
        with open(args.print_merged, encoding="utf-8") as handle:
            node_text = handle.read()
        sys.stdout.write(merge_config(repo_text, node_text))
        return 0

    if not args.node:
        parser.error("--node is required (or use --print-merged)")
    if args.check == args.install:
        parser.error("choose exactly one of --check / --install")

    node_text = read_remote(args.node, args.remote_path)
    merged = merge_config(repo_text, node_text)
    drift = logic_diff(repo_text, node_text)

    # The checkout this installer runs from can be behind origin/main, and then the "repo's
    # script" it would install is the OLD one. --check then compares the node against
    # origin/main's script (the truth) and says plainly which copy is stale; --install refuses
    # unless the operator forces it.
    stale, why, origin_text = local_is_stale(args.repo_script, repo_text)
    use_origin = bool(stale and origin_text)
    truth_text = origin_text if use_origin else repo_text
    truth_drift = logic_diff(truth_text, node_text) if use_origin else drift

    if args.check:
        print(f"# {args.node}:{args.remote_path} vs {args.repo_script}")
        if stale:
            print(f"# WARNING: the local copy of the script is STALE - {why}")
            print("#          the node is compared against origin/main's copy instead.")
        else:
            print(f"# local copy: {why}")
        if truth_drift:
            print(truth_drift)
            print("# drift found: the node's copy is not the repo's script - run with --install")
            return 1
        print("# in sync: the node's deploy script matches the repo")
        return 0

    if stale:
        print(f"REFUSING to install: the local copy of the script is STALE - {why}.", file=sys.stderr)
        print("The node's copy would be rolled back to an older script.", file=sys.stderr)
        print("Update the checkout (git fetch origin && git pull) and run again.", file=sys.stderr)
        if not args.force:
            print("If that is really what you want: --force", file=sys.stderr)
            return 1
        print("# --force given: installing the stale local copy anyway", file=sys.stderr)

    if args.dry_run:
        print(f"# would install the repo script on {args.node}:{args.remote_path}")
        print(config_diff(repo_text, node_text) or "# (config block identical)")
        print(difflib.unified_diff(
            node_text.splitlines(keepends=True), merged.splitlines(keepends=True),
            fromfile="node copy", tofile="merged", n=2,
        ))
        return 0

    backup = install_remote(args.node, args.remote_path, merged)
    print(f"# installed the repo script on {args.node}:{args.remote_path} ({backup})")
    if drift:
        print("# the node's deploy logic changed in this install:")
        print(drift)
    return 0


if __name__ == "__main__":
    sys.exit(main())
