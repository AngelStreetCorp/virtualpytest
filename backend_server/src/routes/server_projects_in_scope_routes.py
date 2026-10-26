"""
Project in-scope + manual linking routes (BUG-0578, TASK-101)
=============================================================

The auto-tag path (`auto_tag_with_project`) only fires on create / update.
The project-detail page surfaces the project ↔ artefact relationship
end-to-end: it needs a way to *see* what's in scope, *add* an existing
artefact manually, and *remove* one without touching the artefact itself.

This module adds the manual surface. Five endpoints, all gated on the
caller being either a team admin OR a project owner (the same ACL the
PATCH / DELETE / link routes use). Every write emits a `[PROJECT_AUDIT]`
log line for ops visibility.

  GET  /server/projects/<project_id>/in-scope
       → devices (grouped by host), executables (flat: scripts +
         testcases + virtual scripts as peers), campaigns (separate
         list). Each item carries `runs_30d`, `pct_pass`, and (where
         available) a `state` / `last_seen_at` for the device rows.

  POST /server/projects/<project_id>/link      body { type, id }
       → manually link an artefact to the project. The body's `type`
         must be one of `script` / `testcase` / `virtual_script` /
         `campaign`. Idempotent — a duplicate link is a 200.

  DELETE /server/projects/<project_id>/link    body { type, id }
       → sever the link. The artefact itself is NOT deleted.

  POST /server/projects/<project_id>/tags/names  body { names: [...] }
       → get-or-create each tag by name and link it to the project as
         a USER tag (`is_scope = false`). Matches the device-flag
         editor pattern (`flags: ["qa-test", "nightly"]`) so the UI
         can reuse the same `+ add tag` dialog as the device editor.

  DELETE /server/projects/<project_id>/tags/names/<name>
       → unlink a user tag. The scope tag (`is_scope = true`) is
         protected: this route refuses to remove it.

Filter contract (BUG-0578 / TASK-101):
  * Devices: `device_flags.flags ∩ project.tag_names ≠ ∅`
  * Executables: `executable_tags.tag_id IN projects_tags.tag_ids`
  * Campaigns: same as executables (`executable_type = 'campaign'`)
  * Tokens: project-wide aggregate (per-item token counts would need a
    join on `ai_usage_stats` that the schema doesn't support today —
    surfaced as a v2 enhancement, not in this slice).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from flask import Blueprint, jsonify, request

from shared.src.lib.database import projects_db
from shared.src.lib.utils.supabase_utils import get_supabase_client
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import org_scope_team_ids
from backend_server.src.lib.project_permissions import can_edit_project as _can_edit_project  # noqa: F401  inline rename keeps the call sites terse
from backend_server.src.routes.server_projects_routes import _not_in_scope_or_missing


logger = logging.getLogger(__name__)


server_projects_in_scope_bp = Blueprint(
    'server_projects_in_scope',
    __name__,
    url_prefix='/server/projects',
)


# ---------------------------------------------------------------------------
# Local helpers (mirror server_projects_routes.py — kept inline to avoid
# circular imports between sibling route modules).
# ---------------------------------------------------------------------------
def _in_team_scope(team_id: str) -> bool:
    scope = org_scope_team_ids()
    return scope is None or str(team_id) in scope


def _audit_log(project_id: str, action: str, details: dict | None = None) -> None:
    """Audit helper — same shape as the G6 helper in
    `server_projects_routes.py`. The project_id in the log line lets
    ops grep the activity feed per project.
    """
    actor = getattr(request, 'user_id', None) or 'unknown'
    import json
    extra = json.dumps(details or {}, default=str, separators=(',', ':'))
    logger.info(
        "[PROJECT_AUDIT] project_id=%s action=%s actor=%s details=%s",
        project_id, action, actor, extra,
    )


def _ai_tokens_for_project(project_id: str, days: int) -> Dict[str, int]:
    """Per-project AI usage summary for the last `days` days.

    Pulls from `ai_calls` (the 90-day per-call log that BUG-0559 added
    `project_id` to). Counts `SUM(tokens_in + tokens_out)` and `COUNT(*)`
    for calls whose `project_id` matches. Returns `{tokens, calls, cost_usd}`
    where `cost_usd` sums the per-call `cost_usd` column when present and
    is `0` when the column was added later or the per-call log has no cost
    data yet.

    Per-item (per-script / per-testcase / per-virtual) totals are still
    deferred — `ai_calls` does not carry a script_id / virtual_script_id
    column. A schema decision is needed before this number can be split
    back into the rows the `ProjectInScope` view shows. Today the figure
    surfaces at the project header; once the schema lands, the same
    helper grows a `GROUP BY` argument.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        sb = _supabase()
        res = (
            sb.table('ai_calls')
            .select('tokens_in, tokens_out, cost_usd, usage_key, user_id')
            .eq('project_id', project_id)
            .gte('ts', cutoff)
            .limit(50000)
            .execute()
        )
        tokens = 0
        calls = 0
        cost_usd_x1000 = 0  # cost_usd is stored as cents; aggregate then divide
        by_feature: Dict[str, int] = {}
        by_sender: Dict[str, int] = {}
        for r in (res.data or []):
            try:
                row_tokens = int(r.get('tokens_in') or 0) + int(r.get('tokens_out') or 0)
            except (TypeError, ValueError):
                continue
            tokens += row_tokens
            calls += 1
            if r.get('usage_key'):
                by_feature[r['usage_key']] = by_feature.get(r['usage_key'], 0) + row_tokens
            if r.get('user_id'):
                by_sender[str(r['user_id'])] = by_sender.get(str(r['user_id']), 0) + row_tokens
            try:
                cost_usd_x1000 += int(r.get('cost_usd') or 0)
            except (TypeError, ValueError):
                continue
        top = lambda d: [{'key': k, 'tokens': v} for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:5]]
        top_senders = top(by_sender)
        if top_senders:
            try:
                names = {
                    p['id']: (p.get('display_name') or p.get('email'))
                    for p in (sb.table('profiles').select('id, display_name, email')
                              .in_('id', [r['key'] for r in top_senders]).execute().data or [])
                }
                for r in top_senders:
                    r['label'] = names.get(r['key']) or r['key'][:8]
            except Exception as e:  # names are cosmetic: fall back to the short id
                logger.error("[@in_scope] sender names error: %s", e)
                for r in top_senders:
                    r['label'] = r['key'][:8]
        return {
            'tokens': tokens,
            'calls': calls,
            'cost_usd': round(cost_usd_x1000 / 1000.0, 4),
            'top_features': top(by_feature),
            'top_senders': top_senders,
        }
    except Exception as e:
        logger.error("[@in_scope] _ai_tokens_for_project error: %s", e)
        return {'tokens': 0, 'calls': 0, 'cost_usd': 0.0, 'top_features': [], 'top_senders': []}


