"""
Standard Block Executor

Executes standard blocks using the BlockRegistry auto-discovery system.
All blocks are discovered from: backend_host/src/builder/blocks/*.py

NO legacy handlers - clean BlockRegistry integration only.
"""

import time
from typing import Dict, List, Any


class StandardBlockExecutor:
    """
    Executor for standard blocks - delegates to BlockRegistry.
    PURE - no log capture (handled by orchestrator)
    """
    
    def __init__(self, device=None):
        """
        Initialize standard block executor
        
        Args:
            device: Optional device instance (for device-specific operations)
        """
        self.device = device
    
    def execute_blocks(self, blocks: List[Dict[str, Any]], context=None) -> Dict[str, Any]:
        """
        Execute batch of standard blocks (PURE - no log capture)
        
        Args:
            blocks: List of block dictionaries
            context: Optional execution context
            
        Returns:
            Dict with success status, results, and execution statistics
        """
        print(f"[@StandardBlockExecutor] Executing {len(blocks)} standard block(s)")
        
        # Validate inputs
        if not blocks:
            return {
                'success': True,
                'message': 'No blocks to execute',
                'results': [],
                'passed_count': 0,
                'total_count': 0
            }
        
        results = []
        passed_count = 0
        
        # Execute each block
        for i, block in enumerate(blocks):
            block_type = block.get('type') or block.get('command')
            
            start_time = time.time()
            result = self._execute_single_block(block, context)
            execution_time = int((time.time() - start_time) * 1000)
            
            # Add execution time to result
            result['execution_time_ms'] = execution_time
            result['block_type'] = block_type
            results.append(result)
            
            # Count successful blocks
            # Support both formats: result_success (0=success) and success (boolean)
            is_success = (
                result.get('result_success') == 0 or  # Legacy format
                result.get('success') is True          # New format
            )
            if is_success:
                passed_count += 1
        
        overall_success = passed_count == len(blocks)
        
        return {
            'success': overall_success,
            'total_count': len(blocks),
            'passed_count': passed_count,
            'failed_count': len(blocks) - passed_count,
            'results': results,
            'message': f'Batch block execution completed: {passed_count}/{len(blocks)} passed'
        }
    
    def _execute_single_block(self, block: Dict[str, Any], context=None) -> Dict[str, Any]:
        """
        Execute a single standard block using BlockRegistry.
        
        Args:
            block: Block dictionary with type/command and params
            context: Optional execution context
            
        Returns:
            Dict with success status, message, and optional output_data
        """
        from backend_host.src.builder.block_registry import execute_block
        
        block_type = block.get('type') or block.get('command')
        params = block.get('params', {}) or block.get('data', {})
        
        print(f"[@StandardBlockExecutor] Executing block: {block_type}")
        
        # Execute through BlockRegistry (auto-discovers from blocks/ folder)
        result = execute_block(block_type, params=params, context=context)
        
        return result


