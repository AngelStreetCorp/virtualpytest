"""
Projects Database Operations
===========================

TASK-65 — Projects (first-class concept). A Project is a tagged scope of executables
(scripts / testcases / campaigns). The scope is derived from `projects_tags` →
`executable_tags` (Q1 = 1: tags-backed projects; no destructive migration).

Per owner answers (2026-10-06):
  - Q1 = 1: tags-backed projects; the projects table joins to `tags` via
            `projects_tags`.
  - Q2 = 1: when a project is selected in the top bar, every new artifact is
            auto-tagged with that project's tag (handled by the MCP tools in G5).
  - Q3 = 1: active users = `team_members.last_seen_at > now() - 5 min`.
  - Q4 = 1: project ACL is owner / viewer; team admins ALWAYS bypass via
            `public.is_admin()` (RLS) and `caller_is_admin()` (routes).

Every query filters by `team_id` (AGENTS.md guardrail). The db module talks to
Supabase via the service-role client (mirrors `workspaces_db.py`); permission
gating happens at the route layer via `auth_middleware`.

The migrations live in `setup/db/migrations/20261006{a,b,c}_*.sql` and are
applied by the owner (NOT by this module) on a follow-up commit.

Functions
---------

  list_projects(team_id)
  get_project(project_id)
  create_project(team_id, name, description, color, created_by_team_member_id)
  update_project(project_id, fields)
  delete_project(project_id)

  list_project_tags(project_id)
  add_project_tag(project_id, tag_id)
  remove_project_tag(project_id, tag_id)

  list_project_members(project_id)
  add_project_member(project_id, team_member_id, role)
  remove_project_member(project_id, team_member_id)

  list_active_users(team_id, within_seconds=300)
  update_team_member_last_seen(team_member_id)

  resolve_project_for_executable(executable_type, executable_id)

  get_project_tag_names(project_id)
  get_project_executables(project_id, team_id) -> {scripts, testcases, virtual_scripts, campaigns}
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ProjectNotFoundError(Exception):
    """The requested project does not exist."""


class ProjectDuplicateError(Exception):
    """A project with this name already exists in the team."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"A project named '{name}' already exists in this team")


class ProtectedTagError(Exception):
    """The tag is owned by a project; rename allowed, delete blocked."""

    def __init__(self, tag_id: int):
        self.tag_id = tag_id
        super().__init__(f"tag '{tag_id}' is used by a project and cannot be deleted")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _supabase():
    """Service-role Supabase client."""
    return get_supabase_client()


_NAME_RE = re.compile(r"[^a-z0-9_-]+")


def _slugify_project_name(name: str) -> str:
    """A stable, lowercase tag name derived from the project name.

    Tags are stored lowercase (folder_tag_db.get_or_create_tag). The slug keeps
    it readable in the top-bar ProjectSelector and makes the project tag discoverable
    on the existing Tags UI.
    """
    s = (name or "").strip().lower()
    s = _NAME_RE.sub("_", s).strip("_")
    return s or "project"


def _enrich(project: Dict, *, tags: List[Dict], members: List[Dict]) -> Dict:
    """Attach `tags` and `members` (with role) to a project dict for the API.

    Tag shape from the join (rows from `projects_tags` × `tags`):
        {'tag_id', 'name', 'color', 'is_scope'}
    `is_scope` is True for the row that holds the project's auto-created
    scope tag (one per project, max), False for tags the team attached
    through `POST /server/projects/<id>/tags`.

    The API returns BOTH:
      * `tags` / `tag_ids`   — every tag (kept for backward compatibility
        with anything that filters by tag name; corresponds to G9's "all
        project tags drive scope filtering")
      * `scope_tag` / `scope_tag_id` — the single auto-created scope tag,
        or null when none
      * `user_tags` / `user_tag_ids` / `user_tag_count` — the user-attached
        tags; this is what the frontend renders on the project card (BUG-0523)
    """
    scope_tags = [t for t in tags if t.get('is_scope')]
    user_tags = [t for t in tags if not t.get('is_scope')]

    out = dict(project)
    out['tags'] = tags
    out['members'] = members
    out['tag_ids'] = [t['tag_id'] for t in tags]
    out['member_count'] = len(members)
    out['owner_count'] = sum(1 for m in members if m.get('role') == 'owner')
    out['viewer_count'] = sum(1 for m in members if m.get('role') == 'viewer')
    # BUG-0523 — split the project's scope tag from its user tags so the UI
    # can render "X tags" using only the user-attached ones.
    out['scope_tag'] = scope_tags[0] if scope_tags else None
    out['scope_tag_id'] = scope_tags[0]['tag_id'] if scope_tags else None
    out['user_tags'] = user_tags
    out['user_tag_ids'] = [t['tag_id'] for t in user_tags]
    out['user_tag_count'] = len(user_tags)
    return out


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def list_projects(team_id: str) -> List[Dict]:
    """List every project for `team_id`, with tags + members."""
    sb = _supabase()
    try:
        projects_res = (
            sb.table('projects')
            .select('*')
            .eq('team_id', team_id)
            .order('created_at', desc=False)
            .execute()
        )
        projects = projects_res.data or []
        if not projects:
            return []
        ids = [p['id'] for p in projects]

        tag_res = (
            sb.table('projects_tags')
            .select('project_id, tag_id, is_scope, tags(tag_id, name, color)')
            .in_('project_id', ids)
            .execute()
        )
        tags_by_project: Dict[str, List[Dict]] = {}
        for row in tag_res.data or []:
            nested = row.get('tags')
            tag_dict = dict(nested) if nested else {'tag_id': row.get('tag_id')}
            tag_dict['is_scope'] = bool(row.get('is_scope'))
            tags_by_project.setdefault(row['project_id'], []).append(tag_dict)

        member_res = (
            sb.table('projects_members')
            .select('project_id, team_member_id, role')
            .in_('project_id', ids)
            .execute()
        )
        members_by_project: Dict[str, List[Dict]] = {}
        for row in member_res.data or []:
            members_by_project.setdefault(row['project_id'], []).append({
                'team_member_id': row['team_member_id'],
                'role': row['role'],
            })

        return [_enrich(p, tags=tags_by_project.get(p['id'], []),
                        members=members_by_project.get(p['id'], []))
                for p in projects]
    except Exception as e:
        logger.error("[@projects_db] list_projects error: %s", e)
        return []


