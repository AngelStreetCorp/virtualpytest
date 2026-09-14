"""
MCP Proxy Routes - Execute prompts via OpenRouter Function Calling

Uses Qwen/Phi-3 models with function calling to decide which MCP tools to execute.
This bridges natural language prompts to MCP tool execution.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
import requests
import json
import os
import sys
from pathlib import Path

# Add backend_server/src to path for MCP server import
current_dir = Path(__file__).parent.parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from mcp.mcp_instance import get_mcp_server

server_mcp_proxy_bp = Blueprint('server_mcp_proxy', __name__, url_prefix='/server/mcp-proxy')

# Get shared MCP server instance (singleton)
mcp_server = get_mcp_server()


@server_mcp_proxy_bp.route('/execute-prompt', methods=['POST'])
@handle_route_exceptions('mcp_proxy:execute_prompt')
def execute_prompt():
    """
    Execute natural language prompt via OpenRouter with function calling (MCP-style)
    
    Simple proxy: expose MCP tools to AI, let AI decide what to call.
    No system prompt engineering, no multi-turn complexity.
    
    Request body:
    {
      "prompt": "Swipe up on the device",
      "device_id": "device1",
      "host_name": "host1", 
      "userinterface_name": "example_mobile",
      "team_id": "team_1",
      "tree_id": "bbf2d95d-72c2-4701-80a7-0b9d131a5c38"
    }
    
    Returns:
    {
      "success": true,
      "result": { ... tool result ... },
      "tool_name": "execute_device_action",
      "tool_arguments": {...}
    }
    """
    data = request.get_json()
    prompt = data.get('prompt')
    device_id = data.get('device_id', 'device1')
    host_name = data.get('host_name', 'host1')
    userinterface_name = data.get('userinterface_name')
    team_id = request.args.get('team_id')
    tree_id = data.get('tree_id')
    device_model = data.get('device_model', 'unknown')  # NEW: device model type
    
    print(f"[@mcp_proxy] Received prompt: {prompt}")
    print(f"[@mcp_proxy] Context - device: {device_id}, host: {host_name}, interface: {userinterface_name}, device_model: {device_model}, team_id: {team_id}")
    
    if not prompt:
        return jsonify({'success': False, 'error': 'Prompt required'}), 400
    
    # Get OpenRouter API key
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured in .env'}), 500
    
    # Get available MCP tools - expose them as-is
    available_tools = mcp_server.get_available_tools()
    
    # Convert MCP tool schemas to OpenRouter tools format
    tools = []
    for tool in available_tools:
        tools.append({
            "type": "function",
            "function": {
                "name": tool['name'],
                "description": tool['description'],  # Use full description - no truncation
                "parameters": tool['inputSchema']
            }
        })
    
    print(f"[@mcp_proxy] Prepared {len(tools)} tools for AI")
    
    # Minimal system message - just provide context, no instructions
    system_message = f'''Device automation context:
- Device: {device_id} on {host_name}
- Device Model: {device_model}
- Interface: {userinterface_name}
- Team: {team_id}
- Tree: {tree_id or 'none'}

Note: Based on device model:
- android_mobile/android_tv: Use ADB/Remote commands (swipe, click_element, etc)
- web/desktop: Use web/desktop automation commands
- For verification: Use commands matching the device model'''

    print(f"[@mcp_proxy] Calling OpenRouter with model: x-ai/grok-3-mini (max 3 iterations)")
    
    # Multi-turn conversation with AI (max 3 iterations)
    messages = [
        {'role': 'system', 'content': system_message},
        {'role': 'user', 'content': prompt}
    ]
    max_iterations = 3
    iteration = 0
    last_tool_result = None
    all_tool_calls = []  # Track all tool calls for frontend display
    ai_reasoning_parts = []  # Collect AI reasoning from each iteration
    
    while iteration < max_iterations:
        iteration += 1
        print(f"[@mcp_proxy] Iteration {iteration}/{max_iterations}")
        
        openrouter_response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://virtualpytest.com',
                'X-Title': 'VirtualPyTest MCP Proxy',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'google/gemini-2.5-pro',
                'messages': messages,
                'tools': tools,
                'tool_choice': 'auto',  # Let AI decide whether to call a tool or ask for clarification
                'max_tokens': 2000,
                'temperature': 0.0
            },
            timeout=60
        )
        
        if not openrouter_response.ok:
            error_text = openrouter_response.text
            print(f"[@mcp_proxy] ❌ OpenRouter error: {openrouter_response.status_code}")
            return jsonify({
                'success': False,
                'error': f'OpenRouter error {openrouter_response.status_code}: {error_text}'
            }), 500
        
        response_data = openrouter_response.json()
        message = response_data['choices'][0]['message']
        
        print(f"[@mcp_proxy] OpenRouter response: {list(message.keys())}")
        
        # Collect AI reasoning (content) if present
        ai_content = message.get('content', '')
        if ai_content:
            ai_reasoning_parts.append(f"[Iteration {iteration}] {ai_content}")
            print(f"[@mcp_proxy] AI reasoning: {ai_content}")
        
        # Check if AI called a tool
        if 'tool_calls' not in message or not message['tool_calls']:
            ai_reasoning_text = message.get('reasoning', 'No reasoning provided')
            print(f"[@mcp_proxy] ⚠️ AI did not call any tool (iteration {iteration})")
            print(f"[@mcp_proxy] AI content: {ai_content}")
            print(f"[@mcp_proxy] AI reasoning: {ai_reasoning_text}")
            
            # Add to reasoning parts
            if ai_reasoning_text:
                ai_reasoning_parts.append(f"[Final reasoning] {ai_reasoning_text}")
            
            # If this is after some tool execution, return the last result
            if last_tool_result:
                print(f"[@mcp_proxy] AI stopped calling tools after iteration {iteration}, returning last result")
                return jsonify({
                    'success': True,
                    'result': last_tool_result,
                    'tool_calls': all_tool_calls,
                    'ai_response': '\n\n'.join(ai_reasoning_parts) if ai_reasoning_parts else ai_content,
                    'iterations': iteration
                })
            
            print(f"[@mcp_proxy] AI did not call any tool and no previous results")
            return jsonify({
                'success': False,
                'error': 'AI did not call any tool',
                'tool_calls': all_tool_calls,
                'ai_response': '\n\n'.join(ai_reasoning_parts) if ai_reasoning_parts else ai_content,
                'ai_reasoning': ai_reasoning_text
            }), 400
        
        # Add assistant message to conversation
        messages.append(message)
        
        # Execute the tool the AI chose
        tool_call = message['tool_calls'][0]
        function_name = tool_call['function']['name']
        function_args_str = tool_call['function']['arguments']
        function_args = json.loads(function_args_str) if isinstance(function_args_str, str) else function_args_str
        
        print(f"[@mcp_proxy] AI chose tool: {function_name}")
        print(f"[@mcp_proxy] Arguments: {json.dumps(function_args, indent=2)}")
        
        # Inject context if missing
        if 'device_id' not in function_args and device_id:
            function_args['device_id'] = device_id
        if 'host_name' not in function_args and host_name:
            function_args['host_name'] = host_name
        if 'team_id' not in function_args and team_id:
            function_args['team_id'] = team_id
        if function_name in ['navigate_to_node', 'verify_device_state']:
            if 'userinterface_name' not in function_args and userinterface_name:
                function_args['userinterface_name'] = userinterface_name
        if function_name == 'navigate_to_node':
            if 'tree_id' not in function_args and tree_id:
                function_args['tree_id'] = tree_id
        
        # Auto-wrap flat params into arrays for execute_device_action
        if function_name == 'execute_device_action' and 'actions' not in function_args:
            action_obj = {'command': function_args.pop('command', ''), 'params': {}}
            standard_keys = {'device_id', 'host_name', 'team_id', 'userinterface_name'}
            for key in list(function_args.keys()):
                if key not in standard_keys:
                    action_obj['params'][key] = function_args.pop(key)
            function_args['actions'] = [action_obj]
        
        # Auto-wrap flat params into arrays for verify_device_state  
        if function_name == 'verify_device_state' and 'verifications' not in function_args:
            verification_obj = {
                'command': function_args.pop('element_id', '') or function_args.pop('command', ''),
                'verification_type': function_args.pop('verification_type', 'image'),
                'params': {}
            }
            standard_keys = {'device_id', 'host_name', 'team_id', 'userinterface_name', 'tree_id', 'node_id'}
            for key in list(function_args.keys()):
                if key not in standard_keys:
                    verification_obj['params'][key] = function_args.pop(key)
            function_args['verifications'] = [verification_obj]
        
        print(f"[@mcp_proxy] Final arguments: {json.dumps(function_args, indent=2)}")
        
        # Call MCP tool
        print(f"[@mcp_proxy] Calling MCP tool: {function_name}")
        mcp_result = mcp_server.handle_tool_call(function_name, function_args)
        
        # Parse result
        if mcp_result.get('isError'):
            error_text = mcp_result['content'][0]['text'] if mcp_result.get('content') else 'Unknown error'
            print(f"[@mcp_proxy] ❌ MCP error: {error_text}")
            return jsonify({
                'success': False,
                'error': f'MCP error: {error_text}',
                'tool_name': function_name,
                'tool_arguments': function_args,
                'iterations': iteration
            }), 500
        
        result_text = mcp_result['content'][0]['text'] if mcp_result.get('content') else '{}'
        
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError:
            result = {'message': result_text}
        
        # Add tool result to conversation
        messages.append({
            'role': 'tool',
            'tool_call_id': tool_call['id'],
            'name': function_name,
            'content': result_text
        })
        
        # Check success for execution tools
        execution_success = True
        if 'success' in result:
            execution_success = result['success']
        
        last_tool_result = result
        
        # Track this tool call for frontend display
        all_tool_calls.append({
            'tool': function_name,
            'arguments': function_args,
            'result': result
        })
        
        # Add reasoning about what the tool did
        tool_description = f"[Tool {len(all_tool_calls)}] Executed {function_name}"
        if execution_success:
            tool_description += " ✅ SUCCESS"
        else:
            tool_description += f" ❌ FAILED: {result.get('error', 'Unknown error')}"
        ai_reasoning_parts.append(tool_description)
        
        # If this was an execution tool (not a list/info tool), consider stopping
        if function_name in ['execute_device_action', 'navigate_to_node', 'verify_device_state', 'execute_testcase']:
            if execution_success:
                print(f"[@mcp_proxy] ✅ Execution tool succeeded, stopping")
                return jsonify({
                    'success': True,
                    'result': result,
                    'tool_calls': all_tool_calls,
                    'ai_response': '\n\n'.join(ai_reasoning_parts),
                    'iterations': iteration
                })
            else:
                error_msg = result.get('error') or result.get('message') or 'Execution failed'
                print(f"[@mcp_proxy] ❌ Execution tool failed: {error_msg}")
                return jsonify({
                    'success': False,
                    'error': f'Tool execution failed: {error_msg}',
                    'result': result,
                    'tool_calls': all_tool_calls,
                    'ai_response': '\n\n'.join(ai_reasoning_parts),
                    'iterations': iteration
                }), 500
        
        # Otherwise, continue to next iteration (e.g., list_actions -> execute_device_action)
        print(f"[@mcp_proxy] Tool executed: {function_name}, continuing to next iteration...")
    
    # Max iterations reached
    print(f"[@mcp_proxy] ⚠️ Max iterations ({max_iterations}) reached")
    return jsonify({
        'success': True,
        'result': last_tool_result or {},
        'tool_calls': all_tool_calls,
        'ai_response': '\n\n'.join(ai_reasoning_parts) if ai_reasoning_parts else f'Completed {max_iterations} iterations',
        'iterations': max_iterations
    })
    
@server_mcp_proxy_bp.route('/list-tools', methods=['GET'])
@handle_route_exceptions('mcp_proxy:list_tools')
def list_tools():
    """
    List available MCP tools (for debugging/discovery)
    """
    available_tools = mcp_server.get_available_tools()
    return jsonify({
        'success': True,
        'tools': [
            {
                'name': tool['name'],
                'description': tool['description'][:200]  # Truncated
            }
            for tool in available_tools
        ],
        'count': len(available_tools)
    })