# ---------------------------------------------------------------------------
# GET — in-scope listing
# ---------------------------------------------------------------------------
@server_projects_in_scope_bp.route(
    '/<project_id>/in-scope', methods=['GET'], strict_slashes=False
)
@handle_route_exceptions('server_projects_in_scope:get_in_scope')
def get_project_in_scope(project_id: str):
    """Devices + executables + campaigns in the project scope.

    Response shape:
        {
          "project_id": "p1",
          "days": 30,
          "tag_names": ["qa-test", "nightly"],
          "totals": {
              "devices": 17, "hosts": 3,
              "executables": {"total": 54, "scripts": 42, "testcases": 8, "virtual": 4},
              "campaigns": 2,
          },
          "devices": [
              {"host_name":"pi4","device_id":"firetv-01","device_name":"Fire TV 1",
               "flags":["qa-test","fire_tv"], "in_scope_via":"qa-test",
               "runs_30d":128, "pct_pass":91, "last_seen_at":"...", "state":"online"},
              ...
          ],
          "executables": [
              {"type":"script","id":"scr_42","name":"login.test.js",
               "runs_30d":312, "pct_pass":96},
              {"type":"testcase","id":"tc_09","name":"Device online",
               "runs_30d":68, "pct_pass":94},
              {"type":"virtual_script","id":"vs_55","name":"Smoke HLS",
               "runs_30d":14, "pct_pass":100},
              ...
          ],
          "campaigns": [
              {"id":"cmp_03","name":"Nightly","schedule":"every day at 02:00",
               "runs_30d":30, "pct_pass":90},
              ...
          ]
        }

    The route is a read; no `can_edit_project` check, no audit line.
    `devices` / `executables` / `campaigns` may be empty lists when the
    project has no artefacts yet — that is the common case for a
    freshly-created project. The frontend renders "no items in scope"
    copy when the lists are empty.
    """
    days = 30
    try:
        days = int(request.args.get('days', '30'))
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))

    project = projects_db.get_project(project_id)
    if project is None or not _in_team_scope(project['team_id']):
        return jsonify({"error": "Project not found"}), 404

    tag_ids = [t['tag_id'] for t in (project.get('tags') or [])]
    tag_names = [
        t.get('name') for t in (project.get('tags') or []) if t.get('name')
    ]
    team_id = str(project['team_id'])

    devices = projects_db.list_in_scope_devices(project_id, team_id, days=days)
    executables = projects_db.list_in_scope_executables(project_id, team_id, days=days)
    campaigns = projects_db.list_in_scope_campaigns(project_id, team_id, days=days)

    # Counters for the project's "Executables" tile (the G11 contract says
    # `{count} scripts` = total of scripts + testcases + virtuals).
    by_type: Dict[str, int] = {'script': 0, 'testcase': 0, 'virtual_script': 0}
    for r in executables:
        by_type[r['type']] = by_type.get(r['type'], 0) + 1
    total_executables = by_type['script'] + by_type['testcase'] + by_type['virtual_script']
    distinct_hosts = sorted({d['host_name'] for d in devices})

    return jsonify({
        'project_id': project_id,
        'days': days,
        'tag_ids': tag_ids,
        'tag_names': tag_names,
        'totals': {
            'devices': len(devices),
            'hosts': len(distinct_hosts),
            'executables': {
                'total': total_executables,
                'scripts': by_type['script'],
                'testcases': by_type['testcase'],
                'virtual': by_type['virtual_script'],
            },
            'campaigns': len(campaigns),
        },
        # BUG-0609 — per-project AI usage summary. The numbers come from
        # `ai_calls` (the 90-day per-call log with `project_id`) and the
        # front-end renders this as a sub-line in the `ProjectInScope`
        # header chrome. Per-script / per-testcase breakdown is still
        # deferred to a future slice that adds a `script_id` column to
        # `ai_calls`; today the figure is the project total only.
        'summary': _ai_tokens_for_project(project_id, days),
        'devices': devices,
        'executables': executables,
        'campaigns': campaigns,
    }), 200


