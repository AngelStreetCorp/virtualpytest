/**
 * useTestCaseExecution Hook
 * 
 * Handles test case execution operations with async socket completion support.
 * Follows Navigation architecture pattern with buildServerUrl + fetch directly.
 */

import { useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { getErrorMessage } from '../../utils/testcase/testCaseHelpers';
import { waitForExecutionSocketEvent } from '../../utils/executionSocketWait';

export interface TestCaseExecutionResult {
  success: boolean;
  result_type?: 'success' | 'failure' | 'error';
  execution_time_ms: number;
  step_count: number;
  script_result_id: string;
  error?: string;
  step_results?: any[];
  report_url?: string;  // 🆕 Report URL from R2
  logs_url?: string;    // 🆕 Logs URL from R2
}

export interface TestCaseExecutionResponse {
  success: boolean;
  execution_id?: string;  // For async execution
  result_type?: 'success' | 'failure' | 'error';
  execution_time_ms?: number;
  step_count?: number;
  script_result_id?: string;
  error?: string;
  step_results?: any[];
  message?: string;
  report_url?: string;  // 🆕 Report URL from R2
  logs_url?: string;    // 🆕 Logs URL from R2
  script_outputs?: Record<string, any>;  // Script output values
  block_outputs?: Record<string, any>;   // Block output values
}

export interface ExecutionStatus {
  execution_id: string;
  status: 'running' | 'completed' | 'failed';
  current_block_id: string | null;
  block_states: {
    [blockId: string]: {
      status: 'success' | 'failure';
      duration: number;
      error?: string;
      message?: string;
    };
  };
  result: TestCaseExecutionResult | null;
  error: string | null;
  elapsed_time_ms: number;
  variables?: Record<string, any>;  // 🆕 NEW: Runtime variable values
  metadata?: Record<string, any>;   // 🆕 NEW: Runtime metadata values
}

export const useTestCaseExecution = () => {
  /**
   * Execute a test case directly from graph with async execution updates
   */
  const executeTestCase = useCallback(async (
    graph: any,  // TestCaseGraph — {variable} placeholders are resolved SERVER-SIDE
                 // from graph.scriptConfig.inputs[].value/default (stamp values with
                 // stampInputValues before calling for a parameterized run)
    deviceId: string,
    hostName: string,
    userinterfaceName?: string,
    testcaseName?: string,
    executionMetadata?: Record<string, any>,
    onProgress?: (status: ExecutionStatus) => void  // Real-time progress callback
  ): Promise<TestCaseExecutionResponse> => {
    try {
      // Step 1: Start async execution
      const startData = await api.post(buildServerUrl(`/server/testcase/execute`), {
        graph_json: graph,
        device_id: deviceId,
        host_name: hostName,
        userinterface_name: userinterfaceName || '',
        testcase_name: testcaseName || 'unsaved_testcase',  // 🆕 NEW: Send test case name
        execution_metadata: executionMetadata || {},
        async_execution: true  // Always use async to prevent timeouts
      });
      
      if (!startData.success) {
        throw new Error(startData.error || 'Failed to start execution');
      }
      
      const executionId = startData.execution_id;
      
      if (!executionId) {
        throw new Error('No execution_id returned');
      }
      
      console.log(`[useTestCaseExecution] Started async execution: ${executionId}`);
      
      // Step 2: Wait for completion via socket event stream
      return await pollExecutionStatus(executionId, onProgress);
      
    } catch (error) {
      console.error('[useTestCaseExecution] Error executing test case:', getErrorMessage(error));
      return {
        success: false,
        error: getErrorMessage(error),
      };
    }
  }, []);

  /**
   * Wait execution completion from socket updates (no polling)
   */
  const pollExecutionStatus = async (
    executionId: string,
    onProgress?: (status: ExecutionStatus) => void
  ): Promise<TestCaseExecutionResponse> => {
    if (onProgress) {
      onProgress({
        execution_id: executionId,
        status: 'running',
        current_block_id: null,
        block_states: {},
        result: null,
        error: null,
        elapsed_time_ms: 0,
      });
    }
    const event = await waitForExecutionSocketEvent(executionId, ['testcase'], 600000);
    const result = event.result;
    if (!result) {
      return { success: false, error: event.error || 'Execution failed' };
    }
    return {
      success: result.success,
      result_type: result.result_type,
      execution_time_ms: result.execution_time_ms,
      step_count: result.step_count,
      script_result_id: result.script_result_id,
      error: result.error,
      step_results: result.step_results,
      report_url: result.report_url,
      logs_url: result.logs_url,
    };
  };

  /**
   * Get execution history for a test case
   */
  const getTestCaseHistory = useCallback(async (testcaseId: string): Promise<{ success: boolean; history: any[] }> => {
    try {
      return await api.get(buildServerUrl(`/server/testcase/${testcaseId}/history`));
    } catch (error) {
      console.error('[useTestCaseExecution] Error getting history:', error);
      return { success: false, history: [] };
    }
  }, []);

  return {
    executeTestCase,
    getTestCaseHistory,
  };
};
