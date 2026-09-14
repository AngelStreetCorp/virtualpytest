"""
Block Registry

Auto-discovers and executes standard and custom blocks.

Architecture:
- Standard blocks: backend_host/src/builder/blocks/*.py
- Custom blocks: backend_host/src/builder/custom_blocks/*.py

Each block file must have:
1. get_block_info() -> Dict (returns metadata)
2. execute(**kwargs) -> Dict (executes the block)
"""

import os
import importlib
from typing import Dict, List, Any

# ✅ Global cache for discovered blocks (prevents re-discovery on every execution)
_BLOCK_CACHE: Dict[str, Any] = {}


def discover_blocks() -> Dict[str, Any]:
    """
    Auto-discover all blocks from blocks/ and custom_blocks/ folders.
    Uses caching to avoid re-discovery on every execution.
    
    Returns:
        Dict mapping command -> block_module
    """
    # ✅ Return cached blocks if already discovered
    if _BLOCK_CACHE:
        return _BLOCK_CACHE
    
    blocks = {}
    
    # Get builder directory
    builder_dir = os.path.dirname(__file__)
    
    # Discover standard blocks
    standard_blocks_dir = os.path.join(builder_dir, 'blocks')
    if os.path.exists(standard_blocks_dir):
        blocks.update(_discover_blocks_in_dir(standard_blocks_dir, 'backend_host.src.builder.blocks'))
    
    # Discover custom blocks (user-defined)
    custom_blocks_dir = os.path.join(builder_dir, 'custom_blocks')
    if os.path.exists(custom_blocks_dir):
        blocks.update(_discover_blocks_in_dir(custom_blocks_dir, 'backend_host.src.builder.custom_blocks'))
    
    print(f"[@block_registry] Discovered {len(blocks)} blocks: {list(blocks.keys())}")
    
    # ✅ Cache the discovered blocks
    _BLOCK_CACHE.update(blocks)
    
    return blocks


def _discover_blocks_in_dir(directory: str, module_prefix: str) -> Dict[str, Any]:
    """
    Discover blocks in a specific directory.
    
    Args:
        directory: Directory path to scan
        module_prefix: Python module prefix (e.g., 'backend_host.src.builder.blocks')
        
    Returns:
        Dict mapping command -> block_module
    """
    blocks = {}
    
    if not os.path.exists(directory):
        return blocks
    
    for filename in os.listdir(directory):
        if not filename.endswith('.py') or filename.startswith('_'):
            continue
        
        module_name = filename[:-3]  # Remove .py extension
        
        try:
            # Import the block module
            module = importlib.import_module(f'{module_prefix}.{module_name}')
            
            # Check if module has required functions
            if not hasattr(module, 'get_block_info') or not hasattr(module, 'execute'):
                print(f"[@block_registry] Skipping {module_name}: missing get_block_info() or execute()")
                continue
            
            # Get block metadata
            block_info = module.get_block_info()
            command = block_info.get('command')
            
            if not command:
                print(f"[@block_registry] Skipping {module_name}: no command in block_info")
                continue
            
            # Register block
            blocks[command] = module
            print(f"[@block_registry] Registered block: {command} ({module_name})")
            
        except Exception as e:
            print(f"[@block_registry] Failed to load {module_name}: {e}")
            continue
    
    return blocks


def get_available_blocks() -> List[Dict[str, Any]]:
    """
    Get list of all available blocks with their metadata.
    
    Returns:
        List of block info dicts
    """
    blocks = discover_blocks()
    block_list = []
    
    for command, module in blocks.items():
        try:
            block_info = module.get_block_info()
            block_list.append(block_info)
        except Exception as e:
            print(f"[@block_registry] Error getting info for {command}: {e}")
            continue
    
    return block_list


def execute_block(command: str, **kwargs) -> Dict[str, Any]:
    """
    Execute a block by command name.
    
    Args:
        command: Block command name (e.g., 'sleep', 'getMenuInfo')
        **kwargs: Block parameters (params dict + context)
        
    Returns:
        Dict with success status and result
    """
    blocks = discover_blocks()
    
    if command not in blocks:
        return {
            'success': False,
            'message': f'Unknown block command: {command}',
            'available_blocks': list(blocks.keys())
        }
    
    module = blocks[command]
    
    try:
        # Extract params from kwargs
        params = kwargs.get('params', {})
        context = kwargs.get('context')
        
        # Execute block with params unpacked
        result = module.execute(context=context, **params)
        
        return result
        
    except Exception as e:
        error_msg = f"Block execution error ({command}): {str(e)}"
        print(f"[@block_registry] {error_msg}")
        import traceback
        traceback.print_exc()
        
        return {
            'success': False,
            'message': error_msg
        }

