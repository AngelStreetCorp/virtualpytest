"""
customer_bundle.py — build a deployable customer delivery bundle. ROLLOUT tooling, TASK-91.

This used to live inside the GitLab feature as `features/gitlab/lib/bundler.py` and was driven
from a panel on the GitLab page. Packaging is a rollout concern, not a GitLab one: it belongs with
`build_customer_bundle.sh`, `deploy_customer.sh` and the delivery note, so it lives here now and is
run by an operator, not by a web page. The GitLab page is a GitLab browser and says nothing about
pins, overlays, zip or tar.gz.

What this adds on top of `build_customer_bundle.sh` — which still owns ALL of staging
(`deploy_customer.sh --stage-only`), the canonical excludes, the internal-path deny-list, the
`.env` leak guards, `BUNDLE_MANIFEST.txt`, the size ceiling and the delivery note:

  1. pick the right refs (git ls-remote on the configured core remote, the overlay's branches),
  2. make the sources available locally as plain checkouts, in an isolated folder,
  3. say up front which archive formats this machine can actually produce.

Step 2 is why a customer network with no GitHub access can build at all. The deployed
`/opt/virtualpytest` is an rsync'd copy with no `.git`, and the builder needs a real checkout to
read the pinned tree's own excludes, its `lib/feature_units.sh` and its staging logic. So the core
is cloned at the PIN into a scratch folder and `REPO_DIR` points there; `--no-checkout` then tells
the builder the tree is already where it wants it. Nothing touches the deployed tree, and the
overlay comes from the customer's own GitLab.

Sources (TASK-99) — every combination produces the same archive + `.sha256` + DELIVERY-*.md:

    --core     github:<tag>                      a production tag of the public repo (VPT_CORE_REMOTE)
               zip:<path>                        a core zip; wrapped as a one-commit git tree tagged
                                                 with the VERSION.txt `current:` value, so the builder
                                                 runs unchanged. The delivery note has no changelog.
    --overlay  gitlab:<project>@<ref>            the integrated GitLab (VPT_GITLAB_URL + _TOKEN)
               github:<url|owner/repo>@<ref>     VPT_GITHUB_TOKEN optional (public repos need none)
               zip:<path>                        must carry customer.conf
               none                              platform-only bundle (default)

Usage:
    customer_bundle.py candidates [--project group/customer-overlay] [--gitlab-url http://gitlab.internal]
    customer_bundle.py build --core github:main-2026.10.13-63726 \\
        --overlay gitlab:group/customer-overlay@main --gitlab-url http://gitlab.internal \\
        [--format zip|tar.gz] [--prev-pin …] [--out DIR]
    customer_bundle.py build --core zip:/tmp/vpt-core.zip --overlay zip:/tmp/overlay.zip
    customer_bundle.py build --core github:v1.0.0 --overlay none

Env:
    VPT_GITHUB_TOKEN    Token for a private GitHub core or overlay (optional; GITHUB_TOKEN is the fallback;
                        user x-access-token, same askpass path as GitLab).
    VPT_GITLAB_TOKEN    Personal Access Token with the api scope, used only to clone the overlay.
                        It reaches git through a 0700 askpass script — never argv, never `ps`,
                        never a URL in the log.
    VPT_GITLAB_URL      GitLab base URL, the default for --gitlab-url. One value serves both the API
                        calls and the overlay clone, so they can never point at different servers.
    VPT_OVERLAY_PROJECT default project for `candidates`.
    VPT_CORE_REMOTE     git URL for the public VirtualPyTest repo (default the public GitHub
                        snapshot). Any git remote works: GitHub, the customer's GitLab mirror, or
                        an internal one. The candidate list is exactly this remote's tags, so a
                        build can never be asked for a PIN it would then fail to fetch.
    VPT_BUILD_ROOT      scratch + artefact directory (default ~/.cache/vpt-customer-bundle,
                        outside the checkout so staging cannot be wiped by a checkout of it)
    VPT_BUILD_TIMEOUT   seconds a build may run (default 3600)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
# The repo root, so `features.gitlab.lib` imports whether this is run as
# `python3 setup/proxmox/node/lib/customer_bundle.py` from the checkout or by absolute path.
REPO_ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from features.gitlab.lib import gitlab_api
from shared.src.lib.utils import git_auth
from features.gitlab.lib.gitlab_api import GitLabError

#: Production stamps look like `main-2026.10.13-63721`; releases are `release-2026.09.15` and
#: `v1.0.0`. A bare branch name is not a PIN, so the candidate list is restricted to this shape —
#: a delivery is cut from a tag, not from whatever a moving branch happens to be this minute.
PIN_RE = re.compile(r'^(?:main-\d{4}\.\d{2}\.\d{2}-\d+|release-\d{4}\.\d{2}\.\d{2}|v\d+\.\d+\.\d+)$')

#: How many log lines the in-memory tail keeps for any caller that wants the recent history.
#: The full log always stays on disk; a build prints a few hundred lines of staging.
LOG_TAIL = 400

class BuildError(RuntimeError):
    """A build could not be started at all (bad ref, missing overlay, no space)."""


def build_root() -> str:
    """Scratch + artefact directory. Outside the checkout so a build cannot be wiped by a
    `git checkout`/rsync of the tree it is staging, and outside the repo so nothing it writes is
    ever committed by accident."""
    return (os.environ.get('VPT_BUILD_ROOT', '').strip()
            or os.path.join(os.path.expanduser('~'), '.cache', 'vpt-customer-bundle'))


def core_remote() -> str:
    return (os.environ.get('VPT_CORE_REMOTE', '').strip()
            or 'https://github.com/AngelStreetCorp/virtualpytest.git')


def _core_auth(remote: str):
    """Askpass env for a GitHub core remote (VPT_GITHUB_TOKEN, else GITHUB_TOKEN; user x-access-token);
    nothing for a mirror, so a GitHub token is never offered to another host. Never argv, never the URL."""
    token = git_auth.github_token() if git_auth.is_github_url(remote) else ''
    return git_auth.askpass_env(token)


def _timeout() -> int:
    try:
        return max(60, int(os.environ.get('VPT_BUILD_TIMEOUT', '3600')))
    except ValueError:
        return 3600


def packers() -> Dict[str, bool]:
    """Which archive formats this host can actually produce.

    The builder only finds a missing `zip` after it has staged the whole tree — minutes of work,
    discovered at the last step. `tar` is always there; `zip` is a separate package, and a
    minimal server image may not have it.
    """
    return {
        'zip': shutil.which('zip') is not None,
        'tar.gz': shutil.which('tar') is not None,
    }


# ─── ref discovery ─────────────────────────────────────────────────────────────

def core_refs(limit: int = 60) -> List[Dict[str, str]]:
    """Production tags of the configured core remote, newest stamp first.

    Read with `ls-remote --tags`, which needs no clone and no credentials for a public repo, so
    listing candidates costs one round trip and leaves nothing on disk.
    """
    remote = core_remote()
    try:
        with _core_auth(remote) as auth:
            proc = subprocess.run(['git', 'ls-remote', '--tags', remote], capture_output=True, text=True,
                                  timeout=60, check=False, env={**os.environ, **auth})
    except Exception as exc:
        raise BuildError(f'Could not reach the core remote {remote}: {exc}') from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or '').strip().splitlines()
        raise BuildError(f'git ls-remote failed for {remote}: '
                         f'{detail[-1] if detail else "unknown error"}')

    shas: Dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[1].endswith('^{}'):
            continue          # the ^{} line is the dereferenced annotated tag; keep the plain one
        shas[parts[1][len('refs/tags/'):]] = parts[0]

    pins = [ref for ref in shas if PIN_RE.match(ref)]

    def sort_key(ref: str) -> Tuple[str, int]:
        """Newest first by the date stamped in the tag name; a tag without one sorts last.

        Both stamped shapes embed an ISO-ish date, so string order is chronological. `v1.0.0`
        carries no date and lands at the bottom rather than pretending to be one.
        """
        m = re.match(r'^(?:main-(\d{4}\.\d{2}\.\d{2})-(\d+)|release-(\d{4}\.\d{2}\.\d{2}))', ref)
        if m:
            return (m.group(1) or m.group(3), int(m.group(2) or 0))
        return ('', 0)

    ordered = sorted(pins, key=sort_key, reverse=True)
    return [{'ref': ref, 'sha': shas[ref][:12]} for ref in ordered[:limit]]


def overlay_refs(project: str, api: str, tok: str) -> List[str]:
    """Branches of the overlay project — the refs a delivery can be cut from."""
    # gitlab_api.branches() now returns names only (entries without a name are dropped,
    # matching the test contract). The route serves {name, commit: null} to keep the
    # frontend shape; here we just want the names for an overlay-ref picker.
    return [n for n in gitlab_api.branches(project, per_page=50, api=api, tok=tok)]


def overlay_clone_url(base_url: str, path_with_namespace: str) -> str:
    """`http://gitlab/group/app.git` from an instance base URL and a project path."""
    return f"{base_url.rstrip('/')}/{path_with_namespace.strip('/')}.git"


def _run(cmd: List[str], cwd: str, log: deque, log_path: str,
         env: Optional[Dict[str, str]] = None, timeout: int = 900) -> int:
    """Run a command, streaming merged output to the log file, stdout and the in-memory tail.

    Streaming rather than capturing is what makes this usable at a terminal: staging a few
    thousand files takes minutes, and an operator who cannot see it move starts a second build.
    """
    log.append('$ ' + ' '.join(cmd))
    with open(log_path, 'a') as handle:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                env={**os.environ, **(env or {})})
        deadline = time.time() + timeout
        try:
            for line in iter(proc.stdout.readline, ''):
                line = line.rstrip('\n')
                handle.write(line + '\n')
                handle.flush()
                log.append(line)
                if time.time() > deadline:
                    proc.kill()
                    raise BuildError(f'timed out after {timeout}s')
            proc.wait(timeout=max(5, deadline - time.time()))
        finally:
            proc.stdout.close()
    return proc.returncode


def _remote_has_tag(dest: str, ref: str, env: Optional[Dict[str, str]] = None) -> bool:
    """Does the remote have a tag by this name? (Cheap: no clone, no history.)"""
    try:
        proc = subprocess.run(['git', '-C', dest, 'ls-remote', '--tags', 'origin', f'refs/tags/{ref}'],
                              capture_output=True, text=True, timeout=60, check=False,
                              env={**os.environ, **(env or {})})
    except Exception:
        return False
    return any(line.strip() for line in (proc.stdout or '').splitlines())


def _clone(dest: str, url: str, ref: str, log: deque, log_path: str,
           env: Optional[Dict[str, str]] = None, timeout: int = 1800,
           also: Optional[List[str]] = None,
           tag_glob: str = '') -> str:
    """A checkout of one ref, with its history, plus `also` fetched but not checked out.

    NOT shallow. `build_customer_bundle.sh` is not the only consumer of this clone: it calls
    `delivery_note.sh`, which reads `git show <pin>:VERSION.txt`, the release note at that pin,
    and the commit diff between the previous pin and this one. A `--depth 1` clone has none of
    that, and the note then fails *silently* at the very end of a successful build — the bundle
    is fine and the one page describing the delivery is missing.

    `init` + `fetch` rather than `clone --branch` so a tag, a branch and a commit sha are all
    "one ref", and so the ref lands as a real local ref the builder's git calls can name.

    Returns the local name of the checked-out ref (a tag name, or `origin/<branch>`; `FETCH_HEAD`
    only for a bare commit sha, which has no name to give).
    """
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)

    def _runq(cmd: List[str]) -> int:
        return _run(cmd, cwd=dest, log=log, log_path=log_path, env=env, timeout=timeout)

    for cmd in (['git', 'init', '--quiet'], ['git', 'remote', 'add', 'origin', url]):
        if _runq(cmd) != 0:
            raise BuildError(f'could not start a checkout of {url} — see the log')

    # A tag and a branch can share a name; ask the remote which one this is, so the fetch
    # writes a ref the delivery note can then name (`git show <pin>:VERSION.txt`).
    is_tag = _remote_has_tag(dest, ref, env)
    if is_tag:
        local, spec = ref, f'+refs/tags/{ref}:refs/tags/{ref}'
    else:
        local, spec = f'origin/{ref}', f'+refs/heads/{ref}:refs/remotes/origin/{ref}'

    # Check out BEFORE the extra fetches: every fetch rewrites FETCH_HEAD, so leaving it until
    # last means the checkout would land on whatever ref the last glob matched — or on nothing.
    if _runq(['git', 'fetch', '--quiet', 'origin', spec]) != 0:
        # An annotated tag the refspec could not create, or a raw commit sha: fetch by name and
        # land on FETCH_HEAD. Only correct because nothing has fetched since.
        if _runq(['git', 'fetch', '--quiet', 'origin', ref]) != 0 \
                or _runq(['git', 'checkout', '--quiet', '--detach', 'FETCH_HEAD']) != 0:
            raise BuildError(f'could not check out "{ref}" from {url} — see the log')
        local = 'FETCH_HEAD'
        if PIN_RE.match(ref):
            # Give the pin a real name: the builder runs `git show <pin>:VERSION.txt`, and
            # FETCH_HEAD is rewritten by the fetches below.
            if _runq(['git', 'tag', '-f', ref, 'FETCH_HEAD']) != 0:
                raise BuildError(f'could not name "{ref}" locally — see the log')
            local = ref
    elif _runq(['git', 'checkout', '--quiet', '--detach', local]) != 0:
        raise BuildError(f'could not check out "{ref}" from {url} — see the log')

    for extra in [r for r in (also or []) if r and r != ref]:
        # History only — the delivery note diffs the previous pin against this one. It was asked
        # for by name, so a missing one is an error, not a note that quietly loses its changelog.
        # Tag or branch, never both in one fetch: git fails the whole fetch when either is absent.
        if _remote_has_tag(dest, extra, env):
            extra_spec = f'+refs/tags/{extra}:refs/tags/{extra}'
        else:
            extra_spec = f'+refs/heads/{extra}:refs/remotes/origin/{extra}'
        if _runq(['git', 'fetch', '--quiet', 'origin', extra_spec]) != 0:
            raise BuildError(f'could not fetch "{extra}" from {url} — is it a tag or branch of '
                             'that remote? See the log')

    if tag_glob:
        _runq(['git', 'fetch', '--quiet', 'origin', f'+refs/tags/{tag_glob}:refs/tags/{tag_glob}'])

    return local


def _askpass_env(script: str, env: Dict[str, str]) -> Dict[str, str]:
    """Feed git the PAT through an askpass script, never through argv or the remote URL.

    A token inside `git clone https://user:tok@host/...` is visible in `ps` to every user on the
    box and lands in the build log this module prints. Askpass keeps it in an owner-only file that
    `build()` deletes as soon as the overlay clone is done.
    """
    env = {**env, **git_auth.git_env(script)}
    if os.environ.get('GITLAB_INSECURE', '').strip() in ('1', 'true', 'yes'):
        env['GIT_SSL_NO_VERIFY'] = '1'
    return env


_write_askpass = git_auth.write_askpass


def _sha256(path: str) -> str:
    try:
        proc = subprocess.run(['sha256sum', os.path.basename(path)], capture_output=True,
                              text=True, cwd=os.path.dirname(path), timeout=300, check=False)
        if proc.returncode == 0 and proc.stdout.split():
            return proc.stdout.split()[0]
    except Exception:
        pass
    return ''


def _bundle_base(log_path: str) -> str:
    """The archive base name THIS build announced (`bundle: <base>` in the manifest it prints).

    The out dir is shared across builds, so "the newest archive in it" can be an older build's —
    or a stale one when this builder produced none. The name the builder itself printed is the
    only thing that identifies this build's files.
    """
    try:
        with open(log_path) as f:
            found = re.findall(r'^bundle: (\S+)\s*$', f.read(), re.M)
    except OSError:
        return ''
    return found[-1] if found else ''


def _collect(out_dir: str, base: str, fmt: str) -> Dict[str, Any]:
    """Read the identity of the archive `<base>.<fmt>` the builder just wrote. {} if it is absent."""
    path = os.path.join(out_dir, f'{base}.{fmt}')
    if not base or not os.path.isfile(path):
        return {}
    sha = ''
    sidecar = path + '.sha256'
    if os.path.isfile(sidecar):
        try:
            with open(sidecar) as f:
                sha = f.read().split()[0]
        except Exception:
            sha = ''
    delivery = os.path.join(out_dir, f'DELIVERY-{base}.md')
    return {
        'name': os.path.basename(path),
        'path': path,
        'size': os.path.getsize(path),
        'sha256': sha or _sha256(path),
        'delivery_note': os.path.basename(delivery) if os.path.isfile(delivery) else '',
    }


# ─── sources: parsing ──────────────────────────────────────────────────────────

CORE_KINDS = ('github', 'zip')
OVERLAY_KINDS = ('gitlab', 'github', 'zip', 'none')

#: A zip is untrusted input: cap what it may expand to (a repo checkout is a few hundred MB).
ZIP_MAX_BYTES = int(os.environ.get('VPT_ZIP_MAX_MB', '2048')) * 1024 * 1024


def parse_core(spec: str) -> Tuple[str, str]:
    """`github:<tag>` or `zip:<path>` -> (kind, value)."""
    kind, sep, value = (spec or '').strip().partition(':')
    if not sep or kind not in CORE_KINDS or not value.strip():
        raise BuildError(f'--core must be github:<tag> or zip:<path> (got "{spec}")')
    return kind, value.strip()


def _split_ref(text: str) -> Tuple[str, str]:
    """`<location>@<ref>` -> (location, ref). The `@` that separates the ref is the last one, and
    only if it sits in the PATH: `https://user@host/org/repo` has an `@` in the authority."""
    idx = text.rfind('@')
    start = text.find('://')
    host_end = text.find('/', start + 3 if start >= 0 else 0)
    if idx < 0 or (start >= 0 and idx < host_end):
        return text, ''
    return text[:idx], text[idx + 1:]


def parse_overlay(spec: str) -> Dict[str, str]:
    """`gitlab:<project>@<ref>` | `github:<url>@<ref>` | `zip:<path>` | `none`
    -> {'kind', 'loc', 'ref'}. The ref defaults to `main` for the two git kinds."""
    spec = (spec or '').strip()
    if spec == 'none':
        return {'kind': 'none', 'loc': '', 'ref': ''}
    kind, sep, value = spec.partition(':')
    if not sep or kind not in OVERLAY_KINDS or kind == 'none' or not value.strip():
        raise BuildError('--overlay must be gitlab:<project>@<ref>, github:<url>@<ref>, '
                         f'zip:<path> or none (got "{spec}")')
    if kind == 'zip':
        return {'kind': 'zip', 'loc': value.strip(), 'ref': ''}
    loc, ref = _split_ref(value.strip())
    if not loc:
        raise BuildError(f'--overlay "{spec}" names no repository')
    return {'kind': kind, 'loc': loc, 'ref': ref or 'main'}


def github_clone_url(loc: str) -> str:
    """A full URL or local path is used as is (a local bare repo stands in for GitHub in tests
    and on air-gapped mirrors); `owner/repo` means github.com."""
    if '://' in loc or loc.startswith(('/', '.', '~', 'git@')):
        return os.path.expanduser(loc)
    return f"https://github.com/{loc.strip('/')}" + ('' if loc.endswith('.git') else '.git')


def _scratch_name(text: str, fallback: str) -> str:
    """A folder name for an overlay: the repo / zip name without `vpt-customer-`. The builder
    names the archive after this folder (`vpt-<overlay>-<version>`)."""
    base = os.path.basename(text.rstrip('/')) or fallback
    for suffix in ('.git', '.zip', '.tar.gz'):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    base = re.sub(r'[^A-Za-z0-9._-]', '-', base).strip('.-') or fallback
    return base


# ─── sources: zip + git wrapping ───────────────────────────────────────────────

def safe_extract_zip(zip_path: str, dest: str) -> None:
    """Extract an untrusted zip under `dest` or raise BuildError, extracting nothing wrong.

    Refused: absolute paths, `..` components, backslashes (Windows separators smuggling a `..`),
    symlinks whose target is absolute or leaves `dest`, an entry that would be written through
    a symlink, and an archive that expands past ZIP_MAX_BYTES. Symlinks that stay inside are
    kept (a repo has a few); unix modes are restored (zipfile drops the exec bit otherwise).
    """
    import stat
    import zipfile

    if not os.path.isfile(zip_path):
        raise BuildError(f'zip not found: {zip_path}')
    os.makedirs(dest, exist_ok=True)
    real_dest = os.path.realpath(dest)

    def inside(path: str) -> bool:
        return os.path.realpath(path) == real_dest or os.path.realpath(path).startswith(real_dest + os.sep)

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise BuildError(f'{zip_path} is not a valid zip: {exc}') from exc
    with zf:
        total = 0
        for info in zf.infolist():
            name = info.filename
            if name.startswith('/') or '\\' in name or re.match(r'^[A-Za-z]:', name) \
                    or '..' in name.split('/'):
                raise BuildError(f'unsafe path in zip: {name!r}')
            total += info.file_size
            if total > ZIP_MAX_BYTES:
                raise BuildError(f'zip expands past {ZIP_MAX_BYTES // 1024 // 1024} MB — refusing')
        for info in zf.infolist():
            target = os.path.join(dest, info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if not inside(os.path.dirname(target) or dest):
                raise BuildError(f'zip entry would be written outside the target: {info.filename!r}')
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if not inside(os.path.dirname(target)):
                raise BuildError(f'zip entry would be written through a symlink: {info.filename!r}')
            if stat.S_ISLNK(mode):
                link = zf.read(info).decode('utf-8', 'replace')
                resolved = os.path.normpath(os.path.join(os.path.dirname(target), link))
                if os.path.isabs(link) or not inside(resolved):
                    raise BuildError(f'symlink escapes the archive: {info.filename} -> {link}')
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(link, target)
                continue
            if os.path.islink(target):
                raise BuildError(f'zip entry would overwrite a symlink: {info.filename!r}')
            with zf.open(info) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out)
            if mode & 0o111:
                os.chmod(target, 0o755)


def find_root(base: str, markers: List[str], max_depth: int = 2) -> str:
    """The folder under `base` (itself, or a top-level folder: GitHub's "Download ZIP" wraps
    everything in `<repo>-<ref>/`) that holds every marker path. '' if there is none."""
    def has(d: str) -> bool:
        return all(os.path.exists(os.path.join(d, m)) for m in markers)
    frontier = [base]
    for _ in range(max_depth + 1):
        nxt: List[str] = []
        for d in frontier:
            if has(d):
                return d
            try:
                nxt += [os.path.join(d, e) for e in sorted(os.listdir(d))
                        if os.path.isdir(os.path.join(d, e)) and e != '.git']
            except OSError:
                pass
        frontier = nxt
    return ''


def read_version(tree: str) -> str:
    """The `current:` identity of a tree's VERSION.txt ('' if absent)."""
    try:
        with open(os.path.join(tree, 'VERSION.txt')) as f:
            for line in f:
                if line.startswith('current:'):
                    return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return ''


