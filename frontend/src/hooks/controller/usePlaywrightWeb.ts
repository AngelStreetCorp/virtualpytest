import { useState, useEffect, useCallback, useRef } from 'react';
import { io, type Socket } from 'socket.io-client';

import { Host } from '../../types/common/Host_Types';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { useControllerApi } from './useControllerApi';
interface PlaywrightWebSession {
  connected: boolean;
  host: Host;
  connectionTime?: Date;
}

export const usePlaywrightWeb = (host: Host) => {
  const hostName = host.host_name;
  const { postToHost } = useControllerApi(host);

  // Session state
  const [session, setSession] = useState<PlaywrightWebSession>({
    connected: false,
    host,
  });

  // Terminal state for command output
  const [terminalOutput, setTerminalOutput] = useState<string>('');
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [currentCommand, setCurrentCommand] = useState('');
  const [isExecuting, setIsExecuting] = useState(false);

  // Async task state for browser_use_task
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<'idle' | 'executing' | 'completed' | 'failed'>(
    'idle',
  );
  const [isBrowserUseExecuting, setIsBrowserUseExecuting] = useState(false);

  // Page state
  const [currentUrl, setCurrentUrl] = useState<string>('');
  const [pageTitle, setPageTitle] = useState<string>('');
  const [error] = useState<string | null>(null);

  // WebSocket connection
  const socketRef = useRef<Socket | null>(null);

  // Auto-scroll terminal ref
  const terminalRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when output changes
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [terminalOutput]);

  // Execute web command using direct fetch to server route (following remote pattern)
  const executeWebCommand = useCallback(
    async (command: string, params: any = {}) => {
      try {
        console.log(
          `[@hook:usePlaywrightWeb] Executing command on ${hostName}:`,
          command,
          params,
        );

        const result = await postToHost('/server/web/executeCommand', {
          command: command,
          params: params,
        });

        console.log(`[@hook:usePlaywrightWeb] Raw command result:`, result);

        // Return the raw server response instead of filtering it
        return result;
      } catch (error) {
        console.error(`[@hook:usePlaywrightWeb] Command execution error:`, error);
        return {
          success: false,
          error: `Failed to execute command: ${error}`,
          execution_time: 0,
        };
      }
    },
    [hostName, postToHost],
  );

  // Get web controller status
  const getStatus = useCallback(async () => {
    try {
      const result = await postToHost('/server/web/getStatus');
      return result;
    } catch (error) {
      return { success: false, error: String(error) };
    }
  }, [hostName, postToHost]);

  // Track currentTaskId in a ref so the socket handler always sees the latest value
  const currentTaskIdRef = useRef<string | null>(null);
  useEffect(() => {
    currentTaskIdRef.current = currentTaskId;
  }, [currentTaskId]);

  const disconnectTaskSocket = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
    }
  }, []);

  // Lazy init: only create socket when async browser_use_task is used.
  const ensureTaskSocketConnection = useCallback(() => {
    if (socketRef.current) return;

    const serverUrl = buildServerUrl('');
    const socket = io(serverUrl, {
      transports: ['websocket'],
      reconnectionAttempts: 5,
      reconnectionDelay: 2000,
    });
    socketRef.current = socket;

    socket.on('task_complete', (data) => {
      console.log('[@hook:usePlaywrightWeb] Task completed:', data);
      const taskId = currentTaskIdRef.current;

      if (data.task_id === taskId) {
        console.log('[@hook:usePlaywrightWeb] Task IDs match - updating UI');
        setTaskStatus(data.success ? 'completed' : 'failed');
        setIsExecuting(false);
        setIsBrowserUseExecuting(false);
        setCurrentTaskId(null);

        // Show execution logs in terminal if available, otherwise show result
        const terminalOutput =
          data.execution_logs || JSON.stringify(data.result || { error: data.error }, null, 2);
        setTerminalOutput(terminalOutput);
      }
    });

    socket.on('connect', () => {
      console.log('[@hook:usePlaywrightWeb] WebSocket connected');
    });

    socket.on('disconnect', () => {
      console.log('[@hook:usePlaywrightWeb] WebSocket disconnected');
    });

    socket.on('connect_error', (error) => {
      console.error('[@hook:usePlaywrightWeb] WebSocket connection error:', error);
    });
  }, []);

  // Initialize web session only. Socket is created lazily for async browser_use_task.
  useEffect(() => {
    const initializeConnection = async () => {
      try {
        console.log('[@hook:usePlaywrightWeb] Initializing connection for', hostName);

        // Test connection by getting status
        const result = await getStatus();

        if (result.success) {
          setSession((prev) => ({
            ...prev,
            connected: true,
            connectionTime: new Date(),
          }));

          console.log('[@hook:usePlaywrightWeb] Connection established successfully');
        } else {
          console.error('[@hook:usePlaywrightWeb] Connection failed:', result.error);
        }
      } catch (error) {
        console.error('[@hook:usePlaywrightWeb] Connection error:', error);
      }
    };

    initializeConnection();

    // Cleanup WebSocket on unmount
    return () => {
      disconnectTaskSocket();
    };
  }, [hostName, getStatus, disconnectTaskSocket]);

  // Execute command with JSON parsing and terminal output
  const executeCommand = useCallback(
    async (commandStr: string) => {
      if (!session.connected || isExecuting) {
        return { success: false, error: 'Not connected or already executing' };
      }

      setIsExecuting(true);

      try {
        console.log('[@hook:usePlaywrightWeb] Executing command:', commandStr);

        // Parse JSON command
        let parsedCommand;
        try {
          parsedCommand = JSON.parse(commandStr);
        } catch {
          throw new Error(
            'Invalid JSON command format. Expected: {"command": "...", "params": {...}}',
          );
        }

        const { command, params } = parsedCommand;

        if (!command) {
          throw new Error('Command field is required in JSON');
        }

        if (command === 'browser_use_task') {
          ensureTaskSocketConnection();
        }

        // Add command to history
        const newHistory = [...commandHistory, commandStr];
        setCommandHistory(newHistory);

        // Execute command
        const result = await executeWebCommand(command, params || {});

        // Handle browser_use_task async response
        if (command === 'browser_use_task' && result.task_id) {
          // This is an async task - store task_id and wait for WebSocket notification
          setCurrentTaskId(result.task_id);
          setTaskStatus('executing');
          setIsBrowserUseExecuting(true);

          // Show initial status in terminal
          const statusOutput = JSON.stringify(
            {
              task_id: result.task_id,
              status: 'executing',
              message: 'Browser-use task started. Waiting for completion...',
            },
            null,
            2,
          );
          setTerminalOutput(statusOutput);

          // Keep isExecuting true - will be set to false by WebSocket callback
          return result;
        } else {
          // Synchronous command - show result immediately
          const resultOutput = JSON.stringify(result, null, 2);
          setTerminalOutput(resultOutput);

          // Keep page state updates
          if (command === 'navigate_to_url' || command === 'get_page_info') {
            setCurrentUrl(result.url || '');
            setPageTitle(result.title || '');
          }

          setIsExecuting(false);
          return result;
        }
      } catch (error) {
        console.error('[@hook:usePlaywrightWeb] Command execution error:', error);

        const errorResult = { success: false, error: String(error) };
        const errorOutput = JSON.stringify(errorResult, null, 2);
        setTerminalOutput(errorOutput);

        setIsExecuting(false);
        return errorResult;
      }
    },
    [session.connected, isExecuting, commandHistory, executeWebCommand, ensureTaskSocketConnection],
  );

  // Clear terminal
  const clearTerminal = useCallback(() => {
    setTerminalOutput('');
  }, []);

  // Reset all state to initial values
  const resetState = useCallback(() => {
    console.log('[@hook:usePlaywrightWeb] Resetting all state to initial values');
    setSession({
      connected: false,
      host,
    });
    setTerminalOutput('');
    setCommandHistory([]);
    setCurrentCommand('');
    setCurrentUrl('');
    setPageTitle('');
    setIsExecuting(false);
    setCurrentTaskId(null);
    setTaskStatus('idle');
    setIsBrowserUseExecuting(false);
    disconnectTaskSocket();
  }, [host, disconnectTaskSocket]);

  // Handle disconnect
  const handleDisconnect = useCallback(async () => {
    setIsExecuting(false);

    try {
      console.log('[@hook:usePlaywrightWeb] Disconnecting from web session');

      // Use the resetState function for consistency
      resetState();

      console.log('[@hook:usePlaywrightWeb] Disconnected successfully');
    } catch (error) {
      console.error('[@hook:usePlaywrightWeb] Disconnect error:', error);
    }
  }, [resetState]);

  // Helper function to open browser
  const openBrowser = useCallback(
    async () => {
      return executeWebCommand('open_browser');
    },
    [executeWebCommand],
  );

  return {
    // State
    session,
    terminalOutput,
    commandHistory,
    currentCommand,
    currentUrl,
    pageTitle,
    isExecuting,
    error,

    // Async task state
    currentTaskId,
    taskStatus,
    isBrowserUseExecuting,

    // Actions
    executeCommand,
    openBrowser,
    clearTerminal,
    resetState,
    handleDisconnect,
    setCurrentCommand,
    getStatus,

    // Refs
    terminalRef,
  };
};
