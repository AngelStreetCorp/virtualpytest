"""
GitLab instances — storage for the page's "set it up" form.

Same shape as the JIRA instance list in backend_server/src/routes/server_integrations_routes.py:
runtime state in a JSON file under state_path(), i.e. outside the deploy tree, so a deploy never
overwrites what an operator configured, and the token never has to be baked into an env file that
gets redeployed.

One record per GitLab the VPT talks to:

    {"id": "main", "name": "Customer GitLab", "base_url": "http://gitlab.internal",
     "token": "glpat-…", "project": "group/app", "ref": "main"}

`project` is the operator's selection: with one project it is chosen implicitly, with several it
is what they last picked, so the page can open straight on it.

Env fallback: with no file at all but GITLAB_TOKEN/GITLAB_URL set, an implicit instance is
synthesised from the environment so a deployment that has always used env vars keeps working
with nothing to configure.
"""

import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

from backend_server.src.lib.utils.integration_state import state_path

CONFIG_PATH = state_path('gitlab_instances.json')

#: RLock, not Lock: upsert/delete/select_project hold it and then call save(), which takes it
#: again. A plain Lock is not reentrant, so that nesting would deadlock the worker on the very
#: first save.
_LOCK = threading.RLock()

#: Fields an operator may set. Anything else in the file is ignored on write, so a hand-edited
#: file cannot smuggle unexpected keys into the runtime dict.
_FIELDS = ('id', 'name', 'base_url', 'token', 'project', 'ref')


def _clean(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: raw.get(k) for k in _FIELDS if k in raw}
    out.setdefault('name', '')
    out.setdefault('base_url', '')
    out.setdefault('token', '')
    out.setdefault('project', '')
    out.setdefault('ref', 'main')
    if not out.get('id'):
        out['id'] = uuid.uuid4().hex[:12]
    out['base_url'] = (out['base_url'] or '').rstrip('/')
    if not out['name']:
        out['name'] = out['base_url'] or out['id']
    return out


def load() -> List[Dict[str, Any]]:
    """Configured instances. Never raises — a broken file must not take the page down."""
    try:
        if not CONFIG_PATH.exists():
            return []
        with open(CONFIG_PATH, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):          # tolerate {"instances": [...]} written by hand
            data = data.get('instances', [])
        return [_clean(row) for row in data if isinstance(row, dict)]
    except Exception as e:
        print(f"[@gitlab] Could not read {CONFIG_PATH}: {e}")
        return []


def save(instances: List[Dict[str, Any]]) -> bool:
    with _LOCK:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, 'w') as f:
                json.dump([_clean(i) for i in instances], f, indent=2)
            try:
                os.chmod(CONFIG_PATH, 0o600)      # it holds personal access tokens
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[@gitlab] Could not write {CONFIG_PATH}: {e}")
            return False


def env_instance() -> Optional[Dict[str, Any]]:
    """Implicit instance from GITLAB_URL / GITLAB_TOKEN, when nothing is configured."""
    token = (os.environ.get('GITLAB_TOKEN') or '').strip()
    if not token:
        return None
    return _clean({
        'id': 'env',
        'name': 'Environment',
        'base_url': os.environ.get('GITLAB_URL', 'https://gitlab.com').rstrip('/'),
        'token': token,
        'ref': 'main',
    })


def effective() -> List[Dict[str, Any]]:
    """What the page should show: the configured instances, or the env one as a fallback."""
    configured = load()
    if configured:
        return configured
    fallback = env_instance()
    return [fallback] if fallback else []


def get(instance_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """One instance by id. Without an id, the first one — the single-instance case."""
    instances = effective()
    if not instances:
        return None
    if not instance_id:
        return instances[0]
    for inst in instances:
        if inst['id'] == instance_id:
            return inst
    return None


def upsert(fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create or update by id, and return the stored record. None when the write failed."""
    with _LOCK:
        instances = load()
        cleaned = _clean(fields)
        for i, inst in enumerate(instances):
            if inst['id'] == cleaned['id']:
                # An empty token on update means "keep the stored one": the form never sends it
                # back, so otherwise saving a renamed instance would wipe its credential.
                if not cleaned.get('token'):
                    cleaned['token'] = inst.get('token', '')
                instances[i] = cleaned
                break
        else:
            instances.append(cleaned)
        return cleaned if save(instances) else None


def delete(instance_id: str) -> bool:
    with _LOCK:
        instances = load()
        remaining = [i for i in instances if i['id'] != instance_id]
        if len(remaining) == len(instances):
            return False
        return save(remaining)


def select_project(instance_id: str, project: str, ref: str = '') -> Optional[Dict[str, Any]]:
    """Remember which project (and branch) the operator picked for this instance."""
    with _LOCK:
        instances = load()
        for inst in instances:
            if inst['id'] == instance_id:
                inst['project'] = project
                if ref:
                    inst['ref'] = ref
                return inst if save(instances) else None
    return None


def public(inst: Dict[str, Any]) -> Dict[str, Any]:
    """Instance for the frontend — the token is never sent to the browser."""
    return {
        'id': inst.get('id'),
        'name': inst.get('name'),
        'base_url': inst.get('base_url'),
        'project': inst.get('project'),
        'ref': inst.get('ref', 'main'),
        'has_token': bool(inst.get('token')),
    }