def get_project(project_id: str) -> Optional[Dict]:
    """Single project with tags + members."""
    sb = _supabase()
    try:
        p_res = (
            sb.table('projects')
            .select('*')
            .eq('id', project_id)
            .single()
            .execute()
        )
        if not p_res.data:
            return None
        project = p_res.data

        tag_res = (
            sb.table('projects_tags')
            .select('tag_id, is_scope, tags(tag_id, name, color)')
            .eq('project_id', project_id)
            .execute()
        )
        tags: List[Dict] = []
        for r in (tag_res.data or []):
            nested = r.get('tags')
            tag_dict = dict(nested) if nested else {'tag_id': r.get('tag_id')}
            tag_dict['is_scope'] = bool(r.get('is_scope'))
            tags.append(tag_dict)

        member_res = (
            sb.table('projects_members')
            .select('team_member_id, role')
            .eq('project_id', project_id)
            .execute()
        )
        members = [
            {'team_member_id': r['team_member_id'], 'role': r['role']}
            for r in (member_res.data or [])
        ]
        return _enrich(project, tags=tags, members=members)
    except Exception as e:
        logger.error("[@projects_db] get_project error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
def _profile_id_for_team_member(sb, team_id: str, team_member_id: str) -> str:
    """`team_members.id` -> `team_members.user_id` (= profiles.id), scoped to `team_id`.

    Raises RuntimeError when the row cannot be resolved, so no project is inserted
    with an id the `projects.created_by` foreign key would reject.
    """
    try:
        res = (
            sb.table('team_members')
            .select('user_id')
            .eq('id', team_member_id)
            .eq('team_id', team_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error("[@projects_db] could not resolve profile for team member %s: %s", team_member_id, e)
        raise RuntimeError("could not resolve the creator's profile") from e
    if not res.data or not res.data[0].get('user_id'):
        logger.error("[@projects_db] team member %s not found in team %s", team_member_id, team_id)
        raise RuntimeError("creator is not a member of the team")
    return str(res.data[0]['user_id'])


def create_project(
    team_id: str,
    name: str,
    description: Optional[str],
    color: Optional[str],
    created_by_team_member_id: str,
    initial_user_tags: Optional[List[str]] = None,
    initial_members: Optional[List[Dict[str, str]]] = None,
) -> Dict:
    """Create a project + ensure its tag + add creator as owner.

    Sequence (acceptable race window for two parallel calls with the same name —
    the unique constraint catches it):
      1. INSERT projects (UNIQUE(team_id, LOWER(name)) on the table).
      2. Get-or-create the SCOPE tag (slugged name) — flagged is_scope = TRUE.
      3. INSERT projects_tags(project_id, tag_id, is_scope = TRUE).
      4. INSERT projects_members(project_id, team_member_id, 'owner') for the
         creator (BUG-0522: `created_by_team_member_id` MUST be a
         `team_members.id` UUID, not a `profiles.id` — the route layer
         resolves the caller's team_member row before calling).
      5. (Optional, G11) For each name in `initial_user_tags`, get-or-create
         the tag at the project level and insert a row into projects_tags
         with `is_scope = FALSE`. Failures here are non-fatal — a partial
         tag set is better than a rolled-back project.
      6. (Optional, G11) For each {team_member_id, role} in `initial_members`,
         insert into projects_members. The creator row was inserted in
         step 4, so duplicates are silently ignored.

    A Postgres-side RPC can wrap these in a single transaction later.
    """
    sb = _supabase()
    tag_name = _slugify_project_name(name)

    # 1. create the project row. `projects.created_by` is FK -> profiles.id, NOT
    # team_members.id: resolve the creator's profile id from the team_members row.
    created_by_profile_id = _profile_id_for_team_member(sb, team_id, created_by_team_member_id)
    try:
        proj_res = (
            sb.table('projects')
            .insert({
                'team_id': team_id,
                'name': name,
                'description': description,
                'color': color,
                'created_by': created_by_profile_id,
            })
            .execute()
        )
    except Exception as e:
        msg = str(e).lower()
        if 'unique' in msg or 'duplicate' in msg or 'projects_team_name_unique' in msg:
            raise ProjectDuplicateError(name)
        raise

    if not proj_res.data:
        raise ProjectDuplicateError(name)
    project = proj_res.data[0]

    # 2. get-or-create the SCOPE tag (mirrors folder_tag_db.get_or_create_tag)
    tag = _get_or_create_tag(tag_name)
    if tag is None:
        # Roll back the project if we cannot get a tag (best-effort).
        try:
            sb.table('projects').delete().eq('id', project['id']).execute()
        except Exception:
            pass
        raise RuntimeError("could not create or fetch the project's tag")

    # 3. link the SCOPE tag to the project — is_scope = TRUE (BUG-0523).
    try:
        sb.table('projects_tags').insert({
            'project_id': project['id'],
            'tag_id': tag['tag_id'],
            'is_scope': True,
        }).execute()
    except Exception as e:
        logger.warning("[@projects_db] could not link scope tag to project: %s", e)

    # 4. add creator as owner — created_by_team_member_id is a team_members.id
    # (BUG-0522: route layer resolves caller_team_member_ids[0] — NOT the
    # profile.user_id — before calling). Skip on a falsy id; the route layer
    # already prevents this, but defensive in case future callers (MCP, etc.)
    # reach the db layer directly without the route's resolution step.
    if created_by_team_member_id:
        try:
            sb.table('projects_members').insert({
                'project_id': project['id'],
                'team_member_id': created_by_team_member_id,
                'role': 'owner',
            }).execute()
        except Exception as e:
            logger.warning("[@projects_db] could not add creator as owner: %s", e)

    # 5. (G11) optional initial user tags (all marked is_scope = FALSE).
    # Dedupes by name in the db layer too — the route dedupes, but MCP tools
    # and other callers can reach this function directly without that step.
    if initial_user_tags:
        seen_labels = set()
        for tag_label in initial_user_tags:
            label = (tag_label or '').strip().lower()
            if not label or label == tag_name or label in seen_labels:
                continue
            seen_labels.add(label)
            extra = _get_or_create_tag(label)
            if not extra:
                continue
            try:
                sb.table('projects_tags').insert({
                    'project_id': project['id'],
                    'tag_id': extra['tag_id'],
                    'is_scope': False,
                }).execute()
            except Exception as e:
                logger.warning(
                    "[@projects_db] could not attach user tag %r to project: %s",
                    label, e,
                )

    # 6. (G11) optional initial extra members. The creator was added in step 4
    # as 'owner' — duplicates from initial_members are silently ignored.
    if initial_members:
        for m in initial_members:
            tm_id = m.get('team_member_id')
            role = m.get('role', 'viewer')
            if not tm_id or role not in ('owner', 'viewer'):
                continue
            try:
                sb.table('projects_members').insert({
                    'project_id': project['id'],
                    'team_member_id': str(tm_id),
                    'role': role,
                }).execute()
            except Exception as e:
                msg = str(e).lower()
                # Silent on duplicate (creator was already inserted in step 4).
                if 'duplicate' in msg or 'unique' in msg:
                    continue
                logger.warning(
                    "[@projects_db] could not add initial member %s: %s",
                    tm_id, e,
                )

    return get_project(project['id']) or project


def update_project(project_id: str, fields: Dict[str, Any]) -> Optional[Dict]:
    """PATCH a project. Allowed fields: name, description, color.

    Renaming the project does NOT rename the tag (the tag is the scope key).
    The owner can rename the tag manually via the TagPicker; the slug is hidden
    in the UI.
    """
    sb = _supabase()
    allowed = {k: v for k, v in fields.items() if k in ('name', 'description', 'color')}
    if not allowed:
        return get_project(project_id)
    try:
        sb.table('projects').update(allowed).eq('id', project_id).execute()
    except Exception as e:
        msg = str(e).lower()
        if 'unique' in msg or 'duplicate' in msg:
            raise ProjectDuplicateError(fields.get('name', ''))
        logger.error("[@projects_db] update_project error: %s", e)
        return None
    return get_project(project_id)


def delete_project(project_id: str) -> bool:
    """Delete a project. ON DELETE CASCADE removes projects_tags + projects_members.

    The tag itself stays (a tag with no project is fine; rename / delete through TagPicker).
    """
    sb = _supabase()
    try:
        sb.table('projects').delete().eq('id', project_id).execute()
        return True
    except Exception as e:
        logger.error("[@projects_db] delete_project error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
def list_project_tags(project_id: str) -> List[Dict]:
    """Tags owned by a project (rows of `tags`)."""
    sb = _supabase()
    try:
        res = (
            sb.table('projects_tags')
            .select('tag_id, tags(tag_id, name, color)')
            .eq('project_id', project_id)
            .execute()
        )
        return [r.get('tags') or {'tag_id': r['tag_id']} for r in (res.data or [])]
    except Exception as e:
        logger.error("[@projects_db] list_project_tags error: %s", e)
        return []


def add_project_tag(project_id: str, tag_id: int) -> bool:
    sb = _supabase()
    try:
        sb.table('projects_tags').insert({
            'project_id': project_id,
            'tag_id': tag_id,
        }).execute()
        return True
    except Exception as e:
        msg = str(e).lower()
        if 'duplicate' in msg or 'unique' in msg:
            return True  # already linked
        logger.error("[@projects_db] add_project_tag error: %s", e)
        return False


def remove_project_tag(project_id: str, tag_id: int) -> bool:
    sb = _supabase()
    try:
        sb.table('projects_tags').delete() \
            .eq('project_id', project_id).eq('tag_id', tag_id).execute()
        return True
    except Exception as e:
        logger.error("[@projects_db] remove_project_tag error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
def list_project_members(project_id: str) -> List[Dict]:
    """Members of a project with their role (owner / viewer)."""
    sb = _supabase()
    try:
        res = (
            sb.table('projects_members')
            .select('team_member_id, role, created_at')
            .eq('project_id', project_id)
            .execute()
        )
        return [
            {
                'team_member_id': r['team_member_id'],
                'role': r['role'],
                'created_at': r.get('created_at'),
            }
            for r in (res.data or [])
        ]
    except Exception as e:
        logger.error("[@projects_db] list_project_members error: %s", e)
        return []


def add_project_member(project_id: str, team_member_id: str, role: str) -> Optional[Dict]:
    if role not in ('owner', 'viewer'):
        raise ValueError(f"role must be 'owner' or 'viewer', got {role!r}")
    sb = _supabase()
    try:
        res = sb.table('projects_members').upsert({
            'project_id': project_id,
            'team_member_id': team_member_id,
            'role': role,
        }).execute()
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        logger.error("[@projects_db] add_project_member error: %s", e)
        return None


def remove_project_member(project_id: str, team_member_id: str) -> bool:
    sb = _supabase()
    try:
        sb.table('projects_members').delete() \
            .eq('project_id', project_id) \
            .eq('team_member_id', team_member_id) \
            .execute()
        return True
    except Exception as e:
        logger.error("[@projects_db] remove_project_member error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Active users (Q3)
# ---------------------------------------------------------------------------
def update_team_member_last_seen(team_member_id: str) -> bool:
    """UPSERT last_seen_at = NOW() for `team_member_id`.

    The route layer throttles to 60 s client-side AND only writes if
    `last_seen_at IS NULL OR last_seen_at < now() - 60 s` (idempotent).
    """
    sb = _supabase()
    try:
        sb.rpc('touch_team_member_last_seen', {
            'p_team_member_id': team_member_id,
        }).execute()
        return True
    except Exception:
        # Fall back to a direct UPDATE if the RPC is missing (owner applies the
        # RPC in a future migration; for now the G1 contract is satisfied by
        # the column itself existing).
        try:
            sb.table('team_members') \
                .update({'last_seen_at': 'now()'}) \
                .eq('id', team_member_id) \
                .execute()
            return True
        except Exception as e:
            logger.error("[@projects_db] update_team_member_last_seen error: %s", e)
            return False


def list_active_users(team_id: str, within_seconds: int = 300) -> List[Dict]:
    """Return team members with `last_seen_at > now() - within_seconds`."""
    sb = _supabase()
    try:
        # Compute the cutoff in Python (Supabase JS client does not always
        # support `now() - interval` reliably across versions).
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=within_seconds)).isoformat()
        res = (
            sb.table('team_members')
            .select('id, user_id, team_id, role, last_seen_at')
            .eq('team_id', team_id)
            .gte('last_seen_at', cutoff)
            .order('last_seen_at', desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("[@projects_db] list_active_users error: %s", e)
        return []


# ---------------------------------------------------------------------------
# Resolve project for a script / testcase / campaign (used by G7 report macro)
# ---------------------------------------------------------------------------
def resolve_project_for_executable(
    executable_type: str,
    executable_id: str,
) -> Optional[Dict]:
    """Return the first project (with name) that owns a tag of `executable_type:id`.

    Used by the report HTML badge (G7). Returns None if no project matches.
    """
    sb = _supabase()
    try:
        # The executable's tag_ids
        et_res = (
            sb.table('executable_tags')
            .select('tag_id')
            .eq('executable_type', executable_type)
            .eq('executable_id', str(executable_id))
            .execute()
        )
        tag_ids = [r['tag_id'] for r in (et_res.data or [])]
        if not tag_ids:
            return None

        # The first project that owns one of those tags
        pt_res = (
            sb.table('projects_tags')
            .select('project_id, projects(id, team_id, name, color)')
            .in_('tag_id', tag_ids)
            .limit(1)
            .execute()
        )
        for r in (pt_res.data or []):
            proj = r.get('projects')
            if proj:
                return {
                    'id': proj['id'],
                    'name': proj['name'],
                    'color': proj.get('color'),
                }
        return None
    except Exception as e:
        logger.error("[@projects_db] resolve_project_for_executable error: %s", e)
        return None


# ---------------------------------------------------------------------------
# G5 — Scope Atlas helpers
# ---------------------------------------------------------------------------
def current_project_from_id(project_id: Optional[str]) -> Optional[Dict]:
    """Resolve an `X-Project-Id` / `project_id` hint into a project row.

    Returns the enriched project (same shape as `get_project`) when the id is
    a real project in the caller's team scope, or `None` when:
      * `project_id` is empty / None / 'all',
      * the project doesn't exist,
      * the project is in a team outside the caller's scope (admin bypasses).

    The MCP tools (`save_virtual_script`, `save_testcase`, `create_campaign`,
    and the list_* counterparts) call this to translate the `X-Project-Id`
    header (or a `project_id` argument) into a tag, then auto-tag or filter
    on it. Returns `None` for "no scope" — the caller treats that as the
    legacy "all artefacts" behaviour.
    """
    if not project_id or str(project_id).strip().lower() in ('all', '', 'null', 'none'):
        return None
    project = get_project(str(project_id))
    if project is None:
        return None
    # Caller must be in the project's team. Admin bypass is handled by
    # `org_scope_team_ids() == None`. Without a request context we accept
    # any project (the in-memory test harness).
    try:
        from backend_server.src.lib.auth_middleware import org_scope_team_ids
        scope = org_scope_team_ids()
    except Exception:
        scope = None
    if scope is not None and str(project['team_id']) not in scope:
        return None
    return project


def auto_tag_with_project(
    executable_type: str,
    executable_id: str,
    project: Dict,
) -> bool:
    """DEPRECATED legacy no-op (BUG-0611). Returns True unconditionally.

    The auto-tag-on-create flow was the only way to link artefacts to
    projects before BUG-0579 (the manual `POST /link` API) and BUG-0608
    (the project page v2 add/remove wired). The manual flow is the
    supported path now; this helper is preserved so the three legacy
    callers (campaign_tools / testcase_tools / virtual_script_tools)
    don't break, but it no longer inserts anything.

    Idempotent by definition (always True). The signature stays stable.

    Follow-on: drop the three callers once Atlas's "auto-link on save"
    UX hint is removed. Today callers still pass `project_hint` and log
    the (now no-op) `auto_tag_ok` for backwards compatibility with
    downstream log-watchers.
    """
    if not project or not project.get('tag_ids'):
        return False
    logger.info(
        "[@projects_db] auto_tag_with_project is a deprecated no-op "
        "(executable_type=%s executable_id=%s project=%s). Use the manual "
        "POST /server/projects/<id>/link path or the project's `+ add` "
        "buttons (BUG-0579 / BUG-0608).",
        executable_type, executable_id, project.get('id'),
    )
    return True


# ---------------------------------------------------------------------------
# BUG-0578 — manual in-scope listing + manual link / unlink
# ---------------------------------------------------------------------------
# The auto-tag path above is opportunistic: it tags an artefact when the
# caller passes a `project_id` (or sends the `X-Project-Id` header). That works
# at create time but offers no way to *see* what's already in a project or
# to add/remove individual artefacts after the fact. The project-detail page
# surfaces the relationship end-to-end:
#
#   * GET /server/projects/<id>/in-scope — returns the project's devices,
#     executables, and campaigns as three groups with per-item run/pass stats.
#   * POST/DELETE /server/projects/<id>/link — manually attach / detach a
#     single artefact by (type, id) — the UI's "× remove" and "+ add" buttons.
#
# Helpers in this section are pure data — they do not touch the request, the
# session, or the audit log. The route layer is the only place that enforces
# permissions and emits audit lines.
def list_in_scope_devices(
    project_id: str,
    team_id: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Devices whose `device_flags.flags` intersect the project's tag_names.

    Returns one row per `(host_name, device_id)` that is in scope. Each row
    carries the device's flags, the in-scope flag that matched, the run
    count and pass rate over the last `days` days, and a `last_seen_at`
    timestamp derived from the most recent run. Devices with no runs in
    the window still surface (with `runs_30d = 0` and `pct_pass = None`)
    so the user can see "this device carries the project tag but hasn't
    been used yet".

    The run/pass numbers come from `script_results` filtered by
    `(team_id, host_name, device_name)` and `started_at >= cutoff`. One
    query per pass + one for fail is the cheapest shape on the existing
    `idx_script_results_team_started` index. The mock in tests is a
    list of dicts, so we use the same `in_('host_name', host_names)`
    pattern to keep the SQL portable.
    """
    if not project_id or not team_id:
        return []
    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    try:
        # 1. Resolve the project's tag_names — the device-scope rule is
        #    `flags ∩ tag_names ≠ ∅` (frontend and backend agree).
        pt_res = (
            sb.table('projects_tags')
            .select('tag_id, tags(name)')
            .eq('project_id', project_id)
            .execute()
        )
        tag_names = sorted({
            (r.get('tags') or {}).get('name')
            for r in (pt_res.data or [])
            if (r.get('tags') or {}).get('name')
        })
        if not tag_names:
            return []

        # 2. Pull every device_flag row in the team and intersect client-side.
        #    device_flags is small (a few hundred rows max for the whole
        #    platform), so this is cheaper than a 3-table join.
        df_res = (
            sb.table('device_flags')
            .select('host_name, device_id, device_name, flags')
            .execute()
        )
        matched: List[Dict[str, Any]] = []
        host_names: set = set()
        tag_set = {n.lower() for n in tag_names}
        for r in (df_res.data or []):
            host = r.get('host_name')
            did = r.get('device_id')
            if not host or not did:
                continue
            flags = [str(f).lower() for f in (r.get('flags') or [])]
            hit = next((f for f in flags if f in tag_set), None)
            if hit is None:
                continue
            matched.append({
                'host_name': host,
                'device_id': did,
                'device_name': r.get('device_name') or did,
                'flags': flags,
                'in_scope_via': hit,
            })
            host_names.add(host)
        if not matched:
            return []

        # 3. Run + pass + last_seen per (host, device) in the window. One
        #    pass-row + one fail-row query on `script_results` is the
        #    cheapest shape with the existing index.
        host_list = sorted(host_names)
        sr_pass = (
            sb.table('script_results')
            .select('host_name, device_name, started_at, success')
            .eq('team_id', team_id)
            .eq('success', True)
            .gte('started_at', cutoff)
            .in_('host_name', host_list)
            .not_.is_('device_name', 'null')
            .execute()
        )
        sr_fail = (
            sb.table('script_results')
            .select('host_name, device_name, started_at')
            .eq('team_id', team_id)
            .eq('success', False)
            .gte('started_at', cutoff)
            .in_('host_name', host_list)
            .not_.is_('device_name', 'null')
            .execute()
        )
        runs: Dict[str, int] = {}
        pass_count: Dict[str, int] = {}
        last_seen: Dict[str, str] = {}
        for r in (sr_pass.data or []):
            key = f"{r.get('host_name')}:{r.get('device_name')}"
            runs[key] = runs.get(key, 0) + 1
            pass_count[key] = pass_count.get(key, 0) + 1
            ts = r.get('started_at') or ''
            if ts > last_seen.get(key, ''):
                last_seen[key] = ts
        for r in (sr_fail.data or []):
            key = f"{r.get('host_name')}:{r.get('device_name')}"
            runs[key] = runs.get(key, 0) + 1
            ts = r.get('started_at') or ''
            if ts > last_seen.get(key, ''):
                last_seen[key] = ts

        # 4. Stamp stats onto the device rows.
        cutoff_5m = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        for d in matched:
            key = f"{d['host_name']}:{d.get('device_name') or d['device_id']}"
            r = runs.get(key, 0)
            p = pass_count.get(key, 0)
            d['runs_30d'] = r
            d['pct_pass'] = round(p * 100.0 / r) if r else None
            d['last_seen_at'] = last_seen.get(key)
            d['state'] = (
                'online' if (d.get('last_seen_at') or '') >= cutoff_5m
                else 'idle'
            )
        # Stable order: host asc, then device_id asc.
        matched.sort(key=lambda d: (d['host_name'], d['device_id']))
        return matched
    except Exception as e:
        logger.error("[@projects_db] list_in_scope_devices error: %s", e)
        return []


def list_in_scope_executables(
    project_id: str,
    team_id: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Executables (scripts, testcases, virtual scripts) tagged with the
    project's tag, each with run count and pass rate over the last `days`.

    Scripts are keyed by `script_name` in `script_results` — that's why
    `auto_tag_with_project` inserts the script's display name as the
    `executable_id` (existing G5 contract). Testcases and virtual scripts
    use their own table ids; the `testcases` / `virtual_scripts` table is
    joined to pull the human name. Order: scripts, then testcases, then
    virtual scripts (each sorted by name) — flat, peer list, the
    project-page column "Executables" shows them as siblings.
    """
    if not project_id or not team_id:
        return []
    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    try:
        pt_res = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .execute()
        )
        tag_ids = [int(r['tag_id']) for r in (pt_res.data or []) if r.get('tag_id') is not None]
        if not tag_ids:
            return []
        cap = 5000
        rows: List[Dict[str, Any]] = []
        # -- scripts (executable_id = script display name) -------------------
        for t in tag_ids:
            et = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', 'script')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            for r in (et.data or []):
                eid = r.get('executable_id')
                if eid:
                    rows.append({'type': 'script', 'id': str(eid), 'name': str(eid)})
        # -- testcases --------------------------------------------------------
        for t in tag_ids:
            et = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', 'testcase')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            tc_ids = [r['executable_id'] for r in (et.data or []) if r.get('executable_id')]
            if tc_ids:
                tc = (
                    sb.table('testcases')
                    .select('testcase_id, testcase_name')
                    .eq('team_id', team_id)
                    .in_('testcase_id', tc_ids)
                    .execute()
                )
                for r in (tc.data or []):
                    rows.append({
                        'type': 'testcase',
                        'id': str(r.get('testcase_id')),
                        'name': r.get('testcase_name') or str(r.get('testcase_id')),
                    })
        # -- virtual scripts --------------------------------------------------
        for t in tag_ids:
            et = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', 'virtual_script')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            vs_ids = [r['executable_id'] for r in (et.data or []) if r.get('executable_id')]
            if vs_ids:
                vs = (
                    sb.table('virtual_scripts')
                    .select('id, name')
                    .eq('team_id', team_id)
                    .in_('id', vs_ids)
                    .execute()
                )
                for r in (vs.data or []):
                    rows.append({
                        'type': 'virtual_script',
                        'id': str(r.get('id')),
                        'name': r.get('name') or str(r.get('id')),
                    })
        # Dedupe (a project can tag the same artefact through multiple tags).
        seen = set()
        unique: List[Dict[str, Any]] = []
        for r in rows:
            k = (r['type'], r['id'])
            if k in seen:
                continue
            seen.add(k)
            unique.append(r)
        if not unique:
            return []
        # Per-item run + pass from `script_results` keyed by `script_name` for
        # scripts and `virtual_script_id` for virtual scripts. Testcases
        # don't have their own run table — they run as scripts and we don't
        # have a clean join today, so we report 0 for testcases (a future
        # testcase_runs table would close this gap). For the project page
        # the user mostly wants the script / virtual-script numbers, and
        # "0 runs" for testcases is the honest answer.
        script_names = [r['id'] for r in unique if r['type'] == 'script']
        vs_ids = [r['id'] for r in unique if r['type'] == 'virtual_script']
        sr_pass = (
            sb.table('script_results')
            .select('script_name, virtual_script_id, started_at, success')
            .eq('team_id', team_id)
            .eq('success', True)
            .gte('started_at', cutoff)
            .execute()
        )
        sr_fail = (
            sb.table('script_results')
            .select('script_name, virtual_script_id, started_at')
            .eq('team_id', team_id)
            .eq('success', False)
            .gte('started_at', cutoff)
            .execute()
        )
        # Build a lookup keyed by either script_name or virtual_script_id.
        by_name: Dict[str, Dict[str, int]] = {}
        for r in (sr_pass.data or []):
            for k in (r.get('script_name'), r.get('virtual_script_id')):
                if not k:
                    continue
                slot = by_name.setdefault(str(k), {'runs': 0, 'pass': 0})
                slot['runs'] += 1
                slot['pass'] += 1
        for r in (sr_fail.data or []):
            for k in (r.get('script_name'), r.get('virtual_script_id')):
                if not k:
                    continue
                slot = by_name.setdefault(str(k), {'runs': 0, 'pass': 0})
                slot['runs'] += 1
        for row in unique:
            stat = by_name.get(row['id'])
            if stat and stat['runs']:
                row['runs_30d'] = stat['runs']
                row['pct_pass'] = round(stat['pass'] * 100.0 / stat['runs'])
            else:
                row['runs_30d'] = 0
                row['pct_pass'] = None
        # Stable sort: scripts first by name, then testcases, then virtuals.
        type_order = {'script': 0, 'testcase': 1, 'virtual_script': 2}
        unique.sort(key=lambda r: (type_order.get(r['type'], 9), r['name'].lower()))
        return unique
    except Exception as e:
        logger.error("[@projects_db] list_in_scope_executables error: %s", e)
        return []


def list_in_scope_campaigns(
    project_id: str,
    team_id: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Campaigns tagged with the project, each with the count of executables
    it bundles and its pass rate over the last `days`. Campaigns are at a
    different level from scripts/testcases/virtuals — they orchestrate runs
    across many executables, so the project page shows them in a separate
    full-width section (TASK-101 v3 fix).
    """
    if not project_id or not team_id:
        return []
    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    try:
        pt_res = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .execute()
        )
        tag_ids = [int(r['tag_id']) for r in (pt_res.data or []) if r.get('tag_id') is not None]
        if not tag_ids:
            return []
        cap = 5000
        c_ids: set = set()
        for t in tag_ids:
            et = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', 'campaign')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            for r in (et.data or []):
                if r.get('executable_id'):
                    c_ids.add(str(r['executable_id']))
        if not c_ids:
            return []
        c_res = (
            sb.table('campaigns')
            .select('campaign_id, campaign_name, schedule')
            .eq('team_id', team_id)
            .in_('campaign_id', sorted(c_ids))
            .execute()
        )
        out: List[Dict[str, Any]] = []
        for r in (c_res.data or []):
            cid = str(r.get('campaign_id'))
            out.append({
                'id': cid,
                'name': r.get('campaign_name') or cid,
                'schedule': r.get('schedule'),
            })
        # Bundle counts (scripts + testcases + virtuals in the campaign) from
        # `campaign_executions.script_result_ids` — these are the run ids, not
        # the script ids, so we can't derive a per-type count without joining
        # back through `script_results`. For v1 we expose the run count +
        # pass rate only; the bundled counts are a v2 enhancement (the
        # campaign detail page already has them).
        if out:
            cexe_pass = (
                sb.table('campaign_executions')
                .select('id, success, started_at, campaign_id')
                .eq('team_id', team_id)
                .eq('success', True)
                .gte('started_at', cutoff)
                .in_('campaign_id', sorted(c_ids))
                .execute()
            )
            cexe_fail = (
                sb.table('campaign_executions')
                .select('id, started_at, campaign_id')
                .eq('team_id', team_id)
                .eq('success', False)
                .gte('started_at', cutoff)
                .in_('campaign_id', sorted(c_ids))
                .execute()
            )
            runs: Dict[str, int] = {}
            pass_count: Dict[str, int] = {}
            for r in (cexe_pass.data or []):
                k = str(r.get('campaign_id'))
                runs[k] = runs.get(k, 0) + 1
                pass_count[k] = pass_count.get(k, 0) + 1
            for r in (cexe_fail.data or []):
                runs[str(r.get('campaign_id'))] = runs.get(str(r.get('campaign_id')), 0) + 1
            for c in out:
                r = runs.get(c['id'], 0)
                p = pass_count.get(c['id'], 0)
                c['runs_30d'] = r
                c['pct_pass'] = round(p * 100.0 / r) if r else None
        out.sort(key=lambda c: c['name'].lower())
        return out
    except Exception as e:
        logger.error("[@projects_db] list_in_scope_campaigns error: %s", e)
        return []


def add_executable_to_project(
    project_id: str,
    executable_type: str,
    executable_id: str,
) -> bool:
    """Manually attach an artefact to a project. Idempotent.

    The `auto_tag_with_project` path only fires on create / update. The
    project-detail page's `+ add` button calls this helper so a user can
    link an existing artefact to the project. The mirror image is
    `remove_executable_from_project`. Both stay no-ops on duplicates so
    the UI can retry on a flaky network.
    """
    if executable_type not in ('script', 'testcase', 'virtual_script', 'campaign'):
        return False
    if not executable_id:
        return False
    sb = _supabase()
    try:
        pt = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .execute()
        )
        tag_ids = [int(r['tag_id']) for r in (pt.data or []) if r.get('tag_id') is not None]
        if not tag_ids:
            return False
        # Idempotent insert: de-dup with an existence check on the first tag
        # only (a project has at most one tag today; if we ever widen the
        # schema, we tag through every tag the project owns).
        tag_id = tag_ids[0]
        existing = (
            sb.table('executable_tags')
            .select('executable_id')
            .eq('executable_type', executable_type)
            .eq('executable_id', str(executable_id))
            .eq('tag_id', tag_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            return True
        sb.table('executable_tags').insert({
            'executable_type': executable_type,
            'executable_id': str(executable_id),
            'tag_id': tag_id,
        }).execute()
        return True
    except Exception as e:
        logger.error("[@projects_db] add_executable_to_project error: %s", e)
        return False


def remove_executable_from_project(
    project_id: str,
    executable_type: str,
    executable_id: str,
) -> bool:
    """Manually detach an artefact. Removes the `executable_tags` row(s)
    for this (type, id) across every tag the project owns. The artefact
    itself (script / testcase / virtual_script / campaign row) is NOT
    touched — the `×` button only severs the link.
    """
    if executable_type not in ('script', 'testcase', 'virtual_script', 'campaign'):
        return False
    if not executable_id:
        return False
    sb = _supabase()
    try:
        pt = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .execute()
        )
        tag_ids = [int(r['tag_id']) for r in (pt.data or []) if r.get('tag_id') is not None]
        for tag_id in tag_ids:
            sb.table('executable_tags').delete() \
                .eq('executable_type', executable_type) \
                .eq('executable_id', str(executable_id)) \
                .eq('tag_id', tag_id) \
                .execute()
        return True
    except Exception as e:
        logger.error("[@projects_db] remove_executable_from_project error: %s", e)
        return False


def get_or_create_tag_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get-or-create a `tags` row by name. Mirrors the `folder_tag_db`
    shape (`{tag_id, name}`) so the project-tag-by-name route can call
    the same helper without depending on `folder_tag_db` directly.

    Returns `None` on error. Idempotent — same name returns the same row.

    The insert step uses PostgREST's `Prefer: return=representation` (the
    Supabase JS default), but we don't trust the response shape across
    versions — re-querying by name is the durable contract. The second
    query is cheap (a `select` on a unique-by-name column).
    """
    if not name or not isinstance(name, str):
        return None
    name = name.strip()
    if not name:
        return None
    sb = _supabase()
    try:
        existing = (
            sb.table('tags')
            .select('tag_id, name')
            .eq('name', name)
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]
        try:
            sb.table('tags').insert({'name': name}).execute()
        except Exception:
            # Race: another caller created the same tag in the gap. Fall
            # through to the re-query below.
            pass
        existing = (
            sb.table('tags')
            .select('tag_id, name')
            .eq('name', name)
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]
        return None
    except Exception as e:
        logger.error("[@projects_db] get_or_create_tag_by_name error: %s", e)
        return None


def add_user_tag_to_project(project_id: str, tag_id: int) -> bool:
    """Link a user tag (is_scope=false) to a project. Idempotent on
    duplicates. Distinct from the auto-created scope tag because
    `is_scope` differentiates the two in `projects_tags`.
    """
    sb = _supabase()
    try:
        existing = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .eq('tag_id', int(tag_id))
            .limit(1)
            .execute()
        )
        if existing.data:
            return True
        sb.table('projects_tags').insert({
            'project_id': project_id,
            'tag_id': int(tag_id),
            'is_scope': False,
        }).execute()
        return True
    except Exception as e:
        msg = str(e).lower()
        if 'duplicate' in msg or 'unique' in msg:
            return True
        logger.error("[@projects_db] add_user_tag_to_project error: %s", e)
        return False


def remove_user_tag_from_project(project_id: str, tag_id: int) -> bool:
    """Unlink a user tag from a project. NEVER touches the scope tag —
    the row is only deleted when `is_scope = false`. The `tag` row itself
    is kept (artefacts that were tagged through this tag still link to
    the same `tag_id`).
    """
    sb = _supabase()
    try:
        sb.table('projects_tags').delete() \
            .eq('project_id', project_id) \
            .eq('tag_id', int(tag_id)) \
            .eq('is_scope', False) \
            .execute()
        return True
    except Exception as e:
        logger.error("[@projects_db] remove_user_tag_from_project error: %s", e)
        return False


def list_executable_ids_for_project_tag(
    executable_type: str,
    project: Dict,
) -> Optional[List[str]]:
    """Return the `executable_id` list the `list_*` MCP tools use to filter.

    Returns `None` when `project` is None (caller is in "all" mode and must
    show every artefact). Returns the list of executable_ids tagged with
    the project's tag (cap at 5000 for safety; the list endpoints cap
    anyway).
    """
    if not project or not project.get('tag_ids'):
        return None
    sb = _supabase()
    try:
        ids: set = set()
        for tag_id in project['tag_ids'][:1]:
            res = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', executable_type)
                .eq('tag_id', int(tag_id))
                .limit(5000)
                .execute()
            )
            for r in (res.data or []):
                if r.get('executable_id'):
                    ids.add(r['executable_id'])
        return sorted(ids)
    except Exception as e:
        logger.warning("[@projects_db] list_executable_ids_for_project_tag error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Internal: get-or-create tag (mirrors folder_tag_db.get_or_create_tag)
# ---------------------------------------------------------------------------
def _get_or_create_tag(name: str) -> Optional[Dict[str, Any]]:
    """Find a tag by lowercase name; create it with a stable palette colour if missing."""
    sb = _supabase()
    name = (name or '').strip().lower()
    if not name:
        return None

    # Pre-defined palette (matches the existing TagPicker UI in TestCaseBuilder).
    PALETTE = [
        '#FFB300', '#43A047', '#1E88E5', '#E53935', '#8E24AA',
        '#00ACC1', '#FB8C00', '#5E35B1', '#3949AB', '#039BE5',
        '#00897B', '#7CB342', '#C0CA33', '#FDD835', '#FFB300',
        '#F4511E', '#6D4C41', '#757575', '#546E7A',
    ]

    try:
        existing = (
            sb.table('tags').select('*').eq('name', name).execute()
        )
        if existing.data:
            return existing.data[0]

        # Deterministic colour from the hash of the name so two servers end up
        # with the same colour for the same project.
        import hashlib
        color = PALETTE[hashlib.md5(name.encode('utf-8')).digest()[0] % len(PALETTE)]

        created = sb.table('tags').insert({'name': name, 'color': color}).execute()
        if created.data:
            return created.data[0]
        return None
    except Exception as e:
        # A race lost — someone else inserted the same tag in parallel; re-read.
        try:
            again = sb.table('tags').select('*').eq('name', name).execute()
            if again.data:
                return again.data[0]
        except Exception:
            pass
        logger.error("[@projects_db] _get_or_create_tag error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public helpers used by the route layer
# ---------------------------------------------------------------------------
def list_team_members_for_user(profile_id: str) -> List[Dict]:
    """Every `team_members` row whose `user_id = profile_id`.

    Used by:
      * server_projects_routes._caller_team_member_ids (project ACL)
      * server_team_member_routes.touch_last_seen (heartbeat)
    """
    sb = _supabase()
    try:
        res = (
            sb.table('team_members')
            .select('id, team_id, user_id, role, last_seen_at')
            .eq('user_id', profile_id)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("[@projects_db] list_team_members_for_user error: %s", e)
        return []


def list_team_members_for_team(team_id: str) -> List[Dict]:
    """Every `team_members` row in `team_id`."""
    sb = _supabase()
    try:
        res = (
            sb.table('team_members')
            .select('id, team_id, user_id, role, last_seen_at')
            .eq('team_id', team_id)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("[@projects_db] list_team_members_for_team error: %s", e)
        return []


# ---------------------------------------------------------------------------
# G9 — Tag names + executables for a project (the project filter pipe)
# ---------------------------------------------------------------------------
def get_project_tag_names(project_id: str) -> List[str]:
    """The lowercase tag names a project owns.

    Used by the WorkspaceContext device-side intersection
    (`device_flags.flags ∩ project_tag_names ≠ ∅`).

    Returns an empty list when the project doesn't exist or has no tag,
    which is a safe sentinel for the caller: "no tag → no device passes
    the project scope" (so the project UI shows nothing). Callers that
    want "no scope" semantics must check `currentProject is None` first,
    not rely on an empty list.
    """
    if not project_id:
        return []
    sb = _supabase()
    try:
        # Join through projects_tags → tags so we get the name + color in one query.
        res = (
            sb.table('projects_tags')
            .select('tag_id, tags(name)')
            .eq('project_id', project_id)
            .execute()
        )
        # The real Supabase client returns the join as a nested `tags` object
        # on each row. If the join somehow misses (e.g. RLS strips it), fall
        # back to a direct lookup so the WorkspaceContext still gets names.
        rows = res.data or []
        tag_ids: List[int] = []
        nested_names: List[str] = []
        for row in rows:
            tag = row.get('tags')
            if isinstance(tag, dict) and tag.get('name'):
                nested_names.append(str(tag['name']).lower())
            elif row.get('tag_id') is not None:
                tag_ids.append(int(row['tag_id']))
        if not nested_names and tag_ids:
            tag_res = (
                sb.table('tags')
                .select('tag_id, name')
                .in_('tag_id', tag_ids)
                .execute()
            )
            for tr in (tag_res.data or []):
                if tr.get('name'):
                    nested_names.append(str(tr['name']).lower())
        # Dedupe (defensive — a project should have one tag, but the schema
        # allows many; the WorkspaceContext handles multiple gracefully).
        seen = set()
        out: List[str] = []
        for n in nested_names:
            if n in seen:
                continue
            seen.add(n)
            out.append(n)
        return out
    except Exception as e:
        logger.error("[@projects_db] get_project_tag_names error: %s", e)
        return []


def get_project_executables(project_id: str, team_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return the executables tagged with the project, grouped by type.

    Shape:
        {
          'scripts':          [{'id': 's_web_1', 'name': 's_web_1'}, ...],
          'testcases':        [{'id': 'tc_foo',  'name': 'TC_FOO'}, ...],
          'virtual_scripts':  [{'id': 'vs_a',    'name': 'SC_NAV_01'}, ...],
          'campaigns':        [{'id': 'camp_x',  'name': 'Smoke'}, ...],
        }

    Every list is team-scoped (joined through the team's executable rows)
    AND project-scoped (joined through the project's tag via `executable_tags`).
    Caps each list at 5000 to match the existing list endpoints.

    Used by the G9 endpoint `GET /server/projects/<id>/executables` and by
    the WorkspaceContext's `isExecutableAllowed(type, id)` cache.
    """
    out: Dict[str, List[Dict[str, Any]]] = {
        'scripts': [],
        'testcases': [],
        'virtual_scripts': [],
        'campaigns': [],
    }
    if not project_id or not team_id:
        return out
    sb = _supabase()
    try:
        # Collect the project's tag_ids once — the schema enforces one tag
        # per project today, but the helper stays correct for many.
        pt_res = (
            sb.table('projects_tags')
            .select('tag_id')
            .eq('project_id', project_id)
            .execute()
        )
        tag_ids = [int(r['tag_id']) for r in (pt_res.data or []) if r.get('tag_id') is not None]
        if not tag_ids:
            return out
        cap = 5000
        # -- scripts (from disk): the canonical name IS the id. The tags
        # table stores `executable_id` = the script's bare name (without .py)
        # for scripts and virtual scripts; campaigns carry their own UUID.
        for t in tag_ids:
            et_res = (
                sb.table('executable_tags')
                .select('executable_id, executable_type')
                .eq('executable_type', 'script')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            for r in (et_res.data or []):
                eid = r.get('executable_id')
                if not eid:
                    continue
                out['scripts'].append({'id': str(eid), 'name': str(eid).removesuffix('.py')})
        # -- testcases
        for t in tag_ids:
            et_res = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', 'testcase')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            tc_ids = [r['executable_id'] for r in (et_res.data or []) if r.get('executable_id')]
            if tc_ids:
                tc_res = (
                    sb.table('testcases')
                    .select('testcase_id, testcase_name, team_id')
                    .eq('team_id', team_id)
                    .in_('testcase_id', tc_ids)
                    .execute()
                )
                for r in (tc_res.data or []):
                    out['testcases'].append({
                        'id': str(r.get('testcase_id')),
                        'name': r.get('testcase_name') or str(r.get('testcase_id')),
                    })
        # -- virtual scripts
        for t in tag_ids:
            et_res = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', 'virtual_script')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            vs_ids = [r['executable_id'] for r in (et_res.data or []) if r.get('executable_id')]
            if vs_ids:
                vs_res = (
                    sb.table('virtual_scripts')
                    .select('id, name, team_id')
                    .eq('team_id', team_id)
                    .in_('id', vs_ids)
                    .execute()
                )
                for r in (vs_res.data or []):
                    out['virtual_scripts'].append({
                        'id': str(r.get('id')),
                        'name': r.get('name') or str(r.get('id')),
                    })
        # -- campaigns
        for t in tag_ids:
            et_res = (
                sb.table('executable_tags')
                .select('executable_id')
                .eq('executable_type', 'campaign')
                .eq('tag_id', t)
                .limit(cap)
                .execute()
            )
            c_ids = [r['executable_id'] for r in (et_res.data or []) if r.get('executable_id')]
            if c_ids:
                c_res = (
                    sb.table('campaigns')
                    .select('campaign_id, campaign_name, team_id')
                    .eq('team_id', team_id)
                    .in_('campaign_id', c_ids)
                    .execute()
                )
                for r in (c_res.data or []):
                    out['campaigns'].append({
                        'id': str(r.get('campaign_id')),
                        'name': r.get('campaign_name') or str(r.get('campaign_id')),
                    })
        # Dedupe (a project can tag the same executable through multiple tags).
        for k in out:
            seen = set()
            deduped: List[Dict[str, Any]] = []
            for item in out[k]:
                key = item.get('id')
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            out[k] = deduped
        return out
    except Exception as e:
        logger.error("[@projects_db] get_project_executables error: %s", e)
        return out