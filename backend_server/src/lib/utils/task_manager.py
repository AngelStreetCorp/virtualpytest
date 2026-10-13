"""
Simple Task Manager for Async Browser-Use Tasks
"""
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

class TaskManager:
    """Thread-safe task manager for browser-use tasks"""
    
    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def create_task(self, command: str, params: Dict[str, Any]) -> str:
        """Create a new task and return task_id"""
        task_id = str(uuid.uuid4())
        
        with self._lock:
            self._tasks[task_id] = {
                'id': task_id,
                'command': command,
                'params': params,
                'status': 'started',
                'created_at': time.time(),
                'completed_at': None,
                'result': None,
                'error': None
            }
        
        return task_id
    
    def complete_task(self, task_id: str, result: Dict[str, Any], error: str = None, success: bool = None):
        """Mark task as completed with result.

        `success` is the caller's verdict, for when a bare `error` does not
        capture the outcome: a host callback can report no transport error and
        still describe a run that never happened (BUG-0089). Callers that have
        no such verdict omit it and keep the original "error means failed" rule.
        """
        with self._lock:
            if task_id in self._tasks:
                failed = bool(error) if success is None else not success
                self._tasks[task_id].update({
                    'status': 'failed' if failed else 'completed',
                    'completed_at': time.time(),
                    'result': result,
                    'error': error
                })
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task by ID"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def record_progress(self, task_id: str, progress: Dict[str, Any]):
        """Keep the latest progress event of a running task (served by the live status adapter)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task['progress'] = progress
                task['progress_at'] = time.time()

    def mark_stop_requested(self, task_id: str, requested_by: str):
        """Record that a user asked to stop this task; the host completion still decides the end."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task['stop_requested_by'] = requested_by
                task['stop_requested_at'] = time.time()
    
    def running_tasks(self, command: str, team_id: str) -> List[Dict[str, Any]]:
        """Copies of one team's tasks of `command` that have not completed yet."""
        with self._lock:
            return [
                dict(task) for task in self._tasks.values()
                if task['command'] == command
                and task['status'] == 'started'
                and str((task.get('params') or {}).get('team_id')) == str(team_id)
            ]

    def cleanup_old_tasks(self, max_age_seconds: int = 3600):
        """Remove tasks older than max_age_seconds"""
        current_time = time.time()
        with self._lock:
            to_remove = [
                task_id for task_id, task in self._tasks.items()
                if current_time - task['created_at'] > max_age_seconds
            ]
            for task_id in to_remove:
                del self._tasks[task_id]

# Global task manager instance
task_manager = TaskManager() 