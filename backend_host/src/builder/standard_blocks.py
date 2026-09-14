"""
Standard Blocks (Wrapper)

Clean wrapper that delegates to BlockRegistry for auto-discovered blocks.

Architecture:
- Standard blocks: backend_host/src/builder/blocks/*.py (auto-discovered)
- NO legacy handlers - all blocks must be in blocks/ folder

Each standard block file must have:
1. get_block_info() -> Dict (metadata with typed params)
2. execute(**kwargs) -> Dict (execution logic)
"""

from typing import Dict, Any, List
from backend_host.src.builder.block_registry import get_available_blocks, execute_block


def get_available_standard_blocks() -> List[Dict[str, Any]]:
    """
    Get available standard blocks with typed parameters.
    
    Delegates to the block registry which auto-discovers blocks from:
    - backend_host/src/builder/blocks/*.py
    
    Returns:
        List of block info dicts with metadata
    """
    return get_available_blocks()


def execute_standard_block(command: str, params: Dict[str, Any] = None, context=None) -> Dict[str, Any]:
    """
    Execute a standard block by command name.
    
    Delegates to the block registry.
    
    Args:
        command: Block command name (e.g., 'sleep', 'evaluate_condition')
        params: Block parameters dict
        context: Execution context
        
    Returns:
        Dict with success status and result
    """
    return execute_block(command, params=params or {}, context=context)

