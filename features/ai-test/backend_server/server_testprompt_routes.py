"""
Server Test Prompt Routes — CRUD, execution, versioning, feedback loop

Test prompts are AI-driven tests with a dev → prod lifecycle.
"""

import json
import re
import threading
import time

from flask import Blueprint, current_app, request, jsonify
from backend_server.src.lib.auth_middleware import require_permission
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.lock_utils import get_client_ip, get_device_lock_info
from backend_server.src.lib.utils.server_utils import get_host_manager
from backend_server.src.lib.utils.trigger_utils import resolve_caller_user
from backend_server.src.routes.server_testcase_routes import (
    acquire_testcase_lock,
    dispatch_testcase_under_lock,
)
from shared.src.lib.utils.build_url_utils import call_host, server_auth_headers
from shared.src.lib.utils.testcase_start import first_block, with_start_node
from ..lib.test_prompts_db import (
    create_test_prompt,
    get_test_prompt,
    list_test_prompts,
    update_test_prompt,
    delete_test_prompt,
    create_new_version,
    get_version_history,
    promote_to_prod,
    link_testcase,
    record_prompt_execution,
    update_prompt_execution,
    add_human_feedback,
    list_prompt_executions,
    get_prompt_execution,
    merge_run_details,
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


def _host_info(host_name):
    """The host's registry entry (in process — no HTTP round trip to ourselves)."""
    return get_host_manager().get_host(host_name)


def _device_model(host_name, device_id):
    host = _host_info(host_name) or {}
    device = next((d for d in host.get('devices', []) if d.get('device_id') == device_id), None)
    return (device or {}).get('device_model') or None


def _take_control_refusal(host_name, device_id, data):
    """A test prompt runs under the caller's Take Control (manual_control by the same user or
    session). Both engines rely on it: the explore agent's MCP tools piggyback on that lock,
    and a graph run goes subordinate under it. Returns a 409 response, or None."""
    lock = get_device_lock_info(host_name, device_id) or {}
    user_id = data.get('user_id') or request.headers.get('X-User-ID') or getattr(request, 'user_id', None)
    session_id = data.get('session_id')
    if lock.get('owner_type') == 'manual_control' and (
        (user_id and lock.get('owner_user_id') == user_id)
        or (session_id and lock.get('owner_session_id') == session_id)
    ):
        return None
    return jsonify({
        'success': False,
        'errorType': 'take_control_required',
        'message': f'Take control of {host_name}:{device_id} before running a test prompt',
        'lock_info': lock or None,
    }), 409


EXPLORE_MAX_SECONDS = 300  # when the skill gives no timeout_seconds
HOME_NODE_LABEL = 'home'  # every user interface has one: its go-home path wakes the device, launches the app


def _deterministic_prenav(execution_id, host_name, device_id, ui_name,
                          target_node_id, target_screen_label, team_id):
    """Go home, then to the starting screen, before the AI runs (TASK-36: every prompt starts
    at home). Home is the gate: if it is not reached (device off, app not launched,
    screensaver), the prompt does not start. Returns (success, start_screen_label, error)."""
    ok, _, err = _prenav_leg(execution_id, host_name, device_id, ui_name, None, HOME_NODE_LABEL, team_id)
    if not ok:
        return False, HOME_NODE_LABEL, (f"Could not reach '{HOME_NODE_LABEL}' ({err}). The prompt did not start: "
                                        "is the device on and the app running?")
    target = (target_screen_label or '').strip()
    if not target or target == HOME_NODE_LABEL:
        return True, HOME_NODE_LABEL, None
    return _prenav_leg(execution_id, host_name, device_id, ui_name, target_node_id, target, team_id)


def _prenav_leg(execution_id, host_name, device_id, ui_name,
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
            headers=server_auth_headers(),
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
                    pr = requests.get(poll_url, params=poll_params,
                                      headers=server_auth_headers(), timeout=10)
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


def _resolve_test_prompt_skill(host_name, device_id):
    """Look up the device_model and return the matching test-prompt skill name.

    Falls back to test-prompt-web for unknown models with a loud warning so
    the next time we see a new device type we know to add a skill for it.
    Returns (skill_name, device_model_or_none).
    """
    model = _device_model(host_name, device_id) or ''
    skill = TEST_PROMPT_SKILL_BY_MODEL.get(model)
    if skill is None:
        print(f"[@testprompt:resolve] WARN: unknown device_model '{model}' for {host_name}/{device_id} — falling back to test-prompt-web. Add it to TEST_PROMPT_SKILL_BY_MODEL.", flush=True)
        return 'test-prompt-web', model or None
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
@require_permission('execution.run:run_test')
@handle_route_exceptions('testprompt:execute')
def testprompt_execute():
    """Run a test prompt. mode=explore (default): the Atlas agent drives the device step by
    step and judges the acceptance criteria. mode=graph: the prompt's linked testcase runs on
    the testcase executor, or, when none is linked (or regenerate=true), a graph is generated
    from the prompt (text.plan) and run. Both require the caller's Take Control."""
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

    mode = data.get('mode') or 'explore'
    if mode not in ('explore', 'graph', 'auto'):
        return jsonify({'success': False, 'message': "mode must be 'explore', 'graph' or 'auto'"}), 400
    refusal = _take_control_refusal(host_name, device_id, data)
    if refusal:
        return refusal

    # Load prompt from DB
    prompt = get_test_prompt(test_prompt_id, team_id)
    if not prompt:
        return jsonify({'success': False, 'message': 'Test prompt not found'}), 404
    saved_prompt = dict(prompt)

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

    # Auto: replay the linked testcase and decide what to do if it fails (_auto_follow_up);
    # with no linked testcase there is nothing to replay, so it explores.
    auto = mode == 'auto'
    if auto:
        mode = 'graph' if prompt.get('testcase_id') else 'explore'

    # Record execution
    execution_id = record_prompt_execution(
        test_prompt_id=test_prompt_id,
        team_id=team_id,
        host_name=host_name,
        device_id=device_id,
        executed_by=data.get('executed_by'),
        run_mode=mode,
        # What actually ran: the page sends the form's values, which may differ from the saved version.
        run_details={
            'prompt': prompt.get('prompt'),
            'acceptance_criteria': prompt.get('acceptance_criteria'),
            'target_screen_label': prompt.get('target_screen_label') or None,
            'userinterface_name': prompt.get('userinterface_name') or None,
            'version': saved_prompt.get('version'),
            'edited': any((prompt.get(k) or '') != (saved_prompt.get(k) or '')
                          for k in ('prompt', 'acceptance_criteria', 'target_screen_label')),
            'auto': auto or None,
        },
    )

    if not execution_id:
        return jsonify({'success': False, 'message': 'Failed to record execution'}), 500

    if mode == 'graph':
        user_id = data.get('user_id') or request.headers.get('X-User-ID')
        auto_ctx = {
            'app': current_app._get_current_object(),
            'prompt': prompt,
            'test_prompt_id': test_prompt_id,
            'host_name': host_name,
            'device_id': device_id,
            'data': data,
            'user_id': user_id,
            'client_ip': get_client_ip(),
            'retried': False,
        } if auto else None
        return _start_graph_run(prompt, execution_id, test_prompt_id, team_id, host_name, device_id, data,
                                auto=auto_ctx)

    return jsonify(_start_exploration(prompt, execution_id, test_prompt_id, team_id, host_name, device_id))


def _start_exploration(prompt, execution_id, test_prompt_id, team_id, host_name, device_id, auto_from=None,
                       auto_decision=None):
    """Run the prompt with the Atlas agent in a background thread (explore mode). Returns the
    response body. auto_from: the auto-mode graph run this exploration follows up; its
    decision gets this run's outcome."""
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
                tree_data = _full_tree(root_tree['id'], team_id)  # subtrees included (live_chup…)
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

                    notes = _interface_notes(ui_name, team_id)
                    nav_tree_text = (
                        "\n\n**Pre-loaded Navigation Tree** (do NOT call get_userinterface_complete — it is not available; use these labels EXACTLY as written when calling navigate_to_node, do not guess or invent labels):\n\n"
                        f"Nodes ({len(nodes)} total):\n" + "\n".join(node_lines) +
                        f"\n\nEdges ({len(edges)} total, format `from -> to [first_action]`):\n" + "\n".join(edge_lines)
                        + ("\n\n**Actions and screen notes** (action nodes are repeatable: navigate_to_node to one performs it once):\n" + notes if notes else '')
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
        try:
            _run_agent_body()
        finally:
            host_info = _host_info(host_name)
            if host_info:
                try:
                    call_host(host_info, '/host/testprompt/runningLog', method='POST',
                              data={'device_id': device_id, 'log': None},
                              query_params={'team_id': team_id}, timeout=5)
                except Exception as log_err:
                    print(f"[@testprompt:agent] running.log clear failed: {log_err}", flush=True)

    def _run_agent_body():
        import asyncio
        import time as _time

        start_time = _time.time()
        from datetime import datetime as _dt0, timezone as _tz0
        run_start_iso = _dt0.fromtimestamp(start_time, tz=_tz0.utc).isoformat()
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
        # The successful device steps, kept so a passing run can be saved as a testcase.
        tool_trace = []
        pending_trace = None

        def _resolve_host_info():
            return _host_info(host_name)

        def _push_running_log(current_msg=None):
            """Mirror the agent's progress into the device's running.log, in the shape the
            testcase executor writes, so the step overlay that polls it shows this run.
            ``current_msg`` is the step in progress (None between steps)."""
            host_info = _resolve_host_info()
            if not host_info:
                return
            completed = [
                {'step_number': i + 1, 'command': st.get('message') or 'step',
                 'description': st.get('message') or '',
                 'status': 'completed' if st.get('success') else 'failed'}
                for i, st in enumerate(step_results)
            ]
            total = len(completed) + (1 if current_msg else 0)
            log = {
                'script_name': f"prompt_{prompt_name}",
                'total_steps': total,
                'current_step_number': total,
                'start_time': run_start_iso,
                'completed_steps': completed[-20:],
            }
            if completed:
                log['previous_step'] = completed[-1]
            if current_msg:
                log['current_step'] = {'step_number': total, 'command': current_msg,
                                       'description': current_msg, 'status': 'current'}
            try:
                call_host(host_info, '/host/testprompt/runningLog', method='POST',
                          data={'device_id': device_id, 'log': log},
                          query_params={'team_id': team_id}, timeout=5)
            except Exception as log_err:
                print(f"[@testprompt:agent] running.log update failed: {log_err}", flush=True)

        def _publish_report(current_status, error_text=None):
            """Generate + upload a script report. Returns (report_url, logs_url, execution_time_ms).

            Called from the happy path AND every error path so error runs still
            get a Report/Logs link in the UI instead of blank cells.
            """
            try:
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
            device_model_for_report = _device_model(host_name, device_id) or 'unknown'
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
        _push_running_log(f"Go to {target_screen or 'home'}")
        prenav_ok, start_screen, prenav_err = _deterministic_prenav(
            execution_id, host_name, device_id, ui_name,
            target_node_id_val, target_screen, team_id,
        )
        if not prenav_ok:
            _emit_testprompt_event(execution_id, 'error',
                                   f"Pre-navigation failed: {prenav_err}")
            log_lines.append(f"[ERROR] Pre-navigation failed: {prenav_err}")
            merge_run_details(execution_id, team_id, error=f"Pre-navigation failed: {prenav_err}")
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
        tool_trace.append({'tool': 'navigate_to_node', 'params': {'target_node_label': HOME_NODE_LABEL}})
        if start_screen != HOME_NODE_LABEL:
            tool_trace.append({'tool': 'navigate_to_node', 'params': {'target_node_label': start_screen}})

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
            skill_name, device_model = _resolve_test_prompt_skill(host_name, device_id)
            print(f"[@testprompt:agent] Resolving skill for device_model='{device_model}' -> {skill_name}", flush=True)
            if not manager.load_skill(skill_name):
                # Hard-fail loud — silently falling back to router mode is the
                # exact bug that ate hours of debugging earlier today.
                raise RuntimeError(
                    f"Failed to load skill '{skill_name}' for device_model='{device_model}'. "
                    f"Check that '{skill_name}' is in assistant.yaml available_skills."
                )
            print(f"[@testprompt:agent] Pre-loaded skill: {skill_name}", flush=True)
            # The skill's timeout_seconds bounds the whole exploration; without it an agent that
            # keeps trying ran for 15+ min and overlapped the next run on the device.
            try:
                from agent.skills.skill_loader import SkillLoader
                explore_limit = int(getattr(SkillLoader.get_all_skills().get(skill_name), 'timeout_seconds', 0) or 0)
            except Exception:
                explore_limit = 0
            explore_limit = explore_limit or EXPLORE_MAX_SECONDS

            # Auto-screenshot helper — calls the AV takeScreenshot API directly
            def _auto_screenshot():
                try:
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
                nonlocal final_message, step_num, prev_tool_name, prev_tool_params, pending_trace, timed_out, agent_error, explore_deadline
                # The limit starts when the run gets the worker's event loop, not while it
                # waits behind an Atlas chat (agent/async_utils.run_in_worker_loop).
                explore_deadline = _time.time() + explore_limit
                async for event in manager.process_message(agent_message, session):
                    # The agent calls the LLM and its tools synchronously, so the event loop never
                    # gets control and asyncio.wait_for cannot fire (BUG-0233: 948 s on a 300 s
                    # limit). Check the deadline on every event instead; the overshoot is one turn.
                    if _time.time() > explore_deadline:
                        timed_out = True
                        break
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
                        pending_trace = ({'tool': tool_name, 'params': prev_tool_params}
                                         if tool_name in _TRACE_TOOLS else None)

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
                        _push_running_log(msg)

                        try:
                            params_repr = json.dumps(tool_params, default=str, ensure_ascii=False)
                        except Exception:
                            params_repr = str(tool_params)
                        log_lines.append(f"[TOOL_CALL] {tool_name}: {params_repr[:4000]}")

                    elif event_type == 'tool_result':
                        # The agent reports every tool call that returned as success: a tool's own
                        # failure (verify_node "❌ Node verification failed") is its isError flag.
                        result_payload = event_dict.get('tool_result')
                        is_error = (event_dict.get('success') == False or 'error' in content_short.lower()
                                    or (isinstance(result_payload, dict) and bool(result_payload.get('isError'))))
                        if pending_trace and not is_error:
                            tool_trace.append(pending_trace)
                        pending_trace = None

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
                        _push_running_log()

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
                        agent_error = content_short

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

            timed_out = False
            agent_error = None  # the agent's last error event (e.g. its AI provider's rate limit)
            explore_deadline = _time.time() + explore_limit
            # Shares the worker's single event loop with Atlas chats (agent/async_utils).
            from agent.async_utils import run_in_worker_loop
            run_in_worker_loop(run())
            if timed_out:
                log_lines.append(f"[ERROR] Exploration stopped after {explore_limit}s (time limit)")
                _emit_testprompt_event(execution_id, 'error',
                                       f"Exploration stopped after {explore_limit}s (time limit)")

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
            # The verdict line is "Overall: PASS" or "Overall: FAIL"; any other overall verdict
            # ("PARTIAL PASS", "UNABLE TO VERIFY") is not a pass, so it is a FAIL, not an error.
            overall = re.search(r'overall:\s*\**\s*([a-z ]+)', msg_lower)
            overall_word = overall.group(1).strip() if overall else ''
            has_pass = overall_word == 'pass'
            has_fail = '[fail]' in msg_lower or bool(overall_word and overall_word != 'pass')
            if timed_out:
                status = 'error'
                merge_run_details(execution_id, team_id,
                                  error=f"Exploration stopped after {explore_limit}s (the skill's time limit)")
            elif has_pass and not has_fail:
                status = 'passed'
            elif has_fail:
                status = 'failed'
            else:
                status = 'error'
                merge_run_details(execution_id, team_id, error=(
                    f"The agent stopped without a verdict: {agent_error}" if agent_error
                    else "The agent stopped without a verdict (no 'Overall: PASS/FAIL' in its report)"))

            report_url, logs_url, execution_time_ms = _publish_report(status)

            update_prompt_execution(
                execution_id=execution_id,
                team_id=team_id,
                status=status,
                report_url=report_url,
                logs_url=logs_url,
                execution_time_ms=execution_time_ms,
                tool_trace=tool_trace,
            )
            merge_run_details(execution_id, team_id, verdict=(final_message or '')[:6000] or None)
            if auto_from:
                merge_run_details(auto_from, team_id, outcome=_auto_set_outcome(
                    auto_decision, team_id, execution_id, 'explore', status))

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
            merge_run_details(execution_id, team_id, error=str(e)[:2000])
            if auto_from:
                merge_run_details(auto_from, team_id, outcome=_auto_set_outcome(
                    auto_decision, team_id, execution_id, 'explore', 'error'))
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

    return {
        'success': True,
        'execution_id': execution_id,
        'test_prompt_id': test_prompt_id,
        'message': 'Execution started via AI agent',
    }


# ============================================================================
# EXPLORE → TESTCASE — a passing exploration's steps as a graph (TASK-36 §3)
# ============================================================================

# Tools whose successful calls are device steps; everything else the agent calls is not kept.
_TRACE_TOOLS = ('navigate_to_node', 'execute_device_action', 'verify_node')
# execute_device_action commands that only read the screen: they are how the agent looked,
# not something the test has to do again.
_READ_ONLY_COMMANDS = {
    'dump_elements', 'dump_ui_elements', 'get_page_info', 'find_element',
    'get_installed_apps', 'take_screenshot',
}


def _node_checks(ui_name, team_id):
    """{node label or id: (verifications, pass_condition)} for every node of the interface
    (subtrees included) that has saved checks: what verify_node ran during the exploration."""
    try:
        from shared.src.lib.database.userinterface_db import get_userinterface_by_name
        from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface
        ui_row = get_userinterface_by_name(ui_name, team_id) if ui_name else None
        root = get_root_tree_for_interface(ui_row['id'], team_id) if ui_row else None
        tree = _full_tree(root['id'], team_id) if root else {}
    except Exception as e:
        print(f"[@testprompt] node checks unavailable for {ui_name}: {e}", flush=True)
        return {}
    checks = {}
    for n in (tree or {}).get('nodes') or []:
        data = n.get('data') or {}
        verifications = n.get('verifications') or data.get('verifications') or []
        if isinstance(verifications, str):
            try:
                verifications = json.loads(verifications)
            except ValueError:
                verifications = []
        items = [{'command': v.get('command'), 'params': v.get('params') or {},
                  'verification_type': v.get('verification_type')}
                 for v in verifications if isinstance(v, dict) and v.get('command')]
        label = n.get('label') or data.get('label')
        if label and items:
            entry = (items, n.get('verification_pass_condition')
                     or data.get('verification_pass_condition') or 'all')
            # verify_node takes a node_label, or a node_id
            for key in (label, n.get('node_id'), n.get('id')):
                if key:
                    checks[key] = entry
    return checks


def _trace_to_graph(trace, node_checks=None):
    """Linear graph of a tool trace: navigate_to_node -> navigation block, execute_device_action
    -> one action block (read-only commands dropped), verify_node -> a verification block with
    that screen's saved checks (node_checks, from _node_checks). Every step is kept, repeats
    included: navigating to an action node (live_chup) three times zaps three times."""
    nodes = [{'id': 'start', 'type': 'start', 'position': {'x': 250, 'y': 100}, 'data': {'label': 'START'}}]
    chain = ['start']
    for entry in trace or []:
        params = entry.get('params') or {}
        if entry.get('tool') == 'navigate_to_node':
            label = params.get('target_node_label') or params.get('node_label')
            if not label:
                continue
            node = {'type': 'navigation', 'data': {'target_node_label': label, 'target_node_id': label}}
        elif entry.get('tool') == 'verify_node':
            label = params.get('node_label') or params.get('node_id')
            checks = (node_checks or {}).get(label)
            if not checks:
                continue
            node = {'type': 'verification', 'data': {'label': f'verify {label}', 'verifications': checks[0],
                                                     'verification_pass_condition': checks[1]}}
        else:
            action_type = params.get('action_type')
            items = [{'command': a.get('command'), 'params': a.get('params') or {},
                      'action_type': a.get('action_type') or action_type}
                     for a in (params.get('actions') or [])
                     if isinstance(a, dict) and a.get('command') and a.get('command') not in _READ_ONLY_COMMANDS]
            if not items:
                continue
            node = {'type': 'action', 'data': {'actions': items}}
        node['id'] = f"trace{len(chain)}"
        node['position'] = {'x': 250, 'y': 100 + 100 * len(chain)}
        nodes.append(node)
        chain.append(node['id'])
    nodes.append({'id': 'success', 'type': 'success', 'position': {'x': 250, 'y': 100 + 100 * len(chain)}, 'data': {'label': 'SUCCESS'}})
    nodes.append({'id': 'failure', 'type': 'failure', 'position': {'x': 450, 'y': 100 + 100 * len(chain)}, 'data': {'label': 'FAILURE'}})
    chain.append('success')
    edges = [{'id': f'e_{a}_{b}', 'source': a, 'target': b, 'sourceHandle': 'success', 'type': 'success'}
             for a, b in zip(chain, chain[1:])]
    return {'nodes': nodes, 'edges': edges}


def _graph_step_lines(graph):
    """The step list of a _trace_to_graph graph, as the preview shows it."""
    lines = []
    for n in graph['nodes']:
        data = n.get('data') or {}
        if n['type'] == 'navigation':
            lines.append(f"Navigate to: {data['target_node_label']}")
        elif n['type'] == 'verification':
            lines.append(f"Verify: {data['label'][len('verify '):]} (its saved checks)")
        elif n['type'] == 'action':
            lines.append('Action: ' + ' + '.join(a['command'] for a in data['actions']))
    return lines


@server_testprompt_bp.route('/server/testprompt/execution/<execution_id>/to-graph', methods=['POST'])
@require_permission('execution.run:run_test')
@handle_route_exceptions('testprompt:execution_to_graph')
def testprompt_execution_to_graph(execution_id):
    """Turn a passing exploration into a proposed testcase graph: its device steps (tool_trace),
    plus verification steps the AI builder adds for the acceptance criteria. Returns the host's
    edit result (graph, analysis, steps_before, steps_after) for the page to preview; saving is
    POST /server/testprompt/<id>/save-testcase."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400
    execution = get_prompt_execution(execution_id, team_id)
    if not execution:
        return jsonify({'success': False, 'message': 'Execution not found'}), 404
    if execution.get('run_mode') != 'explore' or execution.get('status') != 'passed':
        return jsonify({'success': False, 'message': 'Only a passing exploration can be saved as a testcase'}), 400
    if not execution.get('tool_trace'):
        return jsonify({'success': False, 'message': 'This exploration has no recorded steps (it ran before steps were kept)'}), 400
    prompt = get_test_prompt(execution['test_prompt_id'], team_id)
    if not prompt:
        return jsonify({'success': False, 'message': 'Test prompt not found'}), 404
    host_info = _host_info(execution['host_name'])
    if not host_info:
        return jsonify({'success': False, 'message': f"Host {execution['host_name']} is not connected"}), 409

    graph = _trace_to_graph(execution['tool_trace'],
                            _node_checks(prompt.get('userinterface_name'), team_id))
    # The agent checked the screens it judged the criteria on: those checks are the test's.
    # The AI builder only adds checks to an exploration that ran none (it invents them —
    # e.g. key presses and DetectZapping without a key timestamp — so not on top of real ones).
    if any(n['type'] == 'verification' for n in graph['nodes']):
        lines = _graph_step_lines(graph)
        return jsonify({'success': True, 'graph': graph, 'steps_before': lines, 'steps_after': lines,
                        'analysis': "The exploration's steps and the screen checks it passed."})

    criteria = (prompt.get('acceptance_criteria') or '').strip()
    request_text = (
        f"Add verification steps at the end that check these acceptance criteria: {criteria} "
        "Keep every existing step exactly as it is."
        if criteria else "Keep every step exactly as it is."
    )
    result, status_code = call_host(
        host_info, '/host/ai/generatePlan', method='POST',
        data={
            'prompt': request_text,
            'userinterface_name': prompt.get('userinterface_name'),
            'device_id': execution['device_id'],
            'current_graph': graph,
        },
        query_params={'team_id': team_id}, timeout=180,
    )
    return jsonify(result), (status_code if isinstance(status_code, int) and status_code >= 400 else 200)


# ============================================================================
# GRAPH MODE — the prompt as a testcase graph, run by the testcase executor
# ============================================================================

def _safe_name(name):
    return (name or 'test_prompt').replace(' ', '_').replace('/', '_')


def _full_tree(root_tree_id, team_id):
    """The interface's whole tree, subtrees included, as {success, nodes, edges}: get_full_tree reads
    the root tree only, and nodes like web_tv's live_chup live in the subtree of 'live'. A
    subtree's root node repeats its parent node (same node_id): kept once."""
    from shared.src.lib.database.navigation_trees_db import get_complete_tree_hierarchy
    hierarchy = get_complete_tree_hierarchy(root_tree_id, team_id)
    if not hierarchy.get('success'):
        return {'success': False}
    nodes, edges, seen = [], [], set()
    for tree in hierarchy.get('all_trees_data') or []:
        for n in tree.get('nodes') or []:
            key = n.get('node_id') or n.get('id')
            if key not in seen:
                seen.add(key)
                nodes.append(n)
        edges.extend(tree.get('edges') or [])
    return {'success': True, 'nodes': nodes, 'edges': edges}


def _interface_notes(ui_name, team_id):
    """What the screens and actions of an interface mean, from its tree, for both engines: each
    action node (e.g. live_chup = zap channel up) with its parent and description, and any other
    node that has a description. Empty when the tree has none."""
    try:
        from shared.src.lib.database.userinterface_db import get_userinterface_by_name
        from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface
        ui_row = get_userinterface_by_name(ui_name, team_id) if ui_name else None
        root = get_root_tree_for_interface(ui_row['id'], team_id) if ui_row else None
        tree = _full_tree(root['id'], team_id) if root else {}
    except Exception as e:
        print(f"[@testprompt] interface notes unavailable for {ui_name}: {e}", flush=True)
        return ''
    if not tree or not tree.get('success'):
        return ''
    nodes = tree.get('nodes') or []
    label_by_id = {(n.get('node_id') or n.get('id')): (n.get('label') or (n.get('data') or {}).get('label')) for n in nodes}
    parents = {}
    for e in tree.get('edges') or []:
        parents.setdefault(e.get('target_node_id'), e.get('source_node_id'))
    lines = []
    for n in nodes:
        label = n.get('label') or (n.get('data') or {}).get('label')
        desc = ((n.get('data') or {}).get('description') or '').strip()
        if (n.get('node_type') or (n.get('data') or {}).get('node_type')) == 'action':
            parent = label_by_id.get(parents.get(n.get('node_id') or n.get('id'))) or 'its parent screen'
            lines.append(f"- {label}: an action on '{parent}'" + (f" — {desc}" if desc else '') +
                         f". Navigating to it performs the action once and leaves the device on '{parent}';"
                         f" navigate to it N times to do it N times.")
        elif desc:
            lines.append(f"- {label}: {desc}")
    return '\n'.join(lines)


def _graph_prompt_text(prompt):
    """Generation prompt for ai_builder: start screen, the prompt, then the acceptance
    criteria as things to verify, so the graph gets verification blocks for them."""
    parts = []
    target = (prompt.get('target_screen_label') or '').strip()
    if target:
        parts.append(f"Go to {target}.")
    parts.append((prompt.get('prompt') or '').strip())
    criteria = (prompt.get('acceptance_criteria') or '').strip()
    if criteria:
        parts.append(f"Then verify: {criteria}")
    return ' '.join(p for p in parts if p)


def _finish_execution(execution_id, team_id, status, *, message=None, error=None, follow_up=None, **result):
    # An error's message, or a failed run's reason, is kept for the results history.
    reason = error or (message if status == 'error' else None)
    if reason:
        merge_run_details(execution_id, team_id, error=str(reason)[:2000])
    update_prompt_execution(execution_id=execution_id, team_id=team_id, status=status,
                            script_result_id=result.get('script_result_id'),
                            report_url=result.get('report_url'), logs_url=result.get('logs_url'),
                            execution_time_ms=result.get('execution_time_ms'))
    _emit_testprompt_event(execution_id, 'testprompt_completed', message or f"Completed: {status}",
                           status=status, report_url=result.get('report_url'),
                           logs_url=result.get('logs_url'),
                           execution_time_ms=result.get('execution_time_ms'),
                           **(follow_up or {}))


def _start_graph_run(prompt, execution_id, test_prompt_id, team_id, host_name, device_id, data, auto=None):
    """Start a graph run (linked testcase, or generated). auto: the auto-mode context; then the
    caller may be a background thread (a retry), so the user and client IP come from it, and the
    watcher decides what follows a failure."""
    from shared.src.lib.database.testcase_db import get_testcase

    if auto:
        user_id, client_ip = auto['user_id'], auto['client_ip']
    else:
        user_id = data.get('user_id') or request.headers.get('X-User-ID')
        client_ip = get_client_ip()
    payload = {
        'host_name': host_name,
        'device_id': device_id,
        'userinterface_name': prompt.get('userinterface_name', ''),
        'async_execution': True,
        'user_id': user_id,
        'user_name': data.get('user_name'),
        'session_id': data.get('session_id'),
        'execution_metadata': {
            'trigger': {
                'type': 'test_prompt',
                'caller_ip': client_ip,
                'caller_user': resolve_caller_user(user_id, data.get('user_name')),
            },
        },
    }

    testcase = None
    if prompt.get('testcase_id') and not data.get('regenerate'):
        testcase = get_testcase(prompt['testcase_id'], team_id)
        if not testcase:
            _finish_execution(execution_id, team_id, 'error', message='Linked testcase not found')
            return jsonify({'success': False, 'execution_id': execution_id,
                            'message': 'The linked testcase no longer exists — Regenerate or unlink it'}), 404
        endpoint = '/host/testcase/execute'
        payload.update(graph_json=with_start_node(testcase['graph_json'], HOME_NODE_LABEL),
                       testcase_name=testcase['testcase_name'])
        merge_run_details(execution_id, team_id, testcase_id=testcase['testcase_id'],
                          testcase_name=testcase['testcase_name'])
    else:
        merge_run_details(execution_id, team_id, generated=True)
        endpoint = '/host/testcase/execute-from-prompt'
        payload.update(prompt=_graph_prompt_text(prompt),
                       # Context for the AI, apart from the prompt the builder preprocesses (the
                       # notes' words in the prompt were taken for screen names: "times", "verify").
                       notes=_interface_notes(prompt.get('userinterface_name'), team_id),
                       testcase_name=f"prompt_{_safe_name(prompt.get('name'))}",
                       start_node_label=HOME_NODE_LABEL)

    lock, refusal = acquire_testcase_lock(payload, user_id, client_ip, payload['testcase_name'])
    if refusal:
        _finish_execution(execution_id, team_id, 'error', message='Device locked')
        return refusal
    _emit_testprompt_event(execution_id, 'status',
                           'Running the linked testcase' if testcase else 'Generating the graph from the prompt…')
    response, status_code = dispatch_testcase_under_lock(
        lock, endpoint, payload, {'team_id': team_id}, track_async=True, timeout=180)
    response = response if isinstance(response, dict) else {}

    if response.get('needs_disambiguation'):
        analysis = response.get('analysis') or {}
        phrases = [a.get('phrase') for a in analysis.get('ambiguities', []) if a.get('phrase')]
        message = ('The prompt is ambiguous' + (f": {', '.join(phrases)}" if phrases else '')
                   + ' — reword it, or use Explore')
        _finish_execution(execution_id, team_id, 'error', message=message)
        return jsonify({'success': False, 'execution_id': execution_id, 'needs_disambiguation': True,
                        'analysis': analysis, 'message': message})

    host_execution_id = response.get('execution_id')
    if status_code >= 400 or not response.get('success') or not host_execution_id:
        message = response.get('error') or response.get('message') or 'Graph run failed to start'
        _finish_execution(execution_id, team_id, 'error', message=message)
        return jsonify({'success': False, 'execution_id': execution_id, 'message': message}), \
            (status_code if status_code >= 400 else 500)

    graph = payload['graph_json'] if testcase else response.get('graph')
    threading.Thread(
        target=_watch_graph_run,
        args=(execution_id, host_execution_id, host_name, team_id, graph),
        kwargs={'auto': auto},
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'execution_id': execution_id,
        'test_prompt_id': test_prompt_id,
        'mode': 'graph',
        'host_execution_id': host_execution_id,
        'linked_testcase_id': testcase['testcase_id'] if testcase else None,
        'generated_graph': None if testcase else graph,
        'analysis': None if testcase else response.get('analysis'),
        'message': 'Running the linked testcase' if testcase else 'Graph generated and running',
    })


_GRAPH_RUN_MAX_SECONDS = 7200
_REPORT_WAIT_SECONDS = 120


def _watch_graph_run(execution_id, host_execution_id, host_name, team_id, graph, auto=None):
    """Follow a graph run on the host: each block as a live step event, then the verdict,
    report and logs on the execution row. A passing run reports 'completed' before its
    report tail has run (VPT_TESTCASE_BACKGROUND_REPORT), so wait for the report URL."""
    nodes = (graph or {}).get('nodes', []) if isinstance(graph, dict) else []
    labels = {n.get('id'): ((n.get('data') or {}).get('label') or n.get('type') or n.get('id')) for n in nodes}
    kinds = {n.get('id'): n.get('type') for n in nodes}
    started = time.time()
    current_block = None
    reported_blocks = set()
    finished_at = None
    failures = 0
    status = {}
    while time.time() - started < _GRAPH_RUN_MAX_SECONDS:
        time.sleep(2)
        host_info = _host_info(host_name)
        resp, code = call_host(host_info, f'/host/testcase/execution/{host_execution_id}/status',
                               method='GET', query_params={'team_id': team_id}, timeout=10) \
            if host_info else ({}, 0)
        if code != 200 or not isinstance(resp, dict) or not isinstance(resp.get('status'), dict):
            failures += 1
            if failures >= 30:
                _finish_execution(execution_id, team_id, 'error',
                                  message=f'Lost the run on {host_name} (status unavailable)')
                return
            continue
        failures = 0
        status = resp['status']

        for block_id, state in (status.get('block_states') or {}).items():
            if block_id in reported_blocks:
                continue
            reported_blocks.add(block_id)
            outcome = 'passed' if state.get('status') == 'success' else 'failed'
            detail = state.get('error') or state.get('message') or ''
            _emit_testprompt_event(execution_id, 'step' if outcome == 'passed' else 'error',
                                   f"{labels.get(block_id, block_id)} — {outcome}" + (f": {detail}" if detail else ''),
                                   tool_name=kinds.get(block_id))

        block = status.get('current_block_id')
        if block and block != current_block and block not in reported_blocks:
            current_block = block
            _emit_testprompt_event(execution_id, 'step', f"{labels.get(block, block)} — running",
                                   tool_name=kinds.get(block))
        run_state = status.get('status')
        if run_state == 'running':
            continue
        result = status.get('result') or {}
        if run_state == 'completed' and not result.get('report_url'):
            finished_at = finished_at or time.time()
            if time.time() - finished_at < _REPORT_WAIT_SECONDS:
                continue
        break
    else:
        _finish_execution(execution_id, team_id, 'error', message='Graph run timed out')
        return

    result = status.get('result') or {}
    run_state = status.get('status')
    if run_state == 'aborted':
        verdict = 'error'
    elif result.get('success'):
        verdict = 'passed'
    elif run_state in ('completed', 'failed') and result.get('result_type') == 'failure':
        verdict = 'failed'
    else:
        verdict = 'error'
    # Home is the gate (every run starts there): if the first block did not reach it, the test
    # itself never ran — an error, and Auto does not follow it up.
    home_block = first_block(graph)
    home_state = ((status.get('block_states') or {}).get(home_block['id']) or {}) if home_block else {}
    home_failed = verdict != 'passed' and home_state and home_state.get('status') != 'success'
    if home_failed:
        verdict = 'error'
        result = {**result, 'error': f"Could not reach '{HOME_NODE_LABEL}' "
                                     f"({home_state.get('error') or home_state.get('message') or 'navigation failed'}). "
                                     "The prompt did not start: is the device on and the app running?"}
    # Auto mode: decide what follows a failure before reporting it, so the completion event
    # can name the follow-up run.
    follow_up = None
    if auto and verdict != 'passed' and not home_failed:
        follow_up = _auto_follow_up(auto, execution_id, team_id, status, labels, verdict)
    if auto and auto.get('retry_of'):
        merge_run_details(auto['retry_of'], team_id, outcome=_auto_set_outcome(
            auto.get('retry_decision'), team_id, execution_id, 'graph', verdict))
    _finish_execution(
        execution_id, team_id, verdict, follow_up=follow_up,
        message=f"Completed: {verdict}" + (f" — {result.get('error') or status.get('error')}"
                                         if verdict == 'error' and (result.get('error') or status.get('error')) else ''),
        error=(result.get('error') or status.get('error')) if verdict != 'passed' else None,
        script_result_id=result.get('script_result_id'),
        report_url=result.get('report_url'),
        logs_url=result.get('logs_url'),
        execution_time_ms=result.get('execution_time_ms') or status.get('elapsed_time_ms'),
    )



# ============================================================================
# AUTO MODE — a failed graph run, then what? (TASK-36 §3; decision by Jev, TASK-38)
# ============================================================================

AUTO_DECISION_USAGE = 'text.decision.testprompt_on_failure'
AUTO_MIN_CONFIDENCE = 0.6
# Shadow (docs/agent/ai/JEV.md "Rollout"): Jev's pick is logged to ai_decisions and shown, but a
# failure is always explored. The exploration's result is the decision's outcome; once
# scripts/jev_agreement.py --usage text.decision.testprompt_on_failure shows a confidence above
# which Jev is right, set this to True: Jev then reports, retries or explores (unsure → explore).
AUTO_DECISION_GATED = False
AUTO_OPTIONS = [
    {'id': 'app_failure',
     'facts': 'The device reached the expected screens, but what the test checks is not there or not right: '
              'the app really fails the test. Report it as FAILED.'},
    {'id': 'stale_test',
     'facts': 'The saved steps no longer fit the app: a navigation failed, an element moved or was renamed, '
              'a screen changed. Explore with the AI agent instead.'},
    {'id': 'infra_retry',
     'facts': 'The device, stream, host or network misbehaved: timeouts, lost status, no screenshot, host '
              'unreachable. Retry the same test once.'},
]


def _auto_failure_state(auto, status, labels, verdict):
    """The failing run's evidence as text facts: each block's result and error, in run order."""
    steps = []
    for block_id, state in (status.get('block_states') or {}).items():
        steps.append({
            'block': labels.get(block_id, block_id),
            'result': 'passed' if state.get('status') == 'success' else (state.get('status') or 'failed'),
            'detail': (state.get('error') or state.get('message') or '')[:500] or None,
        })
    result = status.get('result') or {}
    return {
        'test_prompt': auto['prompt'].get('prompt'),
        'acceptance_criteria': auto['prompt'].get('acceptance_criteria'),
        'run_verdict': verdict,
        'run_error': (result.get('error') or status.get('error') or '')[:800] or None,
        'steps': steps,
        'device': f"{auto['host_name']} / {auto['device_id']}",
    }


def _auto_decide(team_id, state, refs):
    """Ask the decision model (routed: text.decision.testprompt_on_failure → text.decision → jev).
    choose() logs the call to ai_decisions with refs. Never raises; returns the summary kept on
    the run (the full state is in ai_decisions)."""
    try:
        from shared.src.lib.ai import router
        from shared.src.lib.ai.decisions import choose
        out = choose(router.resolve(AUTO_DECISION_USAGE, team_id),
                     state=state, options=AUTO_OPTIONS, refs=refs,
                     instructions='A saved device test failed. Which explanation fits the evidence, '
                                  'and so what should happen next?')
        return {'decision_id': out.get('decision_id'), 'choice': out.get('choice'),
                'confidence': out.get('confidence'), 'probabilities': out.get('probabilities'),
                'model': out.get('model'), 'ms': out.get('ms'), 'cost': out.get('cost'),
                'error': out.get('error') or None, 'success': bool(out.get('success'))}
    except Exception as e:
        return {'success': False, 'error': str(e)[:300]}


def _auto_set_outcome(decision, team_id, follow_up_execution_id, follow_up_mode, status):
    """The follow-up's result, on the run's decision and on its ai_decisions row."""
    outcome = {'follow_up_execution_id': follow_up_execution_id, 'follow_up_mode': follow_up_mode,
               'follow_up_status': status}
    if (decision or {}).get('decision_id'):
        try:
            from shared.src.lib.ai.decisions import set_outcome
            set_outcome(decision['decision_id'], team_id, outcome)
        except Exception as e:
            print(f"[@testprompt:auto] set_outcome failed: {e}", flush=True)
    return outcome


def _auto_follow_up(auto, execution_id, team_id, status, labels, verdict):
    """After a failed auto-mode graph run: decide, then report it, retry once, or explore.
    Returns the extra fields for the completion event ({follow_up_execution_id, ...}) or None."""
    decision = _auto_decide(team_id, _auto_failure_state(auto, status, labels, verdict),
                            refs={'test_prompt_execution_id': execution_id,
                                  'test_prompt_id': auto['test_prompt_id'],
                                  'rule_action': 'explore', 'gated': AUTO_DECISION_GATED})
    confident = decision.get('success') and (decision.get('confidence') or 0) >= AUTO_MIN_CONFIDENCE
    choice = decision.get('choice') if (confident and AUTO_DECISION_GATED) else None
    if choice == 'app_failure':
        action = 'report_failure'
    elif choice == 'infra_retry' and not auto.get('retried'):
        action = 'retry'
    else:
        action = 'explore'  # shadow, stale test, unsure, model unavailable, or a second infra failure
    decision.update(action=action, gated=AUTO_DECISION_GATED)
    merge_run_details(execution_id, team_id, decision=decision)
    print(f"[@testprompt:auto] {execution_id}: {decision.get('choice')} "
          f"({decision.get('confidence')}) -> {action}", flush=True)
    if action == 'report_failure':
        return {'auto_action': action, 'auto_choice': decision.get('choice')}

    prompt = auto['prompt']
    details = {
        'prompt': prompt.get('prompt'),
        'acceptance_criteria': prompt.get('acceptance_criteria'),
        'target_screen_label': prompt.get('target_screen_label') or None,
        'version': prompt.get('version'),
        'auto': True,
        ('retry_of' if action == 'retry' else 'auto_from'): execution_id,
    }
    follow_id = record_prompt_execution(
        test_prompt_id=auto['test_prompt_id'], team_id=team_id, host_name=auto['host_name'],
        device_id=auto['device_id'], executed_by=auto['data'].get('executed_by'),
        run_mode='graph' if action == 'retry' else 'explore', run_details=details,
    )
    if not follow_id:
        merge_run_details(execution_id, team_id, outcome={'error': 'Could not record the follow-up run'})
        return {'auto_action': action, 'auto_choice': decision.get('choice')}
    merge_run_details(execution_id, team_id, follow_up_execution_id=follow_id)
    # The follow-up starts from this watcher thread: run it in the app's context (jsonify).
    with auto['app'].app_context():
        if action == 'retry':
            _start_graph_run(prompt, follow_id, auto['test_prompt_id'], team_id, auto['host_name'],
                             auto['device_id'], auto['data'],
                             auto={**auto, 'retried': True, 'retry_of': execution_id, 'retry_decision': decision})
        else:
            _start_exploration(prompt, follow_id, auto['test_prompt_id'], team_id, auto['host_name'],
                               auto['device_id'], auto_from=execution_id, auto_decision=decision)
    return {'auto_action': action, 'auto_choice': decision.get('choice'),
            'follow_up_execution_id': follow_id, 'follow_up_mode': 'graph' if action == 'retry' else 'explore'}


@server_testprompt_bp.route('/server/testprompt/<prompt_id>/save-testcase', methods=['POST'])
@require_permission('execution.run:run_test')
@handle_route_exceptions('testprompt:save_testcase')
def testprompt_save_testcase(prompt_id):
    """Save a graph generated by a graph run as a testcase and link it to the prompt, so
    later graph runs replay it without an LLM call."""
    from shared.src.lib.database.testcase_db import create_testcase

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400
    data = request.get_json() or {}
    graph = data.get('graph')
    if not isinstance(graph, dict) or not graph.get('nodes'):
        return jsonify({'success': False, 'message': 'graph is required'}), 400
    prompt = get_test_prompt(prompt_id, team_id)
    if not prompt:
        return jsonify({'success': False, 'message': 'Test prompt not found'}), 404

    created = create_testcase(
        team_id=team_id,
        testcase_name=(data.get('testcase_name') or '').strip() or f"prompt_{_safe_name(prompt.get('name'))}",
        graph_json=graph,
        description=data.get('analysis') or prompt.get('acceptance_criteria'),
        userinterface_name=prompt.get('userinterface_name'),
        created_by=data.get('created_by'),
        creation_method='ai',
        ai_prompt=_graph_prompt_text(prompt),
        ai_analysis=data.get('analysis'),
    )
    # A new row comes back as {testcase_id, testcase_name, success} (BUG-0215).
    testcase_id = created.get('testcase_id') if isinstance(created, dict) else created
    if testcase_id == 'VALIDATION_FAILED':
        return jsonify({'success': False, 'message': 'The graph references nodes, edges or actions that no longer exist'}), 400
    if not testcase_id:
        return jsonify({'success': False, 'message': 'Failed to save the testcase'}), 500
    linked = link_testcase(prompt_id, team_id, testcase_id)
    if data.get('execution_id'):
        merge_run_details(data['execution_id'], team_id, saved_testcase_id=testcase_id)
    return jsonify({'success': bool(linked.get('success')), 'testcase_id': testcase_id,
                    'test_prompt': linked.get('test_prompt')})


@server_testprompt_bp.route('/server/testprompt/<prompt_id>/unlink-testcase', methods=['POST'])
@handle_route_exceptions('testprompt:unlink_testcase')
def testprompt_unlink_testcase(prompt_id):
    """Drop the prompt's link to its testcase (the testcase itself is kept)."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400
    return jsonify(link_testcase(prompt_id, team_id, None))


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
