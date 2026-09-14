"""
AI User Interface Tools for MCP

Exposes the DB-backed AI-learned UI knowledge base
(`shared.src.lib.database.ai_userinterface_db` via `/server/ai_userinterface/*`
HTTP routes) as agent-callable tools.

See `docs/agent/navigation/AI_USERINTERFACE.md` for the schema and the workflow these
tools implement. Every write enforces the verified-only rule (the underlying
schema has `verified_against NOT NULL` on every sub-row).
"""

import json
import logging
from typing import Any, Dict

from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import ErrorCategory, MCPFormatter

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'


class AIUserInterfaceTools:
    """Read / append / supersede / revert the AI UI knowledge base."""

    def __init__(self, api_client: MCPAPIClient):
        self.api_client = api_client
        self.formatter = MCPFormatter()
        self.logger = logging.getLogger(__name__)

    # =========================================================================
    # READ
    # =========================================================================

    def list_ai_userinterfaces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all AI-learned UI parent rows for the team.

        Example: list_ai_userinterfaces(category='stb')

        Args:
            params: {
                'category': str (OPTIONAL - filter by stb / android-tv / android-mobile / web)
            }

        Returns:
            JSON list of parent rows (no sub-rows). Use get_ai_userinterface for full bundle.
        """
        try:
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            query = {'team_id': team_id}
            if params.get('category'):
                query['category'] = params['category']
            result = self.api_client.get('/server/ai_userinterface/list', params=query)
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'list failed'), ErrorCategory.BACKEND)
            rows = result.get('rows', [])
            text = f"{len(rows)} AI UIs:\n" + "\n".join(
                f"- {r['ui_id']} ({r['category']}, v{r.get('version','?')})" for r in rows
            ) if rows else "No AI UIs yet."
            return {'content': [{'type': 'text', 'text': text}], 'isError': False, 'rows': rows}
        except Exception as e:
            self.logger.error(f'list_ai_userinterfaces failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    def get_ai_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch the full bundle for one AI-learned UI.

        Returned bundle layout (5-layer pack model):
          parent         — the ai_userinterfaces row including goto_home_actions and ui_pack_markdown
          screens        — Layer 1 (one row per known screen with layout + focus + reference)
          transitions    — Layer 2 (one row per verified edge with action batch + status tag)
          verifications  — Layer 3 (per-screen assertions)
          tasks          — Layer 4 (named user-facing flows, e.g. read_firmware)
          quirks, known_hardware, fingerprints — sidecar knowledge, optional

        Example: get_ai_userinterface(ui_id='example-5.02')
        Example: get_ai_userinterface(ui_id='example-5.02', variant_id='example-v1-de')  # example box, DE locale

        Args:
            params: {
                'ui_id': str (REQUIRED - slug like 'example-5.02'),
                'include_superseded': bool (OPTIONAL - include retired rows default false),
                'variant_id': str (OPTIONAL - when the UI has locale / hardware variants. If set, the returned ui_pack_markdown is the variant-specific compiled pack and transitions are filtered so variant-specific rows shadow default ones. Known variants for example-5.02: 'example-v1-de' for the DE-locale Arris BLE box.)
            }

        Returns:
            Bundle dict with keys above. The runtime LLM's primary interest is
            `parent.ui_pack_markdown` (the compiled pack, variant-aware) and
            `tasks[*].steps_md`. The `parent._pack_source` field tells you
            whether the pack is the default or a variant.
        """
        try:
            ui_id = params['ui_id']
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            variant_id = params.get('variant_id')
            query = {'team_id': team_id}
            if params.get('include_superseded'):
                query['include_superseded'] = 'true'
            if variant_id:
                query['variant_id'] = variant_id
            result = self.api_client.get(f'/server/ai_userinterface/get/{ui_id}', params=query)
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'not found'), ErrorCategory.NOT_FOUND)
            b = result['bundle']
            p = b['parent']
            # Defensive access: a schema mismatch should surface as len()=0
            # not a hard KeyError that the runtime LLM cannot diagnose.
            def _n(key): return len(b.get(key) or [])
            pack_md = p.get('ui_pack_markdown') or ''
            goto_home = p.get('goto_home_actions') or []
            tasks_list = b.get('tasks') or []

            variants_dict = p.get('ui_pack_markdown_variants') or {}
            if isinstance(variants_dict, str):
                try:
                    variants_dict = json.loads(variants_dict)
                except Exception:
                    variants_dict = {}
            variant_names = list(variants_dict.keys()) if isinstance(variants_dict, dict) else []
            pack_source = p.get('_pack_source', 'default')
            effective_variant = p.get('effective_variant_id')

            header = (
                f"{p['ui_id']} [{p['category']}/{p.get('operator') or p.get('app') or p.get('domain')} "
                f"v{p['version']}]\n"
                f"current_version={p.get('current_version')}, last_verified={p.get('last_verified')}\n"
                f"pack_source={pack_source}"
                f"{f' (variant_id={effective_variant})' if effective_variant else ''}"
                f"{f'  known_variants={variant_names}' if variant_names else ''}\n"
                f"Layer 1 screens={_n('screens')}  Layer 2 transitions={_n('transitions')}  "
                f"Layer 3 verifications={_n('verifications')}  Layer 4 tasks={_n('tasks')} "
                f"(names: {', '.join(t.get('task_name','?') for t in tasks_list) or '—'})"
            )

            # Surface the actual compiled pack + task bodies in the text payload
            # because the runtime LLM only sees content[0].text — the structured
            # `bundle` field is invisible to it. Without this, the agent would have
            # to introspect the bundle dict (which it can't) and would fall back
            # to improvising navigation.
            body_parts = [header]
            if pack_md:
                body_parts.append(
                    f"\n--- ui_pack_markdown (Layer 0-4 compiled view, {len(pack_md)} chars) ---\n"
                    f"{pack_md}\n"
                    f"--- end ui_pack_markdown ---"
                )
            else:
                body_parts.append("\n(ui_pack_markdown is empty — pack not yet compiled)")

            if goto_home:
                body_parts.append(
                    f"\n--- goto_home_actions ({len(goto_home)} steps, machine-readable) ---\n"
                    f"{json.dumps(goto_home)}\n--- end goto_home_actions ---"
                )

            for t in tasks_list:
                name = t.get('task_name', '?')
                steps = t.get('steps_md', '')
                body_parts.append(
                    f"\n--- task: {name} ---\n"
                    f"description: {t.get('description','') or '(none)'}\n"
                    f"steps:\n{steps}\n"
                    f"--- end task: {name} ---"
                )

            text = "\n".join(body_parts)
            return {'content': [{'type': 'text', 'text': text}], 'isError': False, 'bundle': b}
        except KeyError as e:
            # Specific: REAL missing-input-param case (only fires if the caller
            # omits ui_id, since all bundle access is now .get()-protected).
            return self.formatter.format_error(f'missing required input param: {e}', ErrorCategory.VALIDATION)
        except Exception as e:
            self.logger.error(f'get_ai_userinterface failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    def resolve_ai_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map a runtime fingerprint to a UI slug. Glob-aware for software_version_glob (most-specific pattern wins when several match); equality for the others.

        Example: resolve_ai_userinterface(fingerprint_type='software_version_glob', value='EXSTB001-FWR-PRD-04.02-163-AL-AL-...')

        Args:
            params: {
                'fingerprint_type': str (REQUIRED - software_version_glob | foreground_package | url_host),
                'value': str (REQUIRED - the runtime value to match)
            }

        Returns:
            Matched parent row + ui_id and the winning pattern, with an ambiguity
            warning listing the other matching patterns when several matched, and
            the linked production userinterface_id when set (use it for tree
            operations). On no match: matched=false plus up to 3 near-miss
            patterns (closest literal-prefix overlap) explaining why.
        """
        try:
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            payload = {
                'team_id': team_id,
                'fingerprint_type': params['fingerprint_type'],
                'value': params['value'],
            }
            result = self.api_client.post('/server/ai_userinterface/resolve', data=payload)
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'resolve failed'), ErrorCategory.BACKEND)
            if not result.get('matched'):
                near = result.get('near_misses') or []
                lines = ['No matching ui_id']
                if near:
                    lines.append('Closest registered patterns (by literal-prefix overlap with your value):')
                    lines.extend(
                        f"  - {nm.get('pattern')!r} (ui_id={nm.get('ui_id')}, overlap={nm.get('overlap_chars')} chars)"
                        for nm in near
                    )
                    lines.append('If one of these SHOULD have matched, fix/supersede the fingerprint via add_ai_userinterface_fingerprint / supersede_ai_userinterface_row.')
                return {
                    'content': [{'type': 'text', 'text': '\n'.join(lines)}],
                    'isError': False, 'matched': False, 'near_misses': near,
                }
            p = result['parent']
            meta = p.get('_resolve') or {}
            lines = [f"matched: {p['ui_id']} ({p['category']}) via pattern {meta.get('matched_pattern')!r}"]
            also = meta.get('also_matched') or []
            if meta.get('ambiguous'):
                lines.append('WARNING: ambiguous — other fingerprints for a DIFFERENT UI also matched (most-specific pattern won):')
                lines.extend(f"  - {am.get('pattern')!r} -> ui_id={am.get('ui_id')}" for am in also)
                lines.append('If the winner is wrong, supersede the stale fingerprint.')
            elif also:
                lines.append(f"(note: {len(also)} other pattern(s) for the same UI also matched)")
            if p.get('userinterface_id'):
                lines.append(
                    f"production userinterface: {p['userinterface_id']} — use this for tree operations "
                    f"(navigate_to_node, get_userinterface_complete)."
                )
            return {
                'content': [{'type': 'text', 'text': '\n'.join(lines)}],
                'isError': False, 'matched': True, 'parent': p,
            }
        except KeyError as e:
            return self.formatter.format_error(f'missing param: {e}', ErrorCategory.VALIDATION)
        except Exception as e:
            self.logger.error(f'resolve_ai_userinterface failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    def get_ai_userinterface_history(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full version log of one AI-learned UI's parent record (for rollback decisions).

        Example: get_ai_userinterface_history(ai_userinterface_id='b399eac8-ba3a-4d04-bc27-922d5f7fb36c')

        Args:
            params: {
                'ai_userinterface_id': str (REQUIRED - parent uuid from ai_userinterfaces.id)
            }

        Returns:
            Oldest-first list of {version_number, modification_type, modified_by, changes_summary, snapshot}.
        """
        try:
            ai_id = params['ai_userinterface_id']
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            result = self.api_client.get(
                f'/server/ai_userinterface/history/{ai_id}', params={'team_id': team_id}
            )
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'history failed'), ErrorCategory.BACKEND)
            rows = result.get('rows', [])
            text = f"{len(rows)} versions:\n" + "\n".join(
                f"  v{r['version_number']} {r['modification_type']:8} by {r['modified_by']}: {r.get('changes_summary','')}"
                for r in rows
            ) if rows else 'No history.'
            return {'content': [{'type': 'text', 'text': text}], 'isError': False, 'rows': rows}
        except KeyError as e:
            return self.formatter.format_error(f'missing param: {e}', ErrorCategory.VALIDATION)
        except Exception as e:
            self.logger.error(f'get_ai_userinterface_history failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    # =========================================================================
    # (execute_verified_flow was removed — runtime uses ui_pack_markdown + the
    # two raw tools capture_screenshot & execute_device_action; see
    # docs/agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md.)
    # =========================================================================

    # =========================================================================
    # PARENT CRUD
    # =========================================================================

    def create_ai_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new AI-learned UI parent row. Schema CHECK enforces category-required fields (operator/app/domain).

        Example: create_ai_userinterface(actor='claude-opus-4-7', data={'ui_id': 'netflix-8', 'category': 'android-tv', 'app': 'netflix', 'app_package': 'com.netflix.ninja', 'version': '8.x'})

        Args:
            params: {
                'actor': str (REQUIRED - 'claude-opus-4-7' or user email; used for added_by audit field),
                'data': dict (REQUIRED - parent fields. Required keys: ui_id, category, version. Plus operator OR app OR domain depending on category. Optional: userinterface_id — uuid of the linked production userinterfaces row.)
            }

        Returns:
            Created parent row with id and current_version=1. Initial history snapshot is auto-written.
        """
        try:
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            payload = {'team_id': team_id, 'actor': params['actor'], 'data': params['data']}
            result = self.api_client.post('/server/ai_userinterface/create', data=payload)
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'create failed'), ErrorCategory.BACKEND)
            p = result['parent']
            return {
                'content': [{'type': 'text', 'text': f"created {p['ui_id']} (id={p['id']})"}],
                'isError': False, 'parent': p,
            }
        except KeyError as e:
            return self.formatter.format_error(f'missing param: {e}', ErrorCategory.VALIDATION)
        except Exception as e:
            self.logger.error(f'create_ai_userinterface failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    def update_ai_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update editable fields on the parent. Auto-bumps current_version and writes history snapshot.

        Example: update_ai_userinterface(ui_id='example-5.02', actor='claude-opus-4-7', fields={'last_verified': '2026-04-23'}, changes_summary='Re-verified after firmware patch')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'fields': dict (REQUIRED - subset of: identifying_cues, navigation_primitives, hardware_deltas, unknown_todo, last_verified, middleware_version, version, operator, app, app_package, domain, userinterface_id),
                'changes_summary': str (REQUIRED - one-line audit blurb)
            }

        Returns:
            Updated parent row with bumped current_version.
        """
        try:
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            payload = {
                'team_id': team_id,
                'actor': params['actor'],
                'fields': params['fields'],
                'changes_summary': params['changes_summary'],
            }
            result = self.api_client.post(f"/server/ai_userinterface/update/{params['ui_id']}", data=payload)
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'update failed'), ErrorCategory.BACKEND)
            p = result['parent']
            return {
                'content': [{'type': 'text', 'text': f"updated {p['ui_id']} -> v{p['current_version']}"}],
                'isError': False, 'parent': p,
            }
        except KeyError as e:
            return self.formatter.format_error(f'missing param: {e}', ErrorCategory.VALIDATION)
        except Exception as e:
            self.logger.error(f'update_ai_userinterface failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    def revert_ai_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Roll the parent back to the state in history version `to_version`. Writes a new version with modification_type='restore'. Intervening "wrong" versions remain in history for audit.

        Example: revert_ai_userinterface(ui_id='example-5.02', actor='claude-opus-4-7', to_version=1, reason='Hallucinated identifying_cues in v2')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'to_version': int (REQUIRED - existing version_number to restore from),
                'reason': str (REQUIRED - why the revert is needed)
            }

        Returns:
            New parent row (current_version bumped, fields restored from snapshot).
        """
        try:
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            payload = {
                'team_id': team_id,
                'actor': params['actor'],
                'to_version': params['to_version'],
                'reason': params['reason'],
            }
            result = self.api_client.post(f"/server/ai_userinterface/revert/{params['ui_id']}", data=payload)
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'revert failed'), ErrorCategory.BACKEND)
            p = result['parent']
            return {
                'content': [{'type': 'text', 'text': f"reverted {p['ui_id']} to data of v{params['to_version']} (now v{p['current_version']})"}],
                'isError': False, 'parent': p,
            }
        except KeyError as e:
            return self.formatter.format_error(f'missing param: {e}', ErrorCategory.VALIDATION)
        except Exception as e:
            self.logger.error(f'revert_ai_userinterface failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    # =========================================================================
    # APPEND (sub-rows)
    # =========================================================================

    def add_ai_userinterface_screen(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append a verified screen description to a UI.

        Example: add_ai_userinterface_screen(ui_id='example-5.02', actor='claude-opus-4-7', name='settings.info', verified_against='EXSTB001-FWR-PRD-04.02-163-AL-AL-...', identifying_cues='INFO tab focused', exits='BACK returns to settings root')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'name': str (REQUIRED - dot-notation screen name like 'settings.info.about'),
                'verified_against': str (REQUIRED - build/version string seen on screen),
                'identifying_cues': str (OPTIONAL - markdown describing visual cues),
                'exits': str (OPTIONAL - markdown listing exit transitions)
            }

        Returns:
            Inserted screen row.
        """
        return self._append('screen/add', params)

    def add_ai_userinterface_transition(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append a Layer-2 transition (one edge between screens). `actions` is the
        literal array execute_device_action.actions[] accepts (one entry per press,
        no shorthand).

        Example: add_ai_userinterface_transition(ui_id='example-5.02', actor='claude-opus-4-7', from_screen='home', item_label='gear', to_screen='settings', actions=[{...}, ...], verification_status='deterministic')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'from_screen': str (REQUIRED - source screen name),
                'item_label': str (REQUIRED - label of the item being selected),
                'actions': list (REQUIRED - literal action array),
                'to_screen': str (OPTIONAL - destination screen name),
                'verification_status': str (OPTIONAL - unverified|deterministic|flaky|observed; default unverified)
            }

        Returns:
            Inserted transition row.
        """
        return self._append('transition/add', params)

    def add_ai_userinterface_verification(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append a Layer-3 verification (one assertion for a screen).

        Example: add_ai_userinterface_verification(ui_id='example-5.02', actor='claude-opus-4-7', screen_name='home', kind='present', selector='HOME', severity='hard')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'screen_name': str (REQUIRED - matches ai_userinterface_screens.name),
                'kind': str (REQUIRED - present | regex | value_matches),
                'selector': str (REQUIRED - OCR keyword or VLM field name),
                'expected': str (OPTIONAL - regex pattern or literal; required for kind=regex/value_matches),
                'severity': str (OPTIONAL - hard | soft; default hard)
            }

        Returns:
            Inserted verification row.
        """
        return self._append('verification/add', params)

    def add_ai_userinterface_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append a Layer-4 task (named user-facing flow). steps_md is the prose body
        the runtime LLM reads; it should reference Layer-2 transitions by (from_screen, item_label).

        Example: add_ai_userinterface_task(ui_id='example-5.02', actor='claude-opus-4-7', task_name='read_firmware', steps_md='## Step 1...', description='Return BUILD + SOFTWARE versions')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'task_name': str (REQUIRED - stable identifier, e.g. 'read_firmware'),
                'steps_md': str (REQUIRED - markdown body of the task),
                'description': str (OPTIONAL - one-line summary),
                'verify_assertions': list (OPTIONAL - [{screen, assertion_id}, ...]),
                'returns': list (OPTIONAL - [{name, source_screen, extract_via}, ...])
            }

        Returns:
            Inserted task row.
        """
        return self._append('task/add', params)

    def add_ai_userinterface_quirk(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append a verified quirk (timing oddity, absorbed key, animation lag, etc.).

        Example: add_ai_userinterface_quirk(ui_id='example-5.02', actor='claude-opus-4-7', description='OK render after Settings entry can take >2 s', verified_against='EXSTB001-FWR-PRD-04.02-163-AL-AL-...')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'description': str (REQUIRED - the behaviour observed),
                'verified_against': str (REQUIRED - build/version where it was seen)
            }

        Returns:
            Inserted quirk row.
        """
        return self._append('quirk/add', params)

    def add_ai_userinterface_known_hardware(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append a hardware model that has physically rendered this UI.

        Example: add_ai_userinterface_known_hardware(ui_id='example-5.02', actor='claude-opus-4-7', model='example-stb', hw_rev='REV1.0', verified_at='2026-04-22')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'model': str (REQUIRED - hardware model identifier),
                'verified_at': str (REQUIRED - YYYY-MM-DD date verified),
                'hw_rev': str (OPTIONAL - hardware revision string)
            }

        Returns:
            Inserted known_hardware row.
        """
        return self._append('hardware/add', params)

    def add_ai_userinterface_fingerprint(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append a runtime fingerprint that maps a device's state to this UI. The pattern is matched by resolve_ai_userinterface.

        Example: add_ai_userinterface_fingerprint(ui_id='example-5.02', actor='claude-opus-4-7', fingerprint_type='software_version_glob', pattern='EXSTB001-FWR-PRD-04.02-*-AL-AL-*', verified_against='EXSTB001-FWR-PRD-04.02-163-AL-AL-...')

        Args:
            params: {
                'ui_id': str (REQUIRED - slug),
                'actor': str (REQUIRED - audit field),
                'fingerprint_type': str (REQUIRED - software_version_glob | foreground_package | url_host),
                'pattern': str (REQUIRED - glob for version_glob; exact value for the others),
                'verified_against': str (REQUIRED - one literal value the pattern actually matched)
            }

        Returns:
            Inserted fingerprint row.
        """
        return self._append('fingerprint/add', params)

    # =========================================================================
    # SOFT-DELETE
    # =========================================================================

    def supersede_ai_userinterface_row(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mark a sub-row as superseded (soft-delete). Use when a previously-verified row is found wrong. Never destroys data — the audit trail is the safety net.

        Example: supersede_ai_userinterface_row(actor='claude-opus-4-7', table_short='quirks', row_id='abc-123', reason='Could not reproduce on firmware 5.03')

        Args:
            params: {
                'actor': str (REQUIRED - audit field; populates superseded_by),
                'table_short': str (REQUIRED - one of: screens, flows, quirks, known_hardware, fingerprints),
                'row_id': str (REQUIRED - uuid of the row to retire),
                'reason': str (REQUIRED - why it is being retired)
            }

        Returns:
            success=true if row was marked. The row stays in the DB and is visible via get_ai_userinterface(include_superseded=true).
        """
        try:
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            payload = {
                'team_id': team_id,
                'actor': params['actor'],
                'table_short': params['table_short'],
                'row_id': params['row_id'],
                'reason': params['reason'],
            }
            result = self.api_client.post('/server/ai_userinterface/supersede', data=payload)
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'supersede failed'), ErrorCategory.BACKEND)
            return {
                'content': [{'type': 'text', 'text': f"superseded {params['table_short']}/{params['row_id']}"}],
                'isError': False, 'success': True,
            }
        except KeyError as e:
            return self.formatter.format_error(f'missing param: {e}', ErrorCategory.VALIDATION)
        except Exception as e:
            self.logger.error(f'supersede_ai_userinterface_row failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

    # =========================================================================
    # Internal
    # =========================================================================

    def _append(self, endpoint_suffix: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            team_id = params.get('team_id', DEFAULT_TEAM_ID)
            payload = dict(params)
            payload['team_id'] = team_id
            result = self.api_client.post(
                f'/server/ai_userinterface/{endpoint_suffix}', data=payload
            )
            if not result.get('success'):
                return self.formatter.format_error(result.get('error', 'append failed'), ErrorCategory.BACKEND)
            row = result.get('row')
            return {
                'content': [{'type': 'text', 'text': f"inserted row id={row.get('id') if row else '?'}"}],
                'isError': False, 'row': row,
            }
        except Exception as e:
            self.logger.error(f'_append({endpoint_suffix}) failed: {e}', exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
