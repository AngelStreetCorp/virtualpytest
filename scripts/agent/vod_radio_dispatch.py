#!/usr/bin/env python3
"""
Fleet fan-out runner for the content-surface suite (radio / replay / VOD / recording).

The suite itself lives in `test_scripts/content/` and is executed on the platform as a
VIRTUAL SCRIPT, so a run needs no deploy: the sources are pushed to the platform
(`scripts/sync_virtual_scripts.py`), the host materializes the virtual script and runs
it on ONE whole device.

What this runner does, in order:

  1. picks the targets (a table of host/device pairs, one per device),
  2. claims the lease of every target BEFORE anything touches it (env `node1-vpt`),
  3. logs the web browser session in (one account, one session, one device limit),
  4. launches `content_suite` per device and collects the machine-readable case rows
     (`metadata.content_cases` of the persisted script result, with the stdout
     `VPT_CASE_RESULT` lines as a fallback),
  5. releases the lease on EVERY exit path (success, failure, exception, Ctrl-C),
  6. writes a JSON file (every raw case row) and a Markdown summary that keeps
     PRODUCT DEFECTS and INFRA problems in SEPARATE columns.

The report split is the point of this file: an earlier benchmark was invalidated
because infra noise (lease busy, deploy, connectivity, geo-block, session) was read
as a product defect. A row with cause=infra is NOT a product defect, and the report
says so in words.

Usage:
    python3 scripts/agent/vod_radio_dispatch.py --list
    python3 scripts/agent/vod_radio_dispatch.py --dry-run
    python3 scripts/agent/vod_radio_dispatch.py --only stb --cases radio,replay

Secrets: the auto-sign token, the MCP key and the web app password are read into
variables only. They are never printed, never logged, never written to a report and
never passed as a script parameter (script parameters are persisted in the database).
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import datetime as dt
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

try:  # requests is needed for every network call; --list / --dry-run work without it
    import requests
except ImportError:  # pragma: no cover - codebox always has it
    requests = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- fleet

TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"

BACKEND_A_URL = "https://virtualpytest.angelstreet.io"   # node1
BACKEND_B_URL = "https://rpitest.angelstreet.io"         # the Pi site (IPv4 only)

BACKEND_URLS = {"A": BACKEND_A_URL, "B": BACKEND_B_URL}

ALL_CASES = ("radio", "replay", "vod", "recording")

SCRIPT_NAME = "content_suite"
VIRTUAL_SCRIPT_NAME = "content_suite"
SYNC_SCRIPT_REF = "content/content_suite"

RESULT_MARKER = "VPT_CASE_RESULT"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

CAUSE_PRODUCT = "product"
CAUSE_INFRA = "infra"
CAUSE_COVERAGE = "coverage"

# Lease (the registry is the only gate; never --force, never another session's lease)
LEASE_ENV = "node1-vpt"
LEASE_AGENT = "codebox:TASK-168"
# The lease service does NOT let an agent block itself, so two dispatchers that
# share an agent string can hold the same device at the same time. The lease
# agent therefore carries the process id: every run is its own holder, and the
# safety net below can only ever release THIS run's lease.
LEASE_AGENT_RUN = f"{LEASE_AGENT}-{os.getpid()}"
LEASE_PROVIDER = "minimax"
LEASE_PURPOSE = "vod-radio content suite"
LEASE_TTL_MIN = 90

# The web account has a device limit (WEB_UI_ORCHTNET.md §5): one account, one session,
# runs are sequential on one host. So the web platform NEVER runs in parallel.
WEB_PLATFORM = "web"

# The tree nodes the web cases drive. A UI is the right one for this suite only
# when its tree carries them: the platform hosts many UIs for the same device
# model, and the old ones have trees that cannot reach a catalogue item.
WEB_REQUIRED_NODES = ("replay_detail", "vod_player", "tv_guide_programme", "search")


@dataclass(frozen=True)
class Target:
    """One whole device of the fleet."""

    platform: str        # web | mobile | stb
    backend: str         # A | B
    host_name: str
    device_id: str
    device: str          # the device NAME (as the harness reports it)
    userinterface: str   # the UI to test; empty means "resolve it from the platform"
    device_model: str = ""   # the model the UI is looked up by

    @property
    def resource(self) -> str:
        """The lease resource: <host>/<device>."""
        return f"{self.host_name}/{self.device_id}"

    @property
    def backend_url(self) -> str:
        return BACKEND_URLS[self.backend]



def ui_label(target: Target) -> str:
    """What the plan prints in the UI column: the named UI, or the device model
    it is resolved from (the browser UI's own name is customer material)."""
    return target.userinterface or (f"by model: {target.device_model}"
                                    if target.device_model else target.platform)

# The fleet, verified live on 2026-10-23.
# The browser UI is NOT named here: its name is customer material and the leak
# gate keeps it out of publishable paths. It is resolved at run time from the
# platform, by the device model the UI declares (`models: ["web"]`).
# labox-web is NOT a target: it is a retired host (TASK-170, its VM was
# stopped by Proxmox on 2026-10-16). The VM answers again, but it carries a
# checkout from September, so a virtual script that imports the platform's
# shared library fails there with an ImportError. A host that is not a deploy
# target is not a test target either.
TARGETS: Tuple[Target, ...] = (
    # platform, backend, host_name,     device_id, device,       userinterface
    Target("web", "A", "host-clone-1", "host", "browser", "", "web"),
    Target("web", "A", "host-clone-2", "host", "browser", "", "web"),
    Target("web", "A", "labox-backend", "host", "browser", "", "web"),
    Target("web", "B", "vpt-mf1", "host", "browser", "", "web"),
    Target("mobile", "A", "labox-mobile", "device1", "labox-mobile", "stb_android_mobile",
           "android_mobile"),
    Target("mobile", "B", "vpt-pi1", "device1", "S21x", "stb_android_mobile", "android_mobile"),
    Target("mobile", "B", "vpt-mf1", "device6", "S7", "stb_android_mobile", "android_mobile"),
    Target("stb", "B", "vpt-pi1", "device3", "stb3", "stb_tv", "stb"),
    Target("stb", "B", "vpt-pi1", "device4", "stb4", "stb_tv", "stb"),
    Target("stb", "B", "vpt-mf1", "device2", "stbv1", "stb_tv", "stb"),
    Target("stb", "B", "vpt-mf1", "device3", "stbv1+", "stb_tv", "stb"),
)

# The account of the web app. The file is chmod 600 and lives OUTSIDE the repository.
ACCOUNT_ENV_PATH = os.path.expanduser(
    "~/vpt-deliverables/benchmarks/uc-04-web-tree-build/target.env")

# The MCP key is NOT the auto-sign token: /server/mcp wants a Bearer token.
MCP_SECRET_SSH = "server"
MCP_SECRET_ENV_FILE = "/opt/virtualpytest/.env"

# Runs that shell out to a helper need IPv4: rpitest.angelstreet.io resolves to IPv6
# first from codebox and every call to it then times out.
IPV4_PATCH = (
    "import socket,runpy,sys\n"
    "_g=socket.getaddrinfo\n"
    "socket.getaddrinfo=lambda h,p,f=0,*a,**k:_g(h,p,socket.AF_INET,*a,**k)\n"
    "sys.argv=sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0],run_name='__main__')\n"
)


# ------------------------------------------------------------------------ secrets

class Secrets:
    """Every secret of this run, kept in memory only, so nothing can leak by accident."""

    def __init__(self) -> None:
        self._values: List[str] = []
        self._lock = threading.Lock()

    def add(self, value: Optional[str]) -> Optional[str]:
        if value:
            with self._lock:
                self._values.append(value)
        return value

    def redact(self, text: Any) -> str:
        out = str(text)
        with self._lock:
            values = list(self._values)
        for secret in values:
            if secret and secret in out:
                out = out.replace(secret, "<redacted>")
        # belt and braces: anything that looks like a token in a URL
        return re.sub(r"(auto_signed=)[^&\s\"']+", r"\1<redacted>", out)

    def contains(self, text: str) -> bool:
        with self._lock:
            values = list(self._values)
        return any(secret and secret in text for secret in values)


SECRETS = Secrets()

_CREDENTIAL_CACHE: Dict[str, str] = {}
_CREDENTIAL_LOCK = threading.Lock()


def emit(message: str = "") -> None:
    """Print one line, with every secret masked."""
    try:
        print(SECRETS.redact(message), flush=True)
    except BrokenPipeError:
        # the output went into something that closed early (head): stop quietly
        raise


# ------------------------------------------------------------------------ helpers

class DispatchError(Exception):
    """Anything that goes wrong in a way that is not a product defect."""


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def repo_root() -> str:
    """The checkout this run belongs to: the cwd, or the closest parent that has the tree.

    The checkout that carries the content suite wins: the suite is not merged yet, so
    the sources that get pushed as virtual scripts must come from the tree that has
    them, not from an older checkout.
    """
    here = os.path.abspath(os.getcwd())
    candidates = [here] + _parents(here) + [os.path.expanduser("~/virtualpytest")]
    fallback = ""
    for candidate in candidates:
        if not os.path.isfile(os.path.join(candidate, "scripts", "sync_virtual_scripts.py")):
            continue
        if not os.path.isdir(os.path.join(candidate, "test_scripts")):
            continue
        if not fallback:
            fallback = candidate
        if os.path.isfile(os.path.join(candidate, "test_scripts", "content",
                                       f"{SCRIPT_NAME}.py")):
            return candidate
    return fallback or here


def _parents(path: str) -> List[str]:
    out: List[str] = []
    current = path
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            return out
        out.append(parent)
        current = parent


def force_ipv4() -> None:
    """Resolve to IPv4 only. rpitest.angelstreet.io answers on IPv6 first and then hangs."""
    original = socket.getaddrinfo

    def _ipv4_only(host, port, family=0, *args, **kwargs):  # noqa: ANN001
        return original(host, port, socket.AF_INET, *args, **kwargs)

    socket.getaddrinfo = _ipv4_only  # type: ignore[assignment]


def read_env_file(path: str) -> Dict[str, str]:
    """A KEY=VALUE file, as the target.env of the web benchmark has."""
    values: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                values[key.strip()] = value
    except OSError:
        return {}
    return values


# ------------------------------------------------------------------- credentials

def auto_sign_token() -> str:
    """The auto-sign test token (scripts/agent/auto_sign_token.sh). Kept in a variable."""
    with _CREDENTIAL_LOCK:
        cached = _CREDENTIAL_CACHE.get("auto_sign")
    if cached:
        return cached
    script = os.path.join(repo_root(), "scripts", "agent", "auto_sign_token.sh")
    if not os.path.isfile(script):
        raise DispatchError("scripts/agent/auto_sign_token.sh not found in the checkout")
    proc = subprocess.run([script], capture_output=True, text=True, timeout=120)
    token = (proc.stdout or "").strip()
    if proc.returncode != 0 or not token:
        raise DispatchError("could not read the auto-sign token")
    SECRETS.add(token)
    with _CREDENTIAL_LOCK:
        _CREDENTIAL_CACHE["auto_sign"] = token
    return token


def mcp_secret_key() -> str:
    """The MCP Bearer key, read from the backend server's env over ssh.

    The auto-sign token does NOT authenticate /server/mcp (401). The key is a
    credential: it stays in a variable.
    """
    with _CREDENTIAL_LOCK:
        cached = _CREDENTIAL_CACHE.get("mcp_key")
    if cached:
        return cached
    command = (f'sudo -n grep "^MCP_SECRET_KEY=" {MCP_SECRET_ENV_FILE} '
               f"| tail -n 1 | cut -d= -f2-")
    proc = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", MCP_SECRET_SSH, command],
        capture_output=True, text=True, timeout=60)
    key = (proc.stdout or "").strip().strip("\"'").strip()
    if proc.returncode != 0 or not key:
        raise DispatchError("no MCP key available for the browser login")
    SECRETS.add(key)
    with _CREDENTIAL_LOCK:
        _CREDENTIAL_CACHE["mcp_key"] = key
    return key


