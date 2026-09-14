"""
Log Capture Utility

Captures print statements and logs during execution for debugging and display in frontend.
"""

import sys
import io
from contextlib import contextmanager
from typing import List, Optional


class LogCapture:
    """Captures stdout/stderr output during execution"""
    
    def __init__(self):
        self.logs: List[str] = []
        self._old_stdout = None
        self._old_stderr = None
        self._stdout_buffer = None
        self._stderr_buffer = None
    
    def start(self):
        """Start capturing logs"""
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        self._stdout_buffer = io.StringIO()
        self._stderr_buffer = io.StringIO()
        
        # Redirect stdout and stderr to our buffers
        sys.stdout = self._stdout_buffer
        sys.stderr = self._stderr_buffer
    
    def stop(self) -> str:
        """Stop capturing and return logs as string"""
        # Restore original stdout/stderr
        if self._old_stdout:
            sys.stdout = self._old_stdout
        if self._old_stderr:
            sys.stderr = self._old_stderr
        
        # Get captured content
        stdout_content = self._stdout_buffer.getvalue() if self._stdout_buffer else ""
        stderr_content = self._stderr_buffer.getvalue() if self._stderr_buffer else ""
        
        # Combine stdout and stderr
        logs = []
        if stdout_content:
            logs.append(stdout_content)
        if stderr_content:
            logs.append("\n=== STDERR ===\n")
            logs.append(stderr_content)
        
        return "".join(logs)
    
    def get_logs(self) -> str:
        """Get current logs without stopping capture"""
        stdout_content = self._stdout_buffer.getvalue() if self._stdout_buffer else ""
        stderr_content = self._stderr_buffer.getvalue() if self._stderr_buffer else ""
        
        logs = []
        if stdout_content:
            logs.append(stdout_content)
        if stderr_content:
            logs.append("\n=== STDERR ===\n")
            logs.append(stderr_content)
        
        return "".join(logs)


@contextmanager
def capture_execution_logs():
    """Context manager for capturing execution logs"""
    capture = LogCapture()
    capture.start()
    try:
        yield capture
    finally:
        logs = capture.stop()
        capture.logs.append(logs)

