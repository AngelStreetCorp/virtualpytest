/**
 * useTestCaseAI Hook
 * 
 * Handles AI-powered test case generation.
 * Follows Navigation architecture pattern with buildServerUrl + fetch directly.
 */

import { useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { TestCaseGraph } from '../../types/testcase/TestCase_Types';
import { getErrorMessage } from '../../utils/testcase/testCaseHelpers';

export const useTestCaseAI = () => {
  
  /**
   * Generate test case graph from AI prompt
   */
  const generateTestCaseFromPrompt = useCallback(async (
    prompt: string,
    userinterfaceName: string,
    deviceId: string,
    hostName: string
  ): Promise<{ 
    success: boolean; 
    graph?: TestCaseGraph;
    analysis?: string;
    needs_disambiguation?: boolean;
    ambiguities?: any[];
    available_nodes?: any[];
    error?: string;
    generation_stats?: {
      prompt_tokens?: number;
      completion_tokens?: number;
      block_counts?: {
        navigation: number;
        action: number;
        verification: number;
        other: number;
        total: number;
      };
    };
    execution_time?: number;
    message?: string;
  }> => {
    try {
      let result;
      try {
        result = await api.post(buildServerUrl('/server/ai/generatePlan'), {
          prompt,
          userinterface_name: userinterfaceName,
          device_id: deviceId,
          host_name: hostName
        });
      } catch (err: any) {
        return {
          success: false,
          error: err?.message || 'HTTP error',
        };
      }
      
      if (result.success) {
        // Backend now returns data directly (not wrapped in 'plan')
        
        // Check if needs disambiguation
        if (result.needs_disambiguation) {
          return {
            success: false,
            needs_disambiguation: true,
            ambiguities: result.ambiguities || [],
            available_nodes: result.available_nodes || [],
            error: 'Prompt needs disambiguation',
          };
        }
        
        // Check if not feasible
        if (result.feasible === false) {
          return {
            success: false,
            error: result.error || 'Task is not feasible with available navigation nodes',
          };
        }
        
        // Success - return graph with generation stats
        return {
          success: true,
          graph: result.graph,
          analysis: result.analysis,
          generation_stats: result.generation_stats,
          execution_time: result.execution_time,
          message: result.message,
        };
      } else {
        return {
          success: false,
          error: result.error || 'AI generation failed',
        };
      }
    } catch (error) {
      console.error('[useTestCaseAI] Error generating from prompt:', getErrorMessage(error));
      return {
        success: false,
        error: getErrorMessage(error),
      };
    }
  }, []);

  /**
   * Save disambiguation choices and regenerate
   */
  const saveDisambiguationAndRegenerate = useCallback(async (
    prompt: string,
    selections: Array<{ phrase: string; resolved: string }>,
    userinterfaceName: string,
    deviceId: string,
    hostName: string
  ): Promise<{ 
    success: boolean; 
    graph?: TestCaseGraph;
    analysis?: string;
    error?: string;
  }> => {
    try {
      // First, save disambiguation choices
      await api.post(buildServerUrl('/server/ai-disambiguation/saveDisambiguation'), {
        prompt,
        selections,
        userinterface_name: userinterfaceName,
        host_name: hostName
      });
      
      // Then regenerate with saved choices
      return await generateTestCaseFromPrompt(prompt, userinterfaceName, deviceId, hostName);
    } catch (error) {
      console.error('[useTestCaseAI] Error saving disambiguation:', getErrorMessage(error));
      return {
        success: false,
        error: getErrorMessage(error),
      };
    }
  }, [generateTestCaseFromPrompt]);

  return {
    generateTestCaseFromPrompt,
    saveDisambiguationAndRegenerate,
  };
};