def web_account() -> Dict[str, str]:
    """The web test account: URL, login, password. The password is a secret."""
    values = read_env_file(ACCOUNT_ENV_PATH)
    missing = [k for k in ("VPTTV_URL", "VPTTV_LOGIN", "VPTTV_PASSWORD") if not values.get(k)]
    if missing:
        raise DispatchError(f"{ACCOUNT_ENV_PATH} misses {', '.join(missing)}")
    SECRETS.add(values.get("VPTTV_PASSWORD"))
    return values


# ------------------------------------------------------------------------- backends

class Backend:
    """One backend server (A = node1, B = the Pi site)."""

    def __init__(self, key: str, url: str, token: str) -> None:
        self.key = key
        self.url = url.rstrip("/")
        self.token = token

    def _headers(self) -> Dict[str, str]:
        headers = {"X-Auto-Sign": self.token, "Accept": "application/json"}
        # Some deployments want the shared API key as well (scripts/atlas_chat.py sends
        # both). It is a credential: it never leaves this process.
        api_key = os.environ.get("API_KEY")
        if api_key:
            SECRETS.add(api_key)
            headers["X-API-Key"] = api_key
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
                body: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Any:
        if requests is None:
            raise DispatchError("the requests library is missing")
        url = f"{self.url}{path}"
        query = {"team_id": TEAM_ID}
        query.update(params or {})
        try:
            response = requests.request(method, url, params=query, json=body,
                                        headers=self._headers(), timeout=timeout)
        except requests.RequestException as exc:
            raise DispatchError(f"{self.key} backend unreachable: {type(exc).__name__}") from None
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("error") or body.get("message") or "")[:200]
            except ValueError:
                detail = ""
            raise DispatchError(f"{self.key} backend answered HTTP {response.status_code} "
                               f"for {path}"
                               + (f": {SECRETS.redact(detail)}" if detail else ""))
        try:
            return response.json()
        except ValueError:
            raise DispatchError(f"{self.key} backend sent a non-JSON answer for {path}") from None

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Any:
        return self.request("GET", path, params=params, timeout=timeout)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None,
             params: Optional[Dict[str, Any]] = None, timeout: int = 120) -> Any:
        return self.request("POST", path, params=params, body=body, timeout=timeout)


# --------------------------------------------------------------------------- lease

def lease_command(args: Sequence[str]) -> List[str]:
    """The exact remote call: ssh proxmox '~/bin/vpt-lease <args>'."""
    remote = "~/bin/vpt-lease " + " ".join(shlex.quote(str(a)) for a in args)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "proxmox", remote]


@dataclass
class LeaseResult:
    granted: bool
    lease_id: str = ""
    reason: str = ""
    busy: bool = False


