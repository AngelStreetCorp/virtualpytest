"""
Grafana Admin HTTP API helper (the only external integration in user provisioning).

Owns ONLY the Grafana user lifecycle. Called in-process by the user route when a
request carries `grafana: true`, and exposed as a thin HTTP route
(server_grafana_routes) for any other caller.

Env (server-side only):
  GRAFANA_URL             internal base incl. sub-path, e.g. http://192.168.0.106:3000/grafana
  GRAFANA_ADMIN_USER      Grafana *server* admin (Basic auth)
  GRAFANA_ADMIN_PASSWORD

Login = email (unified identity, no separate username).
"""
import os
import logging
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 15


def _cfg():
    base = (os.environ.get('GRAFANA_URL') or '').rstrip('/')
    user = os.environ.get('GRAFANA_ADMIN_USER')
    pw = os.environ.get('GRAFANA_ADMIN_PASSWORD')
    if not (base and user and pw):
        missing = [n for n, v in (
            ('GRAFANA_URL', base), ('GRAFANA_ADMIN_USER', user), ('GRAFANA_ADMIN_PASSWORD', pw)
        ) if not v]
        raise RuntimeError(f"Grafana not configured: missing {', '.join(missing)}")
    return base, (user, pw)


def _find_user(base, auth, email: str) -> Optional[Dict]:
    """Return the Grafana user dict ({id, ...}) or None if absent."""
    r = requests.get(f"{base}/api/users/lookup", params={"loginOrEmail": email},
                      auth=auth, timeout=_TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _set_org_role(base, auth, org_id: int, uid: int, email: str, org_role: str):
    """PATCH the user's org role; if not yet a member of the org, add them."""
    resp = requests.patch(f"{base}/api/orgs/{org_id}/users/{uid}",
                          json={"role": org_role}, auth=auth, timeout=_TIMEOUT)
    if resp.status_code == 404:
        add = requests.post(f"{base}/api/orgs/{org_id}/users",
                            json={"loginOrEmail": email, "role": org_role},
                            auth=auth, timeout=_TIMEOUT)
        add.raise_for_status()
    else:
        resp.raise_for_status()


def grafana_upsert_user(email: str, password: Optional[str] = None,
                        full_name: Optional[str] = None,
                        org_role: str = "Viewer", org_id: int = 1) -> Dict:
    """Create-or-update the Grafana user (login = email) and set its org role.

    Mirrors a Supabase upsert. Idempotent.
    """
    base, auth = _cfg()
    existing = _find_user(base, auth, email)

    if existing:
        uid = existing["id"]
        if password:
            pr = requests.put(f"{base}/api/admin/users/{uid}/password",
                              json={"password": password}, auth=auth, timeout=_TIMEOUT)
            pr.raise_for_status()
    else:
        if not password:
            raise ValueError("password is required to create a Grafana user")
        cr = requests.post(f"{base}/api/admin/users", json={
            "name": full_name or email,
            "email": email,
            "login": email,
            "password": password,
        }, auth=auth, timeout=_TIMEOUT)
        cr.raise_for_status()
        uid = cr.json()["id"]

    _set_org_role(base, auth, org_id, uid, email, org_role)
    logger.info(f"[grafana_admin] upserted {email} (id={uid}, org_role={org_role})")
    return {"user_id": uid, "org_role": org_role}


def grafana_delete_user(email: str) -> Dict:
    """Delete the Grafana user. Idempotent — absent user returns absent:true."""
    base, auth = _cfg()
    existing = _find_user(base, auth, email)
    if not existing:
        return {"deleted": False, "absent": True}
    uid = existing["id"]
    dr = requests.delete(f"{base}/api/admin/users/{uid}", auth=auth, timeout=_TIMEOUT)
    dr.raise_for_status()
    logger.info(f"[grafana_admin] deleted {email} (id={uid})")
    return {"deleted": True, "user_id": uid}


def grafana_set_org_role(email: str, org_role: str, org_id: int = 1) -> Dict:
    """Re-push only the org role (used when a VirtualPyTest admin changes a role)."""
    base, auth = _cfg()
    existing = _find_user(base, auth, email)
    if not existing:
        raise ValueError(f"Grafana user not found: {email}")
    uid = existing["id"]
    _set_org_role(base, auth, org_id, uid, email, org_role)
    logger.info(f"[grafana_admin] set org role {email} -> {org_role}")
    return {"user_id": uid, "org_role": org_role}