# ---------------------------------------------------------------------------
# POST / DELETE — manual artefact link
# ---------------------------------------------------------------------------
@server_projects_in_scope_bp.route(
    '/<project_id>/link', methods=['POST'], strict_slashes=False
)
@handle_route_exceptions('server_projects_in_scope:link_add')
def add_link(project_id: str):
    """Manually attach an artefact to a project. Caller must be admin OR
    project owner. Idempotent — a duplicate link is a 200 with
    `already_linked: true` so the UI can show the right toast.
    """
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({
            "error": "Forbidden",
            "message": "Only admins and project owners can link artefacts to a project",
        }), 403

    data = request.get_json() or {}
    exec_type = data.get('type')
    exec_id = data.get('id')
    if not exec_type or not exec_id:
        return jsonify({"error": "type and id are required"}), 400
    if exec_type not in ('script', 'testcase', 'virtual_script', 'campaign'):
        return jsonify({
            "error": "type must be one of: script, testcase, virtual_script, campaign",
        }), 400

    # Idempotency probe (cheap on the in-memory mock; same pattern as
    # `add_executable_to_project` in projects_db.py).
    already = False
    try:
        sb = _supabase()
        pt = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .execute()
        )
        for r in (pt.data or []):
            tid = int(r.get('tag_id'))
            existing = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', exec_type)
                .eq('executable_id', str(exec_id))
                .eq('tag_id', tid)
                .limit(1)
                .execute()
            )
            if existing.data:
                already = True
                break
    except Exception:
        pass  # non-fatal — the helper has its own try/except

    ok = projects_db.add_executable_to_project(project_id, exec_type, str(exec_id))
    if not ok:
        return jsonify({"error": "Failed to link artefact to project"}), 500

    _audit_log(project_id, 'link_add', {
        'type': exec_type,
        'executable_id': str(exec_id),
        'already_linked': already,
    })
    return jsonify({
        'project_id': project_id,
        'type': exec_type,
        'id': str(exec_id),
        'already_linked': already,
    }), 200


