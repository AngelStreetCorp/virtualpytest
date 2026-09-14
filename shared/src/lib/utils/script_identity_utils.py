"""
Script identity utilities.

Provides stable script reference normalization plus the optional prefix /
display_name overrides shown as the TCnnn chip in the UI and in reports.

Source of truth is the executable_identity table (editable from the Test Cases
page); test_scripts/script_identity_map.json is the legacy fallback, kept for
one release. A forwarded override in VPT_SCRIPT_PREFIX / VPT_SCRIPT_DISPLAY_NAME
still wins over both, which is how the server hands identity to a host.

See setup/db/schema/047_executable_identity.sql and test_scripts/script_identity.md.
"""

import json
import os
import subprocess
from typing import Any, Dict, Optional


def get_project_root() -> str:
    """Get project root from shared/src/lib/utils location."""
    current_dir = os.path.dirname(os.path.abspath(__file__))  # /shared/src/lib/utils
    lib_dir = os.path.dirname(current_dir)                    # /shared/src/lib
    src_dir = os.path.dirname(lib_dir)                        # /shared/src
    shared_dir = os.path.dirname(src_dir)                     # /shared
    project_root = os.path.dirname(shared_dir)                # /virtualpytest
    return project_root


def get_script_identity_map_path() -> str:
    """Return absolute path to script identity mapping file."""
    return os.path.join(get_project_root(), 'test_scripts', 'script_identity_map.json')


def normalize_script_ref(script_ref: Optional[str]) -> str:
    """
    Normalize script identifier to canonical script_ref format.

    Examples:
      - "gw/superping.py" -> "gw/superping"
      - "test_scripts/gw/superping.py" -> "gw/superping"
      - "superping.py" -> "superping"
    """
    if not script_ref:
        return ''

    normalized = script_ref.strip().replace('\\', '/')

    if normalized.startswith('./'):
        normalized = normalized[2:]

    if normalized.startswith('test_scripts/'):
        normalized = normalized[len('test_scripts/'):]

    if normalized.endswith('.py'):
        normalized = normalized[:-3]

    return normalized.strip('/')


def script_ref_from_path(script_path: Optional[str], scripts_dir: Optional[str] = None) -> str:
    """Build canonical script_ref from script path."""
    if not script_path:
        return ''

    normalized_path = os.path.abspath(script_path)
    rel_path = ''

    if scripts_dir:
        try:
            rel_path = os.path.relpath(normalized_path, os.path.abspath(scripts_dir))
        except Exception:
            rel_path = os.path.basename(normalized_path)
    else:
        rel_path = os.path.basename(normalized_path)

    return normalize_script_ref(rel_path)