def git_wrap(tree: str, message: str, branch: str, tag: str, log: deque, log_path: str) -> None:
    """Make `tree` a one-commit repo (fixed author, so the same zip gives the same tree), on
    `branch`, tagged `tag` when given. The builder reads the checkout through git, so this is
    what lets a zip travel the same path as a clone."""
    ident = {'GIT_AUTHOR_NAME': 'vpt-bundle', 'GIT_AUTHOR_EMAIL': 'bundle@virtualpytest.local',
             'GIT_COMMITTER_NAME': 'vpt-bundle', 'GIT_COMMITTER_EMAIL': 'bundle@virtualpytest.local'}
    steps = [['git', 'init', '--quiet'], ['git', 'checkout', '--quiet', '-b', branch],
             ['git', 'add', '-A'],
             # VERSION.txt is git-ignored in the core (the pre-commit hook force-adds it), and the
             # builder cannot stage a tree without its identity.
             ['git', 'add', '-f', '--ignore-errors', '--', 'VERSION.txt'],
             ['git', 'commit', '--quiet', '--allow-empty', '-m', message]]
    if tag:
        steps.append(['git', 'tag', tag])
    for cmd in steps:
        if _run(cmd, cwd=tree, log=log, log_path=log_path, env=ident, timeout=600) != 0:
            raise BuildError(f'could not turn the zip into a git tree ({" ".join(cmd)}) — see the log')


