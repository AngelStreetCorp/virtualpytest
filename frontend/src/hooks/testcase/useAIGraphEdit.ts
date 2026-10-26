/**
 * useAIGraphEdit — change an open step-list graph by prompt (TASK-36 §3).
 *
 * Shared by the Test Builder (AI tab, "Edit open graph") and the QuickTest Builder. It posts
 * the open graph to /server/ai/generatePlan as `current_graph`; the host's AI builder writes
 * it as a step list, the LLM returns the edited list (usage `text.plan`), and the result
 * comes back as a proposal. Nothing changes until the caller applies it.
 */

import { useCallback, useState } from 'react';
import { api } from '../../utils/apiClient';
import { TestCaseGraph } from '../../types/testcase/TestCase_Types';
import { useHostScopedUrl } from '../allServer/useRowServerUrl';

export interface AIGraphEditProposal {
  graph: TestCaseGraph;
  analysis: string;
  /** The open graph as step lines, and the edited graph as step lines. */
  stepsBefore: string[];
  stepsAfter: string[];
}

/** What the Test Builder's AI tab needs to run an edit ("New graph" / "Edit open graph"). */
export interface AIEditControls {
  mode: 'new' | 'edit';
  setMode: (mode: 'new' | 'edit') => void;
  isEditing: boolean;
  proposal: AIGraphEditProposal | null;
  error: string | null;
  propose: () => void;
  apply: () => void;
  cancel: () => void;
}

interface UseAIGraphEditArgs {
  hostName?: string;
  deviceId?: string | null;
  userinterfaceName?: string;
}

export const useAIGraphEdit = ({ hostName, deviceId, userinterfaceName }: UseAIGraphEditArgs) => {
  const hostScopedUrl = useHostScopedUrl();
  const [isEditing, setIsEditing] = useState(false);
  const [proposal, setProposal] = useState<AIGraphEditProposal | null>(null);
  const [error, setError] = useState<string | null>(null);

  const proposeEdit = useCallback(
    async (prompt: string, graph: TestCaseGraph) => {
      if (!prompt.trim() || !hostName || !deviceId || !userinterfaceName) return;
      setIsEditing(true);
      setError(null);
      setProposal(null);
      try {
        const result: any = await api.post(hostScopedUrl(hostName, '/server/ai/generatePlan'), {
          prompt: prompt.trim(),
          userinterface_name: userinterfaceName,
          device_id: deviceId,
          host_name: hostName,
          current_graph: graph,
        });
        if (result?.success && result.graph) {
          setProposal({
            graph: result.graph,
            analysis: result.analysis || '',
            stepsBefore: result.steps_before || [],
            stepsAfter: result.steps_after || [],
          });
        } else {
          setError(result?.error || 'The AI could not edit this test');
        }
      } catch (err: any) {
        setError(err?.message || 'The AI could not edit this test');
      } finally {
        setIsEditing(false);
      }
    },
    [hostName, deviceId, userinterfaceName, hostScopedUrl],
  );

  const clear = useCallback(() => {
    setProposal(null);
    setError(null);
  }, []);

  return { isEditing, proposal, error, proposeEdit, clear };
};
