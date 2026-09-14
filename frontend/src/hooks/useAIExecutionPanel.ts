import { useState, useCallback } from 'react';
import { Host, Device } from '../types/common/Host_Types';
import { useToast } from './useToast';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import { waitForExecutionSocketEvent } from '../utils/executionSocketWait';

interface UseAIExecutionPanelProps {
  host: Host;
  device: Device;
  onDisambiguationDataChange?: (
    data: any,
    resolve: (selections: Record<string, string>, saveToDb: boolean) => void,
    cancel: () => void
  ) => void;
}

type ExecutionStatus = 'idle' | 'success' | 'fail';

interface UseAIExecutionPanelReturn {
  // Prompt state
  prompt: string;
  setPrompt: (prompt: string) => void;
  selectedUserinterface: string;
  setSelectedUserinterface: (ui: string) => void;

  // Result state
  graph: any;
  analysis: string;
  usedAI: boolean; // true = AI generated the plan (wait for Run), false = direct match (auto-run)
  actionLabel: string; // human-readable label of what we're doing (the prompt)
  isGenerating: boolean;

  // Execution state
  isExecuting: boolean;
  executionStatus: ExecutionStatus;

  // Actions
  handleSend: () => Promise<void>;
  handleExecute: () => Promise<void>;
  handleDisambiguationResolve: (selections: Record<string, string>, saveToDb: boolean) => Promise<void>;
}

export const useAIExecutionPanel = ({
  host,
  device,
  onDisambiguationDataChange,
}: Omit<UseAIExecutionPanelProps, 'isControlActive'>): UseAIExecutionPanelReturn => {
  // Prompt state
  const [prompt, setPromptState] = useState('');
  const [selectedUserinterface, setSelectedUserinterface] = useState<string>('');

  // Result state
  const [graph, setGraph] = useState<any>(null);
  const [analysis, setAnalysis] = useState<string>('');
  const [usedAI, setUsedAI] = useState(false);
  const [actionLabel, setActionLabel] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);

  // Execution state
  const [isExecuting, setIsExecuting] = useState(false);
  const [executionStatus, setExecutionStatus] = useState<ExecutionStatus>('idle');

  const { showError, showSuccess, showInfo } = useToast();

  // Reset the whole result lifecycle back to a clean prompt-entry state.
  const resetResult = useCallback(() => {
    setGraph(null);
    setAnalysis('');
    setUsedAI(false);
    setActionLabel('');
    setExecutionStatus('idle');
  }, []);

  // Editing the prompt clears any previous result/status so the panel returns to entry state.
  const setPrompt = useCallback(
    (value: string) => {
      setPromptState(value);
      resetResult();
    },
    [resetResult]
  );

  // Execute a graph (accepts an explicit graph so we can auto-run right after generation
  // without waiting for the `graph` state to flush).
  const executeGraph = useCallback(
    async (graphToRun: any, label: string) => {
      if (!graphToRun) return;

      setIsExecuting(true);
      setExecutionStatus('idle');

      try {
        const result = await api.post(buildServerUrl('/server/testcase/execute'), {
          device_id: device.device_id,
          host_name: host.host_name,
          userinterface_name: selectedUserinterface,
          graph_json: graphToRun,
          async_execution: true,
        });

        if (!result.success) {
          throw new Error(result.error || 'Execution failed');
        }

        showInfo(`Executing "${label}"…`);

        const socketEvent = await waitForExecutionSocketEvent(result.execution_id, ['testcase'], 600000);
        setIsExecuting(false);

        if (socketEvent.result?.success) {
          setExecutionStatus('success');
          showSuccess(`Done: "${label}"`);
        } else {
          setExecutionStatus('fail');
          showError(socketEvent.error || `Failed: "${label}"`);
        }
      } catch (error: any) {
        console.error('[@useAIExecutionPanel] Execution error:', error);
        setIsExecuting(false);
        setExecutionStatus('fail');
        showError(error.message || 'Execution failed');
      }
    },
    [device, host, selectedUserinterface, showError, showSuccess, showInfo]
  );

  // Send the prompt: generate a plan. If it's a direct match (no AI), auto-run it.
  const handleSend = useCallback(async () => {
    if (!prompt.trim() || !selectedUserinterface) return;

    const label = prompt.trim();
    setIsGenerating(true);
    resetResult();
    setActionLabel(label);

    try {
      const result = await api.post(buildServerUrl('/server/ai/generatePlan'), {
        prompt,
        userinterface_name: selectedUserinterface,
        device_id: device.device_id,
        host_name: host.host_name,
      });

      // Disambiguation needed → hand off to the modal.
      if (result.needs_disambiguation) {
        if (onDisambiguationDataChange) {
          onDisambiguationDataChange(
            result,
            (selections, saveToDb) => {
              handleDisambiguationResolve(selections, saveToDb);
            },
            () => setIsGenerating(false)
          );
        } else {
          showError('Disambiguation needed but no handler available');
        }
        setIsGenerating(false);
        return;
      }

      if (!result.success) {
        throw new Error(result.error || 'Could not understand the request');
      }

      const aiWasUsed = !result.exact_match;
      setGraph(result.graph);
      setAnalysis(result.analysis || '');
      setUsedAI(aiWasUsed);
      setIsGenerating(false);

      // Direct match → run immediately. AI plan → wait for the user to click Run.
      if (!aiWasUsed) {
        executeGraph(result.graph, label);
      }
    } catch (error: any) {
      console.error('[@useAIExecutionPanel] Send error:', error);
      showError(error.message || 'Failed to process prompt');
      setIsGenerating(false);
    }
  }, [
    prompt,
    selectedUserinterface,
    device,
    host,
    showError,
    onDisambiguationDataChange,
    resetResult,
    executeGraph,
  ]);

  // Run the currently generated plan (AI path — user-triggered).
  const handleExecute = useCallback(async () => {
    if (!graph) return;
    await executeGraph(graph, actionLabel || prompt.trim());
  }, [graph, actionLabel, prompt, executeGraph]);

  // Re-generate after the user resolves disambiguation.
  const handleDisambiguationResolve = useCallback(
    async (selections: Record<string, string>, saveToDb: boolean) => {
      setIsGenerating(true);

      try {
        if (saveToDb) {
          await api.post(buildServerUrl('/server/ai/saveDisambiguationAndRegenerate'), {
            prompt,
            userinterface_name: selectedUserinterface,
            device_id: device.device_id,
            host_name: host.host_name,
            selections,
          });
        }

        await handleSend();
      } catch (error) {
        console.error('[@useAIExecutionPanel] Disambiguation resolve error:', error);
        showError('Failed to apply disambiguation');
        setIsGenerating(false);
      }
    },
    [prompt, selectedUserinterface, device, host, handleSend, showError]
  );

  return {
    prompt,
    setPrompt,
    selectedUserinterface,
    setSelectedUserinterface,

    graph,
    analysis,
    usedAI,
    actionLabel,
    isGenerating,

    isExecuting,
    executionStatus,

    handleSend,
    handleExecute,
    handleDisambiguationResolve,
  };
};
