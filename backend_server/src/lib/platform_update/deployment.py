"""
Deployment view of Platform update step 3 (TASK-99 G10/G11).

``update_core.sh`` (so ``deploy_bundle.sh`` too) prints ``VPT_PROGRESS {json}`` lines at each per-host
phase boundary. ``setup/proxmox/node/lib/deploy_progress.py`` is the one parser for that format; this
module loads it by path (it is a rollout tool, not part of the backend package), adds the page's own
aggregation (one card per (role, host), an overall count) and the host's own log lines, filtered out
of the run log by host name. Nothing here runs a deploy.
"""

import importlib.util
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

MARKER = 'VPT_PROGRESS '
PHASES = ('rsync', 'install', 'restart', 'health')
HOST_LOG_LINES = 300
_PARSER = None


def project_root() -> Path:
    return Path(os.getenv('VPT_PROJECT_ROOT') or Path(__file__).resolve().parents[4])


def _parser():
    global _PARSER
    if _PARSER is None:
        path = project_root() / 'setup' / 'proxmox' / 'node' / 'lib' / 'deploy_progress.py'
        spec = importlib.util.spec_from_file_location('vpt_deploy_progress', path)
        if spec is None or spec.loader is None or not path.is_file():
            raise FileNotFoundError(f'deploy_progress.py not found at {path}')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PARSER = module
    return _PARSER


def _mentions(line: str, host: str) -> bool:
    """update_core.sh tags the lines of a machine ``==> [host] ...`` or ``==> [node -> host] ...``."""
    return f'[{host}]' in line or f'-> {host}]' in line


def build_view(lines: List[str]) -> Optional[Dict[str, Any]]:
    """The deployment view of a run log, or None when the log carries no progress line at all."""
    if not any(MARKER in line for line in lines):
        return None
    parsed = _parser().parse(lines)
    hosts = parsed['hosts']
    done = total = 0
    for card in hosts:
        card['log'] = [line for line in lines if MARKER not in line and _mentions(line, card['host'])][-HOST_LOG_LINES:]
        for name in PHASES:
            total += 1
            phase = card['phases'].get(name)
            if phase and phase['state'] in ('ok', 'failed', 'skipped'):
                done += 1
        failed = next((p for p in card['phases'].values() if p['state'] == 'failed'), None)
        card['error'] = (failed or {}).get('detail') or ''
    return {
        'hosts': hosts, 'state': parsed['state'], 'started': parsed['started'], 'ended': parsed['ended'],
        'duration_s': parsed['duration_s'], 'phases_done': done, 'phases_total': total,
        'events': parsed['events'], 'ignored': parsed['ignored'],
    }


def timing_summary(view: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What a later deployment history compares: seconds per phase per (role, host). No log lines."""
    if not view:
        return {'state': 'pending', 'duration_s': None, 'hosts': []}
    return {
        'state': view['state'], 'started': view['started'], 'ended': view['ended'],
        'duration_s': view['duration_s'],
        'hosts': [{
            'host': c['host'], 'role': c['role'], 'state': c['state'], 'duration_s': c['duration_s'],
            'phases': {n: {'state': p['state'], 'duration_s': p['duration_s']} for n, p in c['phases'].items()},
        } for c in view['hosts']],
    }
