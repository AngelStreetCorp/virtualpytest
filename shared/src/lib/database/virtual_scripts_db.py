"""
Virtual Scripts Database Operations

Manages DB-stored Python test scripts (source-in-database). Unlike disk scripts
in test_scripts/, virtual scripts never need an rsync deploy — the host fetches
the source from here and materializes it to a temp .py file at execution time.

Version history is maintained automatically by a BEFORE UPDATE trigger
(save_virtual_script_version_history) — this layer is plain CRUD. See
setup/db/schema/039_virtual_scripts.sql and docs/agent/execution/VIRTUAL_SCRIPTS.md.
"""

from typing import Dict, List, Optional, Any
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.database.folder_tag_db import get_or_create_folder, list_all_folders

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def list_virtual_scripts(team_id: str = DEFAULT_TEAM_ID) -> List[Dict[str, Any]]:
    """List virtual scripts for a team, one entry per NAME (metadata, no source).

    A name has up to 3 rows (dev/test/prod). The returned entry is based on the
    canonical 'dev' row (always exists) and carries the per-environment id map so
    callers can resolve which row to run/edit:

        {..dev row fields.., 'environments': {'dev': id, 'test': id|None,
         'prod': id|None}, 'prod_version': int|None}

    Falls back to any available env for the base fields if a 'dev' row is somehow
    missing (legacy data), so a name never silently disappears from the list.
    """
    supabase = get_supabase()
    try:
        result = (
            supabase.table('virtual_scripts')
            .select('id, name, description, target_rules, folder_id, created_by, created_at, updated_at, environment, prod_version')
            .eq('team_id', team_id)
            .order('name')
            .execute()
        )
    except Exception as e:
        # The virtual-scripts feature is optional (features/virtual-scripts), but this
        # list is read unconditionally by the core Run Tests executables route. A
        # deployment that never applied 20260626/20260904/20260907c (table or
        # columns absent) must not lose the whole Run Tests list over it — an
        # empty virtual-script list is the correct answer there. BUG-0063.
        print(f"[@virtual_scripts_db] ⚠️ virtual_scripts unavailable, listing none: {e}")
        return []
    rows = result.data or []
    folder_names = {f['folder_id']: f['name'] for f in list_all_folders()}

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = row.get('name')
        entry = grouped.setdefault(name, {
            'environments': {'dev': None, 'test': None, 'prod': None},
            'prod_version': None,
            '_base': None,
        })
        env = row.get('environment') or 'dev'
        entry['environments'][env] = row.get('id')
        if env == 'prod':
            entry['prod_version'] = row.get('prod_version')
        # Prefer the dev row for the displayed base fields; else keep the first seen.
        if env == 'dev' or entry['_base'] is None:
            entry['_base'] = row

    out: List[Dict[str, Any]] = []
    for name, entry in grouped.items():
        base = dict(entry['_base'] or {})
        base.pop('environment', None)  # base identity is the name, not an env row
        # Present the dev row id as the primary id (the editor edits dev).
        base['id'] = entry['environments'].get('dev') or base.get('id')
        base['environments'] = entry['environments']
        base['prod_version'] = entry['prod_version']
        base['folder'] = folder_names.get(base.get('folder_id'), '(Root)')
        out.append(base)
    out.sort(key=lambda item: (item.get('name') or '').lower())
    return out


