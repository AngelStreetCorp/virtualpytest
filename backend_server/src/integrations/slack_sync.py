"""
Slack Sync Service
Listens to AI agent conversation events and posts to Slack channel

Configuration stored in: config/integrations/slack_config.json (like JIRA)
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Setup path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_server_dir = os.path.dirname(os.path.dirname(current_dir))
project_root = os.path.dirname(backend_server_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_SDK_AVAILABLE = True
except ImportError:
    print("[slack_sync] ⚠️  slack-sdk not installed. Run: pip install slack-sdk")
    SLACK_SDK_AVAILABLE = False

# Config paths
BACKEND_SERVER_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'slack_config.json'
THREADS_PATH = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'slack_threads.json'


class SlackSyncService:
    """
    Slack synchronization service for AI agent conversations
    
    Posts agent messages to Slack channel in threaded conversations.
    Each AI conversation becomes a separate Slack thread.
    """
    
    def __init__(self):
        self.client: Optional[WebClient] = None
        self.config: Dict = {}
        self.threads: Dict = {}
        self.enabled = False
        self.load_config()
    
    def load_config(self):
        """Load Slack configuration from JSON file"""
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH) as f:
                    self.config = json.load(f)
                    
                self.enabled = self.config.get('enabled', False)
                
                # Initialize Slack client if enabled and token available
                if self.enabled and self.config.get('bot_token') and SLACK_SDK_AVAILABLE:
                    self.client = WebClient(token=self.config['bot_token'])
                    print("[slack_sync] ✅ Slack client initialized")
                else:
                    self.client = None
                    if self.enabled and not SLACK_SDK_AVAILABLE:
                        print("[slack_sync] ⚠️  Slack enabled but SDK not available")
            else:
                print(f"[slack_sync] Config not found: {CONFIG_PATH}")
                self.enabled = False
                
            # Load threads mapping
            if THREADS_PATH.exists():
                with open(THREADS_PATH) as f:
                    self.threads = json.load(f)
            else:
                self.threads = {}
                
        except Exception as e:
            print(f"[slack_sync] ❌ Error loading config: {e}")
            self.enabled = False
    
    def save_threads(self):
        """Save threads mapping to file"""
        try:
            THREADS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(THREADS_PATH, 'w') as f:
                json.dump(self.threads, f, indent=2)
        except Exception as e:
            print(f"[slack_sync] ❌ Error saving threads: {e}")
    
    def format_agent_message(self, agent: str, content: str) -> str:
        """Format message for Slack with agent name"""
        # Map agent names to nicknames
        agent_nicknames = {
            'AI Assistant': 'Atlas',
            'QA Web Manager': 'Sherlock',
            'QA Mobile Manager': 'Scout',
            'QA STB Manager': 'Watcher',
            'Monitoring Manager': 'Guardian',
        }
        
        nickname = agent_nicknames.get(agent, agent)
        return f"*{nickname}:* {content}"
    
    def post_message(
        self, 
        conversation_id: str, 
        agent: str, 
        content: str,
        conversation_title: Optional[str] = None
    ):
        """
        Post agent message to Slack channel
        
        Args:
            conversation_id: Unique conversation identifier
            agent: Agent name (e.g., 'AI Assistant', 'QA Web Manager')
            content: Message content to post
            conversation_title: Optional conversation title for new threads
        """
        if not self.enabled or not self.client:
            return
        
        try:
            channel = self.config.get('channel_id')
            if not channel:
                print("[slack_sync] ⚠️  No channel ID configured")
                return
            
            thread_ts = self.threads.get(conversation_id)
            formatted_text = self.format_agent_message(agent, content)
            
            # Create new thread or reply to existing
            if not thread_ts:
                # Create new thread with conversation title
                thread_title = conversation_title or "AI Agent Conversation"
                response = self.client.chat_postMessage(
                    channel=channel,
                    text=f"🤖 {thread_title}",
                    blocks=[
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": f"🤖 {thread_title}"
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": formatted_text
                            }
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"Conversation ID: `{conversation_id[:8]}...` • {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                                }
                            ]
                        }
                    ]
                )
                
                # Save thread timestamp
                self.threads[conversation_id] = response['ts']
                self.threads['_last_sync'] = datetime.now().isoformat()
                self.save_threads()
                
                print(f"[slack_sync] ✅ Created new thread for conversation {conversation_id[:8]}")
            else:
                # Reply to existing thread
                self.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=formatted_text,
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": formatted_text
                            }
                        }
                    ]
                )
                
                print(f"[slack_sync] ✅ Posted reply to conversation {conversation_id[:8]}")
                
        except SlackApiError as e:
            error_code = e.response.get('error', 'unknown')
            print(f"[slack_sync] ❌ Slack API error: {error_code}")
            
            if error_code == 'channel_not_found':
                print("[slack_sync]    Channel not found. Check channel ID.")
            elif error_code == 'not_in_channel':
                print("[slack_sync]    Bot not in channel. Invite bot to channel first.")
            elif error_code == 'invalid_auth':
                print("[slack_sync]    Invalid token. Check bot token configuration.")
                
        except Exception as e:
            print(f"[slack_sync] ❌ Error posting message: {e}")
    
    def post_user_message(
        self,
        conversation_id: str,
        user_name: str,
        content: str,
        conversation_title: Optional[str] = None
    ):
        """
        Post user message to Slack thread
        
        Args:
            conversation_id: Unique conversation identifier
            user_name: User's name
            content: User's message
            conversation_title: Optional conversation title for new threads
        """
        if not self.enabled or not self.client:
            return
        
        # For user messages, we might want to create the thread if it doesn't exist
        thread_ts = self.threads.get(conversation_id)
        
        if not thread_ts and conversation_title:
            # Create thread with user's message
            self.post_message(conversation_id, user_name, content, conversation_title)
        elif thread_ts:
            # Reply to existing thread
            try:
                channel = self.config.get('channel_id')
                self.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"*{user_name}:* {content}",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{user_name}:* {content}"
                            }
                        }
                    ]
                )
                print(f"[slack_sync] ✅ Posted user message to conversation {conversation_id[:8]}")
            except Exception as e:
                print(f"[slack_sync] ❌ Error posting user message: {e}")


# Global singleton instance
_slack_sync_instance: Optional[SlackSyncService] = None


def get_slack_sync() -> SlackSyncService:
    """Get or create global Slack sync service instance"""
    global _slack_sync_instance
    if _slack_sync_instance is None:
        _slack_sync_instance = SlackSyncService()
    return _slack_sync_instance


def reload_slack_config():
    """Reload Slack configuration (called after config updates)"""
    global _slack_sync_instance
    if _slack_sync_instance:
        _slack_sync_instance.load_config()
        print("[slack_sync] ♻️  Configuration reloaded")


# Event listener integration (to be connected to your event system)
def on_agent_message(event: Dict):
    """
    Event handler for agent messages
    
    Expected event format:
    {
        'conversation_id': str,
        'agent': str,
        'content': str,
        'conversation_title': str (optional)
    }
    """
    slack = get_slack_sync()
    if slack.enabled:
        slack.post_message(
            conversation_id=event.get('conversation_id'),
            agent=event.get('agent', 'AI Agent'),
            content=event.get('content', ''),
            conversation_title=event.get('conversation_title')
        )


def on_user_message(event: Dict):
    """
    Event handler for user messages
    
    Expected event format:
    {
        'conversation_id': str,
        'user_name': str,
        'content': str,
        'conversation_title': str (optional)
    }
    """
    slack = get_slack_sync()
    if slack.enabled:
        slack.post_user_message(
            conversation_id=event.get('conversation_id'),
            user_name=event.get('user_name', 'User'),
            content=event.get('content', ''),
            conversation_title=event.get('conversation_title')
        )


if __name__ == '__main__':
    # Test the service
    print("[slack_sync] Testing Slack sync service...")
    slack = get_slack_sync()
    
    if slack.enabled:
        print(f"[slack_sync] Enabled: {slack.enabled}")
        print(f"[slack_sync] Channel: {slack.config.get('channel_id', 'Not set')}")
        print(f"[slack_sync] Threads tracked: {len(slack.threads)}")
    else:
        print("[slack_sync] Service is disabled or not configured")

