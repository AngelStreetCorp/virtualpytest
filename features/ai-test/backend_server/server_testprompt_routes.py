"""
Server Test Prompt Routes — CRUD, execution, versioning, feedback loop

Test prompts are AI-driven tests with a dev → prod lifecycle.
"""

import json

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
from ..lib.test_prompts_db import (
    create_test_prompt,
    get_test_prompt,
    list_test_prompts,
    update_test_prompt,
    delete_test_prompt,
    create_new_version,
    get_version_history,
    promote_to_prod,
    record_prompt_execution,
    update_prompt_execution,
    add_human_feedback,
    list_prompt_executions,
)

server_testprompt_bp = Blueprint('server_testprompt', __name__)


# ============================================================================
# LIVE EVENT STREAMING (Socket.IO)
# ============================================================================
# The agent runs in a background thread. We emit each tool_call/tool_result/error
# to the /agent namespace so the frontend can show a live log while the run is
# in progress instead of waiting for the final row to land in Supabase.

_socketio_instance = None


def register_testprompt_socketio(socketio):
    """Wire the Flask-SocketIO instance so live events can be emitted."""
    global _socketio_instance
    _socketio_instance = socketio


def _emit_testprompt_event(execution_id, event_type, content, **extra):
    if _socketio_instance is None or not execution_id:
        return
    try:
        from datetime import datetime
        _socketio_instance.emit(
            'agent_event',
            {
                'type': event_type,
                'agent': 'TestPrompt',
                'content': content,
                'execution_id': execution_id,
                'timestamp': datetime.now().isoformat(),
                **extra,
            },
            room=f'testprompt:{execution_id}',
            namespace='/agent',
        )
    except Exception as e:
        print(f"[@testprompt:emit] failed: {e}", flush=True)


def _deterministic_prenav(execution_id, host_name, device_id, ui_name,
                          target_node_id, target_screen_label, team_id):
    """Navigate deterministically to the starting screen BEFORE invoking the AI.

    The agent used to do this itself as its first navigate_to_node tool call,
    but that tool has a 60s timeout inside the tool adapter and the AI can also
    hallucinate target labels. Running the navigation from our own code removes
    both failure modes and lets the AI start with `current_screen` already known.

    Returns (success: bool, start_screen_label: str, error: Optional[str]).
    """
    import requests

    start_label = (target_screen_label or '').strip()
    _emit_testprompt_event(execution_id, 'prenav_start',
                           f"Navigating to starting screen '{start_label or '(root)'}'")

    try:
        from shared.src.lib.database.userinterface_db import get_userinterface_by_name
        from shared.src.lib.database.navigation_trees_db import (
            get_root_tree_for_interface, get_tree_nodes,
        )
    except Exception as e:
        return False, start_label or 'home', f"Import failed: {e}"

    try:
        ui_row = get_userinterface_by_name(ui_name, team_id) if ui_name else None
        if not ui_row:
            return False, start_label or 'home', f"User interface '{ui_name}' not found"
        root_tree = get_root_tree_for_interface(ui_row['id'], team_id)
        if not root_tree:
            return False, start_label or 'home', f"No navigation tree for '{ui_name}'"
        tree_id = root_tree.get('id') or root_tree.get('tree_id')
        if not tree_id:
            return False, start_label or 'home', "Navigation tree has no id"

        # When no target is provided, navigate to the root node of the
        # interface's tree (the node with data.is_root=true). This is the
        # default "home" node and its label may differ per interface.
        if not target_node_id and not start_label:
            nodes_result = get_tree_nodes(tree_id, team_id, page=0, limit=200)
            nodes = nodes_result.get('nodes', []) if nodes_result.get('success') else []
            root_node = next(
                (n for n in nodes
                 if n.get('data', {}).get('is_root') is True),
                None,
            )
            if root_node:
                target_node_id = root_node.get('node_id') or root_node.get('id')
                start_label = root_node.get('data', {}).get('label', 'home')
                print(f"[@testprompt:prenav] Resolved root node: "
                      f"{start_label} ({target_node_id})")
            else:
                start_label = 'home'
                print(f"[@testprompt:prenav] No root node found, "
                      f"falling back to label 'home'")

        payload = {
            'userinterface_name': ui_name,
            'device_id': device_id,
            'host_name': host_name,
        }
        if target_node_id:
            payload['target_node_id'] = target_node_id
        else:
            payload['target_node_label'] = start_label

        # 120s matches the server-side route timeout
        resp = requests.post(
            f'http://localhost:5109/server/navigation/execute/{tree_id}',
            json=payload,
            params={'team_id': team_id},
            timeout=130,
        )
        try:
            data = resp.json()
        except Exception:
            return False, start_label, f"Navigation HTTP {resp.status_code}: non-JSON response"

        if not resp.ok or not data.get('success'):
            err = data.get('error') or data.get('message') or f"HTTP {resp.status_code}"
            return False, start_label, err

        # The host navigation endpoint is ASYNC — it returns
        # {success: true, execution_id: ...} immediately and runs
        # navigation in a background thread. We must poll the status
        # endpoint until the execution completes, same as the frontend
        # does via waitForExecutionSocketEvent in navigationExecutionUtils.ts.
        nav_exec_id = data.get('execution_id')
        if nav_exec_id:
            import time as _time
            poll_url = (f'http://localhost:5109/server/navigation'
                        f'/execution/{nav_exec_id}/status')
            poll_params = {'team_id': team_id, 'device_id': device_id,
                           'host_name': host_name}
            deadline = _time.time() + 120
            while _time.time() < deadline:
                _time.sleep(1)
                try:
                    pr = requests.get(poll_url, params=poll_params, timeout=10)
                    ps = pr.json() if pr.ok else {}
                except Exception:
                    continue
                status = ps.get('status', '')
                if status == 'completed':
                    _emit_testprompt_event(execution_id, 'prenav_done',
                                           f"Arrived at '{start_label}'")
                    return True, start_label, None
                if status == 'error':
                    return False, start_label, ps.get('error') or 'Navigation failed'
                # still running — keep polling
            return False, start_label, "Pre-navigation timed out (poll)"
        else:
            # Synchronous response (web devices) — already done
            _emit_testprompt_event(execution_id, 'prenav_done',
                                   f"Arrived at '{start_label}'")
            return True, start_label, None

    except requests.Timeout:
        return False, start_label, "Pre-navigation timed out"
    except Exception as e:
        return False, start_label, str(e)


