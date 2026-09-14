"""
Typing Compatibility Module

This module ensures that typing imports are available globally to fix compatibility issues
with third-party packages that use typing annotations without proper imports.

This fixes issues like:
- Supabase: "name 'Tuple' is not defined"
- Selenium: "name 'List' is not defined"
- Other packages that assume typing imports are globally available

Usage:
    Import this module early in your application startup:
    
    from shared.src.lib.utils.typing_compatibility import ensure_typing_compatibility
    ensure_typing_compatibility()
    
    Or simply import the module to auto-apply the fix:
    
    import shared.src.lib.utils.typing_compatibility
"""

import sys
from typing import TYPE_CHECKING

# List of typing imports that should be made globally available
TYPING_IMPORTS = [
    'Tuple', 'Dict', 'List', 'Optional', 'Any', 'Union', 'Set', 'FrozenSet',
    'Callable', 'Iterator', 'Iterable', 'Generator', 'Awaitable', 'Coroutine',
    'AsyncIterator', 'AsyncIterable', 'AsyncGenerator', 'Type', 'ClassVar',
    'Final', 'Literal', 'TypeVar', 'Generic', 'Protocol', 'runtime_checkable',
    'overload', 'cast', 'get_type_hints', 'get_origin', 'get_args'
]

def ensure_typing_compatibility():
    """
    Ensure typing imports are available in the global namespace.
    
    This fixes compatibility issues with third-party packages that use typing
    annotations without proper imports.
    """
    try:
        # Import all common typing constructs
        import typing
        import builtins
        
        # Make typing imports available globally
        for name in TYPING_IMPORTS:
            if hasattr(typing, name) and not hasattr(builtins, name):
                setattr(builtins, name, getattr(typing, name))
        
        print(f"[typing_compatibility] Applied global typing compatibility for {len(TYPING_IMPORTS)} types")
        
    except ImportError:
        # Fallback for older Python versions
        try:
            import typing_extensions as typing
            import builtins
            
            for name in TYPING_IMPORTS:
                if hasattr(typing, name) and not hasattr(builtins, name):
                    setattr(builtins, name, getattr(typing, name))
            
            print(f"[typing_compatibility] Applied global typing compatibility using typing_extensions")
            
        except ImportError:
            print(f"[typing_compatibility] Warning: Could not apply typing compatibility - typing_extensions not available")

def check_typing_availability():
    """
    Check which typing imports are available globally.
    Useful for debugging typing compatibility issues.
    """
    import builtins
    available = []
    missing = []
    
    for name in TYPING_IMPORTS:
        if hasattr(builtins, name):
            available.append(name)
        else:
            missing.append(name)
    
    print(f"[typing_compatibility] Available globally: {available}")
    if missing:
        print(f"[typing_compatibility] Missing globally: {missing}")
    
    return available, missing

# Auto-apply typing compatibility when this module is imported
ensure_typing_compatibility()
