/**
 * useExecutionState Hook
 * 
 * Unified execution state management for test case execution.
 * Tracks block-level execution states and provides real-time updates.
 * 
 * Modes:
 * - single_block: Execute one block via play button
 * - test_case: Execute full test case from START to terminal block
 */

import { useState, useCallback } from 'react';
import { ExecutionResultType } from '../../types/testcase/TestCase_Types';

export interface BlockExecutionState {
  status: 'idle' | 'pending' | 'executing' | 'success' | 'failure' | 'error';
  startTime?: number;
  endTime?: number;
  duration?: number;
  error?: string;
  result?: any;
}

export interface UnifiedExecutionState {
  mode: 'idle' | 'single_block' | 'test_case';
  isExecuting: boolean;
  currentBlockId: string | null;
  previousBlockId: string | null; // 🆕 Track previous block for edge animations
  blockStates: Map<string, BlockExecutionState>;
  edgeStates: Map<string, 'idle' | 'active' | 'success' | 'failure'>; // 🆕 Track edge execution states
  result: {
    success: boolean;
    result_type?: ExecutionResultType;
    execution_time_ms: number;
    error?: string;
    step_count?: number;
    report_url?: string;  // 🆕 R2 report URL
    logs_url?: string;    // 🆕 R2 logs URL
  } | null;
  startTime?: number;
}

const COMPLETED_BLOCK_STATUSES = ['success', 'failure', 'error'] as const;

const getResolvedDuration = (
  updates: Partial<BlockExecutionState>,
  current: BlockExecutionState
): number | undefined => {
  if (updates.duration !== undefined) {
    return updates.duration;
  }
  if (updates.endTime && current.startTime) {
    return updates.endTime - current.startTime;
  }
  return current.duration;
};

export const useExecutionState = () => {
  const [state, setState] = useState<UnifiedExecutionState>({
    mode: 'idle',
    isExecuting: false,
    currentBlockId: null,
    previousBlockId: null,
    blockStates: new Map(),
    edgeStates: new Map(),
    result: null,
  });

  /**
   * Start a new execution
   */
  const startExecution = useCallback((
    mode: 'single_block' | 'test_case',
    blockIds?: string[]
  ) => {
    const newBlockStates = new Map<string, BlockExecutionState>();
    
    // Initialize block states as pending
    blockIds?.forEach(id => {
      newBlockStates.set(id, { status: 'pending' });
    });

    setState({
      mode,
      isExecuting: true,
      currentBlockId: blockIds?.[0] || null,
      previousBlockId: null,
      blockStates: newBlockStates,
      edgeStates: new Map(), // Reset edge states
      result: null,
      startTime: Date.now(),
    });
  }, []);

  /**
   * Update a specific block's execution state
   */
  const updateBlockState = useCallback((
    blockId: string,
    updates: Partial<BlockExecutionState>
  ) => {
    setState(prev => {
      const newBlockStates = new Map(prev.blockStates);
      const current = newBlockStates.get(blockId) || { status: 'idle' };
      
      newBlockStates.set(blockId, { 
        ...current, 
        ...updates,
        duration: getResolvedDuration(updates, current),
      });

      return {
        ...prev,
        blockStates: newBlockStates,
      };
    });
  }, []);

  /**
   * Start executing a specific block
   */
  const startBlockExecution = useCallback((blockId: string) => {
    setState(prev => {
      const newBlockStates = new Map(prev.blockStates);
      newBlockStates.set(blockId, {
        status: 'executing',
        startTime: Date.now(),
      });

      return {
        ...prev,
        previousBlockId: prev.currentBlockId, // Track previous for edge animation
        currentBlockId: blockId,
        blockStates: newBlockStates,
      };
    });
  }, []);

  /**
   * Complete a block execution with result
   */
  const completeBlockExecution = useCallback((
    blockId: string,
    success: boolean,
    error?: string,
    result?: any
  ) => {
    setState(prev => {
      const newBlockStates = new Map(prev.blockStates);
      const current = newBlockStates.get(blockId);
      const endTime = Date.now();
      
      newBlockStates.set(blockId, {
        status: success ? 'success' : error?.includes('no') && error?.includes('connection') ? 'error' : 'failure',
        startTime: current?.startTime,
        endTime,
        duration: current?.startTime ? endTime - current.startTime : undefined,
        error,
        result,
      });

      // 🆕 Update edge state for edges connected to this block
      // Mark outgoing edges based on block result
      const newEdgeStates = new Map(prev.edgeStates);
      
      // Note: Edge keys will be set by TestCaseBuilder based on graph structure
      // Here we just maintain the state, actual edge key generation happens in TestCaseBuilder

      return {
        ...prev,
        blockStates: newBlockStates,
        edgeStates: newEdgeStates,
      };
    });
  }, []);

  /**
   * Set the current executing block
   */
  const setCurrentBlock = useCallback((blockId: string | null) => {
    setState(prev => ({ 
      ...prev, 
      previousBlockId: prev.currentBlockId,
      currentBlockId: blockId 
    }));
  }, []);

  /**
   * Complete the entire execution
   */
  const completeExecution = useCallback((result: UnifiedExecutionState['result']) => {
    setState(prev => ({
      ...prev,
      isExecuting: false,
      currentBlockId: null,
      previousBlockId: null,
      result,
    }));
  }, []);

  /**
   * Reset execution state (clear all)
   */
  const resetExecution = useCallback(() => {
    setState({
      mode: 'idle',
      isExecuting: false,
      currentBlockId: null,
      previousBlockId: null,
      blockStates: new Map(),
      edgeStates: new Map(),
      result: null,
    });
  }, []);

  /**
   * Get execution progress (0-100)
   */
  const getProgress = useCallback((): number => {
    const total = state.blockStates.size;
    if (total === 0) return 0;

    const completed = Array.from(state.blockStates.values()).filter(
      (s) => COMPLETED_BLOCK_STATUSES.includes(s.status as (typeof COMPLETED_BLOCK_STATUSES)[number])
    ).length;

    return Math.round((completed / total) * 100);
  }, [state.blockStates]);

  /**
   * Update edge execution state
   */
  const updateEdgeState = useCallback((
    edgeId: string,
    state: 'idle' | 'active' | 'success' | 'failure'
  ) => {
    setState(prev => {
      const newEdgeStates = new Map(prev.edgeStates);
      newEdgeStates.set(edgeId, state);
      return {
        ...prev,
        edgeStates: newEdgeStates,
      };
    });
  }, []);

  /**
   * Get elapsed time in seconds
   */
  const getElapsedTime = useCallback((): number => {
    if (!state.startTime) return 0;
    return (Date.now() - state.startTime) / 1000;
  }, [state.startTime]);

  return {
    state,
    startExecution,
    updateBlockState,
    startBlockExecution,
    completeBlockExecution,
    setCurrentBlock,
    completeExecution,
    resetExecution,
    updateEdgeState, // 🆕 New method for updating edge states
    getProgress,
    getElapsedTime,
  };
};

