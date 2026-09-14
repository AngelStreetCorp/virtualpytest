"""
Bash Desktop Controller Implementation

This controller provides bash command execution functionality on the host machine.
Simple local command execution only - no SSH, no connection checks.
"""

from typing import Dict, Any, List, Optional
import subprocess
import time
import json
import os
from pathlib import Path
from ..base_controller import DesktopControllerInterface


class BashDesktopController(DesktopControllerInterface):
    """Bash desktop controller for executing bash commands locally on the host machine."""
    
    def __init__(self, **kwargs):
        """Initialize the Bash desktop controller."""
        super().__init__("Bash Desktop", "bash")
        
        # Command execution state
        self.last_command_output = ""
        self.last_command_error = ""
        self.last_exit_code = 0
        
        print(f"[@controller:BashDesktop] Initialized for local execution")
    
    def connect(self) -> bool:
        """Connect to host machine (always true for local execution)."""
        print(f"Desktop[{self.desktop_type.upper()}]: Local execution ready")
        return True
            
    def disconnect(self) -> bool:
        """Disconnect from host machine (always true for local execution)."""
        print(f"Desktop[{self.desktop_type.upper()}]: Local execution disconnected")
        return True
            
    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute bash command directly on local host.
        
        Args:
            command: Command type ('execute_bash_command')
            params: Command parameters containing the actual bash command
            
        Returns:
            Dict: Command execution result
        """
        if params is None:
            params = {}
        
        print(f"Desktop[{self.desktop_type.upper()}]: Executing command '{command}' with params: {params}")
        
        if command == 'execute_bash_command':
            bash_command = params.get('command') or params.get('bash_command')
            working_dir = params.get('working_dir')
            timeout = params.get('timeout', 30)
            
            if not bash_command:
                return {
                    'success': False,
                    'output': '',
                    'error': 'No bash command provided',
                    'exit_code': -1,
                    'execution_time': 0
                }
            
            # Execute the bash command directly using subprocess
            start_time = time.time()
            
            try:
                # Execute bash commands safely without shell=True to prevent command injection
                # Use ['bash', '-c', command] for proper bash interpretation
                process = subprocess.Popen(
                    ['bash', '-c', bash_command],
                    shell=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=working_dir
                )
                
                # Wait for command completion with timeout
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                    exit_code = process.returncode
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    exit_code = -1
                    stderr = f"Command timed out after {timeout} seconds\n{stderr}"
                
                execution_time = int((time.time() - start_time) * 1000)  # Convert to milliseconds
                success = exit_code == 0
                
                # Store last command results
                self.last_command_output = stdout or ''
                self.last_command_error = stderr or ''
                self.last_exit_code = exit_code
                
                if success:
                    print(f"Desktop[{self.desktop_type.upper()}]: Executing local command: '{bash_command}' - SUCCESS")
                else:
                    print(f"Desktop[{self.desktop_type.upper()}]: Executing local command: '{bash_command}' - FAILED (exit code {exit_code}): {stderr[:200] if stderr else 'No error details'}")
                
                return {
                    'success': success,
                    'output': stdout or '',
                    'error': stderr or '',
                    'exit_code': exit_code,
                    'execution_time': execution_time
                }
                
            except Exception as e:
                execution_time = int((time.time() - start_time) * 1000)
                error_msg = f"Local command execution error: {e}"
                print(f"Desktop[{self.desktop_type.upper()}]: {error_msg}")
                
                return {
                    'success': False,
                    'output': '',
                    'error': error_msg,
                    'exit_code': -1,
                    'execution_time': execution_time
                }
        
        else:
            print(f"Desktop[{self.desktop_type.upper()}]: Unknown command: {command}")
            return {
                'success': False,
                'output': '',
                'error': f'Unknown command: {command}',
                'exit_code': -1,
                'execution_time': 0
            }
    
    def get_available_actions(self) -> Dict[str, Any]:
        """Get available actions for Bash desktop controller."""
        return {
            'Desktop': [
                {
                    'id': 'bash_command',
                    'label': 'Execute Bash Command',
                    'command': 'execute_bash_command',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Execute a bash command on the host system',
                    'requiresInput': True,
                    'inputLabel': 'Bash command',
                    'inputPlaceholder': 'ls -la, ps aux, echo "hello"'
                }
            ]
        } 