def claim_lease(resource: str, wait_s: int, ttl_min: int = LEASE_TTL_MIN) -> LeaseResult:
    """Claim <host>/<device> in env node1-vpt. Never --force, never another session's lease.

    The lease is claimed with `--kind server` ON PURPOSE. The lease service
    defaults a device resource to kind=host, which only blocks a restart of
    that host: a run started through the server API (`POST
    /server/script/execute`) also breaks when the SERVER restarts, and a
    server deploy that does not wait for us kills the run mid-flight (it did
    exactly that once: the deploy landed while two STB jobs were running and
    they died with no result). kind=server makes the server + full deploys
    wait for this run instead. The lease is released as soon as the job ends,
    so the deploy is only delayed for the minutes the job actually runs.

    Exit codes of the lease service: 0 granted, 3 busy, 4 a deploy is pending,
    5 the service is unreachable (treat as busy, never as free).

    Exit 4 is not a skip: the lease rules say to wait for the pending deploy
    and claim again, so a deploy that is merely queued does not cost us the
    device. The wait is bounded by the remaining wait budget.
    """
    deadline = time.monotonic() + max(0, wait_s)
    deploy_waits = 0
    while True:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            return LeaseResult(False, reason=f"lease busy: no grant within {wait_s}s", busy=True)
        args = ["claim", LEASE_ENV, resource, "--agent", LEASE_AGENT_RUN, "--provider", LEASE_PROVIDER,
                "--purpose", LEASE_PURPOSE, "--ttl", str(ttl_min), "--kind", "server", "--wait"]
        command = lease_command(args)
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=remaining)
        except subprocess.TimeoutExpired:
            # The wait was too long: SKIP the target, never force it.
            return LeaseResult(False, reason=f"lease busy: no grant within {wait_s}s", busy=True)
        except OSError as exc:
            return LeaseResult(False, reason=f"lease service unreachable: {type(exc).__name__}", busy=True)

        if proc.returncode == 0:
            lease_id = _parse_lease_id(proc.stdout or "")
            if not lease_id:
                return LeaseResult(False, reason="lease granted but no lease id was printed", busy=True)
            return LeaseResult(True, lease_id=lease_id)
        if proc.returncode == 4:
            # A deploy is pending on this resource: wait for it, then claim again.
            deploy_waits += 1
            if deploy_waits > 3:
                return LeaseResult(False, reason="lease busy: a deploy is pending on it", busy=True)
            budget = int(deadline - time.monotonic())
            if budget <= 0:
                return LeaseResult(False, reason="lease busy: no grant within %ds" % wait_s, busy=True)
            print(f"[lease] {resource}: a deploy is pending on it, waiting for it "
                  f"(up to {budget}s)", flush=True)
            if not wait_for_pending_deploy(budget):
                return LeaseResult(False, reason="lease busy: a deploy is pending on it", busy=True)
            continue
        if proc.returncode == 3:
            return LeaseResult(False, reason="lease busy: another session holds it", busy=True)
        if proc.returncode == 5:
            return LeaseResult(False, reason="lease service unavailable (exit 5)", busy=True)
        detail = ""
        tail = (proc.stderr or proc.stdout or "").strip()
        if tail:
            detail = SECRETS.redact(tail.splitlines()[-1][:300])
        return LeaseResult(False, reason=f"lease claim failed (exit {proc.returncode})"
                                          + (f": {detail}" if detail else ""))


def wait_for_pending_deploy(budget_s: int) -> bool:
    """Wait for a queued deploy on the env to finish. True when the queue is clear.

    The lease service's own rule for exit 4: `vpt-lease deploy wait --env <env>`,
    then claim again. Bounded by the caller's budget so the fleet run cannot
    hang forever on a deploy.
    """
    command = lease_command(["deploy", "wait", "--env", LEASE_ENV])
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=budget_s)
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return False
    return proc.returncode == 0


def _parse_lease_id(stdout: str) -> str:
    """The lease service prints the lease id on stdout (8 hex chars)."""
    found = ""
    for line in stdout.splitlines():
        line = line.strip()
        if re.fullmatch(r"[0-9a-f]{6,12}", line):
            found = line
        else:
            match = re.search(r"\b([0-9a-f]{6,12})\b", line)
            if match and ("lease" in line.lower() or "granted" in line.lower()):
                found = match.group(1)
    return found


def release_lease(lease_id: str) -> str:
    """Release the lease we hold. Never anybody else's."""
    if not lease_id:
        return ""
    try:
        proc = subprocess.run(lease_command(["release", lease_id]),
                              capture_output=True, text=True, timeout=90)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"release failed: {type(exc).__name__}"
    if proc.returncode != 0:
        detail = SECRETS.redact((proc.stderr or "").strip()[:200])
        return f"release failed (exit {proc.returncode})" + (f": {detail}" if detail else "")
    return ""


def abort_running_script(backend: "Backend", target: Target, task_id: str) -> str:
    """Stop an overrunning script on its device.

    A script that never finishes keeps the device locked long after this job
    gave up on it. The platform has its own abort for that, and the platform's
    route is the only one that knows which run to stop.
    """
    if not task_id:
        return "no task id to abort"
    try:
        answer = backend.post("/server/script/abortRunning", body={
            "host_name": target.host_name,
            "device_id": target.device_id,
            "task_id": task_id,
        }, timeout=60)
    except Exception as exc:                                   # noqa: BLE001
        return f"the abort failed: {type(exc).__name__}: {exc}"
    if not isinstance(answer, dict) or not answer.get("success"):
        return "the platform did not abort the run"
    emit(f"[run] {target.resource}: the overrunning script was aborted on the device")
    return ""


