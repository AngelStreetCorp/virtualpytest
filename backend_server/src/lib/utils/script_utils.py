#!/usr/bin/env python3
"""
Server-Side Script Utilities

Server-specific script utilities for script management and analysis.
Only contains functions needed by the server (no host-specific functionality).
"""

import os
import glob
import ast
from typing import Dict, List, Optional, Set, Tuple
from shared.src.lib.utils.script_target_rules_utils import extract_script_target_rules_from_path

# Import from shared library (ai_utils is shared between server and host)
try:
    from shared.src.lib.utils.ai_utils import setup_script_environment
except ImportError:
    # Fallback if shared library not available
    def setup_script_environment(script_name: str = "script"):
        return {'success': False, 'error': 'AI utilities not available'}


def _get_project_root() -> str:
    """Find project root from server location"""
    current_dir = os.path.dirname(os.path.abspath(__file__))  # /backend_server/src/lib/utils
    lib_dir = os.path.dirname(current_dir)  # /backend_server/src/lib
    src_dir = os.path.dirname(lib_dir)  # /backend_server/src
    backend_server_dir = os.path.dirname(src_dir)  # /backend_server
    return os.path.dirname(backend_server_dir)  # /virtualpytest


def get_scripts_directory() -> str:
    """Get the default scripts directory path (test_scripts)"""
    project_root = _get_project_root()

    # Use test_scripts folder as the primary scripts location
    return os.path.join(project_root, 'test_scripts')


def _resolve_script_base_and_relative(script_name: str) -> Tuple[str, str]:
    """Resolve script name to a base directory and relative script path."""
    project_root = _get_project_root()
    normalized_name = (script_name or '').replace('\\', '/').lstrip('/')

    if normalized_name.startswith('test_campaign/'):
        base_dir = os.path.join(project_root, 'test_campaign')
        relative_name = normalized_name[len('test_campaign/'):]
    elif normalized_name.startswith('test_scripts/'):
        base_dir = os.path.join(project_root, 'test_scripts')
        relative_name = normalized_name[len('test_scripts/'):]
    else:
        base_dir = os.path.join(project_root, 'test_scripts')
        relative_name = normalized_name

    return base_dir, relative_name


def get_script_path(script_name: str) -> str:
    """Get full path to a script file in test_scripts or test_campaign."""
    base_dir, relative_name = _resolve_script_base_and_relative(script_name)
    base_dir_abs = os.path.abspath(base_dir)

    # Handle script names that already have .py extension
    if relative_name.endswith('.py'):
        script_path = os.path.join(base_dir_abs, relative_name)
    else:
        script_path = os.path.join(base_dir_abs, f'{relative_name}.py')

    script_path = os.path.abspath(script_path)
    if not script_path.startswith(f'{base_dir_abs}{os.sep}') and script_path != base_dir_abs:
        raise ValueError(f'Invalid script path: {script_name}')

    if not os.path.exists(script_path):
        raise ValueError(f'Script not found: {script_path}')

    return script_path


def list_available_scripts() -> list:
    """List all available Python scripts in the scripts directory (supports depth 1 subfolders)"""
    scripts_dir = get_scripts_directory()
    
    if not os.path.exists(scripts_dir):
        return []
    
    available_scripts = []

    # Find all Python files in the root scripts directory
    root_pattern = os.path.join(scripts_dir, '*.py')
    root_files = glob.glob(root_pattern)
    
    for script_file in root_files:
        filename = os.path.basename(script_file)
        script_name = os.path.splitext(filename)[0]  # Remove .py extension
        
        if not is_discoverable_script_ref(script_name):
            continue
            
        available_scripts.append(script_name)
    
    # Find all Python files in subdirectories (depth 1 only)
    subfolder_pattern = os.path.join(scripts_dir, '*', '*.py')
    subfolder_files = glob.glob(subfolder_pattern)
    
    for script_file in subfolder_files:
        # Get relative path from scripts_dir
        rel_path = os.path.relpath(script_file, scripts_dir)
        # Remove .py extension
        script_name = os.path.splitext(rel_path)[0]
        # Replace backslashes with forward slashes for Windows compatibility
        script_name = script_name.replace('\\', '/')
        
        if not is_discoverable_script_ref(script_name):
            continue
            
        available_scripts.append(script_name)
    
    # Include campaign scripts from test_campaign/ (prefixed so get_script_path resolves them)
    campaign_dir = os.path.join(os.path.dirname(scripts_dir), 'test_campaign')
    if os.path.exists(campaign_dir):
        for script_file in sorted(glob.glob(os.path.join(campaign_dir, '*.py'))):
            filename = os.path.basename(script_file)
            script_name = 'test_campaign/' + os.path.splitext(filename)[0]
            if is_discoverable_script_ref(script_name):
                available_scripts.append(script_name)

    # Sort alphabetically
    available_scripts.sort()

    return available_scripts


def extract_script_target_rules(script_name: str):
    """Extract target rules from a script file via simple AST parsing."""
    try:
        script_path = get_script_path(script_name)
    except ValueError:
        return None
    return extract_script_target_rules_from_path(script_path)


def extract_script_description(script_name: str):
    """Extract _script_description from a script file."""
    from shared.src.lib.utils.script_target_rules_utils import extract_script_description_from_path
    try:
        script_path = get_script_path(script_name)
    except ValueError:
        return None
    return extract_script_description_from_path(script_path)