# Map device_model -> test-prompt skill name. Each platform has its own skill
# because the controllers accept entirely different command sets (web =
# Playwright commands, android_mobile = ADB, android_tv = D-pad only,
# stb = IR press_key only). Adding a new device model here without registering
# the matching skill in assistant.yaml will be caught by the hard-fail in
# _resolve_test_prompt_skill().
TEST_PROMPT_SKILL_BY_MODEL = {
    'host_vnc':       'test-prompt-web',
    'web':            'test-prompt-web',
    'android_mobile': 'test-prompt-mobile',
    'android_tablet': 'test-prompt-mobile',
    'android_tv':     'test-prompt-androidtv',
    'stb':            'test-prompt-stb',
    'eos_stb':        'test-prompt-stb',
}


def _resolve_test_prompt_skill(host_name, device_id, team_id):
    """Look up the device_model and return the matching test-prompt skill name.

    Falls back to test-prompt-web for unknown models with a loud warning so
    the next time we see a new device type we know to add a skill for it.
    Returns (skill_name, device_model_or_none).
    """
    import requests
    try:
        resp = requests.get(
            'http://localhost:5109/server/system/getAllHosts',
            params={'team_id': team_id},
            timeout=5,
        )
        data = resp.json() if resp.ok else None
    except Exception as e:
        print(f"[@testprompt:resolve] WARN: getAllHosts failed: {e} — falling back to test-prompt-web", flush=True)
        return 'test-prompt-web', None

    hosts = data if isinstance(data, list) else (data.get('hosts', []) if isinstance(data, dict) else [])
    host = next((h for h in hosts if h.get('host_name') == host_name), None)
    if not host:
        print(f"[@testprompt:resolve] WARN: host '{host_name}' not found in registry — falling back to test-prompt-web", flush=True)
        return 'test-prompt-web', None

    device = next((d for d in host.get('devices', []) if d.get('device_id') == device_id), None)
    model = (device or {}).get('device_model', '') or ''
    skill = TEST_PROMPT_SKILL_BY_MODEL.get(model)
    if skill is None:
        print(f"[@testprompt:resolve] WARN: unknown device_model '{model}' for {host_name}/{device_id} — falling back to test-prompt-web. Add it to TEST_PROMPT_SKILL_BY_MODEL.", flush=True)
        return 'test-prompt-web', model
    return skill, model


# ============================================================================
# CRUD
# ============================================================================

