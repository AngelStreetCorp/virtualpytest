import { useState, useCallback, useMemo, useRef } from 'react';
import { Host, Device } from '../types/common/Host_Types';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import { useToast } from './useToast';
import { 
  AIPlan, 
  AIExecutionStatus, 
  AIExecutionSummary,
  AIErrorType,
  AI_CONSTANTS 
} from '../types/aiagent/AIAgent_Types';
import type { DisambiguationData } from '../types/aiagent/AIDisambiguation_Types';

interface UseAIProps {
  host: Host;
  device: Device;
  mode: 'real-time' | 'test-case';
}

export const useAI = ({ host, device, mode: _mode }: UseAIProps) => {
  const [isExecuting, setIsExecuting] = useState(false);
  const [currentPlan, setCurrentPlan] = useState<AIPlan | null>(null);
  const [executionStatus, setExecutionStatus] = useState<AIExecutionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [taskResult, setTaskResult] = useState<{ success: boolean; message: string } | null>(null);
  
  // Disambiguation state (NEW)
  const [disambiguationData, setDisambiguationData] = useState<DisambiguationData | null>(null);
  const pendingExecution = useRef<{
    userinterface_name: string;
    useCache: boolean;
  } | null>(null);
  
  // Toast notifications
  const toast = useToast();
  
  // Track completion toast to prevent duplicates
  const completionToastShown = useRef(false);
  
  // Track polling state to prevent duplicate toasts
  const pollCount = useRef(0);
  const lastStepToastShown = useRef<string | null>(null);
  
  // Track unique toasts to prevent duplicates across execution
  const shownToasts = useRef<Set<string>>(new Set());

  // Helper function to enhance error messages for specific error types
  const enhanceErrorMessage = useCallback((error: string, errorType?: AIErrorType) => {
    // Handle specific error types from backend
    if (errorType) {
      switch (errorType) {
        case 'ai_timeout':
          return '⏱️ AI service timed out. The request took too long to process. Please try again.';
        case 'ai_connection_error':
          return '🌐 Connection to AI service failed. Please check your internet connection and try again.';
        case 'ai_auth_error':
          return '🔑 AI service authentication failed. Please contact support if this persists.';
        case 'ai_rate_limit':
          return '🚦 AI service rate limit exceeded. Please wait a moment and try again.';
        case 'ai_call_exception':
          return '⚠️ Unexpected AI service error. Please try again or contact support.';
        case 'ai_call_failed':
          return '❌ AI service call failed. Please try again.';
        case 'navigation_error':
          return '🧭 Navigation error occurred. Please try again.';
        case 'network_error':
          return '🌐 Network connection issue. Please check your connection and try again.';
      }
    }
    
    // Legacy error message enhancement (keep for backward compatibility)
    if (error.includes('429') || error.includes('rate limit')) {
      return '🤖 AI service is temporarily busy. Please wait a moment and try again.';
    }
    if (error.includes('timeout')) {
      return '⏱️ AI service timed out. Please try again.';
    }
    if (error.includes('connection') || error.includes('network')) {
      return '🌐 Network connection issue. Please check your connection and try again.';
    }
    if (error.includes('API key') || error.includes('authentication')) {
      return '🔑 Authentication issue with AI service. Please contact support.';
    }
    if (error.includes('No path found to')) {
      const nodeMatch = error.match(/No path found to '([^']+)'/);
      const nodeName = nodeMatch ? nodeMatch[1] : 'target location';
      return `🧭 Cannot navigate to "${nodeName}" - screen not found in navigation tree.`;
    }
    
    return error; // Return original error for other cases
  }, []);

  // Execution summary calculation (like old useAIAgent)
  const executionSummary = useMemo((): AIExecutionSummary | null => {
    if (!currentPlan?.steps || !executionStatus?.execution_log) return null;

    const executionLog = executionStatus.execution_log;
    const completedSteps = executionLog.filter(entry => entry.action_type === 'step_success');
    const failedSteps = executionLog.filter(entry => entry.action_type === 'step_failed');
    const taskCompleted = executionLog.some(entry => entry.action_type === 'task_completed');
    const taskFailed = executionLog.some(entry => entry.action_type === 'task_failed');

    if (!taskCompleted && !taskFailed && !isExecuting) return null;

    // Calculate total duration and average step duration
    const stepDurations = executionLog
      .filter(entry => entry.action_type === 'step_success' || entry.action_type === 'step_failed')
      .map(entry => entry.data?.duration || 0);
    
    const totalDuration = executionLog.find(entry => 
      entry.action_type === 'task_completed' || entry.action_type === 'task_failed'
    )?.data?.duration || (executionStatus.execution_summary?.total_duration || 0);

    const averageStepDuration = stepDurations.length > 0 
      ? stepDurations.reduce((sum, duration) => sum + duration, 0) / stepDurations.length 
      : 0;

    const success = taskCompleted && failedSteps.length === 0;
    
    return {
      totalSteps: currentPlan.steps.length,
      completedSteps: completedSteps.length,
      failedSteps: failedSteps.length,
      totalDuration,
      averageStepDuration,
      success,
      message: success 
        ? `All ${completedSteps.length} steps completed successfully`
        : `${completedSteps.length}/${currentPlan.steps.length} steps completed, ${failedSteps.length} failed`
    };
  }, [executionStatus?.execution_log, currentPlan?.steps, isExecuting]);

  // Process plan steps with execution status for UI display
  const processedSteps = useMemo(() => {
    // Return empty array if no plan
    if (!currentPlan?.steps) {
      return [];
    }

    // If no execution log yet, return plan steps with pending status
    if (!executionStatus?.execution_log) {
      return currentPlan.steps.map((step: any, index: number) => ({
        ...step,
        stepNumber: parseInt(step.step) || index + 1,
        status: 'pending' as const,
        completedEntry: null,
        failedEntry: null,
        isCurrent: false,
        duration: undefined
      }));
    }

    const executionLog = executionStatus.execution_log;
    const currentStepText = executionStatus?.current_step || '';

    const processed = currentPlan.steps.map((step: any, index: number) => {
      const stepNumber = parseInt(step.step) || index + 1;
      const completedEntry = executionLog.find(entry => 
        entry.action_type === 'step_success' && entry.data?.step === stepNumber
      );
      const failedEntry = executionLog.find(entry => 
        entry.action_type === 'step_failed' && entry.data?.step === stepNumber
      );
      const isCurrent = currentStepText && currentStepText.includes(`Step ${stepNumber}`);
      
      let status: 'pending' | 'current' | 'completed' | 'failed';
      if (completedEntry) status = 'completed';
      else if (failedEntry) status = 'failed';
      else if (isCurrent) status = 'current';
      else status = 'pending';

      // Merge transitions from execution results (if available)
      const stepResult = executionStatus?.step_results?.find((r: any) => r.step_id === stepNumber);
      const transitions = stepResult?.transitions || step.transitions; // Prefer execution result, fallback to plan
      
      // Extract duration from execution log
      const duration = completedEntry?.data?.duration || failedEntry?.data?.duration;

      return {
        ...step,
        stepNumber,
        status,
        completedEntry,
        failedEntry,
        isCurrent,
        duration,
        transitions  // Include transitions from execution or plan
      };
    });
    
    return processed;
  }, [currentPlan?.steps, executionStatus?.execution_log, executionStatus?.current_step, isExecuting]);

  const analyzeCompatibility = useCallback(async (prompt: string) => {
    try {
      const result = await api.post(buildServerUrl('/server/ai/analyzeCompatibility'), {
        prompt,
        host_name: host.host_name,
        device_id: device.device_id
      });
      if (result.error) throw new Error(result.error);
      
      return result;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Analysis failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, [host.host_name, device.device_id]);

  const generatePlan = useCallback(async (prompt: string, userinterface_name: string) => {
    try {
      const result = await api.post(buildServerUrl('/server/ai/generatePlan'), {
        prompt,
        userinterface_name,
        host_name: host.host_name,
        device_id: device.device_id
      });
      if (result.error) throw new Error(result.error);
      
      setCurrentPlan(result.plan);
      return result.plan;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Plan generation failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, [host.host_name, device.device_id]);

  /**
   * Execute an AI task with optional plan caching
   * 
   * @param prompt - The task description
   * @param userinterface_name - The UI context
   * @param useCache - Whether to use cached AI plans for similar tasks. 
   *                   When false, always generates fresh plans but successful plans are still stored.
   *                   When true, attempts to reuse compatible cached plans.
   * @param skipAnalysis - Whether to skip pre-analysis (used after disambiguation)
   */
  const executeTask = useCallback(async (
    prompt: string, 
    userinterface_name: string, 
    useCache: boolean = false,
    skipAnalysis: boolean = false
  ) => {
    if (isExecuting) return;

    // Clear previous state
    setCurrentPlan(null);
    setExecutionStatus(null);
    setError(null);
    setTaskResult(null);
    completionToastShown.current = false;
    
    // Reset polling counters and toast tracking for new task
    pollCount.current = 0;
    lastStepToastShown.current = null;
    shownToasts.current.clear();

    setIsExecuting(true);

    try {
      // UNIFIED FLOW: One route handles everything
      if (!skipAnalysis) {
        // Validation/disambiguation handled by backend
      }

      // Execute task (backend handles validation, disambiguation, generation, execution)
      toast.showInfo(`🤖 Starting AI task`, { duration: AI_CONSTANTS.TOAST_DURATION.INFO });

      const result = await api.post(buildServerUrl('/server/testcase/execute-from-prompt'), {
        prompt,
        userinterface_name,
        device_id: device.device_id,
        host_name: host.host_name,
        use_cache: useCache,
        async_execution: true,
        save: false,  // Live AI Modal does NOT save
        skip_validation: skipAnalysis  // Skip if already validated after disambiguation
      });
      
      // Handle disambiguation response from unified route
      if (result.needs_disambiguation) {
        setIsExecuting(false);
        setDisambiguationData({
          ...result.analysis,
          available_nodes: result.available_nodes || []
        });
        pendingExecution.current = { userinterface_name, useCache };
        return; // Pause execution until user resolves
      }
      
      if (result.error) throw new Error(result.error);

      const executionId = result.execution_id;

      // Poll for status with rich updates
      const pollStatus = async () => {
        let previousLogLength = 0;
        let notFoundCount = 0;
        const maxNotFoundAttempts = 10; // Stop after 10 consecutive "not found" errors
        const startTime = Date.now();
        const maxPollTime = AI_CONSTANTS.MAX_WAIT_TIME; // 5 minutes
        
        while (true) {
          pollCount.current += 1;
          
          // FAIL-FAST: Stop polling after max wait time
          const elapsedTime = Date.now() - startTime;
          if (elapsedTime > maxPollTime) {
            setIsExecuting(false);
            setError('Execution timeout - stopped polling after 5 minutes');
            toast.showError(`⏱️ AI execution timeout - stopped polling after ${Math.round(maxPollTime/1000)}s`, { 
              duration: AI_CONSTANTS.TOAST_DURATION.ERROR 
            });
            break;
          }
          
          // Minimal polling feedback - only on first poll
          if (pollCount.current === 1) {
            toast.showInfo(`🔄 Monitoring AI execution...`, { 
              duration: AI_CONSTANTS.TOAST_DURATION.INFO 
            });
          }
          
          const status = await api.post(buildServerUrl(`/server/ai/getStatus`), {
            execution_id: executionId,
            device_id: device.device_id,
            host_name: host.host_name
          });

          // FAIL-FAST: If execution not found repeatedly, stop polling
          if (!status.success && status.error && status.error.includes('not found')) {
            notFoundCount++;
            if (notFoundCount >= maxNotFoundAttempts) {
              setIsExecuting(false);
              setError(`Execution not found after ${maxNotFoundAttempts} attempts - execution may have failed to start`);
              toast.showError(`❌ Execution not found - stopped polling`, { 
                duration: AI_CONSTANTS.TOAST_DURATION.ERROR 
              });
              break;
            }
            await new Promise(resolve => setTimeout(resolve, AI_CONSTANTS.POLL_INTERVAL));
            continue;
          }
          
          // Reset not found counter if we got a valid response
          notFoundCount = 0;

          setExecutionStatus(status);

          // DEBUG: Log the status response to see what we're getting
          console.log('[@useAI] Status response received:', {
            has_plan: !!status.plan,
            plan_keys: status.plan ? Object.keys(status.plan) : [],
            has_analysis: status.plan?.analysis ? true : false,
            analysis_preview: status.plan?.analysis?.substring(0, 50),
            execution_log_length: status.execution_log?.length || 0
          });

          // Extract and set plan if available from status.plan
          // Plan will be null while generating, then set once AI responds
          if (status.plan && status.plan !== null) {
            const shouldUpdate = !currentPlan || 
                                (currentPlan.steps?.length || 0) < (status.plan.steps?.length || 0) ||
                                currentPlan.analysis !== status.plan.analysis;
            
            if (shouldUpdate) {
              console.log('[@useAI] Setting/updating plan from status.plan:', {
                id: status.plan.id,
                has_analysis: !!status.plan.analysis,
                has_steps: !!status.plan.steps,
                steps_count: status.plan.steps?.length || 0,
                feasible: status.plan.feasible,
                was_update: !!currentPlan
              });
              setCurrentPlan(status.plan);
              
              // Show toast when plan is generated (has steps)
              if (status.plan.steps && status.plan.steps.length > 0) {
                const planToastKey = `plan-generated-${status.plan.id || 'unknown'}`;
                if (!shownToasts.current.has(planToastKey)) {
                  shownToasts.current.add(planToastKey);
                  toast.showSuccess(`📋 AI plan generated with ${status.plan.steps.length} steps`, { 
                    duration: AI_CONSTANTS.TOAST_DURATION.INFO 
                  });
                }
              }
            }
          }

          // Fallback: Extract plan from execution_log (legacy compatibility)
          if (!currentPlan && status.execution_log) {
            const planEntry = status.execution_log.find((entry: any) => 
              entry.action_type === 'plan_generated'
            );
            if (planEntry && planEntry.value) {
              setCurrentPlan(planEntry.value);
              const planToastKey = `plan-generated-${planEntry.value.id || 'legacy'}`;
              if (!shownToasts.current.has(planToastKey)) {
                shownToasts.current.add(planToastKey);
                toast.showSuccess(`📋 AI plan generated with ${planEntry.value.steps?.length || 0} steps`, { 
                  duration: AI_CONSTANTS.TOAST_DURATION.INFO 
                });
              }
            }
          }

          // Track new log entries for state updates (no toasts here - handled by components)
          if (status.execution_log && status.execution_log.length > previousLogLength) {
            previousLogLength = status.execution_log.length;
          }

          if (!status.is_executing) {
            setIsExecuting(false);
            
            // Extract task result from execution log
            const completionEntry = status.execution_log?.find((entry: any) => 
              entry.action_type === 'task_completed' || entry.action_type === 'task_failed'
            );

            if (completionEntry) {
              const success = completionEntry.action_type === 'task_completed';
              const taskData = completionEntry.data || completionEntry.value;
              const duration = taskData?.duration || 0;
              
              setTaskResult({ 
                success, 
                message: success ? 'Task Completed' : 'Task Failed' 
              });

              // Show completion toast with duration (unique per execution)
              const completionToastKey = `task-${success ? 'completed' : 'failed'}-${executionId}`;
              if (!shownToasts.current.has(completionToastKey)) {
                shownToasts.current.add(completionToastKey);
                completionToastShown.current = true;
                if (success) {
                  toast.showSuccess(`🎉 Task completed in ${duration.toFixed(1)}s`, { 
                    duration: AI_CONSTANTS.TOAST_DURATION.SUCCESS 
                  });
                } else {
                  toast.showError(`⚠️ Task failed in ${duration.toFixed(1)}s`, { 
                    duration: AI_CONSTANTS.TOAST_DURATION.ERROR 
                  });
                }
              }
            } else {
              // Fallback completion toast (unique per execution)
              const fallbackToastKey = `task-fallback-${executionId}`;
              if (!shownToasts.current.has(fallbackToastKey)) {
                shownToasts.current.add(fallbackToastKey);
                completionToastShown.current = true;
                const success = status.success !== false;
                if (success) {
                  toast.showSuccess(`🎉 Task completed successfully`, { 
                    duration: AI_CONSTANTS.TOAST_DURATION.SUCCESS 
                  });
                } else {
                  toast.showError(`⚠️ Task failed`, { 
                    duration: AI_CONSTANTS.TOAST_DURATION.ERROR 
                  });
                }
              }
            }
            break;
          }

          await new Promise(resolve => setTimeout(resolve, AI_CONSTANTS.POLL_INTERVAL));
        }
      };

      pollStatus();

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Execution failed';
      const enhancedError = enhanceErrorMessage(errorMessage);
      setError(enhancedError);
      setIsExecuting(false);
      toast.showError(`❌ AI task failed: ${enhancedError}`, { 
        duration: AI_CONSTANTS.TOAST_DURATION.ERROR 
      });
    }
  }, [host, device, isExecuting, currentPlan, toast, enhanceErrorMessage]);

  const executeTestCase = useCallback(async (testCaseId: string) => {
    try {
      const result = await api.post(buildServerUrl('/server/ai-testcase/execute'), {
        test_case_id: testCaseId,
        device_id: device.device_id,
        host_name: host.host_name
      });
      if (result.error) throw new Error(result.error);
      
      return result;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Test case execution failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, [host, device]);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  // Disambiguation handlers
  const handleDisambiguationResolve = useCallback(async (
    selections: Record<string, string>,
    saveToDb: boolean
  ) => {
    const pending = pendingExecution.current;
    if (!pending) return;

    // Save to database if requested
    if (saveToDb && Object.keys(selections).length > 0) {
      try {
        const selectionsArray = Object.entries(selections).map(([phrase, resolved]) => ({
          phrase,
          resolved
        }));

        await api.post(buildServerUrl('/server/ai/saveDisambiguation'), {
          host_name: host.host_name,
          userinterface_name: pending.userinterface_name,
          selections: selectionsArray
        });

        toast.showSuccess(`🎓 Saved ${selectionsArray.length} preference(s)`, { duration: 3000 });
      } catch (err) {
        console.error('[@useAI] Failed to save disambiguation:', err);
      }
    }

    // Clear modal
    setDisambiguationData(null);

    // Build resolved prompt by replacing phrases
    let resolvedPrompt = disambiguationData?.original_prompt || '';
    Object.entries(selections).forEach(([phrase, resolved]) => {
      resolvedPrompt = resolvedPrompt.replace(new RegExp(phrase, 'gi'), resolved);
    });

    // Clear pending execution
    pendingExecution.current = null;

    // Re-execute with resolved prompt (skip analysis since we already resolved it)
    executeTask(resolvedPrompt, pending.userinterface_name, pending.useCache, true);
  }, [disambiguationData, executeTask, toast]);

  const handleDisambiguationCancel = useCallback(() => {
    setDisambiguationData(null);
    pendingExecution.current = null;
  }, []);

  return {
    // State
    isExecuting,
    currentPlan,
    executionStatus,
    error,
    taskResult,
    executionSummary,

    // Disambiguation state (NEW)
    disambiguationData,
    handleDisambiguationResolve,
    handleDisambiguationCancel,

    // Computed values for backward compatibility
    executionLog: executionStatus?.execution_log || [],
    currentStep: executionStatus?.current_step || '',
    progressPercentage: executionStatus?.progress_percentage || 0,
    isPlanFeasible: currentPlan?.feasible !== false,

    // Processed data for UI components
    processedSteps,

    // Actions
    analyzeCompatibility,
    generatePlan,
    executeTask,
    executeTestCase,
    clearError
  };
};
