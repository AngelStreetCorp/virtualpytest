"""Database item of Platform update step 1 (TASK-109): ask the database VM for a fresh backup.

The server never runs ``pg_dump`` itself: its client may be older than the database (Debian 12 ships 15, the lab
database is 17), and ``pg_dump`` refuses a newer server. The database VM already makes the right backup
(``/usr/local/bin/vpt-db-backup.sh``: ``docker exec ... pg_dump -F c`` with the database's own version) every night and
reports it to ``POST /server/system/backup/report``. The VM agent (infra/vm_agent/README.md) can start that same script on
request:

  POST /actions/db-backup  (header X-VM-Agent-Token)  -> 202, the script runs in the background
  GET  /actions/db-backup                              -> {running, exit_code, log_tail, ...}

The agent address and the token come from ``settings.get`` (Platform update -> Settings, else the ``database`` entry of
``INFRA_VM_AGENTS`` and ``VM_AGENT_ACTION_TOKEN`` in the .env). Without
both, the last nightly report is used: OK when it is younger than 24 h, KO otherwise. Everything that touches the
network or the clock goes through ``Deps`` so the tests mock it.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import settings

AGENT_NAME = 'database'
AGENT_ACTION_PATH = '/actions/db-backup'
POLL_SECONDS = 5
TIMEOUT_SECONDS = 20 * 60
REPORT_GRACE_SECONDS = 60          # the script exited 0 but its report has not reached the server yet
AGENT_HTTP_TIMEOUT = 10
MAX_AGE_HOURS = 24
MAX_AGENT_ERRORS = 3
FIX_RUN_ON_VM = 'Run on the database VM: sudo bash /usr/local/bin/vpt-db-backup.sh'
FIX_AGENT = ('Platform update -> Settings -> Set up DB backup: it makes the token and shows the one command to run on the '
             'database VM (or VM_AGENT_ACTION_TOKEN in the server .env). Or run on the database VM: sudo bash /usr/local/bin/vpt-db-backup.sh')


def _http(method: str, url: str, headers: Dict[str, str], timeout: int) -> Tuple[int, Any]:
    req = urllib.request.Request(url, method=method, headers=headers, data=b'' if method == 'POST' else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw or b'{}')
    except ValueError:
        return status, {}


def _report() -> dict:
    from backend_server.src.routes.server_system_routes import get_db_backup_status
    return get_db_backup_status()


@dataclass
class Deps:
    env: Dict[str, str] = field(default_factory=lambda: dict(os.environ))
    http: Callable[[str, str, Dict[str, str], int], Tuple[int, Any]] = _http
    report: Callable[[], dict] = _report
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)  # noqa: E731
    sleep: Callable[[float], None] = time.sleep
    poll_seconds: float = POLL_SECONDS
    timeout_seconds: float = TIMEOUT_SECONDS


def agent_address(env: Dict[str, str]) -> str:
    """host:port of the ``database`` entry of INFRA_VM_AGENTS, '' when there is none."""
    return settings.get('database_agent', env)


def _agent(deps: Deps) -> Tuple[str, str]:
    return agent_address(deps.env), settings.get('vm_agent_action_token', deps.env)


def _call(deps: Deps, method: str, address: str, token: str) -> Tuple[int, Any]:
    return deps.http(method, f'http://{address}{AGENT_ACTION_PATH}', {'X-VM-Agent-Token': token}, AGENT_HTTP_TIMEOUT)


def _parse(ts: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _reported(rep: dict) -> Optional[datetime]:
    """When the report reached the server (server clock); the VM's own timestamp only when that is missing."""
    return _parse(rep.get('reported_at')) or _parse(rep.get('timestamp_iso'))


