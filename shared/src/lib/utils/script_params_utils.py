"""Script parameters from source text: ``_script_args`` (``--name:type:default[:a|b]``) and argparse
calls, enriched with ``_arg_descriptions``. Used by the script routes (the run form) and by Sherlock
(the arguments a run actually got, next to their meaning)."""

import re


def analyze_script_source(source_text, script_name='virtual_script'):
    """
    Analyze Python *source text* to extract parameter information (argparse /
    _script_args). Shared by disk-script analysis (analyze_script_parameters)
    and DB-stored virtual scripts.
    """
    original_source = source_text or ''

    # Read first 300 lines to analyze parameters (some scripts have args later in file)
    lines = [line.strip() for line in original_source.splitlines()[:300]]
    script_content = '\n'.join(lines)

    # Look for both argparse patterns AND _script_args decorator patterns
    parameters = []
        
    # FIRST: Check for _script_args pattern (used by @script decorator framework)
    # Format: main._script_args = ['--param:type:default', ...]
    script_args_pattern = r"_script_args\s*=\s*\[(.*?)\]"
    script_args_match = re.search(script_args_pattern, script_content, re.DOTALL)
        
    if script_args_match:
        args_content = script_args_match.group(1)
        # Parse each argument: '--param:type:default' or '--param:type'
        # Extract strings between quotes, but ignore Python comments after them
        arg_items = re.findall(r"['\"]([^'\"]+)['\"]", args_content)
        print(f"[@analyze_script] Found _script_args raw: {arg_items}")
        
        for arg_item in arg_items:
            # Strip any Python comments that somehow got included (after # character)
            if '#' in arg_item:
                arg_item = arg_item.split('#')[0].strip()
            
            # Strip any commas or whitespace that got included
            arg_item = arg_item.strip().rstrip(',').strip()
            
            # Parse format: --param-name:type:default or --param-name:type
            # Extended: --param-name:type:default:choice1|choice2|choice3
            # NOTE: defaults may contain colons (e.g. URLs like https://192.168.1.1),
            # so we identify the choices part by the presence of '|' and rejoin the rest as default.
            all_parts = arg_item.split(':')
            if len(all_parts) >= 2:
                # Keep dashes in parameter names - they're used for command-line arguments
                param_name = all_parts[0].replace('--', '')
                param_type = all_parts[1] if len(all_parts) > 1 else 'str'

                # Remaining parts after name:type — find choices (contains '|')
                remaining = all_parts[2:]
                choices_raw = None
                default_parts = remaining
                for ri in range(len(remaining) - 1, -1, -1):
                    if '|' in remaining[ri]:
                        choices_raw = remaining[ri]
                        default_parts = remaining[:ri]
                        break
                default_value = ':'.join(default_parts) if default_parts else None

                # Convert default values
                if default_value == 'None':
                    default_value = None
                elif default_value == 'true' or default_value == 'True':
                    default_value = 'true'
                elif default_value == 'false' or default_value == 'False':
                    default_value = 'false'

                # Parse pipe-separated choices
                choices = [c.strip() for c in choices_raw.split('|') if c.strip()] if choices_raw else None

                param = {
                    'name': param_name,
                    'type': 'optional',
                    'required': False,
                    'help': '',
                    'default': default_value,
                    'dataType': param_type,
                }
                if choices:
                    param['choices'] = choices
                print(f"[@analyze_script] Parsed parameter from _script_args: {param}")
                parameters.append(param)
        
    # SECOND: Look for argparse patterns (fallback for scripts not using @script decorator)
    parser_patterns = [
        r"parser\.add_argument\(['\"]([^'\"]+)['\"][^)]*\)",
        r"parser\.add_argument\(['\"]--([^'\"]+)['\"][^)]*\)",
        r"parser\.add_argument\(['\"]([^'\"]+)['\"].*help=['\"]([^'\"]*)['\"]",
    ]
        
    # Extract positional arguments (required) - only if not already found in _script_args
    positional_pattern = r"parser\.add_argument\(['\"]([^-][^'\"]*)['\"](?:[^)]*help=['\"]([^'\"]*)['\"])?[^)]*\)"
    positional_matches = re.findall(positional_pattern, script_content, re.MULTILINE)
        
    for match in positional_matches:
        param_name = match[0]
        help_text = match[1] if len(match) > 1 else ''
        
        # Skip if already added from _script_args
        if not any(p['name'] == param_name for p in parameters):
            parameters.append({
                'name': param_name,
                'type': 'positional',
                'required': True,
                'help': help_text,
                'default': None
            })
        
    # Extract optional arguments with better multi-line handling
    # Look for parser.add_argument('--param_name', ... ) patterns that can span multiple lines
    optional_pattern = r"parser\.add_argument\(['\"]--([^'\"]+)['\"]([^)]*?)\)"
        
    # Find all add_argument calls for optional parameters - only if not already found in _script_args
    for match in re.finditer(optional_pattern, script_content, re.MULTILINE | re.DOTALL):
        param_name = match.group(1)
        
        # Skip if already added from _script_args
        if any(p['name'] == param_name for p in parameters):
            continue
        
        args_content = match.group(2)  # Everything between the parameter name and closing )
        
        # Extract help text
        help_match = re.search(r"help=['\"]([^'\"]*)['\"]", args_content)
        help_text = help_match.group(1) if help_match else ''
        
        # Extract default value
        default_match = re.search(r"default=([^,)]+)", args_content)
        default_value = None
        if default_match:
            default_raw = default_match.group(1).strip()
            # Handle different types of defaults
            if default_raw == 'True':
                default_value = 'true'
            elif default_raw == 'False':
                default_value = 'false'
            elif default_raw.startswith("'") and default_raw.endswith("'"):
                default_value = default_raw[1:-1]
            elif default_raw.startswith('"') and default_raw.endswith('"'):
                default_value = default_raw[1:-1]
            elif default_raw.isdigit():
                default_value = default_raw
            else:
                # For complex expressions like lambda, just take the value before comma/parenthesis
                default_value = default_raw.split(',')[0].split(')')[0].strip()
        
        parameters.append({
            'name': param_name,
            'type': 'optional',
            'required': False,
            'help': help_text,
            'default': default_value
        })
        
    # NO MORE INJECTION - Scripts explicitly define all their parameters
    # Framework parameters (userinterface_name, host, device) should be
    # explicitly defined in script's _script_args if the script needs them
        
    # Special handling for common patterns
    if 'userinterface_name' in [p['name'] for p in parameters]:
        # Add suggestions for userinterface_name based on common patterns
        ui_param = next(p for p in parameters if p['name'] == 'userinterface_name')
        ui_param['suggestions'] = [
            'example_mobile',
            'example_androidtv'
        ]
        
    # Enrich parameters with _arg_descriptions if available (from source)
    try:
        from shared.src.lib.utils.script_target_rules_utils import extract_arg_descriptions_from_source
        arg_descs = extract_arg_descriptions_from_source(original_source)
        if arg_descs:
            for param in parameters:
                desc = arg_descs.get(param['name'])
                if desc:
                    param['description'] = desc
    except Exception:
        pass

    return {
        'success': True,
        'parameters': parameters,
        'script_name': script_name,
        'has_parameters': len(parameters) > 0
    }
