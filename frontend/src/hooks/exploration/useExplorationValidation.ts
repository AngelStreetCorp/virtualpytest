/**
 * AI Exploration Validation Hook
 * 
 * Centralized hook for managing AI exploration edge validation logic.
 * Separates business logic from UI components.
 */

import { useState, useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

export interface ValidationResult {
  step: number;
  itemName: string;
  sourceNode: string;
  targetNode: string;
  forward: {
    action: string;
    result: 'success' | 'failure';
    message?: string;
  };
  backward: {
    action: string;
    result: 'success' | 'warning' | 'skipped' | 'failure';
    message?: string;
  };
}

export interface ExplorationValidationState {
  isValidating: boolean;
  isComplete: boolean;
  progress: { current: number; total: number };
  results: ValidationResult[];
  currentStep: string;
  error: string | null;
}

export interface UseExplorationValidationProps {
  explorationId: string;
  explorationHostName: string;
  treeId: string;
  selectedDeviceId: string;
}

export const useExplorationValidation = ({
  explorationId,
  explorationHostName,
  treeId,
  selectedDeviceId
}: UseExplorationValidationProps) => {
  const [state, setState] = useState<ExplorationValidationState>({
    isValidating: false,
    isComplete: false,
    progress: { current: 0, total: 0 },
    results: [],
    currentStep: '',
    error: null
  });

  /**
   * Start validation process
   */
  const startValidation = useCallback(async () => {
    console.log('[@useExplorationValidation] Starting validation');
    console.log('  Exploration ID:', explorationId);
    console.log('  Device ID:', selectedDeviceId);
    console.log('  Host:', explorationHostName);

    try {
      const data = await api.post(buildServerUrl(`/server/ai-generation/start-validation`), {
        exploration_id: explorationId,
        host_name: explorationHostName,
        tree_id: treeId,
        device_id: selectedDeviceId
      });
      
      // ✅ PROPER ERROR HANDLING: Check data.success, not just response.ok
      if (!data.success) {
        const errorMsg = data.error || 'Failed to start validation';
        console.error('[@useExplorationValidation] Start validation failed:', errorMsg);
        console.error('  Full response:', data);
        
        setState(prev => ({
          ...prev,
          error: errorMsg,
          isValidating: false
        }));
        
        return { success: false, error: errorMsg };
      }

      console.log('[@useExplorationValidation] Validation started successfully');
      console.log('  Total items:', data.total_items);

      setState(prev => ({
        ...prev,
        isValidating: true,
        error: null,
        progress: { current: 0, total: data.total_items || 0 }
      }));

      return { success: true, total_items: data.total_items };

    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useExplorationValidation] Exception starting validation:', err);
      console.error('  Error details:', errorMsg);
      
      setState(prev => ({
        ...prev,
        error: errorMsg,
        isValidating: false
      }));
      
      return { success: false, error: errorMsg };
    }
  }, [explorationId, explorationHostName, treeId, selectedDeviceId]);

  /**
   * Validate next item
   */
  const validateNextItem = useCallback(async (): Promise<{ success: boolean; has_more_items: boolean; error?: string }> => {
    console.log('[@useExplorationValidation] Validating next item...');

    try {
      setState(prev => ({
        ...prev,
        currentStep: ''
      }));

      const data = await api.post(buildServerUrl(`/server/ai-generation/validate-next-item`), {
        exploration_id: explorationId,
        host_name: explorationHostName,
        device_id: selectedDeviceId
      });
      
      // ✅ PROPER ERROR HANDLING
      if (!data.success) {
        const errorMsg = data.error || 'Failed to validate item';
        console.error('[@useExplorationValidation] Validate item failed:', errorMsg);
        console.error('  Full response:', data);
        
        setState(prev => ({
          ...prev,
          error: errorMsg,
          isValidating: false
        }));
        
        return { success: false, has_more_items: false, error: errorMsg };
      }

      // Update progress
      if (data.progress) {
        setState(prev => ({
          ...prev,
          progress: {
            current: data.progress.current_item,
            total: data.progress.total_items
          }
        }));
      }

      // Update current step
      setState(prev => ({
        ...prev,
        currentStep: data.item || ''
      }));

      // Add result(s)
        const formatAction = (actionSet: any) => {
          if (!actionSet) return '';
          return actionSet.action || '';
        };

      // ✅ TV DUAL-LAYER: Handle edges array (horizontal + vertical)
      if (data.edges && Array.isArray(data.edges)) {
        console.log('[@useExplorationValidation] Processing TV dual-layer edges:', data.edges.length);
        
        const newResults: ValidationResult[] = [];
        const baseStep = data.progress?.current_item || state.results.length + 1;
        
        // Edge 1: Horizontal (only show forward - RIGHT)
        const horizontalEdge = data.edges.find((e: any) => e.edge_type === 'horizontal');
        if (horizontalEdge) {
          newResults.push({
            step: baseStep,
            itemName: data.item,
            sourceNode: horizontalEdge.action_sets.forward?.source || 'home',
            targetNode: horizontalEdge.action_sets.forward?.target || '',
            forward: {
              action: formatAction(horizontalEdge.action_sets.forward),
              result: horizontalEdge.action_sets.forward?.result === 'success' ? 'success' : 'failure'
            },
            backward: {
              action: formatAction(horizontalEdge.action_sets.reverse),
              result: horizontalEdge.action_sets.reverse?.result === 'success' ? 'success' : 'failure'
            }
          });
        }
        
        // Edge 2: Vertical - forward (OK) 
        const verticalEdge = data.edges.find((e: any) => e.edge_type === 'vertical');
        if (verticalEdge) {
          newResults.push({
            step: baseStep,
            itemName: data.item,
            sourceNode: verticalEdge.action_sets.forward?.source || '',
            targetNode: verticalEdge.action_sets.forward?.target || '',
            forward: {
              action: formatAction(verticalEdge.action_sets.forward),
              result: verticalEdge.action_sets.forward?.result === 'success' ? 'success' : 'failure'
            },
            backward: {
              action: formatAction(verticalEdge.action_sets.reverse),
              result: verticalEdge.action_sets.reverse?.result === 'success' ? 'success' : 'failure'
            }
          });
        }
        
        setState(prev => ({
          ...prev,
          results: [...prev.results, ...newResults]
        }));
        
        console.log('[@useExplorationValidation] Added', newResults.length, 'TV edge results');
      }
      // ✅ MOBILE/WEB: Single action_sets
      else if (data.action_sets) {
        const result: ValidationResult = {
          step: data.progress?.current_item || state.results.length + 1,
          itemName: data.item,
          sourceNode: data.action_sets.forward?.source || 'home',
          targetNode: data.action_sets.forward?.target || data.node_name || '',
          forward: {
            action: formatAction(data.action_sets.forward),
            result: data.click_result === 'success' ? 'success' : 'failure',
            message: data.click_result === 'failed' ? 'Click failed' : undefined
          },
          backward: {
            action: formatAction(data.action_sets.reverse),
            result: data.back_result === 'success' ? 'success' :
              data.back_result === 'warning' ? 'warning' :
                data.back_result === 'skipped' ? 'skipped' : 'failure',
            message: data.back_result !== 'success' ? data.back_result : undefined
          }
        };

        setState(prev => ({
          ...prev,
          results: [...prev.results, result]
        }));

        console.log('[@useExplorationValidation] Item validated:', data.item);
        console.log('  Forward result:', data.click_result);
        console.log('  Backward result:', data.back_result);
      }

      // Check if done
      if (!data.has_more_items) {
        console.log('[@useExplorationValidation] ✅ Validation complete!');
        
        setState(prev => ({
          ...prev,
          isValidating: false,
          isComplete: true,
          progress: {
            ...prev.progress,
            current: prev.progress.total
          }
        }));
        
        return { success: true, has_more_items: false };
      }

      return { success: true, has_more_items: true };

    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useExplorationValidation] Exception validating item:', err);
      console.error('  Error details:', errorMsg);
      
      setState(prev => ({
        ...prev,
        error: errorMsg,
        isValidating: false
      }));
      
      return { success: false, has_more_items: false, error: errorMsg };
    }
  }, [explorationId, explorationHostName, selectedDeviceId, state.results.length]);

  /**
   * Reset validation state
   */
  const resetValidation = useCallback(() => {
    console.log('[@useExplorationValidation] Resetting validation state');
    
    setState({
      isValidating: false,
      isComplete: false,
      progress: { current: 0, total: 0 },
      results: [],
      currentStep: '',
      error: null
    });
  }, []);

  return {
    // State
    isValidating: state.isValidating,
    isComplete: state.isComplete,
    progress: state.progress,
    results: state.results,
    currentStep: state.currentStep,
    error: state.error,

    // Actions
    startValidation,
    validateNextItem,
    resetValidation
  };
};

