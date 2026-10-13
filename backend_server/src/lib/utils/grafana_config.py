"""
Grafana integration config loader.

Reads backend_server/config/integrations/grafana_config.json (same convention
as slack_config.json / jira_instances.json). Tiny by design — only seeds the
default role and the VirtualPyTest-role -> Grafana-org-role mirror. No group/role
resolution logic (an upstream group is just a team name; roles live in VirtualPyTest).
"""
import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

# backend_server/src/lib/utils/grafana_config.py -> backend_server/
BACKEND_SERVER_ROOT = Path(__file__).parent.parent.parent.parent
CONFIG_PATH = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'grafana_config.json'

_DEFAULTS: Dict = {
    "default_role": "viewer",
    # TASK-31 D1: only an admin edits dashboards. Everyone else is a Viewer, so nobody can rewrite
    # a panel's SQL and drop the device-scope filter.
    "grafana_role_by_role": {"admin": "Admin", "manager": "Viewer", "developer": "Viewer",
                             "tester": "Viewer", "viewer": "Viewer"},
    "grafana_org_id": 1,
}


def load_grafana_config() -> Dict:
    """Load grafana_config.json, falling back to safe defaults if absent/invalid."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            # Per-role map merged key by key: a config written before a role existed must not
            # drop that role to the "Viewer" fallback.
            role_map = {**_DEFAULTS["grafana_role_by_role"], **(cfg.get("grafana_role_by_role") or {})}
            return {**_DEFAULTS, **cfg, "grafana_role_by_role": role_map}
    except Exception as e:
        logger.warning(f"[grafana_config] Could not load {CONFIG_PATH}: {e}; using defaults")
    return dict(_DEFAULTS)


def default_role() -> str:
    return load_grafana_config().get("default_role", "viewer")


def grafana_role_for(platform_role: str) -> str:
    """Map a VirtualPyTest role -> Grafana org role (default Viewer)."""
    return load_grafana_config().get("grafana_role_by_role", {}).get(platform_role, "Viewer")


def grafana_org_id() -> int:
    return int(load_grafana_config().get("grafana_org_id", 1))
