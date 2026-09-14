"""
Declarative Script Framework
Ultra-simple decorator-based script execution
"""

import functools
from typing import Callable, Any
from .script_executor import ScriptExecutor, handle_keyboard_interrupt, handle_unexpected_error
from .cli_arg_utils import str_to_bool

# Global context for current script execution
_current_context = None
_current_executor = None

def script(name: str, description: str, default_device: str = "host", capture_artifacts: bool = True):
    """
    Decorator that handles all script infrastructure automatically

    Scripts declare their parameters in _script_args. If userinterface_name is
    declared as a parameter, it will be added to the argparser automatically.

    capture_artifacts: when False, the initial/final screenshots and the execution
    video are neither captured nor uploaded to storage (MinIO/R2). Use for scripts
    with no meaningful visual state (e.g. network/CLI diagnostics on the host).

    Examples:
        # Script without UI navigation
        @script("dns_lookuptime", "Perform DNS lookup")
        def main():
            perform_dns_lookup()

        main._script_args = ['--dns:str:google.com']

        # Script with UI navigation
        @script("goto_live", "Navigate to live node")
        def main():
            navigate_to("live")

        main._script_args = ['userinterface_name:str:example_mobile']

        # Script with no meaningful screenshots/video (skip capture + upload)
        @script("dns_lookuptime", "Perform DNS lookup", capture_artifacts=False)
        def main():
            perform_dns_lookup()
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper():
            global _current_context, _current_executor

            # Setup everything automatically
            executor = ScriptExecutor(name, description, default_device=default_device, capture_artifacts=capture_artifacts)
            parser = executor.create_argument_parser()
            
            # Add script-specific arguments from function attribute
            # Check both the original function and the wrapper (since _script_args is set after decoration)
            script_args = None
            if hasattr(func, '_script_args'):
                script_args = func._script_args
            elif hasattr(wrapper, '_script_args'):
                script_args = wrapper._script_args
            
            if script_args:
                for arg_spec in script_args:
                    # Parse format: '--name:type:default' or '--name:type:default:choices'
                    # NOTE: defaults may contain colons (e.g. URLs like https://192.168.1.1),
                    # so we identify the choices part by the presence of '|' and rejoin the rest as default.
                    all_parts = arg_spec.split(':')
                    if len(all_parts) < 3:
                        continue

                    arg_name = all_parts[0]
                    arg_type = all_parts[1]
                    remaining = all_parts[2:]
                    choices_str = None
                    default_parts = remaining
                    for ri in range(len(remaining) - 1, -1, -1):
                        if '|' in remaining[ri]:
                            choices_str = remaining[ri]
                            default_parts = remaining[:ri]
                            break
                    default_value = ':'.join(default_parts) if default_parts else ''
                    
                    # Convert type string to actual type
                    if arg_type == 'int':
                        parser.add_argument(arg_name, type=int, default=int(default_value),
                                           help=f'{arg_name.replace("--", "").replace("_", " ").title()} (default: {default_value})')
                    elif arg_type == 'float':
                        parser.add_argument(arg_name, type=float, default=float(default_value),
                                           help=f'{arg_name.replace("--", "").replace("_", " ").title()} (default: {default_value})')
                    elif arg_type == 'str':
                        kwargs = dict(type=str, default=default_value,
                                      help=f'{arg_name.replace("--", "").replace("_", " ").title()} (default: {default_value})')
                        if choices_str:
                            kwargs['choices'] = choices_str.split('|')
                        parser.add_argument(arg_name, **kwargs)
                    elif arg_type == 'bool':
                        default_bool = default_value.lower() in ('true', 't', 'yes', 'y', '1')
                        parser.add_argument(arg_name, type=str_to_bool, default=default_bool,
                                           help=f'{arg_name.replace("--", "").replace("_", " ").title()} (default: {default_value})')
            
            args, unknown_args = parser.parse_known_args()
            if unknown_args:
                print(f"[script_decorator] Ignoring unknown arguments: {' '.join(unknown_args)}")
            print(f"[script_decorator] Parsed args: {vars(args)}")
            
            context = executor.setup_execution_context(args, enable_db_tracking=True)
            
            if context.error_message:
                userinterface = getattr(args, 'userinterface_name', None)
                executor.cleanup_and_exit(context, userinterface)
                return
            
            # Set global context for helper functions
            _current_context = context
            _current_executor = executor
            context.args = args
            
            try:
                result = func()
            
                if result is None or result is True:
                    executor.test_success(context)
                else:
                    executor.test_fail(context)
                    
            except KeyboardInterrupt:
                handle_keyboard_interrupt(name)
            except Exception as e:
                handle_unexpected_error(name, e)
            finally:
                userinterface = getattr(args, 'userinterface_name', None)
                executor.cleanup_and_exit(context, userinterface)
                _current_context = None
                _current_executor = None
        
        return wrapper
    return decorator

def get_device():
    """Get current device"""
    return _current_context.selected_device

def get_context():
    """Get current execution context"""
    return _current_context

def get_args():
    """Get parsed command line arguments"""
    return _current_context.args