def _normalize_script_reference(script_ref: str) -> str:
    """Normalize a project-relative script reference into the form used by APIs."""
    normalized = (script_ref or '').replace('\\', '/').strip()
    normalized = normalized.lstrip('/')
    if normalized.startswith('./'):
        normalized = normalized[2:]
    if normalized.startswith('test_scripts/'):
        normalized = normalized[len('test_scripts/'):]
    return normalized


def is_discoverable_script_ref(script_ref: str) -> bool:
    """Is this a runnable script, as opposed to a helper module?

    The single rule for "should this appear in a run picker". Applies to disk
    scripts AND virtual scripts: a virtual script named `utils_gw_network` is a
    library pulled in through `_script_libs`, not something a user can execute,
    and listing it invites a run that dies on the missing @script entry point.

    Accepts a ref with or without the .py suffix, with or without a folder.
    """
    normalized = (script_ref or '').replace('\\', '/')
    filename = normalized.rsplit('/', 1)[-1]

    if filename in {'ai_testcase_executor', 'ai_testcase_executor.py'}:
        return False
    if filename.startswith('utils_') or filename.startswith('lib_') or filename.startswith('common_') or filename.startswith('_'):
        return False
    if '__pycache__' in normalized or normalized.startswith('.'):
        return False
    return True


def _list_scripts_in_relative_dir(relative_dir: str) -> List[str]:
    """List Python scripts directly inside one project-relative directory."""
    project_root = _get_project_root()
    normalized_dir = (relative_dir or '').replace('\\', '/').strip().strip('/')
    if not normalized_dir:
        return []

    abs_dir = os.path.abspath(os.path.join(project_root, normalized_dir))
    project_root_abs = os.path.abspath(project_root)
    if not abs_dir.startswith(f'{project_root_abs}{os.sep}') and abs_dir != project_root_abs:
        return []
    if not os.path.isdir(abs_dir):
        return []

    results: List[str] = []
    for script_file in sorted(glob.glob(os.path.join(abs_dir, '*.py'))):
        rel_path = os.path.relpath(script_file, project_root).replace('\\', '/')
        normalized_ref = _normalize_script_reference(rel_path)
        if is_discoverable_script_ref(normalized_ref):
            results.append(normalized_ref)
    return results


def _extract_string_list(node: ast.AST) -> Optional[List[str]]:
    if isinstance(node, (ast.List, ast.Tuple)):
        values: List[str] = []
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                values.append(element.value)
            else:
                return None
        return values
    return None


def _extract_batch_campaign_definition(script_path: str) -> Optional[Dict[str, List[str]]]:
    """
    Parse a `test_campaign/*.py` wrapper that calls `execute_batch_campaign(...)`.

    Returns only statically declared include/exclude selectors. Dynamic campaign
    builders fall back to wrapper-level analysis in the UI.
    """
    try:
        with open(script_path, 'r', encoding='utf-8') as handle:
            tree = ast.parse(handle.read(), filename=script_path)
    except (OSError, SyntaxError):
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        func_name = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr

        if func_name != 'execute_batch_campaign':
            continue

        extracted: Dict[str, List[str]] = {
            'include_dirs': [],
            'include_scripts': [],
            'exclude_scripts': [],
        }
        parse_failed = False

        for keyword in node.keywords:
            if keyword.arg not in extracted:
                continue
            values = _extract_string_list(keyword.value)
            if values is None:
                parse_failed = True
                break
            extracted[keyword.arg] = values

        if not parse_failed:
            return extracted

    return None


def get_recursive_campaign_contained_scripts(
    campaign_script_name: str,
    *,
    max_depth: int = 8,
    visited: Optional[Set[str]] = None,
) -> List[Dict[str, str]]:
    """
    Recursively expand a file campaign into the concrete scripts it contains.

    Supports static `execute_batch_campaign(...)` wrappers and nested
    `test_campaign/...` references. If the wrapper cannot be expanded safely,
    returns an empty list so callers can fall back to wrapper-level analysis.
    """
    normalized_campaign = _normalize_script_reference(campaign_script_name)
    if not normalized_campaign.startswith('test_campaign/'):
        return []
    if max_depth <= 0:
        return []

    seen_campaigns = set(visited or set())
    if normalized_campaign in seen_campaigns:
        return []
    seen_campaigns.add(normalized_campaign)

    try:
        campaign_path = get_script_path(normalized_campaign)
    except ValueError:
        return []

    definition = _extract_batch_campaign_definition(campaign_path)
    if not definition:
        return []

    resolved_refs: List[str] = []
    seen_refs: Set[str] = set()

    for relative_dir in definition.get('include_dirs', []):
        for script_ref in _list_scripts_in_relative_dir(relative_dir):
            if script_ref not in seen_refs:
                resolved_refs.append(script_ref)
                seen_refs.add(script_ref)

    for script_ref in definition.get('include_scripts', []):
        normalized_ref = _normalize_script_reference(script_ref)
        if normalized_ref and normalized_ref not in seen_refs:
            resolved_refs.append(normalized_ref)
            seen_refs.add(normalized_ref)

    excluded_refs = {
        _normalize_script_reference(script_ref)
        for script_ref in definition.get('exclude_scripts', [])
    }

    contained_scripts: List[Dict[str, str]] = []
    for script_ref in resolved_refs:
        if script_ref in excluded_refs:
            continue

        if script_ref.startswith('test_campaign/'):
            contained_scripts.extend(
                get_recursive_campaign_contained_scripts(
                    script_ref,
                    max_depth=max_depth - 1,
                    visited=seen_campaigns,
                )
            )
            continue

        contained_scripts.append({
            'script_name': script_ref,
            'script_type': 'script',
            'description': extract_script_description(script_ref) or '',
        })

    return contained_scripts