# ─── the build ─────────────────────────────────────────────────────────────────

def _prepare_core(kind: str, value: str, root: str, prev_ref: str,
                  log: deque, log_path: str) -> Tuple[str, str, str]:
    """-> (core_dir, pin, scratch to delete afterwards or '')."""
    if kind == 'github':
        if not PIN_RE.match(value):
            raise BuildError(f'"{value}" is not a production tag '
                             '(expected main-<date>-<build>, release-<date> or v<major>.<minor>.<patch>)')
        core_dir = os.path.join(root, 'core-' + value)
        remote = core_remote()
        with _core_auth(remote) as auth:        # a private GitHub snapshot needs the token; a mirror gets none
            _clone(core_dir, remote, value, log, log_path, env=auth,
                   also=[prev_ref] if prev_ref else [], tag_glob='release-*')
        return core_dir, value, ''

    scratch = os.path.join(root, 'core-zip-' + uuid.uuid4().hex[:8])
    safe_extract_zip(value, scratch)
    core_dir = find_root(scratch, ['VERSION.txt', 'setup/proxmox/node/build_customer_bundle.sh'])
    if not core_dir:
        shutil.rmtree(scratch, ignore_errors=True)
        raise BuildError(f'{value} is not a VirtualPyTest core: no folder holds VERSION.txt and '
                         'setup/proxmox/node/build_customer_bundle.sh')
    version = read_version(core_dir)
    if not version or re.search(r'[\s~^:?*\[\\]', version) or '..' in version:
        shutil.rmtree(scratch, ignore_errors=True)
        raise BuildError(f'VERSION.txt in {value} has no usable "current:" line (got "{version}")')
    try:
        git_wrap(core_dir, f'zip source {version}', 'main', version, deque(maxlen=LOG_TAIL), log_path)
    except BuildError:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    return core_dir, version, scratch


