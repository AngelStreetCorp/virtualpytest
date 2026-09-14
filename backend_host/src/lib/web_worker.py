"""
Dedicated Playwright Worker Thread

Owns a single long-lived thread where ALL Playwright operations execute.
Provides async (execution_id-based) and sync submission APIs.
"""

from __future__ import annotations

import threading
import queue
import time
import uuid
from typing import Callable, Dict, Any, Optional, Awaitable, Set


class WebTask:
    def __init__(self, kind: str, payload: Dict[str, Any], run_fn: Callable[[], Awaitable[Dict[str, Any]]]):
        self.execution_id: str = str(uuid.uuid4())
        self.kind: str = kind
        self.payload: Dict[str, Any] = payload
        self.run_fn: Callable[[], Awaitable[Dict[str, Any]]] = run_fn
        self.done: threading.Event = threading.Event()
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None


class WebWorker:
    _instance: Optional["WebWorker"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._q: "queue.Queue[WebTask]" = queue.Queue()
        self._executions: Dict[str, Dict[str, Any]] = {}
        self._exec_lock: threading.Lock = threading.Lock()
        self._cancelled_execution_ids: Set[str] = set()
        self._current_execution_id: Optional[str] = None
        self._current_async_task = None
        
        # Persistent async loop
        self.loop = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        
        self._thread: threading.Thread = threading.Thread(
            target=self._worker_thread,
            name="PlaywrightAsyncWorker",
            daemon=True,
        )
        self._thread.start()

    @classmethod
    def instance(cls) -> "WebWorker":
        with cls._lock:
            if not cls._instance:
                cls._instance = WebWorker()
        return cls._instance

    def submit_async(self, kind: str, payload: Dict[str, Any], run_fn: Callable[[], Awaitable[Dict[str, Any]]]) -> str:
        task = WebTask(kind, payload, run_fn)
        with self._exec_lock:
            self._executions[task.execution_id] = {
                'execution_id': task.execution_id,
                'status': 'running',
                'result': None,
                'error': None,
                'start_time': time.time(),
                'progress': 0,
                'message': f'{kind} started',
                'payload': payload or {},
            }
        self._q.put(task)
        return task.execution_id

    def submit_sync(self, kind: str, payload: Dict[str, Any], run_fn: Callable[[], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
        task_id = self.submit_async(kind, payload, run_fn)
        while True:
            status = self.get_status(task_id)
            if status['status'] == 'completed':
                return status['result']
            elif status['status'] == 'error':
                return {'success': False, 'error': status['error']}
            time.sleep(0.1)

    def get_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        with self._exec_lock:
            status = self._executions.get(execution_id)
            if not status:
                return None
            elapsed = int((time.time() - status['start_time']) * 1000)
            # Return a copy without start_time
            view = dict(status)
            view['elapsed_time_ms'] = elapsed
            view.pop('start_time', None)
            return view

    def _find_execution_for_device_locked(self, device_id: str) -> Optional[str]:
        """Find latest non-terminal execution for a specific device."""
        candidates = [
            (execution_id, state)
            for execution_id, state in self._executions.items()
            if isinstance(state.get('payload'), dict)
            and state['payload'].get('device_id') == device_id
            and state.get('status') not in ('completed', 'error', 'aborted')
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[1].get('start_time', 0), reverse=True)
        return candidates[0][0]

    def cancel_execution(self, execution_id: Optional[str] = None, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Cancel a queued/running execution."""
        task_to_cancel = None

        with self._exec_lock:
            resolved_execution_id = execution_id
            if not resolved_execution_id and device_id:
                resolved_execution_id = self._find_execution_for_device_locked(device_id)

            if not resolved_execution_id:
                return {
                    'success': False,
                    'error': 'No active execution found',
                }

            state = self._executions.get(resolved_execution_id)
            if not state:
                return {
                    'success': False,
                    'error': f'Execution {resolved_execution_id} not found',
                }

            current_status = state.get('status')
            if current_status in ('completed', 'error', 'aborted'):
                return {
                    'success': False,
                    'error': f'Execution already {current_status}',
                    'execution_id': resolved_execution_id,
                }

            state.update({
                'status': 'aborted',
                'error': 'Action execution aborted by user',
                'progress': 100,
                'message': 'Action execution aborted by user',
            })
            self._cancelled_execution_ids.add(resolved_execution_id)

            if self._current_execution_id == resolved_execution_id and self._current_async_task is not None:
                task_to_cancel = self._current_async_task

        if task_to_cancel is not None and self.loop is not None:
            def _cancel_task():
                if not task_to_cancel.done():
                    task_to_cancel.cancel()

            self.loop.call_soon_threadsafe(_cancel_task)

        return {
            'success': True,
            'aborted': True,
            'execution_id': resolved_execution_id,
            'message': 'Action execution aborted by user',
        }

    def _worker_thread(self):
        import asyncio
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Don't initialize Playwright on startup - Chrome might not be running yet
        # Initialize lazily on first task that needs it
        print("[WebWorker] Async worker thread started, Playwright will initialize on first use")
        self.loop.create_task(self._queue_processor())
        self.loop.run_forever()

    async def _init_playwright_if_needed(self):
        """Initialize Playwright lazily when first needed."""
        if self._playwright is not None:
            return  # Already initialized
        
        try:
            from playwright.async_api import async_playwright
            print("[WebWorker] Initializing Playwright (lazy init)...")
            self._playwright = await async_playwright().start()
            
            # Try to connect to existing Chrome, if fails we'll let the controller launch it
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp('http://127.0.0.1:9222')
                self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
                self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
                print("[WebWorker] Persistent Playwright initialized and connected to Chrome")
            except Exception as e:
                print(f"[WebWorker] Could not connect to Chrome on init ({e}), will connect when needed")
                # Don't fail - let the controller handle Chrome launching
                self._browser = None
                self._context = None
                self._page = None
        except Exception as e:
            print(f"[WebWorker] Failed to initialize Playwright: {e}")
            raise

    async def _queue_processor(self):
        """Process tasks from the queue in the dedicated async loop."""
        import asyncio

        while True:
            # Get task from queue (blocking, but in executor to not block loop)
            task = await self.loop.run_in_executor(None, self._q.get)
            
            try:
                with self._exec_lock:
                    execution_state = self._executions.get(task.execution_id)
                    if execution_state and execution_state.get('status') == 'aborted':
                        continue
                    self._current_execution_id = task.execution_id

                # Only initialize Playwright for web-related tasks (not for remote, ADB, etc.)
                # This prevents unnecessary Chrome connection attempts for Android/TV actions
                if task.kind == 'web' or (isinstance(task.payload, dict) and task.payload.get('requires_playwright', False)):
                    await self._init_playwright_if_needed()
                
                # Execute the async task using run_coroutine_threadsafe pattern
                # Since we're already IN the loop, run via task so it can be cancelled.
                self._current_async_task = asyncio.create_task(task.run_fn())
                result = await self._current_async_task
                
                with self._exec_lock:
                    if task.execution_id in self._executions:
                        if self._executions[task.execution_id].get('status') == 'aborted':
                            continue
                        self._executions[task.execution_id].update({
                            'status': 'completed',
                            'result': result,
                            'progress': 100,
                            'message': result.get('message', 'Completed')
                        })
            except asyncio.CancelledError:
                with self._exec_lock:
                    if task.execution_id in self._executions:
                        self._executions[task.execution_id].update({
                            'status': 'aborted',
                            'error': 'Action execution aborted by user',
                            'progress': 100,
                            'message': 'Action execution aborted by user',
                        })
            except Exception as e:
                print(f"[WebWorker] Task {task.execution_id} failed: {e}")
                import traceback
                traceback.print_exc()
                with self._exec_lock:
                    if task.execution_id in self._executions:
                        self._executions[task.execution_id].update({
                            'status': 'error',
                            'error': str(e),
                            'message': f'Failed: {e}'
                        })
            finally:
                with self._exec_lock:
                    if self._current_execution_id == task.execution_id:
                        self._current_execution_id = None
                    self._current_async_task = None
                task.done.set()

