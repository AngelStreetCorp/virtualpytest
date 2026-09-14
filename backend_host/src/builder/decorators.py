"""
Block Decorators

Shared decorators for standard and custom blocks.
"""

import io
import sys
from functools import wraps


def capture_logs(func):
    """
    Decorator to capture logs from block execution with Tee (terminal + buffer).
    
    Logs are written to BOTH:
    - Terminal (for real-time debugging)
    - Buffer (for frontend display)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Start capturing logs with Tee (print to both terminal and buffer)
        log_buffer = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        
        # Tee class to write to multiple streams (terminal + buffer)
        class Tee:
            def __init__(self, *streams):
                self.streams = streams
            def write(self, data):
                for stream in self.streams:
                    stream.write(data)
                    stream.flush()
            def flush(self):
                for stream in self.streams:
                    stream.flush()
        
        try:
            # Redirect stdout/stderr to BOTH terminal and buffer
            sys.stdout = Tee(old_stdout, log_buffer)
            sys.stderr = Tee(old_stderr, log_buffer)
            
            # Execute function
            result = func(*args, **kwargs)
            
            # Add captured logs to result
            if isinstance(result, dict):
                result['logs'] = log_buffer.getvalue()
            
            return result
        finally:
            # Always restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    return wrapper

