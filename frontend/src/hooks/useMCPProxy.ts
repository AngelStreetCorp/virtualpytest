/**
 * MCP Proxy Hook - Execute prompts via OpenRouter Function Calling
 * 
 * This hook sends natural language prompts to the backend MCP proxy,
 * which uses OpenRouter with function calling to decide which MCP tools to execute.
 */

import { useState, useCallback } from 'react';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';

interface MCPProxyResult {
  success: boolean;
  result: any;
  tool_calls: Array<{
    tool: string;
    arguments: Record<string, any>;
    result: any;
  }>;
  ai_response: string;
  error?: string;
}

export const useMCPProxy = () => {
  const [isExecuting, setIsExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<MCPProxyResult | null>(null);

  /**
   * Execute natural language prompt via MCP proxy
   * 
   * Examples:
   * - "Swipe up"
   * - "Take a screenshot"
   * - "Navigate to home"
   * - "Verify that Replay button is visible"
   */
  const executePrompt = useCallback(async (
    prompt: string,
    deviceId: string,
    hostName: string,
    userinterfaceName?: string,
    teamId?: string,
    treeId?: string,
    deviceModel?: string
  ): Promise<MCPProxyResult> => {
    setIsExecuting(true);
    setError(null);

    try {
      console.log('[@useMCPProxy] Executing prompt:', prompt);
      console.log('[@useMCPProxy] Context:', { deviceId, hostName, userinterfaceName, teamId, treeId, deviceModel });

      // ✅ buildServerUrl automatically adds team_id from URL context
      const result: MCPProxyResult = await api.post(buildServerUrl('/server/mcp-proxy/execute-prompt'), {
        prompt,
        device_id: deviceId,
        host_name: hostName,
        userinterface_name: userinterfaceName,
        tree_id: treeId,
        device_model: deviceModel,
      });
      
      if (!result.success) {
        throw new Error(result.error || 'Execution failed');
      }

      console.log('[@useMCPProxy] Success!', result);
      console.log('[@useMCPProxy] Tool calls:', result.tool_calls);
      console.log('[@useMCPProxy] AI response:', result.ai_response);

      setLastResult(result);
      return result;

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useMCPProxy] Error:', errorMessage);
      setError(errorMessage);
      throw err;
    } finally {
      setIsExecuting(false);
    }
  }, []);

  /**
   * List available MCP tools (for debugging)
   */
  const listAvailableTools = useCallback(async () => {
    try {
      const data = await api.get<{ tools?: any[] }>(buildServerUrl('/server/mcp-proxy/list-tools'));
      return data.tools ?? [];
    } catch (err) {
      console.error('[@useMCPProxy] Failed to list tools:', err);
      return [];
    }
  }, []);

  return {
    executePrompt,
    listAvailableTools,
    isExecuting,
    error,
    lastResult
  };
};