@server_projects_in_scope_bp.route(
    '/<project_id>/link', methods=['DELETE'], strict_slashes=False
)
@handle_route_exceptions('server_projects_in_scope:link_remove')
def remove_link(project_id: str):
    """Manually detach an artefact. The artefact row is NOT deleted —
    only the `executable_tags` link is severed. Caller must be admin OR
    project owner. Idempotent: removing a non-existent link is a 200
    with `was_linked: false` so the UI can show "already removed".
    """
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({
            "error": "Forbidden",
            "message": "Only admins and project owners can unlink artefacts from a project",
        }), 403

    data = request.get_json() or {}
    exec_type = data.get('type')
    exec_id = data.get('id')
    if not exec_type or not exec_id:
        return jsonify({"error": "type and id are required"}), 400
    if exec_type not in ('script', 'testcase', 'virtual_script', 'campaign'):
        return jsonify({
            "error": "type must be one of: script, testcase, virtual_script, campaign",
        }), 400

    # Probe: was the link present? The actual remove is unconditional —
    # we don't fail if the row is already gone (the UI uses optimistic
    # updates and the network can race).
    was_linked = False
    try:
        sb = _supabase()
        pt = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .execute()
        )
        for r in (pt.data or []):
            tid = int(r.get('tag_id'))
            existing = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', exec_type)
                .eq('executable_id', str(exec_id))
                .eq('tag_id', tid)
                .limit(1)
                .execute()
            )
            if existing.data:
                was_linked = True
                break
    except Exception:
        pass

    ok = projects_db.remove_executable_from_project(project_id, exec_type, str(exec_id))
    if not ok:
        return jsonify({"error": "Failed to unlink artefact from project"}), 500

    _audit_log(project_id, 'link_remove', {
        'type': exec_type,
        'executable_id': str(exec_id),
        'was_linked': was_linked,
    })
    return jsonify({
        'project_id': project_id,
        'type': exec_type,
        'id': str(exec_id),
        'was_linked': was_linked,
    }), 200