@server_testprompt_bp.route('/server/testprompt/save', methods=['POST'])
@handle_route_exceptions('testprompt:save')
def testprompt_save():
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    prompt_id = data.get('id')

    if prompt_id:
        # Update existing
        result = update_test_prompt(
            prompt_id, team_id,
            name=data.get('name'),
            prompt=data.get('prompt'),
            acceptance_criteria=data.get('acceptance_criteria'),
            target_screen_node_id=data.get('target_screen_node_id'),
            target_screen_label=data.get('target_screen_label'),
            userinterface_name=data.get('userinterface_name'),
        )
    else:
        # Create new
        result = create_test_prompt(
            team_id=team_id,
            name=data.get('name', 'Untitled'),
            prompt=data.get('prompt', ''),
            acceptance_criteria=data.get('acceptance_criteria', ''),
            userinterface_name=data.get('userinterface_name', ''),
            target_screen_node_id=data.get('target_screen_node_id'),
            target_screen_label=data.get('target_screen_label'),
            created_by=data.get('created_by'),
        )

    return jsonify(result)


@server_testprompt_bp.route('/server/testprompt/list', methods=['GET'])
@handle_route_exceptions('testprompt:list')
def testprompt_list():
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    mode = request.args.get('mode')
    prompts = list_test_prompts(team_id, mode=mode)
    return jsonify({'success': True, 'test_prompts': prompts})


@server_testprompt_bp.route('/server/testprompt/<prompt_id>', methods=['GET'])
@handle_route_exceptions('testprompt:get')
def testprompt_get(prompt_id):
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    prompt = get_test_prompt(prompt_id, team_id)
    if not prompt:
        return jsonify({'success': False, 'message': 'Test prompt not found'}), 404

    versions = get_version_history(prompt_id, team_id)
    return jsonify({'success': True, 'test_prompt': prompt, 'versions': versions})


@server_testprompt_bp.route('/server/testprompt/<prompt_id>', methods=['DELETE'])
@handle_route_exceptions('testprompt:delete')
def testprompt_delete(prompt_id):
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    success = delete_test_prompt(prompt_id, team_id)
    return jsonify({'success': success})


# ============================================================================
# VERSIONING
# ============================================================================

@server_testprompt_bp.route('/server/testprompt/<prompt_id>/new-version', methods=['POST'])
@handle_route_exceptions('testprompt:new_version')
def testprompt_new_version(prompt_id):
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    result = create_new_version(
        parent_id=prompt_id,
        team_id=team_id,
        prompt=data.get('prompt', ''),
        acceptance_criteria=data.get('acceptance_criteria', ''),
        created_by=data.get('created_by'),
    )
    return jsonify(result)


@server_testprompt_bp.route('/server/testprompt/<prompt_id>/promote', methods=['POST'])
@handle_route_exceptions('testprompt:promote')
def testprompt_promote(prompt_id):
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    result = promote_to_prod(prompt_id, team_id)
    return jsonify(result)


# ============================================================================
# EXECUTION
# ============================================================================

