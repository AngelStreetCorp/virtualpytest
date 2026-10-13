"""Browser-Use Integration Utility"""

import asyncio
import time
from typing import Dict, Any

# browser_use should be installed in the environment via requirements.txt
# No need to manipulate sys.path for properly installed packages

from browser_use import Agent
from browser_use.llm import ChatOpenAI

BROWSER_USAGE = 'agent.browser'
_OPENAI_COMPATIBLE_PRESETS = ('openrouter', 'openai', 'openai_compatible')


def _counted_http_client(hop: dict, team_id: str | None):
    """httpx client that reports every chat-completions response to the server's AI stats.

    A direct host-reach call never touches the server passthrough, and one browser-use task is N
    model calls, so each response is counted here (the server records them like any other call)."""
    import httpx
    from shared.src.lib.ai import gateway
    from shared.src.lib.ai.provider_client import openai_call_usage

    started: dict[int, float] = {}

    async def _on_request(request):
        started[id(request)] = time.time()

    async def _on_response(response):
        ms = int((time.time() - started.pop(id(response.request), time.time())) * 1000)
        if not str(response.request.url).endswith('/chat/completions'):
            return
        usage_block: dict = {}
        try:
            await response.aread()
            usage_block = (response.json() or {}).get('usage') or {}
        except Exception:
            pass
        ok = response.status_code < 400
        # The report is a blocking POST: keep it off the event loop.
        await asyncio.to_thread(
            gateway.report_direct_call, BROWSER_USAGE, team_id, hop, ok=ok, ms=ms,
            call_usage=openai_call_usage(usage_block), error_type=None if ok else 'server',
        )

    return httpx.AsyncClient(event_hooks={'request': [_on_request], 'response': [_on_response]},
                             timeout=httpx.Timeout(float(hop.get('timeout_s') or 120)))


def build_browser_llm(team_id: str | None = None) -> ChatOpenAI:
    """browser-use LLM from the ``agent.browser`` AI route (TASK-30).

    browser-use drives an OpenAI client itself, so the route must point at an
    OpenAI-compatible profile. A keyless LAN endpoint marked reach=host is called
    directly; any other goes through the server passthrough, which swaps in the
    routed model and the API key (hosts hold no provider keys).
    """
    from shared.src.lib.ai import gateway
    from shared.src.lib.utils.build_url_utils import buildServerUrl, server_auth_headers

    hop = gateway.describe(BROWSER_USAGE, team_id)['chain'][0]
    if hop['preset'] not in _OPENAI_COMPATIBLE_PRESETS:
        raise RuntimeError(f"{BROWSER_USAGE} routes to '{hop['profile']}' ({hop['preset']}); "
                           "browser-use needs an OpenAI-compatible profile")
    if hop['reach'] == 'host':
        return ChatOpenAI(model=hop['model'], api_key='local', base_url=hop['base_url'],
                          temperature=hop.get('temperature'), http_client=_counted_http_client(hop, team_id))
    headers = dict(server_auth_headers())
    if team_id:
        headers['X-VPT-Team-Id'] = team_id
    return ChatOpenAI(
        model=hop['model'],
        api_key='vpt-gateway',  # ignored: the server authenticates X-API-Key and holds the real key
        base_url=buildServerUrl(f'/server/ai/openai/{BROWSER_USAGE}'),
        default_headers=headers,
        temperature=hop.get('temperature'),
    )


class BrowserUseManager:
    """Simple browser-use manager with session reuse"""
    
    def __init__(self, playwright_utils):
        self.playwright_utils = playwright_utils
        self.llm = None
        
    def _get_llm(self):
        if self.llm is None:
            self.llm = build_browser_llm()
        return self.llm

    async def execute_task(self, task: str, max_steps: int = 20) -> Dict[str, Any]:
        """Execute browser-use task with configurable max_steps.
        
        Args:
            task: Task description for browser-use
            max_steps: Maximum steps for browser-use agent (default: 20)
        """
        start_time = time.time()
        execution_logs = []
        
        # Capture both print and logging output during execution
        import logging
        import io
        
        # Create string buffer to capture logs
        log_capture_string = io.StringIO()
        
        # Set up logging handler to capture browser-use logs
        log_handler = logging.StreamHandler(log_capture_string)
        log_handler.setLevel(logging.INFO)
        
        # Get root logger and browser-use specific loggers
        root_logger = logging.getLogger()
        browser_use_logger = logging.getLogger('browser_use')
        
        # Store original handlers
        original_handlers = root_logger.handlers[:]
        browser_use_original_handlers = browser_use_logger.handlers[:]
        
        # Add our capture handler
        root_logger.addHandler(log_handler)
        browser_use_logger.addHandler(log_handler)
        
        # Also capture print output
        original_print = print
        def capture_print(*args, **kwargs):
            # Call original print
            original_print(*args, **kwargs)
            # Capture the output
            if args:
                log_line = ' '.join(str(arg) for arg in args)
                execution_logs.append(log_line)
        
        # Replace print temporarily
        import builtins
        builtins.print = capture_print
        
        try:
            # Connect to existing browser
            _, _, _, page = await self.playwright_utils.connect_to_chrome()
            
            # Get current viewport to preserve it
            current_viewport = await page.evaluate("""() => ({
                width: window.innerWidth,
                height: window.innerHeight
            })""")
            
            # Create browser profile that preserves current viewport
            from browser_use.browser.profile import BrowserProfile
            browser_profile = BrowserProfile(
                viewport=current_viewport,
                no_viewport=False
            )
            
            # Create and run agent with existing page and preserved viewport
            agent = Agent(
                task=task, 
                llm=self._get_llm(), 
                page=page,
                browser_profile=browser_profile,
                use_vision=True,
                max_failures=5,  # Allow more failures before stopping
                retry_delay=2    # Shorter retry delay
            )
            await agent.run(max_steps=max_steps)
            
            # Get captured logs
            captured_logs = log_capture_string.getvalue()
            all_logs = execution_logs + [captured_logs] if captured_logs else execution_logs
            
            return {
                'success': True,
                'task': task,
                'execution_time': int((time.time() - start_time) * 1000),
                'result_summary': 'Task completed',
                'execution_logs': '\n'.join(all_logs)
            }
            
        finally:
            # Restore original print
            builtins.print = original_print
            
            # Restore original logging handlers
            root_logger.handlers = original_handlers
            browser_use_logger.handlers = browser_use_original_handlers 