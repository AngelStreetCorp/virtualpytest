"""Virtual Script Tools — let an agent write, read and save DB-stored Python scripts.

Same routes as the Virtual Scripts editor (/server/virtual-script/...), so a script
saved here is validated the same way (syntax hard-fails, missing @script /
_script_args are warnings) and shows up in Run Tests and list_scripts at once.
See docs/agent/execution/VIRTUAL_SCRIPTS.md.
"""

import re
from typing import Dict, Any, Optional
from backend_server.src.mcp.utils.api_client import MCPAPIClient
from shared.src.lib.config.constants import get_team_id

# A virtual script name is also a Python module name: _script_libs imports it and
# the host writes it to `<name>.py` with no mkdir, so no folder, dot or dash.
_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,99}$')


def _text(text: str, is_error: bool = False, **extra) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error, **extra}


# The agent a script is credited to (created_by). The chat agent's id, from the trusted session context.
_CREATORS = {"scripter": "forge", "assistant": "atlas", "analyzer": "sherlock", "monitor": "nightwatch",
             "masterchief": "masterchief"}


def _creator(agent_id: Optional[str]) -> str:
    return _CREATORS.get(str(agent_id or ""), "atlas")


class VirtualScriptTools:
    """Create, update and read virtual scripts (DB-stored Python test scripts)"""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client

    def _find_dev_row(self, name: str, team_id: str) -> Optional[Dict[str, Any]]:
        listed = self.api.get('/server/virtual-script/list', params={'team_id': team_id})
        for row in listed.get('scripts') or []:
            if row.get('name') == name:
                return row
        return None

    def get_virtual_script(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read a virtual script's Python source (dev version) so you can change it and save it back.

        Use this before save_virtual_script when the user asks to edit an existing virtual script.

        Example: get_virtual_script(name='SC_NAV_01_GotoLive')

        Args:
            params: {
                'name': str (REQUIRED - virtual script name as shown by list_scripts)
            }

        Returns:
            MCP response with the source, description, folder and virtual_script_id
        """
        name = (params.get('name') or '').strip()
        team_id = params.get('team_id', get_team_id())
        if not name:
            return _text("name is required", True)

        row = self._find_dev_row(name, team_id)
        if not row:
            return _text(f"No virtual script named '{name}'. Call list_scripts() to see the names.", True)

        full = self.api.get(f"/server/virtual-script/{row['id']}", params={'team_id': team_id})
        script = full.get('script') or {}
        if not full.get('success') or not script:
            return _text(full.get('error') or f"Could not read virtual script '{name}'", True)

        source = script.get('source') or ''
        return _text(
            f"Virtual script '{name}' (folder {row.get('folder') or '(Root)'}, id {row['id']}):\n\n```python\n{source}\n```",
            virtual_script_id=row['id'],
            source=source,
            description=script.get('description'),
            folder=row.get('folder'),
        )

    def save_virtual_script(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save a virtual script (DB-stored Python test script): creates it, or overwrites the dev version if the name exists.

        The script runs on a host with no deploy and appears in Run Tests and list_scripts at once.
        The source must compile: a syntax error is returned with its line, fix it and save again.
        Follow the create-virtual-script skill template (@script decorator, main._script_args,
        main._script_description, main._target_rules). Name: SC_<CAT>_<NUM>_<CamelCase>, letters,
        digits and underscores only; utils_/lib_/common_ names are libraries (imported via
        _script_libs, never run).

        Example: save_virtual_script(name='SC_NAV_01_GotoLive', source='#!/usr/bin/env python3 ...', folder='atlas')

        Args:
            params: {
                'name': str (REQUIRED - script name, e.g. SC_NAV_01_GotoLive),
                'source': str (REQUIRED - full Python source of the script),
                'description': str (OPTIONAL - one line; defaults to main._script_description),
                'doc': str (OPTIONAL - markdown shown in the editor's Doc tab),
                'folder': str (OPTIONAL - folder to file it under, created if missing)
            }

        Returns:
            MCP response with virtual_script_id, created/updated, parsed parameters and warnings
        """
        name = (params.get('name') or '').strip()
        source = params.get('source') or ''
        team_id = params.get('team_id', get_team_id())

        if not _NAME_RE.match(name):
            return _text(
                f"Invalid name '{name}': use letters, digits and underscores only, starting with a letter "
                "(e.g. SC_NAV_01_GotoLive). No folder in the name: pass folder instead.", True)
        if not source.strip():
            return _text("source is required", True)

        existing = self._find_dev_row(name, team_id)
        data = {
            'name': name,
            'source': source,
            'description': params.get('description'),
            'doc': params.get('doc'),
            'folder': params.get('folder'),
            'created_by': _creator(params.get('_context_agent_id')),
        }
        if existing:
            data['id'] = existing['id']

        result = self.api.post('/server/virtual-script/save', data=data, params={'team_id': team_id})

        if not result.get('success'):
            validation = result.get('validation') or {}
            err = validation.get('error') or {}
            if result.get('error') == 'syntax_error' and err:
                return _text(
                    f"Syntax error line {err.get('line')}: {err.get('msg')}\n{err.get('text') or ''}\n"
                    "Fix the source and call save_virtual_script again.", True)
            return _text(f"Save failed: {result.get('error') or result}", True)

        # TASK-65 G5: when the caller passed a `project_id` (or one is in the
        # `X-Project-Id` header on the request), auto-tag the new/updated
        # script with the project's tag. Tagging failures are warnings, not
        # hard errors — the script is already saved.
        project_hint = params.get('project_id') or self._project_id_from_header()
        project = None
        auto_tag_ok = False
        if project_hint:
            try:
                from shared.src.lib.database import projects_db
                project = projects_db.current_project_from_id(project_hint)
                if project:
                    auto_tag_ok = projects_db.auto_tag_with_project(
                        'virtual_script', str(result.get('id')), project,
                    )
            except Exception as e:  # noqa: BLE001 — auto-tag must never break the save
                project = None

        action = 'updated' if existing else 'created'
        warnings = (result.get('validation') or {}).get('warnings') or []
        parameters = result.get('parameters') or []
        flags = ', '.join(f"--{p.get('name')}" for p in parameters if p.get('name')) or 'none'
        lines = [
            f"Virtual script '{name}' {action} (id {result.get('id')}).",
            f"Parameters: {flags}",
        ]
        if warnings:
            lines.append("Warnings: " + '; '.join(str(w) for w in warnings))
        if project:
            if auto_tag_ok:
                lines.append(
                    f"Auto-tagged with project '{project['name']}' (id {project['id']}). "
                    f"It will appear in the project's tag list and the project-scoped list_scripts view.")
            else:
                lines.append(
                    f"Note: project '{project['name']}' was given but the auto-tag step could not link the script to the project's tag. "
                    f"The script is still saved and you can tag it manually from the editor.")
        lines.append(
            f"Run it with execute_script(script_name='{name}', virtual_script_id='{result.get('id')}', host_name, device_id).")
        return _text(
            '\n'.join(lines),
            virtual_script_id=result.get('id'),
            action=action,
            parameters=parameters,
            warnings=warnings,
            project_id=(project['id'] if project else None),
        )

    def _project_id_from_header(self) -> Optional[str]:
        """Pull the current project from the `X-Project-Id` header the
        frontend sets when the user picked a project from ProjectSelector.

        The MCP `api_client` keeps the active headers; we ask it directly
        rather than depending on Flask's `request` (the MCP server may be
        running as a stdio process or inside a worker, not necessarily
        under a Flask app context).
        """
        try:
            headers = getattr(self.api, 'headers', None) or {}
            if isinstance(headers, dict):
                return headers.get('X-Project-Id') or headers.get('x-project-id')
        except Exception:
            return None
        return None
