"""
Tool definitions for VirtualPyTest MCP Server - AUTO-GENERATED

All tool definitions are now auto-generated from implementation docstrings.
Zero manual configuration - just add a *_tools.py file and it's automatically included!
"""

from .build_definitions import get_builder, get_tool_handlers, TOOL_REGISTRY

# Get the global builder instance
_builder = get_builder()

# Create getter functions for each category (for backward compatibility)
def get_control_tools():
    return _builder.get_tools('control')

def get_action_tools():
    return _builder.get_tools('action')

def get_navigation_tools():
    return _builder.get_tools('navigation')

def get_verification_tools():
    return _builder.get_tools('verification')

def get_testcase_tools():
    return _builder.get_tools('testcase')

def get_script_tools():
    return _builder.get_tools('script')

def get_ai_tools():
    return _builder.get_tools('ai')

def get_screenshot_tools():
    return _builder.get_tools('screenshot')

def get_transcript_tools():
    return _builder.get_tools('transcript')

def get_device_tools():
    return _builder.get_tools('device')

def get_logs_tools():
    return _builder.get_tools('logs')

def get_tree_tools():
    return _builder.get_tools('tree')

def get_userinterface_tools():
    return _builder.get_tools('userinterface')

def get_requirements_tools():
    return _builder.get_tools('requirements')

def get_screen_analysis_tools():
    return _builder.get_tools('screen_analysis')

def get_exploration_tools():
    return _builder.get_tools('exploration')

def get_deployment_tools():
    return _builder.get_tools('deployment')

def get_analysis_tools():
    return _builder.get_tools('analysis')

def get_campaign_tools():
    return _builder.get_tools('campaign')

def get_admin_tools():
    return _builder.get_tools('admin')


__all__ = [
    'TOOL_REGISTRY',
    'get_builder',
    'get_tool_handlers',
    'get_control_tools',
    'get_action_tools',
    'get_navigation_tools',
    'get_verification_tools',
    'get_testcase_tools',
    'get_script_tools',
    'get_ai_tools',
    'get_screenshot_tools',
    'get_transcript_tools',
    'get_device_tools',
    'get_logs_tools',
    'get_tree_tools',
    'get_userinterface_tools',
    'get_requirements_tools',
    'get_screen_analysis_tools',
    'get_exploration_tools',
    'get_deployment_tools',
    'get_analysis_tools',
    'get_campaign_tools',
    'get_admin_tools',
]