def release_own_lease_for(resource: str, since_epoch: int) -> str:
    """Safety net after a claim timeout: if the claim was granted just before the wait
    was cut, the lease would sit there for its whole TTL. Only OUR agent's lease, only
    on OUR resource, only if it was created after the claim started."""
    try:
        proc = subprocess.run(lease_command(["list", LEASE_ENV, "--json"]),
                              capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        return ""
    notes: List[str] = []
    for lease in payload.get("leases") or []:
        if lease.get("agent") != LEASE_AGENT_RUN:
            continue
        if str(lease.get("resource", "")).lower() != resource.lower():
            continue
        if int(lease.get("since") or 0) < since_epoch:
            continue
        lease_id = str(lease.get("id") or "")
        if lease_id:
            notes.append(release_lease(lease_id))
    return "; ".join(n for n in notes if n)


# ------------------------------------------------------------------- virtual script

def sync_virtual_scripts(backend: Backend, root: str) -> Tuple[bool, str]:
    """Push the local sources to the platform as virtual scripts (no deploy)."""
    sync_script = os.path.join(root, "scripts", "sync_virtual_scripts.py")
    if not os.path.isfile(sync_script):
        return False, "scripts/sync_virtual_scripts.py not found in the checkout"
    suite = os.path.join(root, "test_scripts", "content", f"{SCRIPT_NAME}.py")
    if not os.path.isfile(suite):
        return False, (f"the checkout {root} does not carry test_scripts/content/"
                       f"{SCRIPT_NAME}.py — run the dispatcher from the checkout that has "
                       f"the suite")
    env = os.environ.copy()
    env["SERVER_URL"] = backend.url
    env["TEAM_ID"] = TEAM_ID
    env["AUTO_SIGN_TOKEN"] = backend.token
    if env.get("API_KEY"):
        SECRETS.add(env["API_KEY"])
    command = [sys.executable, "-c", IPV4_PATCH, sync_script, "--scripts", SYNC_SCRIPT_REF]
    try:
        proc = subprocess.run(command, cwd=root, env=env, capture_output=True,
                              text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return False, "the virtual-script sync timed out"
    except OSError as exc:
        return False, f"the virtual-script sync could not run: {type(exc).__name__}"
    if proc.returncode != 0:
        tail = (proc.stdout or "") + (proc.stderr or "")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        detail = SECRETS.redact(lines[-1][:300]) if lines else ""
        return False, f"the virtual-script sync failed (exit {proc.returncode})" \
                      + (f": {detail}" if detail else "")
    return True, ""


def virtual_script_id(backend: Backend) -> str:
    """The id of the virtual script `content_suite` on this backend."""
    payload = backend.get("/server/virtual-script/list", timeout=90)
    scripts = payload.get("scripts") if isinstance(payload, dict) else payload
    for entry in scripts or []:
        if str(entry.get("name") or "") == VIRTUAL_SCRIPT_NAME:
            script_id = str(entry.get("id") or "")
            if script_id:
                return script_id
    raise DispatchError(f"the virtual script {VIRTUAL_SCRIPT_NAME} is not on backend {backend.key}")


def _tree_node_labels(backend: Backend, tree_id: str) -> Set[str]:
    """The node labels of a navigation tree, read from the platform."""
    payload = backend.get(f"/server/navigationTrees/{tree_id}/nodes",
                          params={"team_id": TEAM_ID}, timeout=60)
    nodes = payload.get("nodes") if isinstance(payload, dict) else payload
    return {str(n.get("label")) for n in (nodes or []) if isinstance(n, dict)}


def _best_by_tree(backend: Backend, candidates: List[Dict[str, Any]],
                  required_nodes: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """The candidates whose tree can actually serve the cases.

    The platform hosts many UIs for one device model (21 of them drive the
    'web' model), and the order of the list is not a quality order: the first
    one is an old UI whose tree cannot reach a catalogue item at all. The tree
    is the judge — a UI whose tree carries the nodes the cases drive is the
    one that can answer them.
    """
    scored: List[Tuple[int, Dict[str, Any]]] = []
    ordered = sorted(candidates, key=lambda e: str(e.get("updated_at") or ""), reverse=True)
    for entry in ordered:
        tree_id = str((entry.get("root_tree") or {}).get("id") or "")
        if not tree_id:
            continue
        try:
            labels = _tree_node_labels(backend, tree_id)
        except DispatchError:
            continue
        have = sum(1 for node in required_nodes if node in labels)
        if have:
            scored.append((have, entry))
        if have == len(required_nodes):
            break
    if not scored:
        return []
    best = max(have for have, _ in scored)
    return [entry for have, entry in scored if have == best]


def resolve_userinterface(backend: Backend, device_model: str,
                          required_nodes: Tuple[str, ...] = ()) -> str:
    """The name of the UI that serves a device model, read from the platform.

    The browser UI carries a customer codename, so it is not written in this
    file (the leak gate keeps customer material out of publishable paths). The
    platform knows which UI serves which device model: every UI row lists the
    device models it drives in `models`. The `dev` row wins: it is the one the
    navigation tree is built on.

    With `required_nodes` the tree decides: of the UIs that drive the model,
    the one whose tree carries those nodes is chosen, because a UI whose tree
    cannot reach a catalogue item makes every web case a guess.
    """
    payload = backend.get("/server/userinterface/getAllUserInterfaces", timeout=90)
    entries = payload if isinstance(payload, list) else (payload.get("interfaces")
                                                         or payload.get("userinterfaces")
                                                         or payload.get("data") or [])
    candidates = []
    for entry in entries or []:
        models = entry.get("models") or []
        if isinstance(models, str):
            models = [models]
        if device_model in [str(m) for m in models]:
            candidates.append(entry)
    if not candidates:
        raise DispatchError(f"no UI on backend {backend.key} drives the device model "
                            f"'{device_model}'")
    if required_nodes:
        fitting = _best_by_tree(backend, candidates, required_nodes)
        if fitting:
            candidates = fitting
    dev = [c for c in candidates if str(c.get("mode") or "").lower() == "dev"]
    chosen = (dev or candidates)[0]
    name = str(chosen.get("name") or chosen.get("userinterface_name") or "")
    if not name:
        raise DispatchError(f"the UI for the device model '{device_model}' has no name")
    return name


# ------------------------------------------------------------------------ web login

def mcp_call(backend: Backend, key: str, tool: str, **arguments: Any) -> Tuple[str, bool]:
    """One MCP JSON-RPC tool call. Returns (text, is_error).

    The MCP endpoint wants the Bearer key (the auto-sign token answers 401) and it is
    behind Cloudflare, so `requests` is used (urllib's user-agent is banned).
    """
    if requests is None:
        raise DispatchError("the requests library is missing")
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}
    headers = {"Authorization": f"Bearer {key}",
               "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    url = f"{backend.url}/server/mcp"
    try:
        response = requests.post(url, json=body, headers=headers, timeout=300)
    except requests.RequestException as exc:
        raise DispatchError(f"the MCP call failed: {type(exc).__name__}") from None
    if response.status_code >= 400:
        raise DispatchError(f"the MCP call answered HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not payload:
        # the endpoint may answer text/event-stream
        for line in (response.text or "").splitlines():
            if line.startswith("data:"):
                try:
                    payload = json.loads(line[5:].strip())
                    break
                except ValueError:
                    continue
    if payload.get("error"):
        raise DispatchError("the MCP call was refused")
    result = payload.get("result") or {}
    text = "\n".join(str(c.get("text", "")) for c in result.get("content", [])
                     if c.get("type") == "text")
    return text, bool(result.get("isError"))


def _js_state(text: str) -> Dict[str, Any]:
    """Read the small JSON blob a browser execute_javascript answers with."""
    match = re.search(r'"result":\s*"(\{.*?\})"', text)
    if not match:
        return {}
    try:
        raw = match.group(1).encode().decode("unicode_escape")
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}


def web_login(backend: Backend, target: Target, account: Dict[str, str]) -> None:
    """Make sure the browser of this host is logged in before the web job.

    The login is the one from WEB_UI_ORCHTNET.md §1: the SSO page (Keycloak) with the
    fields #username and #password and the button #kc-login. The password goes into a
    device action, never into a script parameter (those are persisted in the database)
    and never into a log line.
    """
    key = mcp_secret_key()
    token = auto_sign_token()
    atlas = _atlas_chat()
    session_id = atlas.create_session(backend.url, True, token)
    atlas.take_device_control(backend.url, True, token, target.host_name,
                              target.device_id, session_id)
    try:
        _, is_error = mcp_call(
            backend, key, "execute_device_action",
            host_name=target.host_name, device_id=target.device_id, session_id=session_id,
            actions=[{"command": "open_browser", "params": {"wait_time": 2000}}])
        if is_error:
            raise DispatchError("the browser would not open on this host")

        probe = ("JSON.stringify({u: localStorage.getItem('flutter.username'), "
                 "href: location.href})")
        state = _browser_state(backend, key, target, session_id, account, probe)
        if state.get("u"):
            emit(f"[web] {target.resource}: the browser session is already logged in")
            return

        # The app opens the SSO page when it is logged out.
        actions = [
            {"command": "input_text",
             "params": {"selector": "#username", "text": account["VPTTV_LOGIN"]}},
            {"command": "input_text",
             "params": {"selector": "#password", "text": account["VPTTV_PASSWORD"]}},
            {"command": "click_element",
             "params": {"selector": "#kc-login", "wait_time": 6000}},
        ]
        _, is_error = mcp_call(
            backend, key, "execute_device_action",
            host_name=target.host_name, device_id=target.device_id, session_id=session_id,
            actions=actions)
        if is_error:
            raise DispatchError("the SSO login was refused on this host")

        state = _browser_state(backend, key, target, session_id, account, probe)
        if not state.get("u"):
            raise DispatchError("the browser session is still not logged in after the SSO login")
        emit(f"[web] {target.resource}: the browser session is logged in")
    finally:
        # The device control is given back whatever happens.
        try:
            atlas.release_device_control(backend.url, True, token, target.host_name,
                                         target.device_id, session_id)
        except Exception:  # noqa: BLE001 - the release must never mask the real error
            pass


def _browser_state(backend: Backend, key: str, target: Target, session_id: str,
                   account: Dict[str, str], probe: str) -> Dict[str, Any]:
    text, _ = mcp_call(
        backend, key, "execute_device_action",
        host_name=target.host_name, device_id=target.device_id, session_id=session_id,
        actions=[{"command": "navigate_to_url", "params": {"url": account["VPTTV_URL"]}},
                 {"command": "execute_javascript", "params": {"script": probe}}])
    return _js_state(text)


def _atlas_chat():
    """scripts/atlas_chat.py: the session + device-control calls of the platform."""
    root = repo_root()
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import atlas_chat  # type: ignore
    except ImportError as exc:
        raise DispatchError("scripts/atlas_chat.py is not importable "
                            "(python-socketio missing?)") from exc
    return atlas_chat


# -------------------------------------------------------------------------- the job

def skip_rows(target: Target, cases: Sequence[str], reason: str,
              cause: str = CAUSE_INFRA, status: str = STATUS_SKIP) -> List[Dict[str, Any]]:
    """One row per case, so the counts of the report always add up."""
    return [{"case": case, "platform": target.platform, "host": target.host_name,
             "device": target.device, "status": status, "cause": cause,
             "duration_s": 0.0, "reason": reason} for case in cases]


@dataclass
class JobOutcome:
    target: Target
    state: str = "ok"           # ok | skipped_busy | skipped_infra | failed
    rows: List[Dict[str, Any]] = field(default_factory=list)
    lease_id: str = ""
    task_id: str = ""
    reason: str = ""
    duration_s: float = 0.0


class Runner:
    """The whole run: the plan, the leases, the jobs and the report."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.cases = list(args.cases)
        self.targets = select_targets(args.only)
        self.parallel_targets = [t for t in self.targets if t.platform != WEB_PLATFORM]
        self.web_targets = [t for t in self.targets if t.platform == WEB_PLATFORM]
        self.max_parallel = args.max_parallel if args.max_parallel else len(self.parallel_targets)
        self.max_parallel = max(1, min(self.max_parallel, max(1, len(self.parallel_targets))))
        self.backends: Dict[str, Backend] = {}
        self.synced: Dict[str, bool] = {}
        self.sync_errors: Dict[str, str] = {}
        self.script_ids: Dict[str, str] = {}
        self.ui_names: Dict[str, str] = {}    # "<backend>:<model>" -> UI name
        self._sync_lock = threading.Lock()
        self._id_lock = threading.Lock()
        self.outcomes: List[JobOutcome] = []
        self._outcome_lock = threading.Lock()
        # When this run began: a result row from before it belongs to another
        # run and must never end up in this run's report.
        self.run_started_epoch = utc_iso()

    # -------------------------------------------------------------- preparation

    def ui_name_for(self, target: Target) -> str:
        """The UI to test on this target: the one named in the plan, or the one
        the platform says drives this device model (resolved once, cached)."""
        if target.userinterface:
            return target.userinterface
        model = target.device_model or target.platform
        key = f"{target.backend}:{model}"
        with self._id_lock:
            cached = self.ui_names.get(key)
        if cached:
            return cached
        backend = self.backend_for(target)
        required = WEB_REQUIRED_NODES if target.platform == WEB_PLATFORM else ()
        name = resolve_userinterface(backend, model, required)
        with self._id_lock:
            self.ui_names[key] = name
        return name

    def backend_for(self, target: Target) -> Backend:
        with self._id_lock:
            backend = self.backends.get(target.backend)
            if backend is None:
                token = auto_sign_token()
                backend = Backend(target.backend, target.backend_url, token)
                self.backends[target.backend] = backend
            return backend

    def ensure_ready(self, target: Target) -> None:
        """The virtual script must exist on the backend of this target (once per backend)."""
        backend = self.backend_for(target)
        with self._sync_lock:
            if target.backend not in self.synced:
                if self.args.no_sync:
                    self.synced[target.backend] = True
                    self.sync_errors[target.backend] = ""
                else:
                    ok, detail = sync_virtual_scripts(backend, repo_root())
                    self.synced[target.backend] = ok
                    self.sync_errors[target.backend] = detail
                    if not ok:
                        raise DispatchError(detail or "the virtual script could not be pushed "
                                                       f"to backend {target.backend}")
                    emit(f"[sync] backend {target.backend}: {SCRIPT_NAME} pushed as a "
                         f"virtual script")
            elif not self.synced[target.backend]:
                raise DispatchError(self.sync_errors.get(target.backend)
                                    or f"the virtual script could not be pushed to backend "
                                       f"{target.backend}")
            if target.backend not in self.script_ids:
                self.script_ids[target.backend] = virtual_script_id(backend)

    def parameters_for(self, target: Target) -> str:
        """The parameter string of the script. NEVER a password: parameters are persisted.

        `--device` is not optional: the script picks the device from it
        (`args.device or default_device or "host"`), and without it the run
        lands on the host device or on the first device of the host — the
        wrong box, under our lease. `--host` is tolerated by the framework.
        """
        parts = [f"--cases {','.join(self.cases)}", f"--platform {target.platform}",
                 f"--host {target.host_name}", f"--device {target.device_id}"]
        ui = self.ui_name_for(target)
        if ui:
            parts.append(f"--userinterface {ui}")
        for extra in self.args.param:
            name, _, value = str(extra).partition("=")
            name = name.strip().lstrip("-")
            value = value.strip()
            if not name:
                continue
            parts.append(f"--{name} {value}")
        parameters = " ".join(parts)
        if SECRETS.contains(parameters):
            raise DispatchError("refusing to send a secret as a script parameter")
        return parameters

    # ------------------------------------------------------------------ the job

    def run_target(self, target: Target) -> JobOutcome:
        started = time.time()
        outcome = JobOutcome(target=target)
        lease_id = ""
        claim_started = int(time.time())
        try:
            lease = claim_lease(target.resource, self.args.lease_wait_s)
            if not lease.granted:
                outcome.state = "skipped_busy" if lease.busy else "skipped_infra"
                outcome.reason = lease.reason
                outcome.rows = skip_rows(target, self.cases, lease.reason)
                if lease.busy:
                    release_own_lease_for(target.resource, claim_started)
                return outcome
            lease_id = lease.lease_id
            outcome.lease_id = lease_id

            backend = self.backend_for(target)
            self.ensure_ready(target)

            if target.platform == WEB_PLATFORM:
                account = web_account()
                # The SSO login is a courtesy, not a condition: the app keeps
                # working for a guest (its own sign-in bypass), so a host that
                # refuses the login still gets a run — as a guest. Skipping the
                # whole target would hide the web platform behind one refused
                # login.
                try:
                    web_login(backend, target, account)
                except DispatchError as exc:
                    emit(f"[web] {target.resource}: the account login was refused "
                         f"({SECRETS.redact(str(exc))}); the run continues as a guest")

            rows, task_id, reason = self.launch_and_collect(target, backend)
            outcome.rows = rows
            outcome.task_id = task_id
            outcome.reason = reason
            outcome.state = "ok"
            return outcome
        except DispatchError as exc:
            outcome.state = "skipped_infra"
            outcome.reason = SECRETS.redact(str(exc))
            outcome.rows = skip_rows(target, self.cases, outcome.reason)
            return outcome
        except Exception as exc:  # noqa: BLE001 - a crash is infra, never a product defect
            outcome.state = "skipped_infra"
            outcome.reason = SECRETS.redact(f"{type(exc).__name__}: {exc}")
            outcome.rows = skip_rows(target, self.cases, outcome.reason)
            return outcome
        finally:
            # The lease is released on EVERY exit path: success, failure, exception, Ctrl-C.
            if lease_id:
                problem = release_lease(lease_id)
                if problem:
                    emit(f"[lease] {target.resource}: {problem}")
            outcome.duration_s = round(time.time() - started, 2)

    def launch_and_collect(self, target: Target, backend: Backend) -> Tuple[List[Dict[str, Any]],
                                                                         str, str]:
        """Launch the virtual script on this device and collect its case rows."""
        script_id = self.script_ids.get(target.backend)
        if not script_id:
            script_id = virtual_script_id(backend)
            with self._sync_lock:
                self.script_ids[target.backend] = script_id
        body = {
            "host_name": target.host_name,
            "device_id": target.device_id,
            "script_name": SCRIPT_NAME,
            "virtual_script_id": script_id,
            "parameters": self.parameters_for(target),
            # A busy device is refused, not queued: a queued run would start after this
            # job released its lease, on a device another session may be using.
            "queue_if_locked": False,
        }
        answer = backend.post("/server/script/execute", body=body, timeout=180)
        task_id = str((answer or {}).get("task_id") or "")
        if not task_id:
            raise DispatchError("the backend did not return a task id for the launch")
        emit(f"[run] {target.resource}: {SCRIPT_NAME} started (task {task_id})")

        deadline = time.time() + self.args.job_timeout_s
        task: Dict[str, Any] = {}
        while True:
            status = backend.get(f"/server/script/status/{task_id}", timeout=60)
            task = (status or {}).get("task") or {}
            state = str(task.get("status") or "")
            if state in ("completed", "failed"):
                break
            if time.time() > deadline:
                # the script is overrunning on the device: abort it there, so it
                # does not keep the device locked after this job gives up
                abort_running_script(backend, target, task_id)
                raise DispatchError(f"the script did not finish within {self.args.job_timeout_s}s")
            time.sleep(self.args.poll_s)

        result = task.get("result") or {}
        rows = self.rows_from_metadata(backend, target, result)
        source = "metadata.content_cases"
        if not rows:
            rows = self.rows_from_logs(result)
            source = "stdout VPT_CASE_RESULT lines"
        if not rows:
            reason = "the script produced no case row"
            error = str(result.get("error") or "")
            if error:
                reason = f"{reason}: {SECRETS.redact(error[:200])}"
            raise DispatchError(reason)
        emit(f"[run] {target.resource}: {len(rows)} case rows ({source})")
        return rows, task_id, source

    def rows_from_metadata(self, backend: Backend, target: Target,
                           result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The rows of the persisted script result: metadata.content_cases.

        The result of THIS job only. The endpoint lists the results of every
        run of that script on that host, newest first, so picking "the first
        one with case rows" can silently return an OLDER run's rows — which
        would put another run's verdict in this run's report. The job's own
        script_result_id is the only exact key; without it, the candidate must
        at least belong to this run (same parameters, started after the run
        began). No match means no rows.
        """
        script_result_id = str(result.get("script_result_id") or "")
        try:
            payload = backend.get("/server/script-results/getAllScriptResults",
                                  params={"script_name": SCRIPT_NAME,
                                          "host_name": target.host_name,
                                          "limit": 50}, timeout=90)
        except DispatchError:
            return []
        rows = payload if isinstance(payload, list) else (payload or {}).get("results") or []
        candidates = [r for r in rows if isinstance(r, dict)]
        if script_result_id:
            candidates = [r for r in candidates if str(r.get("id") or "") == script_result_id]
        else:
            wanted_device = f"--device {target.device_id}"
            started_after = self.run_started_epoch
            fresh = []
            for candidate in candidates:
                metadata = candidate.get("metadata")
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except ValueError:
                        metadata = {}
                parameters = str((metadata or {}).get("parameters") or "")
                started_at = str(candidate.get("started_at") or "")
                if wanted_device not in parameters:
                    continue
                if started_after and started_at and started_at < started_after:
                    continue
                fresh.append(candidate)
            candidates = fresh
        for candidate in candidates:
            metadata = candidate.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except ValueError:
                    metadata = {}
            if isinstance(metadata, dict):
                cases = metadata.get("content_cases")
                if isinstance(cases, list) and cases:
                    return [c for c in cases if isinstance(c, dict)]
        return []

    def rows_from_logs(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fallback: the VPT_CASE_RESULT lines of the script stdout (the uploaded log)."""
        logs_url = str(result.get("logs_url") or "")
        if not logs_url or requests is None:
            return []
        try:
            response = requests.get(logs_url, timeout=180)
        except requests.RequestException:
            return []
        if response.status_code >= 400:
            return []
        rows: List[Dict[str, Any]] = []
        for line in (response.text or "").splitlines():
            if RESULT_MARKER not in line:
                continue
            payload = line.split(RESULT_MARKER, 1)[1].strip()
            try:
                row = json.loads(payload)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    # ------------------------------------------------------------------- the run

    def run(self) -> int:
        started = time.time()
        self.print_plan()
        if self.args.dry_run:
            emit("[dry-run] nothing was claimed, pushed, launched or written.")
            return 0

        out_dir = prepare_out_dir(self.args.out)
        emit(f"[run] report directory: {out_dir}")
        try:
            # Phase 1: STB and mobile, in parallel. One whole device per job.
            if self.parallel_targets:
                emit(f"[run] phase 1: {len(self.parallel_targets)} STB/mobile jobs, "
                     f"max {self.max_parallel} at a time")
                pool = futures.ThreadPoolExecutor(max_workers=self.max_parallel)
                try:
                    for outcome in pool.map(self.run_target, self.parallel_targets):
                        self.record(outcome)
                finally:
                    # A Ctrl-C must not wait for the in-flight jobs: they hold the
                    # device leases, and a lease held while nobody works blocks
                    # everybody. wait=False lets the threads unwind on their own
                    # (each releases its own lease in its finally), and
                    # cancel_futures stops the jobs that have not started.
                    pool.shutdown(wait=False, cancel_futures=True)

            # Phase 2: the web platform, strictly sequential (one account, one session).
            if self.web_targets:
                emit(f"[run] phase 2: {len(self.web_targets)} web jobs, one at a time "
                     f"(the account has a device limit)")
                for target in self.web_targets:
                    self.record(self.run_target(target))
        finally:
            # The report is written even when the run is interrupted: what was measured
            # is worth more than a clean exit.
            rows: List[Dict[str, Any]] = []
            for outcome in self.outcomes:
                rows.extend(outcome.rows)
            write_reports(out_dir, rows, self.outcomes, self)
            emit(f"[run] report written in {out_dir}")
        emit(f"[run] done in {round(time.time() - started, 1)}s — {out_dir}")
        return 0

    def record(self, outcome: JobOutcome) -> None:
        with self._outcome_lock:
            self.outcomes.append(outcome)
        label = {"ok": "done", "skipped_busy": "skipped (busy)",
                 "skipped_infra": "skipped (infra)", "failed": "failed"}.get(outcome.state,
                                                                             outcome.state)
        emit(f"[{label}] {outcome.target.resource} "
             f"({len(outcome.rows)} rows)"
             + (f" — {outcome.reason}" if outcome.reason else ""))

    # ------------------------------------------------------------------- the plan

    def print_plan(self) -> None:
        emit(f"Fleet plan — content-surface suite ({', '.join(self.cases)})")
        emit("")
        emit("Backends:")
        emit(f"  A  {BACKEND_A_URL}  (node1)")
        emit(f"  B  {BACKEND_B_URL}  (the Pi site, IPv4 forced)")
        emit("")
        emit(f"Phase 1 — parallel (STB + mobile), max {self.max_parallel} at a time"
             if self.parallel_targets else "Phase 1 — parallel (STB + mobile): no target selected")
        emit(f"  {'#':>2}  {'platform':<7} {'be':<3} {'host/device':<22} {'device':<13} "
             f"{'userinterface':<19} lease resource")
        for index, target in enumerate(self.parallel_targets, 1):
            emit(f"  {index:>2}  {target.platform:<7} {target.backend:<3} "
                 f"{target.resource:<22} {target.device:<13} {ui_label(target):<19} "
                 f"{LEASE_ENV} {target.resource}")
        if not self.parallel_targets:
            emit("  (none)")
        emit("")
        emit("Phase 2 — sequential (web: one account, one session, device limit)")
        emit(f"  {'#':>2}  {'platform':<7} {'be':<3} {'host/device':<22} {'device':<13} "
             f"{'userinterface':<19} lease resource")
        for index, target in enumerate(self.web_targets, 1):
            emit(f"  {index:>2}  {target.platform:<7} {target.backend:<3} "
                 f"{target.resource:<22} {target.device:<13} {ui_label(target):<19} "
                 f"{LEASE_ENV} {target.resource}")
        if not self.web_targets:
            emit("  (none)")
        emit("")
        emit("Lease per job (never --force, released on every exit path):")
        emit(f"  ssh proxmox '~/bin/vpt-lease claim {LEASE_ENV} <host>/<device> "
             f"--agent {LEASE_AGENT_RUN} --provider {LEASE_PROVIDER} --kind server "
             f"--purpose \"{LEASE_PURPOSE}\" --ttl {LEASE_TTL_MIN} --wait'")
        emit(f"  ssh proxmox '~/bin/vpt-lease release <lease-id>'")
        emit("")
        emit("Virtual script (no deploy): scripts/sync_virtual_scripts.py "
             f"--scripts {SYNC_SCRIPT_REF}, then POST /server/script/execute.")


# -------------------------------------------------------------------------- targets

def select_targets(only: Sequence[str]) -> List[Target]:
    """The targets of this run: every one, or the ones the selectors match.

    A selector is a platform (web, mobile, stb), a host (vpt-pi1) or a host/device
    (vpt-pi1/device3). A bare device id is NOT a selector: `device3` exists on two
    hosts and would be ambiguous.
    """
    if not only:
        return list(TARGETS)
    wanted = [str(o).strip().lower() for o in only if str(o).strip()]
    selected: List[Target] = []
    for target in TARGETS:
        for selector in wanted:
            if selector in (target.platform, target.host_name.lower(),
                            target.resource.lower()):
                selected.append(target)
                break
    # keep the fleet order, without duplicates
    seen = set()
    ordered = []
    for target in selected:
        if target.resource not in seen:
            seen.add(target.resource)
            ordered.append(target)
    return ordered


def print_target_table() -> None:
    emit(f"{'platform':<8} {'be':<3} {'host':<16} {'device_id':<10} {'device':<13} "
         f"{'userinterface':<19} lease resource")
    for target in TARGETS:
        emit(f"{target.platform:<8} {target.backend:<3} {target.host_name:<16} "
             f"{target.device_id:<10} {target.device:<13} {ui_label(target):<19} "
             f"{LEASE_ENV} {target.resource}")
    emit("")
    emit(f"{len(TARGETS)} targets — "
         f"{sum(1 for t in TARGETS if t.platform != WEB_PLATFORM)} STB/mobile (parallel), "
         f"{sum(1 for t in TARGETS if t.platform == WEB_PLATFORM)} web (strictly sequential)")


# ------------------------------------------------------------------------- report

def prepare_out_dir(out: Optional[str]) -> str:
    base = out or os.path.expanduser(f"~/vpt-deliverables/vod-radio-runs/{utc_stamp()}")
    os.makedirs(base, exist_ok=True)
    return base


def _counts(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_SKIP: 0}
    for row in rows:
        status = str(row.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _redact_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The raw case rows, with any secret masked (there should be none)."""
    clean: List[Dict[str, Any]] = []
    for row in rows:
        item: Dict[str, Any] = {}
        for key, value in row.items():
            item[key] = SECRETS.redact(value) if isinstance(value, str) else value
        clean.append(item)
    return clean


def write_reports(out_dir: str, rows: List[Dict[str, Any]],
                  outcomes: Sequence[JobOutcome], runner: Runner) -> Tuple[str, str]:
    """One JSON file (every raw case row) and one Markdown file (the human summary)."""
    json_path = os.path.join(out_dir, "content_cases.json")
    md_path = os.path.join(out_dir, "report.md")

    payload = {
        "run_started_utc": utc_iso(),
        "team_id": TEAM_ID,
        "script_name": SCRIPT_NAME,
        "cases": runner.cases,
        "targets": [t.resource for t in runner.targets],
        "backends": BACKEND_URLS,
        "lease": {"env": LEASE_ENV, "agent": LEASE_AGENT_RUN, "ttl_min": LEASE_TTL_MIN},
        "rows": _redact_rows(rows),
        "jobs": [{"target": o.target.resource, "platform": o.target.platform,
                  "backend": o.target.backend, "state": o.state,
                  "lease_id": o.lease_id, "task_id": o.task_id,
                  "reason": SECRETS.redact(o.reason), "duration_s": o.duration_s}
                 for o in outcomes],
    }
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)

    markdown = build_markdown(rows, outcomes, runner)
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    return json_path, md_path


def build_markdown(rows: Sequence[Dict[str, Any]], outcomes: Sequence[JobOutcome],
                   runner: Runner) -> str:
    lines: List[str] = []
    lines.append("# Content-surface suite — fleet run")
    lines.append("")
    lines.append(f"*Cases: {', '.join(runner.cases)}*  ")
    lines.append(f"*Targets: {len(runner.targets)} "
                 f"({len(runner.parallel_targets)} STB/mobile in parallel, "
                 f"{len(runner.web_targets)} web sequential)*  ")
    lines.append(f"*Generated: {utc_iso()}*")
    lines.append("")

    # ---------------------------------------------------------------- counts
    platforms = ["web", "mobile", "stb"]
    lines.append("## Results")
    lines.append("")
    lines.append("| platform | PASS | FAIL | SKIP | total |")
    lines.append("|---|---|---|---|---|")
    for platform in platforms:
        subset = [r for r in rows if str(r.get("platform")) == platform]
        if not subset:
            continue
        counts = _counts(subset)
        lines.append(f"| {platform} | {counts[STATUS_PASS]} | {counts[STATUS_FAIL]} | "
                     f"{counts[STATUS_SKIP]} | {len(subset)} |")
    overall = _counts(rows)
    lines.append(f"| **overall** | **{overall[STATUS_PASS]}** | **{overall[STATUS_FAIL]}** | "
                 f"**{overall[STATUS_SKIP]}** | **{len(rows)}** |")
    lines.append("")

    # ------------------------------------------------------- failures by cause
    failures = [r for r in rows if str(r.get("status")) == STATUS_FAIL]
    product = [r for r in failures if str(r.get("cause")) == CAUSE_PRODUCT]
    infra = [r for r in failures if str(r.get("cause")) == CAUSE_INFRA]
    coverage = [r for r in failures if str(r.get("cause")) == CAUSE_COVERAGE]
    other = [r for r in failures if str(r.get("cause")) not in
             (CAUSE_PRODUCT, CAUSE_INFRA, CAUSE_COVERAGE)]

    lines.append("## Failures by cause")
    lines.append("")
    lines.append(f"* {len(product)} product defect(s), {len(infra)} infra problem(s), "
                 f"{len(coverage)} coverage gap(s), {len(other)} unattributed.")
    lines.append("")

    lines.append(f"### Product defects — {len(product)}")
    lines.append("")
    if product:
        lines.append("Real product bugs. These are the ones to fix.")
        lines.append("")
        lines.append("| case | platform | host | device | cause | reason |")
        lines.append("|---|---|---|---|---|---|")
        for row in product:
            lines.append(_failure_line(row))
    else:
        lines.append("None.")
    lines.append("")

    lines.append(f"### Infra problems — {len(infra)}")
    lines.append("")
    lines.append("**These are NOT product defects.** Lease, deploy, connectivity, "
                 "geo-block and session problems live here. Nothing in this section "
                 "says the product is broken.")
    lines.append("")
    if infra:
        lines.append("| case | platform | host | device | cause | reason |")
        lines.append("|---|---|---|---|---|---|")
        for row in infra:
            lines.append(_failure_line(row))
    else:
        lines.append("None.")
    lines.append("")

    lines.append(f"### Coverage gaps — {len(coverage)}")
    lines.append("")
    lines.append("The surface was not reachable or not mapped for that case. "
                 "Not a product defect either, but not a pass.")
    lines.append("")
    if coverage:
        lines.append("| case | platform | host | device | cause | reason |")
        lines.append("|---|---|---|---|---|---|")
        for row in coverage:
            lines.append(_failure_line(row))
    else:
        lines.append("None.")
    lines.append("")

    if other:
        lines.append(f"### Unattributed failures — {len(other)}")
        lines.append("")
        lines.append("| case | platform | host | device | cause | reason |")
        lines.append("|---|---|---|---|---|---|")
        for row in other:
            lines.append(_failure_line(row))
        lines.append("")

    # ------------------------------------------------------------ skipped rows
    skipped = [r for r in rows if str(r.get("status")) == STATUS_SKIP]
    if skipped:
        lines.append(f"## Skipped cases — {len(skipped)}")
        lines.append("")
        lines.append("| case | platform | host | device | cause | reason |")
        lines.append("|---|---|---|---|---|---|")
        for row in skipped:
            lines.append(_failure_line(row))
        lines.append("")

    # ------------------------------------------------------- busy targets
    busy = [o for o in outcomes if o.state == "skipped_busy"]
    lines.append(f"## Targets skipped because they were busy — {len(busy)}")
    lines.append("")
    if busy:
        lines.append("| target | platform | backend | reason |")
        lines.append("|---|---|---|---|")
        for outcome in busy:
            lines.append(f"| {outcome.target.resource} | {outcome.target.platform} | "
                         f"{outcome.target.backend} | {_clean(outcome.reason)} |")
    else:
        lines.append("None — every target was leased.")
    lines.append("")

    # --------------------------------------------------------------- the jobs
    lines.append("## Jobs")
    lines.append("")
    lines.append("| target | platform | backend | state | cases | lease | task | note |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for outcome in outcomes:
        lines.append(
            f"| {outcome.target.resource} | {outcome.target.platform} | {outcome.target.backend} | "
            f"{outcome.state} | {len(outcome.rows)} | {outcome.lease_id or '-'} | "
            f"{outcome.task_id or '-'} | {_clean(outcome.reason)} |")
    lines.append("")

    lines.append("## How to read this report")
    lines.append("")
    lines.append("* `cause=product` — a defect of the product under test.")
    lines.append("* `cause=infra` — the run could not reach the product (lease, deploy, "
                 "connectivity, geo-block, session). **NOT a product defect.**")
    lines.append("* `cause=coverage` — the surface was not reachable or not mapped for that "
                 "case. Not a product defect, not a pass.")
    lines.append("* A SKIP is never counted as a pass.")
    lines.append("")
    return "\n".join(lines) + "\n"


def _failure_line(row: Dict[str, Any]) -> str:
    return (f"| {row.get('case', '')} | {row.get('platform', '')} | {row.get('host', '')} | "
            f"{row.get('device', '')} | {row.get('cause', '')} | {_clean(row.get('reason', ''))} |")


def _clean(value: Any) -> str:
    text = SECRETS.redact(str(value if value is not None else ""))
    text = text.replace("|", "\\|").replace("\n", " ").strip()
    return text[:300]


# ----------------------------------------------------------------------------- CLI

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fleet fan-out runner for the content-surface suite "
                    "(radio / replay / VOD / recording).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", default=[],
                        metavar="SELECTOR",
                        help="restrict the run: a platform (web, mobile, stb), "
                             "a host (vpt-pi1) or a host/device (vpt-pi1/device3). "
                             "Repeatable.")
    parser.add_argument("--cases", default=",".join(ALL_CASES),
                        help="comma-separated cases to run: " + ",".join(ALL_CASES))
    parser.add_argument("--max-parallel", type=int, default=0, metavar="N",
                        help="how many STB/mobile jobs run at the same time "
                             "(default: the number of STB/mobile targets; the web "
                             "platform always runs alone)")
    parser.add_argument("--out", default="",
                        help="run directory for the JSON rows and the Markdown summary "
                             "(default: ~/vpt-deliverables/vod-radio-runs/<UTC timestamp>/)")
    parser.add_argument("--list", action="store_true",
                        help="print the target table and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan (targets, leases, order) and exit without "
                             "touching anything")
    parser.add_argument("--no-sync", action="store_true",
                        help="do not push the virtual script (it must already be on the "
                             "backends)")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                        help="extra script argument, e.g. --param record_wait_s=30 "
                             "(never a secret: parameters are persisted)")
    parser.add_argument("--lease-wait-s", type=int, default=300, metavar="SECONDS",
                        help="how long a busy lease is waited for before the target is "
                             "skipped as an infra skip (never forced)")
    parser.add_argument("--lease-ttl", type=int, default=LEASE_TTL_MIN, metavar="MINUTES",
                        help="lease TTL in minutes")
    parser.add_argument("--job-timeout-s", type=int, default=1800, metavar="SECONDS",
                        help="how long one script run may take before it is an infra skip")
    parser.add_argument("--poll-s", type=int, default=10, metavar="SECONDS",
                        help="how often the script status is polled")
    parser.add_argument("--no-ipv4", action="store_true",
                        help="do not force IPv4 (the Pi backend needs it)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    cases = [c.strip().lower() for c in str(args.cases).split(",") if c.strip()]
    unknown = [c for c in cases if c not in ALL_CASES]
    if unknown:
        print(f"unknown case(s): {', '.join(unknown)} (known: {', '.join(ALL_CASES)})",
              file=sys.stderr)
        return 2
    args.cases = cases or list(ALL_CASES)

    if args.list:
        print_target_table()
        return 0

    if not args.no_ipv4:
        force_ipv4()

    runner = Runner(args)
    if not runner.targets:
        emit("no target matches the selection")
        return 2

    try:
        return runner.run()
    except KeyboardInterrupt:
        emit("interrupted — every lease that was held has been released")
        return 130
    except BrokenPipeError:
        # the output was piped into something that closed (head): leave quietly
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