def _prepare_overlay(ov: Dict[str, str], root: str, api: str, tok: str, base_url: str,
                     github_tok: str, log: deque, log_path: str) -> Tuple[str, str]:
    """-> (overlay_dir, scratch parent to delete). overlay_dir is '' for `none`.

    The overlay lands in `<scratch>/<name>` because the builder names the archive after that
    folder. A token reaches git only through a 0700 askpass file that is gone before staging."""
    kind = ov['kind']
    if kind == 'none':
        return '', ''
    scratch = os.path.join(root, 'overlay-' + uuid.uuid4().hex[:8])
    askpass = os.path.join(root, '.askpass-' + uuid.uuid4().hex[:8])
    try:
        if kind == 'zip':
            tmp = os.path.join(scratch, '_x')
            safe_extract_zip(ov['loc'], tmp)
            src = find_root(tmp, ['customer.conf'])
            if not src:
                raise BuildError(f'{ov["loc"]} has no customer.conf — that is what tells the builder '
                                 'which features this customer does not get.')
            overlay_dir = os.path.join(scratch, _scratch_name(ov['loc'], 'overlay'))
            os.rename(src, overlay_dir)
            if not os.path.isdir(os.path.join(overlay_dir, '.git')):
                git_wrap(overlay_dir, 'zip source', 'main', '', deque(maxlen=LOG_TAIL), log_path)
            return overlay_dir, scratch

        if kind == 'gitlab':
            if not tok:
                raise BuildError('a GitLab token is required to read the overlay')
            url = overlay_clone_url(base_url, ov['loc'])
            name = _scratch_name(ov['loc'], 'overlay')
            username = 'oauth2'
            try:
                username = (gitlab_api.current_user(api=api, tok=tok) or {}).get('username') or 'oauth2'
            except Exception:
                # A token that can read projects but not /user still clones fine — GitLab only
                # uses the username to fill the Basic auth prompt, so any non-empty value works.
                pass
            secret = tok
        else:
            url = github_clone_url(ov['loc'])
            name = _scratch_name(ov['loc'], 'overlay')
            username, secret = 'x-access-token', github_tok     # optional: a public repo needs none

        overlay_dir = os.path.join(scratch, name)
        os.makedirs(overlay_dir, exist_ok=True)
        env = None
        if secret:
            _write_askpass(askpass, username, secret)
            env = _askpass_env(askpass, {})
        try:
            _clone(overlay_dir, url, ov['ref'], log, log_path, env=env, tag_glob='release-*')
        finally:
            # The token is only needed to clone; do not leave it on disk through the long stage.
            try:
                os.remove(askpass)
            except OSError:
                pass
        if not os.path.isfile(os.path.join(overlay_dir, 'customer.conf')):
            raise BuildError(
                f'{ov["loc"]}@{ov["ref"]} has no customer.conf — that is what tells the builder '
                'which features this customer does not get. Point at an overlay branch, not an '
                'application repository.')
        return overlay_dir, scratch
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def build(core: str, overlay: str, api: str = '', tok: str = '', base_url: str = '',
          fmt: str = 'zip', prev_ref: str = '', out_dir: str = '',
          github_tok: str = '') -> Dict[str, Any]:
    """Build the delivery bundle and return its archive record. Raises BuildError.

    `core` is `github:<tag>` or `zip:<path>`; `overlay` is `gitlab:<project>@<ref>`,
    `github:<url>@<ref>`, `zip:<path>` or `none` (a platform-only bundle).

    Synchronous on purpose. This used to be a background job with a job id, a status file and
    a poll endpoint, because the GitLab page drove it; with packaging back in the rollout the
    operator runs one command and watches it print. A build stages thousands of files, so the
    log is streamed to stdout and kept on disk next to the artefact.
    """
    core_kind, core_value = parse_core(core)
    ov = parse_overlay(overlay)
    fmt = 'tar.gz' if str(fmt).strip() in ('tar.gz', 'tar', 'targz') else 'zip'
    if core_kind == 'github' and not core_value:
        raise BuildError('a production tag is required')
    if core_kind == 'github' and not PIN_RE.match(core_value):
        raise BuildError(f'"{core_value}" is not a production tag '
                         '(expected main-<date>-<build>, release-<date> or v<major>.<minor>.<patch>)')
    if ov['kind'] == 'gitlab' and not tok:
        raise BuildError('a GitLab token is required to read the overlay')

    root = build_root()
    out_dir = out_dir or os.path.join(root, 'out')
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(root, 'build-' + time.strftime('%Y%m%d-%H%M%S') + '.log')
    log: deque = deque(maxlen=LOG_TAIL)

    def echo(line: str) -> None:
        log.append(line)
        print(line, flush=True)

    # 1. the core, with the history the delivery note needs (a zip has none: one commit)
    echo('--- 1/3 core ---')
    core_dir, pin, core_scratch = _prepare_core(core_kind, core_value, root, prev_ref, log, log_path)
    overlay_scratch = ''
    try:
        # 2. the overlay
        echo('')
        echo('--- 2/3 overlay ---')
        if ov['kind'] == 'none':
            echo('no overlay: platform-only bundle')
        overlay_dir, overlay_scratch = _prepare_overlay(ov, root, api, tok, base_url,
                                                        github_tok, log, log_path)

        # 3. the builder itself
        builder = os.path.join(core_dir, 'setup', 'proxmox', 'node', 'build_customer_bundle.sh')
        if not os.path.isfile(builder):
            raise BuildError(f'{pin} carries no setup/proxmox/node/build_customer_bundle.sh '
                             '(this tag predates the bundle builder) — cut the delivery from a newer tag.')
        cmd = ['bash', builder] + ([overlay_dir] if overlay_dir else []) + \
              ['--no-checkout', '--pin', pin, '--out', out_dir]
        if fmt == 'zip':
            cmd.append('--zip')
        if prev_ref:
            cmd += ['--prev-pin', prev_ref]
        echo('')
        echo('--- 3/3 bundle ---')
        rc = _run(cmd, cwd=core_dir, log=log, log_path=log_path,
                  env={'REPO_DIR': core_dir, 'VPT_CORE_SOURCE': core_kind}, timeout=_timeout())

        if rc != 0:
            raise BuildError(f'build_customer_bundle.sh exited {rc} (see {log_path})')
        archive = _collect(out_dir, _bundle_base(log_path), fmt)
        if not archive:
            raise BuildError(f'the builder finished but produced no archive (see {log_path})')
        return archive
    finally:
        # A github core checkout is kept (reused and overwritten on purpose); the rest is per-build.
        for scratch in (overlay_scratch, core_scratch):
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def candidates(project: str = '', api: str = '', tok: str = '', base_url: str = '',
               github_tok: str = '') -> Dict[str, Any]:
    """What can be built right now, per source type. A source that cannot be used says why
    (`usable: false` + `reason`/`error`) instead of failing the whole listing: an offline
    install has no GitHub and still has zip, and the page needs to grey out exactly that."""
    out: Dict[str, Any] = {
        'success': True,
        'packers': packers(),
        'core': {
            'github': {'usable': False, 'remote': core_remote(), 'refs': [], 'error': ''},
            'zip': {'usable': True},
        },
        'overlay': {
            'gitlab': {'usable': False, 'project': project, 'refs': [], 'reason': '', 'error': ''},
            'github': {'usable': True, 'token_set': bool(github_tok)},
            'zip': {'usable': True},
            'none': {'usable': True},
        },
    }
    try:
        out['core']['github']['refs'] = core_refs()
        out['core']['github']['usable'] = True
    except BuildError as exc:
        out['core']['github']['error'] = str(exc)

    gl = out['overlay']['gitlab']
    if not (base_url and tok):
        gl['reason'] = 'set VPT_GITLAB_URL and VPT_GITLAB_TOKEN'
    elif not project:
        gl['usable'] = True
        gl['reason'] = 'no project given: branches not listed'
    else:
        try:
            gl['refs'] = overlay_refs(project, api, tok)
            gl['usable'] = True
        except GitLabError as exc:
            gl['error'] = str(exc)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog='customer_bundle.py',
        description='Build a deployable bundle from any source (TASK-91 / TASK-99).')
    sub = ap.add_subparsers(dest='cmd', required=True)

    c = sub.add_parser('candidates', help='list what each source type can offer right now')
    c.add_argument('--project', default='', help='GitLab overlay project, e.g. group/customer-overlay '
                                                  '(default: $VPT_OVERLAY_PROJECT)')
    c.add_argument('--gitlab-url', default=os.environ.get('VPT_GITLAB_URL', ''),
                   help='GitLab base URL (default: $VPT_GITLAB_URL)')

    b = sub.add_parser('build', help='build the bundle')
    b.add_argument('--core', required=True, metavar='github:<tag>|zip:<path>',
                   help='VirtualPyTest itself: a production tag of the public repo, or a core zip')
    b.add_argument('--overlay', default='none',
                   metavar='gitlab:<project>@<ref>|github:<url>@<ref>|zip:<path>|none',
                   help='the customer layer (default: none = platform-only bundle)')
    b.add_argument('--gitlab-url', default=os.environ.get('VPT_GITLAB_URL', ''),
                   help='GitLab base URL for a gitlab: overlay (default: $VPT_GITLAB_URL)')
    b.add_argument('--format', default='zip', choices=['zip', 'tar.gz'])
    b.add_argument('--prev-pin', default='', help='platform ref the customer runs today')
    b.add_argument('--out', default='', help='where the archive is written')

    args = ap.parse_args(argv)
    tok = os.environ.get('VPT_GITLAB_TOKEN', '')
    github_tok = git_auth.github_token()
    # One URL for the API calls and the overlay clone.
    url = args.gitlab_url

    if args.cmd == 'candidates':
        project = args.project or os.environ.get('VPT_OVERLAY_PROJECT', '')
        print(json.dumps(candidates(project, url, tok, url, github_tok), indent=2))
        return 0

    try:
        needs_gitlab = parse_overlay(args.overlay)['kind'] == 'gitlab'
    except BuildError as exc:
        print(f'FAILED: {exc}', file=sys.stderr)
        return 1
    if needs_gitlab and not url:
        ap.error('--gitlab-url is required for a gitlab: overlay (or set VPT_GITLAB_URL)')
    if needs_gitlab and not tok:
        ap.error('set VPT_GITLAB_TOKEN (a Personal Access Token with the api scope)')
    try:
        record = build(args.core, args.overlay, api=url, tok=tok, base_url=url,
                       fmt=args.format, prev_ref=args.prev_pin, out_dir=args.out,
                       github_tok=github_tok)
    except BuildError as exc:
        print(f'FAILED: {exc}', file=sys.stderr)
        return 1
    print('')
    print(json.dumps(record, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