def load_script_identity_map() -> Dict[str, Dict[str, Any]]:
    """
    Load script identity map keyed by normalized script_ref.

    Returns:
      Dict[script_ref, mapping_entry]
    """
    map_path = get_script_identity_map_path()

    if not os.path.exists(map_path):
        return {}

    try:
        with open(map_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        scripts = raw.get('scripts', {}) if isinstance(raw, dict) else {}
        if not isinstance(scripts, dict):
            return {}

        normalized_map: Dict[str, Dict[str, Any]] = {}
        for key, value in scripts.items():
            norm_key = normalize_script_ref(key)
            if not norm_key:
                continue
            if isinstance(value, dict):
                normalized_map[norm_key] = value

        return normalized_map
    except Exception as e:
        print(f"[@script_identity_utils] Failed to load mapping file: {e}")
        return {}


def _lookup_by_basename(script_map: Dict[str, Dict[str, Any]],
                        script_ref: str) -> Dict[str, Any]:
    """Fall back to matching on the file basename.

    A script converted to a virtual script is renamed from 'gw/superping' to
    'superping' (virtual-script names carry no folder), while a legacy JSON map
    is still keyed 'gw/superping'. Without this fallback a scheduled run of a
    converted script silently loses its TCnnn prefix. The browser-side cache
    (frontend/src/utils/identityMapCache.ts) has always done this; the backend
    did not.

    Ambiguous basenames (same file name in two folders) are ignored rather than
    guessed.
    """
    if not script_ref:
        return {}

    basename = script_ref.rsplit('/', 1)[-1]
    matches = [entry for key, entry in script_map.items()
               if key.rsplit('/', 1)[-1] == basename and isinstance(entry, dict)]
    return matches[0] if len(matches) == 1 else {}


def load_effective_identity_map(team_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Legacy JSON map with the DB rows overlaid on top (DB wins per key).

    Used by GET /server/script/identity-map so one request gives the browser the
    complete picture during the release where both sources are live.
    """
    effective: Dict[str, Dict[str, Any]] = dict(load_script_identity_map())

    for script_ref, entry in _load_db_identity_map(team_id).items():
        effective[script_ref] = {
            'prefix': entry.get('prefix'),
            'display_name': entry.get('display_name'),
        }

    return effective


def _load_db_identity_map(team_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """DB-backed identity map, or {} in any context without a usable DB.

    Imported lazily and guarded: this module is imported by the script child
    process, which may run without Supabase configured at all.
    """
    try:
        from shared.src.lib.database.executable_identity_db import get_cached_identity_map
        return get_cached_identity_map(team_id) or {}
    except Exception as e:
        print(f"[@script_identity_utils] DB identity lookup unavailable: {e}")
        return {}


def resolve_script_identity(script_ref_or_name: Optional[str],
                            team_id: Optional[str] = None,
                            use_db: bool = True) -> Dict[str, Any]:
    """
    Resolve canonical script identity plus optional metadata overrides.

    Priority for prefix/display_name:
      1. VPT_SCRIPT_PREFIX / VPT_SCRIPT_DISPLAY_NAME env vars (injected by the
         host parent process when frontend/server provided them)
      2. executable_identity DB rows for the team (the editable source of truth)
      3. test_scripts/script_identity_map.json on local disk (legacy fallback)

    Steps 2 and 3 each try an exact script_ref match first, then an unambiguous
    basename match (see _lookup_by_basename).

    Returns dict:
      {
        "script_ref": "gw/superping",
        "prefix": "TC001" | None,
        "display_name": "Super Ping" | None
      }
    """
    script_ref = normalize_script_ref(script_ref_or_name)

    env_prefix = (os.getenv('VPT_SCRIPT_PREFIX') or '').strip() or None
    env_display = (os.getenv('VPT_SCRIPT_DISPLAY_NAME') or '').strip() or None
    if env_prefix or env_display:
        return {
            'script_ref': script_ref,
            'prefix': env_prefix,
            'display_name': env_display,
        }

    entry: Dict[str, Any] = {}

    if use_db:
        db_map = _load_db_identity_map(team_id)
        entry = db_map.get(script_ref) or _lookup_by_basename(db_map, script_ref)

    if not entry:
        script_map = load_script_identity_map()
        entry = script_map.get(script_ref) or _lookup_by_basename(script_map, script_ref)

    prefix = entry.get('prefix') if isinstance(entry, dict) else None
    display_name = entry.get('display_name') if isinstance(entry, dict) else None

    return {
        'script_ref': script_ref,
        'prefix': prefix,
        'display_name': display_name,
    }


def _normalize_repo_http_url(repo_url: Optional[str]) -> str:
    """Normalize git remote URL to a browser-friendly repository URL."""
    if not repo_url:
        return ''

    normalized = repo_url.strip()
    if normalized.endswith('.git'):
        normalized = normalized[:-4]

    if normalized.startswith('git@'):
        host_and_path = normalized[4:]
        if ':' not in host_and_path:
            return ''
        host, path = host_and_path.split(':', 1)
        return f'https://{host}/{path}'

    if normalized.startswith('https://') or normalized.startswith('http://'):
        protocol, remainder = normalized.split('://', 1)
        if '@' in remainder:
            remainder = remainder.split('@', 1)[1]
        return f'{protocol}://{remainder}'

    return normalized


def infer_repository_http_url() -> str:
    """Infer repository browser URL from env or local git remote."""
    env_repo_url = (
        os.getenv('VPT_REPOSITORY_URL')
        or os.getenv('REPOSITORY_URL')
        or os.getenv('GIT_REPOSITORY_URL')
        or os.getenv('CI_REPOSITORY_URL')
    )
    if env_repo_url:
        return _normalize_repo_http_url(env_repo_url)

    try:
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return _normalize_repo_http_url(result.stdout.strip())
    except Exception:
        pass

    return ''


def infer_source_branch() -> str:
    """Infer current source branch, with env override and safe fallback."""
    branch = (
        os.getenv('VPT_SCRIPT_SOURCE_BRANCH')
        or os.getenv('VPT_REPOSITORY_BRANCH')
        or os.getenv('GIT_BRANCH')
        or os.getenv('BRANCH_NAME')
        or os.getenv('CI_COMMIT_REF_NAME')
    )
    if branch:
        return branch.strip()

    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        inferred = result.stdout.strip()
        if result.returncode == 0 and inferred and inferred != 'HEAD':
            return inferred
    except Exception:
        pass

    return 'main'


def build_script_source_url(script_ref: Optional[str], branch: Optional[str] = None) -> str:
    """Build a browser URL pointing to the source file for one script."""
    normalized_ref = normalize_script_ref(script_ref)
    if not normalized_ref:
        return ''

    repo_url = infer_repository_http_url()
    if not repo_url:
        return ''

    source_branch = (branch or infer_source_branch()).strip() or 'main'
    script_path = f'test_scripts/{normalized_ref}.py'

    if 'github.com' in repo_url:
        return f'{repo_url}/blob/{source_branch}/{script_path}'
    if 'gitlab.com' in repo_url:
        return f'{repo_url}/-/blob/{source_branch}/{script_path}'

    return f'{repo_url}/blob/{source_branch}/{script_path}'


def resolve_script_source_path(script_ref: Optional[str]) -> str:
    """Resolve the local test script path for one normalized script reference."""
    normalized_ref = normalize_script_ref(script_ref)
    if not normalized_ref:
        return ''

    candidate_path = os.path.join(get_project_root(), 'test_scripts', f'{normalized_ref}.py')
    if os.path.exists(candidate_path):
        return candidate_path

    return ''
