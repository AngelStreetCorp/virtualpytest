"""
Agent Chat → Slack Integration Hook

Connects agent chat websocket events to Slack sync service.
"""
import sys
import os

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_server_dir = os.path.dirname(os.path.dirname(current_dir))
project_root = os.path.dirname(backend_server_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from integrations.slack_sync import get_slack_sync
    SLACK_AVAILABLE = True
except ImportError:
    print("[agent_slack_hook] ⚠️  Slack sync not available")
    SLACK_AVAILABLE = False


def on_agent_message_websocket(session_id: str, agent: str, content: str, message_type: str = 'message'):
    """
    Hook for agent websocket messages
    
    Call this from server_agent_routes.py when emitting agent_event
    
    Args:
        session_id: WebSocket session ID (used as conversation_id)
        agent: Agent name (e.g., 'QA Manager', 'AI Assistant')
        content: Message content
        message_type: Event type ('message', 'result', etc.)
    """
    if not SLACK_AVAILABLE:
        return
    
    # Only sync actual messages, not tool calls or thinking
    if message_type not in ['message', 'result']:
        return
    
    slack = get_slack_sync()
    if not slack.enabled:
        return
    
    try:
        # Map agent names to display names
        agent_display = agent or 'AI Agent'
        
        # Post to Slack
        slack.post_message(
            conversation_id=session_id,
            agent=agent_display,
            content=content,
            conversation_title=f"Chat Session {session_id[:8]}"
        )
        
        print(f"[agent_slack_hook] ✅ Posted {agent_display} message to Slack (session: {session_id[:8]})")
    except Exception as e:
        print(f"[agent_slack_hook] ❌ Error posting to Slack: {e}")


def on_user_message_websocket(session_id: str, user_name: str, content: str):
    """
    Hook for user websocket messages
    
    Call this from server_agent_routes.py when user sends message
    
    Args:
        session_id: WebSocket session ID
        user_name: User's display name
        content: Message content
    """
    if not SLACK_AVAILABLE:
        return
    
    slack = get_slack_sync()
    if not slack.enabled:
        return
    
    try:
        slack.post_user_message(
            conversation_id=session_id,
            user_name=user_name or 'User',
            content=content,
            conversation_title=f"Chat Session {session_id[:8]}"
        )
        
        print(f"[agent_slack_hook] ✅ Posted user message to Slack (session: {session_id[:8]})")
    except Exception as e:
        print(f"[agent_slack_hook] ❌ Error posting user message to Slack: {e}")


def send_to_slack_channel(channel: str, message: str, agent_name: str = 'Agent'):
    """
    Send message to a specific Slack channel (e.g., #sherlock for background tasks)
    Each call creates a NEW top-level message (not a thread reply).
    
    Args:
        channel: Channel name (e.g., '#sherlock', '#alerts')
        message: Message content (formatted markdown)
        agent_name: Name of the agent sending the message
    """
    if not SLACK_AVAILABLE:
        return
    
    slack = get_slack_sync()
    if not slack.enabled:
        return
    
    try:
        # Use a unique conversation ID for each message to avoid threading
        # This makes each Sherlock analysis a separate message in #sherlock
        import time
        conversation_id = f"channel_{channel.replace('#', '')}_{int(time.time() * 1000)}"
        
        slack.post_message(
            conversation_id=conversation_id,
            agent=agent_name,
            content=message,
            conversation_title=f"{agent_name} Analysis"
        )
        
        print(f"[agent_slack_hook] ✅ Posted {agent_name} message to {channel}")
    except Exception as e:
        print(f"[agent_slack_hook] ❌ Error posting to {channel}: {e}")