@server_testprompt_bp.route('/server/testprompt/execute', methods=['POST'])
@handle_route_exceptions('testprompt:execute')
def testprompt_execute():
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    test_prompt_id = data.get('test_prompt_id')
    host_name = data.get('host_name')
    device_id = data.get('device_id')

    if not all([test_prompt_id, host_name, device_id]):
        return jsonify({'success': False, 'message': 'test_prompt_id, host_name, device_id are required'}), 400

    # Load prompt from DB
    prompt = get_test_prompt(test_prompt_id, team_id)
    if not prompt:
        return jsonify({'success': False, 'message': 'Test prompt not found'}), 404

    # Optional inline overrides — let the frontend send the in-memory (possibly
    # unsaved) form values so the user can iterate without bumping the saved
    # version. Falls back to the persisted prompt fields when not provided.
    override_prompt = data.get('prompt')
    override_criteria = data.get('acceptance_criteria')
    override_target_label = data.get('target_screen_label')
    override_target_node = data.get('target_screen_node_id')

    if override_prompt is not None and str(override_prompt).strip():
        prompt = dict(prompt)
        prompt['prompt'] = override_prompt
    if override_criteria is not None and str(override_criteria).strip():
        prompt = dict(prompt) if not isinstance(prompt, dict) else prompt
        prompt['acceptance_criteria'] = override_criteria
    if override_target_label is not None:
        prompt = dict(prompt) if not isinstance(prompt, dict) else prompt
        prompt['target_screen_label'] = override_target_label
    if override_target_node is not None:
        prompt = dict(prompt) if not isinstance(prompt, dict) else prompt
        prompt['target_screen_node_id'] = override_target_node

    # Record execution
    execution_id = record_prompt_execution(
        test_prompt_id=test_prompt_id,
        team_id=team_id,
        host_name=host_name,
        device_id=device_id,
        executed_by=data.get('executed_by'),
    )

    if not execution_id:
        return jsonify({'success': False, 'message': 'Failed to record execution'}), 500

    # Build agent message from prompt + criteria
    target_screen = prompt.get('target_screen_label', '')
    ui_name = prompt.get('userinterface_name', '')

    # Pre-load the navigation tree server-side and embed it in the agent message.
    # Without this, the LLM has to call get_userinterface_complete and then guess
    # node labels — MiniMax in particular tends to skip the lookup and hallucinate
    # labels like "TV Guide" that don't exist in the tree, causing every navigate_to_node
    # call to fail. With the tree pre-loaded, the agent can copy labels verbatim.
    nav_tree_text = ''
    try:
        from shared.src.lib.database.userinterface_db import get_userinterface_by_name
        from shared.src.lib.database.navigation_trees_db import (
            get_root_tree_for_interface,
            get_full_tree,
        )

        ui_row = get_userinterface_by_name(ui_name, team_id) if ui_name else None
        if ui_row:
            root_tree = get_root_tree_for_interface(ui_row['id'], team_id)
            if root_tree:
                tree_data = get_full_tree(root_tree['id'], team_id)
                if tree_data.get('success'):
                    nodes = tree_data.get('nodes') or []
                    edges = tree_data.get('edges') or []

                    # Build a node_id -> label map for resolving edge endpoints.
                    label_by_id = {}
                    for n in nodes:
                        nid = n.get('node_id') or n.get('id')
                        lbl = n.get('label') or (n.get('data') or {}).get('label')
                        if nid and lbl:
                            label_by_id[nid] = lbl

                    # Cap to avoid blowing the context window on huge trees.
                    MAX_NODES = 200
                    MAX_EDGES = 400
                    node_lines = []
                    for n in nodes[:MAX_NODES]:
                        lbl = n.get('label') or (n.get('data') or {}).get('label') or '(unlabeled)'
                        ntype = n.get('node_type') or (n.get('data') or {}).get('node_type') or 'screen'
                        node_lines.append(f"- {lbl} ({ntype})")
                    if len(nodes) > MAX_NODES:
                        node_lines.append(f"- ... ({len(nodes) - MAX_NODES} more nodes truncated)")

                    edge_lines = []
                    for e in edges[:MAX_EDGES]:
                        src = label_by_id.get(e.get('source_node_id'), '?')
                        dst = label_by_id.get(e.get('target_node_id'), '?')
                        # Pull first action command from the default action set if available.
                        first_cmd = ''
                        try:
                            action_sets = e.get('action_sets') or []
                            default_id = e.get('default_action_set_id')
                            chosen = next((a for a in action_sets if a.get('id') == default_id), None) or (action_sets[0] if action_sets else None)
                            if chosen:
                                acts = chosen.get('actions') or []
                                if acts:
                                    first_cmd = acts[0].get('command', '') or ''
                        except Exception:
                            pass
                        suffix = f" [{first_cmd}]" if first_cmd else ''
                        edge_lines.append(f"- {src} -> {dst}{suffix}")
                    if len(edges) > MAX_EDGES:
                        edge_lines.append(f"- ... ({len(edges) - MAX_EDGES} more edges truncated)")

                    nav_tree_text = (
                        "\n\n**Pre-loaded Navigation Tree** (do NOT call get_userinterface_complete — it is not available; use these labels EXACTLY as written when calling navigate_to_node, do not guess or invent labels):\n\n"
                        f"Nodes ({len(nodes)} total):\n" + "\n".join(node_lines) +
                        f"\n\nEdges ({len(edges)} total, format `from -> to [first_action]`):\n" + "\n".join(edge_lines)
                    )
                    print(f"[@testprompt:execute] Pre-loaded nav tree: {len(nodes)} nodes, {len(edges)} edges for ui={ui_name}", flush=True)
                else:
                    print(f"[@testprompt:execute] get_full_tree failed for ui={ui_name}", flush=True)
            else:
                print(f"[@testprompt:execute] No root tree for ui={ui_name}", flush=True)
        else:
            print(f"[@testprompt:execute] User interface not found: {ui_name}", flush=True)
    except Exception as _tree_err:
        print(f"[@testprompt:execute] Failed to pre-load nav tree: {_tree_err}", flush=True)

    # agent_message is finalised inside _run_agent() AFTER the deterministic
    # pre-nav step so we can tell the AI the actual starting screen.

    # Run agent in background thread
    import threading

    prompt_name = prompt.get('name', 'test_prompt').replace(' ', '_').replace('/', '_')
    prompt_text = prompt['prompt']
    criteria_text = prompt['acceptance_criteria']
    target_node_id_val = prompt.get('target_screen_node_id') or None

    def _run_agent():
        import asyncio
        import time as _time

        start_time = _time.time()
        report_url = None
        logs_url = None

        # Collector state + helpers are initialised up-front so the pre-nav
        # failure path AND the main exception handler can both call
        # _publish_report() with whatever partial data we already have.
        final_message = ''
        log_lines = []
        step_results = []
        screenshot_urls = []
        step_num = 0
        prev_tool_name = ''
        prev_tool_params = {}

        def _self_api_get(endpoint, params):
            import requests
            try:
                resp = requests.get(f'http://localhost:5109{endpoint}', params=params, timeout=5)
                return resp.json()
            except Exception:
                return None

        def _resolve_host_info():
            hosts_result = _self_api_get('/server/system/getAllHosts', {'team_id': team_id})
            if isinstance(hosts_result, list):
                return next((h for h in hosts_result if h.get('host_name') == host_name), None)
            if isinstance(hosts_result, dict) and hosts_result.get('hosts'):
                return next((h for h in hosts_result['hosts'] if h.get('host_name') == host_name), None)
            return None

        def _publish_report(current_status, error_text=None):
            """Generate + upload a script report. Returns (report_url, logs_url, execution_time_ms).

            Called from the happy path AND every error path so error runs still
            get a Report/Logs link in the UI instead of blank cells.
            """
            try:
                from backend_server.src.lib.utils.route_utils import call_host
                from shared.src.lib.database.script_results_db import (
                    record_script_execution_start,
                    update_script_execution_result,
                )
                from shared.src.lib.utils.report_generation_utils import (
                    generate_and_upload_script_report,
                )
            except Exception as imp_err:
                print(f"[@testprompt:agent] Report import error: {imp_err}", flush=True)
                return None, None, int((_time.time() - start_time) * 1000)

            execution_time_ms_local = int((_time.time() - start_time) * 1000)
            # Preserve the AI's final reasoning — this is the whole point of
            # running a test prompt (the "why did it pass / fail"). The report
            # template renders execution_summary verbatim, so we embed it
            # prominently here. Without this, the HTML report shows the tool
            # calls but never reveals what the AI concluded.
            ai_verdict = (final_message or '').strip()
            summary_parts = [
                f"Prompt: {prompt_text}",
                "",
                f"Acceptance Criteria: {criteria_text}",
                "",
                f"Target Screen: {start_screen}",
                f"Result: {current_status.upper()}",
                f"Duration: {execution_time_ms_local}ms",
                f"Steps: {len(step_results)}",
                f"Screenshots: {len(screenshot_urls)}",
            ]
            if ai_verdict:
                summary_parts.extend(["", "AI Verdict:", ai_verdict])
            if error_text:
                summary_parts.extend(["", f"Error: {error_text}"])
            summary = "\n".join(summary_parts)

            # stdout is what populates the "Execution Logs: Click here" file in
            # R2. Put the AI verdict at the top so readers don't have to scroll
            # through 200 lines of tool-call traces to find the conclusion.
            stdout_sections = []
            if ai_verdict:
                stdout_sections.append("=== AI Verdict ===\n" + ai_verdict + "\n")
            stdout_sections.append("=== Tool Trace ===")
            stdout_sections.append('\n'.join(log_lines) if log_lines else '(no tool events captured)')
            if error_text:
                stdout_sections.append(f"\n[FATAL ERROR] {error_text}")
            stdout_text = '\n'.join(stdout_sections)

            report_url_local = None
            logs_url_local = None
            script_full_name = f"prompt_{prompt_name}"
            device_model_for_report = 'host_vnc'
            try:
                script_result_id = record_script_execution_start(
                    team_id=team_id,
                    script_name=script_full_name,
                    script_type='test_prompt',
                    host_name=host_name,
                    device_name=device_id,
                    userinterface_name=ui_name,
                    metadata={'test_prompt_id': test_prompt_id, 'prompt_execution_id': execution_id},
                )

                # Capture + upload video via the host — mirrors what script_executor
                # does in-process. Must happen AFTER script_result_id is known so the
                # video lands in the same R2 folder as the report.
                test_video_url_local = ''
                try:
                    host_info = _resolve_host_info()
                    if host_info:
                        video_duration = max(10.0, execution_time_ms_local / 1000.0)
                        video_result = call_host(
                            host_info, '/host/av/takeVideoForReport',
                            method='POST',
                            data={
                                'device_id': device_id,
                                'duration': video_duration,
                                'start_time': start_time,
                                'device_model': device_model_for_report,
                                'script_name': script_full_name,
                                'script_result_id': script_result_id,
                            },
                            query_params={'team_id': team_id},
                            timeout=60,
                        )
                        if isinstance(video_result, tuple):
                            video_result = video_result[0]
                        test_video_url_local = video_result.get('video_url', '') if isinstance(video_result, dict) else ''
                except Exception as video_err:
                    print(f"[@testprompt:agent] Video capture error: {video_err}", flush=True)

                report_result = generate_and_upload_script_report(
                    script_name=script_full_name,
                    device_info={'device_id': device_id, 'device_name': device_id, 'device_model': device_model_for_report},
                    host_info={'host_name': host_name},
                    execution_time=execution_time_ms_local,
                    success=(current_status == 'passed'),
                    step_results=step_results,
                    screenshot_paths=screenshot_urls,
                    screenshot_url_mapping={},
                    execution_summary=summary,
                    stdout=stdout_text,
                    test_video_url=test_video_url_local,
                    script_result_id=script_result_id,
                )
                report_url_local = (report_result or {}).get('report_url')
                logs_url_local = (report_result or {}).get('logs_url')
                if script_result_id:
                    update_script_execution_result(
                        script_result_id=script_result_id,
                        success=(current_status == 'passed'),
                        execution_time_ms=execution_time_ms_local,
                        html_report_r2_url=report_url_local,
                        logs_r2_url=logs_url_local,
                    )
                print(f"[@testprompt:agent] Report ({current_status}): {report_url_local}", flush=True)
            except Exception as report_err:
                print(f"[@testprompt:agent] Report generation error: {report_err}", flush=True)
                import traceback
                traceback.print_exc()

            return report_url_local, logs_url_local, execution_time_ms_local

        # Deterministic pre-navigation (before the AI runs). If this fails we
        # abort loudly instead of letting the AI try and fail with a 60s timeout.
        _emit_testprompt_event(execution_id, 'status', 'Pre-navigating to starting screen…')
        prenav_ok, start_screen, prenav_err = _deterministic_prenav(
            execution_id, host_name, device_id, ui_name,
            target_node_id_val, target_screen, team_id,
        )
        if not prenav_ok:
            _emit_testprompt_event(execution_id, 'error',
                                   f"Pre-navigation failed: {prenav_err}")
            log_lines.append(f"[ERROR] Pre-navigation failed: {prenav_err}")
            report_url, logs_url, execution_time_ms = _publish_report(
                'error', error_text=f"Pre-navigation failed: {prenav_err}"
            )
            try:
                update_prompt_execution(
                    execution_id=execution_id,
                    team_id=team_id,
                    status='error',
                    report_url=report_url,
                    logs_url=logs_url,
                    execution_time_ms=execution_time_ms,
                )
            except Exception:
                pass
            _emit_testprompt_event(execution_id, 'testprompt_completed',
                                   'Completed with pre-nav failure',
                                   status='error',
                                   report_url=report_url,
                                   logs_url=logs_url,
                                   execution_time_ms=execution_time_ms)
            return

        agent_message = (
            f"Execute test prompt on device.\n\n"
            f"**Host:** {host_name}\n"
            f"**Device:** {device_id}\n"
            f"**Interface:** {ui_name}\n"
            f"**Starting Screen:** {start_screen} (you are already here — do NOT call navigate_to_node to reach it)\n\n"
            f"**Prompt:** {prompt_text}\n\n"
            f"**Acceptance Criteria:** {criteria_text}"
            f"{nav_tree_text}"
        )

        try:
            from backend_server.src.routes.server_agent_routes import get_manager, get_session_manager

            session_mgr = get_session_manager()
            session = session_mgr.create_session()
            session.set_context('host_name', host_name)
            session.set_context('device_id', device_id)
            session.set_context('userinterface_name', ui_name)
            session.set_context('team_id', team_id)
            session.set_context('agent_id', 'assistant')

            manager = get_manager(team_id=team_id, agent_id='assistant', session=session)
            skill_name, device_model = _resolve_test_prompt_skill(host_name, device_id, team_id)
            print(f"[@testprompt:agent] Resolving skill for device_model='{device_model}' -> {skill_name}", flush=True)
            if not manager.load_skill(skill_name):
                # Hard-fail loud — silently falling back to router mode is the
                # exact bug that ate hours of debugging earlier today.
                raise RuntimeError(
                    f"Failed to load skill '{skill_name}' for device_model='{device_model}'. "
                    f"Check that '{skill_name}' is in assistant.yaml available_skills."
                )
            print(f"[@testprompt:agent] Pre-loaded skill: {skill_name}", flush=True)

            # Auto-screenshot helper — calls the AV takeScreenshot API directly
            def _auto_screenshot():
                try:
                    from backend_server.src.lib.utils.route_utils import call_host
                    host_info = _resolve_host_info()
                    if host_info:
                        result = call_host(host_info, '/host/av/takeScreenshot',
                                          method='POST',
                                          data={'device_id': device_id},
                                          query_params={'team_id': team_id},
                                          timeout=10)
                        if isinstance(result, tuple):
                            result = result[0]
                        screenshot_url = result.get('screenshot_url') if isinstance(result, dict) else None
                        if screenshot_url:
                            print(f"[@testprompt:agent] Auto-screenshot: {screenshot_url[:80]}", flush=True)
                            return screenshot_url
                except Exception as e:
                    print(f"[@testprompt:agent] Auto-screenshot error: {e}", flush=True)
                return None

            # Initial screenshot
            initial_ss = _auto_screenshot()
            if initial_ss:
                screenshot_urls.append(initial_ss)

            from datetime import datetime as _dt, timezone as _tz
            from shared.src.lib.utils.local_debug_browser_helpers import append_local_debug_step_result

            # Pending step context carried from tool_call to tool_result so we can
            # stamp the step once — same shape facebook_check.py builds via
            # append_local_debug_step_result (which is the canonical step-record
            # helper used by every local-debug script).
            pending_step = {'t0': None, 'start_iso': None, 'msg': '', 'actions': []}

            async def run():
                nonlocal final_message, step_num, prev_tool_name, prev_tool_params
                async for event in manager.process_message(agent_message, session):
                    event_dict = event.to_dict() if hasattr(event, 'to_dict') else {}
                    event_type = event_dict.get('type', '')
                    content = str(event_dict.get('content', ''))
                    content_short = content[:200]

                    if event_type == 'tool_call':
                        tool_name = event_dict.get('tool_name', '')
                        tool_params = event_dict.get('tool_params', {})
                        prev_tool_name = tool_name
                        prev_tool_params = tool_params if isinstance(tool_params, dict) else {}
                        step_num += 1

                        # Build step description
                        if tool_name == 'execute_device_action':
                            actions = prev_tool_params.get('actions', [])
                            cmds = [a.get('command', '?') for a in actions] if isinstance(actions, list) else []
                            msg = ', '.join(cmds) if cmds else 'device action'
                        else:
                            msg = tool_name

                        pending_step['t0'] = _time.time()
                        pending_step['start_iso'] = _dt.now(_tz.utc).isoformat()
                        pending_step['msg'] = msg
                        pending_step['actions'] = [{'command': msg, 'params': {}}]

                        try:
                            params_repr = json.dumps(tool_params, default=str, ensure_ascii=False)
                        except Exception:
                            params_repr = str(tool_params)
                        log_lines.append(f"[TOOL_CALL] {tool_name}: {params_repr[:4000]}")

                    elif event_type == 'tool_result':
                        is_error = event_dict.get('success') == False or 'error' in content_short.lower()

                        # Extract the human-readable payload from the MCP result.
                        # Shape: {"content":[{"type":"text","text":"..."}], "isError": bool}
                        # dump_elements / find_element put their actual output (XML dump,
                        # matched element, etc.) inside content[0].text — that's what we
                        # want visible in the HTML report, not the JSON-escaped wrapper.
                        tool_result_payload = event_dict.get('tool_result')
                        payload_text = ''
                        if isinstance(tool_result_payload, dict):
                            blocks = tool_result_payload.get('content')
                            if isinstance(blocks, list):
                                payload_text = '\n'.join(
                                    b.get('text', '') for b in blocks
                                    if isinstance(b, dict) and b.get('type') == 'text' and b.get('text')
                                )
                        if not payload_text and tool_result_payload is not None:
                            try:
                                payload_text = json.dumps(tool_result_payload, default=str, ensure_ascii=False, indent=2)
                            except Exception:
                                payload_text = str(tool_result_payload)
                        if not payload_text:
                            payload_text = content

                        if pending_step['t0'] is not None:
                            end_iso = _dt.now(_tz.utc).isoformat()
                            duration_ms = int((_time.time() - pending_step['t0']) * 1000)
                            append_local_debug_step_result(
                                step_results=step_results,
                                message=pending_step['msg'],
                                success=not is_error,
                                from_node='current',
                                to_node='current',
                                actions=pending_step['actions'],
                                verifications=[],
                                screenshot_path='',
                                step_start_time=pending_step['start_iso'],
                                step_end_time=end_iso,
                                step_duration_ms=duration_ms,
                            )
                            # Surface the tool output in the HTML report: renderer
                            # reads step['script_output'] (stdout/stderr/exit_code)
                            # and emits a <pre> block. Keeps the payload visible in
                            # the report itself, same way scripts do via stdout.
                            step_results[-1]['script_output'] = {
                                'stdout': '' if is_error else payload_text,
                                'stderr': payload_text if is_error else '',
                                'exit_code': 1 if is_error else 0,
                            }
                            if is_error:
                                step_results[-1]['error'] = content_short
                            pending_step['t0'] = None

                        log_lines.append(f"[TOOL_RESULT] {'ERROR' if is_error else 'OK'}: {payload_text[:8000]}")

                        # Auto-screenshot after every successful tool call so
                        # each step in the HTML report has a visual.
                        if not is_error:
                            ss = _auto_screenshot()
                            if ss:
                                screenshot_urls.append(ss)
                                if step_results:
                                    step_results[-1]['screenshot_path'] = ss
                                    step_results[-1]['step_end_screenshot_path'] = ss

                    elif event_type in ('message', 'result'):
                        final_message = event_dict.get('content', '')
                        log_lines.append(f"[MESSAGE] {str(final_message)}")

                    elif event_type == 'error':
                        log_lines.append(f"[ERROR] {content_short}")

                    print(f"[@testprompt:agent] {event_type}: {content_short[:100]}", flush=True)

                    # Stream the event to the frontend so the user sees progress
                    # while the run is still in flight. Extra fields (tool name,
                    # params, step number) help render a richer live log.
                    emit_extra = {}
                    if event_type == 'tool_call':
                        emit_extra['tool_name'] = event_dict.get('tool_name', '')
                        emit_extra['tool_params'] = event_dict.get('tool_params', {})
                        emit_extra['step_number'] = step_num
                    _emit_testprompt_event(execution_id, event_type, content_short, **emit_extra)

            asyncio.run(run())

            # Final screenshot — append unconditionally so the report always has a
            # distinct [-1] entry for the "Final State" card. VNC takeScreenshot
            # can return the same latest.png URL across calls; deduplicating here
            # would collapse initial + final into one and leave Final State blank.
            final_ss = _auto_screenshot()
            if final_ss:
                screenshot_urls.append(final_ss)

            # Parse pass/fail. If the agent's final message contains neither
            # an explicit pass nor fail marker (e.g. it crashed mid-run, the LLM
            # returned 400, the message is empty, etc.), record as 'error' so
            # broken runs do not silently look like successes.
            msg_lower = (final_message or '').lower()
            has_pass = 'overall: pass' in msg_lower or '### overall: pass' in msg_lower
            has_fail = '[fail]' in msg_lower or 'overall: fail' in msg_lower
            if has_pass and not has_fail:
                status = 'passed'
            elif has_fail:
                status = 'failed'
            else:
                status = 'error'

            report_url, logs_url, execution_time_ms = _publish_report(status)

            update_prompt_execution(
                execution_id=execution_id,
                team_id=team_id,
                status=status,
                report_url=report_url,
                logs_url=logs_url,
                execution_time_ms=execution_time_ms,
            )

            print(f"[@testprompt:agent] Execution {execution_id} completed: {status}, {len(step_results)} steps, {len(screenshot_urls)} screenshots", flush=True)

            _emit_testprompt_event(
                execution_id, 'testprompt_completed',
                f"Completed: {status}",
                status=status,
                report_url=report_url,
                logs_url=logs_url,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            print(f"[@testprompt:agent] Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Still produce a report + logs URL so the UI has something to link
            # to. Without this the "Error" row just shows empty Report/Logs.
            report_url, logs_url, execution_time_ms = _publish_report('error', error_text=str(e))
            update_prompt_execution(
                execution_id=execution_id,
                team_id=team_id,
                status='error',
                report_url=report_url,
                logs_url=logs_url,
                execution_time_ms=execution_time_ms,
            )
            _emit_testprompt_event(
                execution_id, 'testprompt_completed',
                f"Completed with error: {e}",
                status='error',
                report_url=report_url,
                logs_url=logs_url,
                execution_time_ms=execution_time_ms,
            )

    thread = threading.Thread(target=_run_agent, daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'execution_id': execution_id,
        'test_prompt_id': test_prompt_id,
        'message': 'Execution started via AI agent',
    })


# ============================================================================
# EXECUTION FEEDBACK
# ============================================================================

@server_testprompt_bp.route('/server/testprompt/<prompt_id>/executions', methods=['GET'])
@handle_route_exceptions('testprompt:list_executions')
def testprompt_list_executions(prompt_id):
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    executions = list_prompt_executions(prompt_id, team_id)
    return jsonify({'success': True, 'executions': executions})


@server_testprompt_bp.route('/server/testprompt/execution/<execution_id>/feedback', methods=['POST'])
@handle_route_exceptions('testprompt:feedback')
def testprompt_feedback(execution_id):
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    data = request.get_json()
    feedback = data.get('feedback', '') if data else ''

    success = add_human_feedback(execution_id, team_id, feedback)
    return jsonify({'success': success})
