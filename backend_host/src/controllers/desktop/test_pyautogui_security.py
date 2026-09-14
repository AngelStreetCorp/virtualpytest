#!/usr/bin/env python3
"""
PyAutoGUI Security Testing Script

This script tests the security validations in the PyAutoGUI controller.
"""

import sys
import os

# Add paths for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_host_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
project_root = os.path.dirname(backend_host_dir)
sys.path.insert(0, project_root)

from backend_host.src.controllers.desktop.pyautogui import PyAutoGUIDesktopController

def test_security_validations():
    """Test all security validations"""
    print("=" * 70)
    print("PyAutoGUI Security Validation Tests")
    print("=" * 70)
    
    # Create controller instance
    controller = PyAutoGUIDesktopController()
    
    # Test cases for text input validation
    print("\n" + "=" * 70)
    print("TEST 1: Dangerous Command Patterns")
    print("=" * 70)
    
    dangerous_texts = [
        "rm -rf /",
        "cat .env",
        "sudo rm file",
        "shutdown now",
        "chmod 777 /etc/passwd",
        "cat /etc/shadow",
        "dd if=/dev/zero of=/dev/sda",
        "echo 'safe text'",  # This should pass
    ]
    
    for text in dangerous_texts:
        is_valid, error = controller._validate_text_input(text)
        status = "✅ ALLOWED" if is_valid else "❌ BLOCKED"
        print(f"{status}: '{text}'")
        if not is_valid:
            print(f"  Reason: {error}")
    
    # Test cases for application launch validation
    print("\n" + "=" * 70)
    print("TEST 2: Application Launch Restrictions")
    print("=" * 70)
    
    apps = [
        "bash",
        "sudo",
        "rm",
        "notepad",  # This should pass
        "firefox",  # This should pass
        "shutdown",
        "systemctl",
    ]
    
    for app in apps:
        is_valid, error = controller._validate_application(app)
        status = "✅ ALLOWED" if is_valid else "❌ BLOCKED"
        print(f"{status}: '{app}'")
        if not is_valid:
            print(f"  Reason: {error}")
    
    # Test cases for image path validation
    print("\n" + "=" * 70)
    print("TEST 3: Image Path Restrictions")
    print("=" * 70)
    
    paths = [
        "/tmp/image.png",  # This should pass
        "../../../etc/passwd",
        "/etc/config.png",
        "/home/user/image.png",  # This should pass
        "C:\\Windows\\System32\\image.png",
    ]
    
    for path in paths:
        is_valid, error = controller._validate_image_path(path)
        status = "✅ ALLOWED" if is_valid else "❌ BLOCKED"
        print(f"{status}: '{path}'")
        if not is_valid:
            print(f"  Reason: {error}")
    
    # Test execute_command with dangerous inputs
    print("\n" + "=" * 70)
    print("TEST 4: Full Command Execution Tests")
    print("=" * 70)
    
    test_commands = [
        {
            'command': 'execute_pyautogui_type',
            'params': {'text': 'cat .env'}
        },
        {
            'command': 'execute_pyautogui_type',
            'params': {'text': 'Hello World'}  # This should pass
        },
        {
            'command': 'execute_pyautogui_launch',
            'params': {'app_name': 'sudo'}
        },
        {
            'command': 'execute_pyautogui_launch',
            'params': {'app_name': 'notepad'}  # This should pass (but may fail if not installed)
        },
    ]
    
    for test in test_commands:
        result = controller.execute_command(test['command'], test['params'])
        status = "✅ SUCCESS" if result['success'] else "❌ BLOCKED"
        print(f"{status}: {test['command']} - {test['params']}")
        if not result['success']:
            print(f"  Error: {result['error']}")
    
    print("\n" + "=" * 70)
    print("Security Tests Completed!")
    print("=" * 70)

if __name__ == '__main__':
    test_security_validations()