# ---------------------------------------------------------------------------
# POST / DELETE — user tags by name (matches the device-flag pattern)
# ---------------------------------------------------------------------------
@server_projects_in_scope_bp.route(
    '/<project_id>/tags/names', methods=['POST'], strict_slashes=False
)
@handle_route_exceptions('server_projects_in_scope:tag_names_add')
def add_user_tag_by_name(project_id: str):
    """Add one or more user tags to a project by name. Get-or-create each
    tag, then link it to the project as `is_scope = false`. The scope
    tag (auto from project name) is read-only and cannot be re-added
    through this route — that would be a no-op anyway.

    Matches the device-flag editor pattern (`PUT /server/device-flags/...
    ` body `{flags: ["qa-test", "nightly"]}`) so the project page can
    reuse the same `+ add tag` input.
    """
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({
            "error": "Forbidden",
            "message": "Only admins and project owners can manage project tags",
        }), 403

    data = request.get_json() or {}
    names = data.get('names') or data.get('tag_names')
    if not isinstance(names, list) or not names:
        return jsonify({"error": "names must be a non-empty list of strings"}), 400
    names = [str(n).strip() for n in names if str(n).strip()]
    if not names:
        return jsonify({"error": "no non-empty tag names provided"}), 400
    if any(not n.replace('-', '').replace('_', '').isalnum() for n in names):
        return jsonify({
            "error": "tag names must be alphanumeric (plus '-' and '_')",
        }), 400

    added: List[str] = []
    skipped: List[str] = []
    for name in names:
        tag = projects_db.get_or_create_tag_by_name(name)
        if not tag:
            return jsonify({"error": f"Failed to create tag '{name}'"}), 500
        # Don't allow re-adding the scope tag — its name is fixed at create
        # time and re-adding it as a user tag would be a no-op anyway.
        existing = projects_db.list_project_tags(project_id)
        scope_names = {t.get('name') for t in existing if t.get('is_scope')}
        if name in scope_names:
            skipped.append(name)
            continue
        if not projects_db.add_user_tag_to_project(project_id, int(tag['tag_id'])):
            return jsonify({"error": f"Failed to add tag '{name}'"}), 500
        added.append(name)

    _audit_log(project_id, 'tag_add_by_name', {
        'added': added,
        'skipped_scope': skipped,
    })
    return jsonify({
        'project_id': project_id,
        'added': added,
        'skipped': skipped,
    }), 200


@server_projects_in_scope_bp.route(
    '/<project_id>/tags/names/<string:tag_name>', methods=['DELETE'],
    strict_slashes=False,
)
@handle_route_exceptions('server_projects_in_scope:tag_names_remove')
def remove_user_tag_by_name(project_id: str, tag_name: str):
    """Unlink a user tag from a project. The scope tag is protected —
    this route returns 400 if you try to remove the project's auto
    scope tag (its name is the slug of the project name). The `tag` row
    itself is kept: artefacts that were tagged through this tag still
    link to the same `tag_id`.
    """
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({
            "error": "Forbidden",
            "message": "Only admins and project owners can manage project tags",
        }), 403

    if not tag_name or not tag_name.strip():
        return jsonify({"error": "tag_name is required"}), 400

    # The scope tag's name is the slug of the project name. The DB
    # enforce via `is_scope = false` is the source of truth, but we also
    # surface a clean 400 here so the UI shows "Cannot remove scope tag"
    # instead of "no rows affected". We query `projects_tags` directly
    # because `list_project_tags` returns the embedded `tags` object
    # (which doesn't carry `is_scope`).
    sb = _supabase()
    pt_res = (
        sb.table('projects_tags')
        .select('is_scope, tags(name)')
        .eq('project_id', project_id)
        .execute()
    )
    scope_match = next(
        (
            r for r in (pt_res.data or [])
            if ((r.get('tags') or {}).get('name') == tag_name
                and r.get('is_scope'))
        ),
        None,
    )
    if scope_match:
        return jsonify({
            "error": "Cannot remove the project's scope tag",
            "message": "The scope tag is auto-created from the project name and is read-only",
        }), 400

    sb = _supabase()
    tag_row = (
        sb.table('tags')
        .select('tag_id, name')
        .eq('name', tag_name)
        .limit(1)
        .execute()
    )
    if not (tag_row.data or []):
        return jsonify({"error": f"tag '{tag_name}' not found"}), 404
    tag_id = int(tag_row.data[0]['tag_id'])
    if not projects_db.remove_user_tag_from_project(project_id, tag_id):
        return jsonify({"error": "Failed to remove tag from project"}), 500

    _audit_log(project_id, 'tag_remove_by_name', {'tag_name': tag_name})
    return jsonify({
        'project_id': project_id,
        'tag_name': tag_name,
    }), 200


# ---------------------------------------------------------------------------
# Local imports that depend on the helpers above being defined
# ---------------------------------------------------------------------------
# (moved to the top of the file — the local `_not_in_scope_or_missing`
# and `_can_edit_project` from `server_projects_routes` are imported
# alongside the other top-level imports.)


def _supabase():
    return get_supabase_client()