def _size(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f'{value / 1024 ** 2:.0f} MB' if value >= 1024 ** 2 else f'{int(value)} B'
    return str(value or '?')


def _line(rep: dict, suffix: str = '') -> str:
    nfs = 'yes' if rep.get('nfs_copy') else 'no'
    return f'{rep.get("filename") or "?"} · {_size(rep.get("size"))} · NFS copy {nfs}{suffix}'


def _age(rep: dict, deps: Deps) -> Optional[float]:
    when = _parse(rep.get('timestamp_iso')) or _reported(rep)
    return None if when is None else (deps.now() - when).total_seconds() / 3600


def _human_age(hours: float) -> str:
    return f'{int(hours * 60)} min' if hours < 1 else f'{hours:.0f} h'


def last_report_state(deps: Deps) -> Tuple[bool, str, dict]:
    """(fresh, text, report): is the last nightly report younger than 24 h."""
    try:
        rep = deps.report() or {}
    except Exception as exc:
        return False, f'The backup report cannot be read ({type(exc).__name__}).', {}
    if not rep.get('filename'):
        return False, 'The database VM has never reported a backup.', {}
    hours = _age(rep, deps)
    if hours is None:
        return False, 'The last backup report has no readable date.', rep
    text = f'last nightly backup {_human_age(hours)} ago'
    return hours < MAX_AGE_HOURS, text, rep


def agent_answers(deps: Deps) -> Tuple[bool, str]:
    """Does the agent action answer to this server's token. -> (ok, why)."""
    address, token = _agent(deps)
    if not (address and token):
        return False, 'no agent address or token configured'
    try:
        status, _ = _call(deps, 'GET', address, token)
    except Exception as exc:
        return False, f'{address} does not answer ({type(exc).__name__})'
    if status == 200:
        return True, f'{address} accepts backup requests'
    return False, {401: 'token refused (HTTP 401)', 404: 'action not enabled on the agent (HTTP 404)'}.get(status, f'HTTP {status}')


# -- set-up from the page (TASK-128 G2) ----------------------------------------------------------------------------
TOKEN_FILE = '/root/vm_agent_token'
KEEP_CONTAINERS = '<your existing --containers value>'


def server_ip(address: str) -> str:
    """This server's address as the database VM sees it (the interface that routes to ``address``), '' when unknown.
    A UDP connect sends nothing."""
    import socket
    try:
        host, port = address.rsplit(':', 1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((host, int(port)))
            return sock.getsockname()[0]
    except (OSError, ValueError):
        return ''


def setup_command(token: str, project_root: str, allow_ip: str = '') -> str:
    """The one line to run as root on the database VM. The token is only in this string, shown once."""
    allow = allow_ip or '<this server IP>'
    return (f"(umask 077; printf '%s' '{token}' > {TOKEN_FILE}) && "
            f"{project_root.rstrip('/')}/infra/vm_agent/install.sh --containers '{KEEP_CONTAINERS}' --allow {allow} "
            f"--action db-backup --action-token-file {TOKEN_FILE}")


DB_CONTAINER = 'supabase_db_supabase'
DB_BACKUP_DIR = '/data/backups'
_DUMP_RE = re.compile(r'\b(vpt_postgres_[0-9_]+\.dump)\b')


def restore_command(detail: str) -> str:
    """TASK-128 G7: the command to restore the dump named in the backup item, for root on the database VM. '' when no
    file name is found. Shown, never run: it replaces the whole database (docs/agent/infra/DATABASE.md, "Restore a
    specific dump"; the dump and the container are the ones ``vpt-db-backup.sh`` writes and uses)."""
    match = _DUMP_RE.search(detail or '')
    if not match:
        return ''
    c = DB_CONTAINER
    return (f'docker cp {DB_BACKUP_DIR}/{match.group(1)} {c}:/tmp/restore.dump && '
            f'docker exec {c} pg_restore -U postgres -d postgres --clean --if-exists -F c /tmp/restore.dump; '
            f'docker exec {c} rm -f /tmp/restore.dump; docker restart supabase_rest_supabase')


# -- the item ----------------------------------------------------------------------------------------------------
def _ko(detail: str, fix: str = FIX_RUN_ON_VM) -> Dict[str, Any]:
    return {'status': 'ko', 'detail': detail, 'size': 0, 'fix': fix}


def _ok(detail: str) -> Dict[str, Any]:
    return {'status': 'ok', 'detail': detail, 'size': 0, 'fix': ''}


def _fallback(deps: Deps, why: str) -> Dict[str, Any]:
    fresh, text, rep = last_report_state(deps)
    if fresh:
        return _ok(_line(rep, f' · {text} ({why})'))
    return _ko(f'{text[:1].upper()}{text[1:]}; {why}.' if rep else f'{text} ({why}).')


def _log(lines: List[str]) -> str:
    return ' | '.join(str(x) for x in (lines or [])[-8:])[:600]


def request_backup(deps: Deps, log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Ask the database VM for a fresh backup and wait for its report. -> ``{status, detail, size, fix}``."""
    address, token = _agent(deps)
    if not (address and token):
        return _fallback(deps, 'no VM agent action configured')
    started = deps.now()
    try:
        status, body = _call(deps, 'POST', address, token)
    except Exception as exc:
        return _ko(f'The database VM agent at {address} does not answer ({type(exc).__name__}).', FIX_AGENT)
    if status in (401, 404):
        return _ko('The database VM agent refused the request: ' + ('wrong token.' if status == 401 else 'the db-backup action is not enabled.'),
                   FIX_AGENT)
    if status == 429:
        return _ko(f'The database VM made a backup less than 5 minutes ago (retry in {int((body or {}).get("retry_after", 0))} s).',
                   'Wait a few minutes and back up again.')
    if status not in (202, 409):          # 409: a backup is already running (maybe the nightly one): wait for its report
        return _ko(f'The database VM agent answered HTTP {status}: {(body or {}).get("error", "")}'.strip(), FIX_AGENT)
    log(f'Database VM backup requested ({"already running" if status == 409 else "started"}); waiting for its report')
    deadline = deps.timeout_seconds
    waited, errors, finished_at = 0.0, 0, None
    while True:
        try:
            code, st = _call(deps, 'GET', address, token)
            errors = 0
        except Exception:
            code, st, errors = 0, {}, errors + 1
        rep = deps.report() or {}
        when = _reported(rep)
        if when is not None and when > started and rep.get('filename'):
            return _ok(_line(rep))
        if code == 200 and isinstance(st, dict):
            if st.get('running') is False and st.get('exit_code') not in (None, 0):
                return _ko(f'The database backup script failed (exit {st.get("exit_code")}): {_log(st.get("log_tail"))}',
                           'Read the script output above, fix it on the database VM, then back up again.')
            if st.get('running') is False and st.get('exit_code') == 0:
                finished_at = waited if finished_at is None else finished_at
                if waited - finished_at >= REPORT_GRACE_SECONDS:
                    return _ko('The backup finished but its report never reached the server.',
                               'On the database VM check VPT_API_KEY in /etc/cron.d/vpt-db-backup matches this server API_KEY; '
                               'last output: ' + _log(st.get('log_tail')))
        elif errors >= MAX_AGENT_ERRORS or code in (401, 404):
            return _ko(f'The database VM agent stopped answering while the backup ran (HTTP {code or "no answer"}).', FIX_AGENT)
        if waited >= deadline:
            return _ko(f'No fresh backup report after {int(deadline // 60)} minutes.',
                       'Check the database VM (disk, docker) or run: sudo bash /usr/local/bin/vpt-db-backup.sh')
        deps.sleep(deps.poll_seconds)
        waited += deps.poll_seconds


# -- the prerequisite ----------------------------------------------------------------------------------------------
def prerequisite(deps: Deps) -> Tuple[bool, str, str]:
    """-> (ok, detail, log) for the ``db_backup`` prerequisite."""
    ok, why = agent_answers(deps)
    fresh, text, _rep = last_report_state(deps)
    log = f'agent action: {"ok" if ok else "no"} ({why})\nnightly report: {"ok" if fresh else "no"} ({text})'
    if ok:
        return True, f'The database VM agent answers ({why.split(" ")[0]}): step 1 asks it for a fresh backup.', log
    if fresh:
        return True, f'No agent action ({why}); step 1 will use the {text}.', log
    return False, f'No way to get a database backup: agent action {why}; {text}.', log