def get_virtual_script(script_id: str, team_id: str = DEFAULT_TEAM_ID) -> Optional[Dict[str, Any]]:
    """Get a single virtual script (incl. source) by id."""
    supabase = get_supabase()
    result = (
        supabase.table('virtual_scripts')
        .select('*')
        .eq('id', script_id)
        .eq('team_id', team_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_virtual_script_by_name(
    name: str,
    team_id: str = DEFAULT_TEAM_ID,
    environment: str = 'dev',
) -> Optional[Dict[str, Any]]:
    """Get a single virtual script (incl. source) by name for a given environment.

    A name has up to 3 rows; without an env filter the lookup is ambiguous. Defaults
    to 'dev' (the canonical, always-present row). Callers resolving a shared library
    (`_script_libs`) or a specific version pass the environment they want.
    """
    supabase = get_supabase()
    result = (
        supabase.table('virtual_scripts')
        .select('*')
        .eq('name', name)
        .eq('team_id', team_id)
        .eq('environment', environment)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def create_virtual_script(
    name: str,
    source: str,
    team_id: str = DEFAULT_TEAM_ID,
    description: Optional[str] = None,
    doc: Optional[str] = None,
    target_rules: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
    environment: str = 'dev',
    folder: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new virtual script row. Raises if (name, environment) already exists
    for the team. New scripts default to the canonical 'dev' environment."""
    supabase = get_supabase()
    payload = {
        'team_id': team_id,
        'name': name,
        'source': source,
        'description': description,
        'doc': doc,
        'target_rules': target_rules,
        'created_by': created_by,
        'environment': environment,
        'folder_id': get_or_create_folder(folder) if folder else 0,
    }
    result = supabase.table('virtual_scripts').insert(payload).execute()
    return (result.data or [{}])[0]


def update_virtual_script(
    script_id: str,
    team_id: str = DEFAULT_TEAM_ID,
    name: Optional[str] = None,
    source: Optional[str] = None,
    description: Optional[str] = None,
    doc: Optional[str] = None,
    target_rules: Optional[Dict[str, Any]] = None,
    folder: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update a virtual script. The DB trigger snapshots the prior version to history."""
    supabase = get_supabase()
    update_fields: Dict[str, Any] = {}
    if name is not None:
        update_fields['name'] = name
    if source is not None:
        update_fields['source'] = source
    if description is not None:
        update_fields['description'] = description
    if doc is not None:
        update_fields['doc'] = doc
    if target_rules is not None:
        update_fields['target_rules'] = target_rules
    if folder is not None:
        update_fields['folder_id'] = get_or_create_folder(folder)
    if not update_fields:
        return get_virtual_script(script_id, team_id)

    result = (
        supabase.table('virtual_scripts')
        .update(update_fields)
        .eq('id', script_id)
        .eq('team_id', team_id)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def delete_virtual_script(script_id: str, team_id: str = DEFAULT_TEAM_ID) -> bool:
    """Delete a virtual script (history rows cascade)."""
    supabase = get_supabase()
    result = (
        supabase.table('virtual_scripts')
        .delete()
        .eq('id', script_id)
        .eq('team_id', team_id)
        .execute()
    )
    return bool(result.data)


def get_virtual_script_versions(script_id: str, team_id: str = DEFAULT_TEAM_ID) -> List[Dict[str, Any]]:
    """Return version history (newest first), plus a synthesized 'latest' entry."""
    supabase = get_supabase()
    history = (
        supabase.table('virtual_scripts_history')
        .select('version_number, name, description, snapshot_timestamp, change_description')
        .eq('virtual_script_id', script_id)
        .eq('team_id', team_id)
        .order('version_number', desc=True)
        .execute()
    ).data or []

    current = get_virtual_script(script_id, team_id)
    versions: List[Dict[str, Any]] = []
    if current:
        versions.append({
            'version_number': None,  # None = current/latest
            'name': current.get('name'),
            'description': current.get('description'),
            'snapshot_timestamp': current.get('updated_at'),
            'change_description': 'Current version',
            'is_current': True,
        })
    versions.extend(history)
    return versions


def restore_virtual_script_version(
    script_id: str,
    version_number: int,
    team_id: str = DEFAULT_TEAM_ID,
) -> Optional[Dict[str, Any]]:
    """Restore a historical version's source into the current script.

    This issues a normal update, so the trigger snapshots the (pre-restore)
    current version to history first — restore is itself versioned.
    """
    supabase = get_supabase()
    snapshot = (
        supabase.table('virtual_scripts_history')
        .select('*')
        .eq('virtual_script_id', script_id)
        .eq('team_id', team_id)
        .eq('version_number', version_number)
        .limit(1)
        .execute()
    ).data or []
    if not snapshot:
        return None
    snap = snapshot[0]
    return update_virtual_script(
        script_id,
        team_id=team_id,
        source=snap.get('source'),
        description=snap.get('description'),
        doc=snap.get('doc'),
        target_rules=snap.get('target_rules'),
    )


# --- Lifecycle: promote + convert -------------------------------------------

_ENV_ORDER = ['dev', 'test', 'prod']


def promote_virtual_script(
    name: str,
    team_id: str = DEFAULT_TEAM_ID,
    target_env: str = 'test',
) -> Dict[str, Any]:
    """Promote a virtual script one step up the lifecycle by COPYING source.

    dev -> test, or test -> prod. The source (and description/doc/target_rules) of
    the lower environment's row is copied into the target row, which is created if
    it does not exist yet, else updated in place.

    On promote-to-prod, updating the existing prod row fires the BEFORE-UPDATE
    history trigger, which snapshots the *previous* prod source to
    virtual_scripts_history as the N-1 rollback point; prod_version is then bumped
    (1 on first promote). See docs/tasks/TASK-07-virtual-script-lifecycle.md.

    Returns {'success': bool, 'error'?: str, 'script'?: row, 'prod_version'?: int}.
    """
    if target_env not in ('test', 'prod'):
        return {'success': False, 'error': f"Cannot promote to '{target_env}' (only test/prod)"}
    source_env = _ENV_ORDER[_ENV_ORDER.index(target_env) - 1]  # test<-dev, prod<-test

    src_row = get_virtual_script_by_name(name, team_id, environment=source_env)
    if not src_row:
        return {'success': False, 'error': f"No '{source_env}' version of '{name}' to promote"}

    supabase = get_supabase()
    target_row = get_virtual_script_by_name(name, team_id, environment=target_env)

    fields = {
        'source': src_row.get('source'),
        'description': src_row.get('description'),
        'doc': src_row.get('doc'),
        'target_rules': src_row.get('target_rules'),
        'folder_id': src_row.get('folder_id'),
    }

    if target_row:
        # Update in place. On prod, bump the version counter — the trigger has
        # already stashed the prior source to history as N-1.
        if target_env == 'prod':
            fields['prod_version'] = (target_row.get('prod_version') or 0) + 1
        result = (
            supabase.table('virtual_scripts')
            .update(fields)
            .eq('id', target_row['id'])
            .eq('team_id', team_id)
            .execute()
        )
        row = (result.data or [None])[0]
    else:
        payload = {
            'team_id': team_id,
            'name': name,
            'environment': target_env,
            'created_by': src_row.get('created_by'),
            **fields,
        }
        if target_env == 'prod':
            payload['prod_version'] = 1
        result = supabase.table('virtual_scripts').insert(payload).execute()
        row = (result.data or [None])[0]

    if not row:
        return {'success': False, 'error': 'Promote failed'}
    return {'success': True, 'script': row, 'prod_version': row.get('prod_version')}


def upsert_virtual_script_dev(
    name: str,
    source: str,
    team_id: str = DEFAULT_TEAM_ID,
    description: Optional[str] = None,
    doc: Optional[str] = None,
    target_rules: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
    folder: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the dev row for `name`, or overwrite its source if it already exists.

    Used by Convert-to-virtual (disk script -> virtual): convert is an idempotent
    re-import into the canonical dev row (decision 4 — overwrite on collision).
    `folder` carries the disk subfolder across, so a converted 'gw/superping'
    becomes the virtual script 'superping' filed under 'gw' (TASK-11).

    Returns {'success': bool, 'script': row, 'action': 'created'|'updated'}.
    """
    existing = get_virtual_script_by_name(name, team_id, environment='dev')
    if existing:
        row = update_virtual_script(
            existing['id'], team_id=team_id, source=source,
            description=description, doc=doc, target_rules=target_rules,
            folder=folder,
        )
        return {'success': bool(row), 'script': row, 'action': 'updated'}
    row = create_virtual_script(
        name=name, source=source, team_id=team_id, description=description,
        doc=doc, target_rules=target_rules, created_by=created_by, environment='dev',
        folder=folder,
    )
    return {'success': bool(row), 'script': row, 'action': 'created'}
