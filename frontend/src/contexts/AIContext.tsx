import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { useSocket } from './SocketContext';
import { useAgentChatContext } from './AgentChatContext';
import { useAuth } from '../hooks/auth/useAuth';
import { isAuthEnabled } from '../lib/supabase';
import { useHostData } from '../hooks/useHostManager';

// Same storage keys as useAgentChat to share data
const STORAGE_KEY_API = 'virtualpytest_ai_api_key';
const STORAGE_KEY_PROVIDER = 'virtualpytest_ai_provider';
const STORAGE_KEY_AUTO_NAV = 'virtualpytest_allow_auto_navigation';
const STORAGE_KEY_AI_STATUS = 'virtualpytest_ai_status';

// Strip <think>...</think> tags from AI responses
const stripThinkTags = (text: string) => text.replace(/<think>[\s\S]*?<\/think>\s*/g, '').trim();

// generateId no longer needed — useAgentChat generates conversation IDs
// generateId removed — useAgentChat generates conversation IDs

interface AIState {
  // Panel Visibility
  isCommandOpen: boolean;
  isPilotOpen: boolean;
  isLogsOpen: boolean;
  
  // Task State
  activeTask: string | null;
  isProcessing: boolean;
  executionSteps: ExecutionStep[];
  
  // Status
  status: 'checking' | 'ready' | 'needs_key' | 'error';

  // When true, the floating "Ask AI" Fab is hidden (e.g. while a fullscreen
  // stream modal is open). Ref-counted so nested/multiple openers are safe.
  suppressFloatingButton: boolean;
  pushFloatingButtonSuppress: () => void;
  popFloatingButtonSuppress: () => void;

  // Skills Control
  allowAutoNavigation: boolean;
  setAllowAutoNavigation: (value: boolean) => void;
  
  // Actions
  toggleCommand: () => void;
  togglePilot: () => void;
  toggleLogs: () => void;
  openCommand: () => void;
  closeCommand: () => void;
  setTask: (task: string) => void;
  setProcessing: (processing: boolean) => void;
  
  // Backend Communication
  sendMessage: (message: string, agentId?: string) => void;
  isConnected: boolean;

  // Response
  lastResponse: string | null;

  // Agent Selection
  selectedAgentId: string;
  setSelectedAgentId: (id: string) => void;
}

interface ExecutionStep {
  id: string;
  label: string;
  status: 'pending' | 'active' | 'done' | 'error';
  detail?: string;
}

const AIContext = createContext<AIState | undefined>(undefined);

export const AIProvider: React.FC<{children: React.ReactNode}> = ({ children }) => {
  // The ONE conversation engine — AIContext delegates to it
  const agentChat = useAgentChatContext();

  const [isCommandOpen, setCmdOpen] = useState(false);
  const [isPilotOpen, setPilotOpen] = useState(false);
  const [isLogsOpen, setLogsOpen] = useState(false);
  const [floatingSuppressCount, setFloatingSuppressCount] = useState(0);
  const [activeTask, setActiveTask] = useState<string | null>(null);
  const [isProcessing, setProcessing] = useState(false);
  const [executionSteps, setExecutionSteps] = useState<ExecutionStep[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [lastResponse, setLastResponse] = useState<string | null>(null);
  // sessionId managed by SocketContext — AIContext reads status from agentChat
  const [, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<'checking' | 'ready' | 'needs_key' | 'error'>(() => {
    const cached = localStorage.getItem(STORAGE_KEY_AI_STATUS);
    return cached === 'needs_key' ? 'needs_key' : 'checking';
  });
  const [selectedAgentId, setSelectedAgentId] = useState('assistant');
  
  // Skills control - default OFF (disabled)
  const [allowAutoNavigation, setAllowAutoNavigationState] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY_AUTO_NAV);
    return saved === 'true'; // Default false if not set
  });
  
  // Persist auto-navigation preference
  const setAllowAutoNavigation = useCallback((value: boolean) => {
    setAllowAutoNavigationState(value);
    localStorage.setItem(STORAGE_KEY_AUTO_NAV, String(value));
  }, []);
  
  const currentConversationIdRef = useRef<string | null>(null);
  const pendingEventsRef = useRef<any[]>([]);
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const canInitializeAgent = !isAuthEnabled || isAuthenticated;

  // Use centralized socket and host data
  const { socket, connect, initSession: socketInitSession, registerEventHandler, unregisterEventHandler } = useSocket();
  const { getAllHosts } = useHostData();
  const socketRef = useRef(socket);
  // Keep socketRef in sync — socket may arrive after initial render
  useEffect(() => { socketRef.current = socket; }, [socket]);

  // Check API key and initialize session
  useEffect(() => {
    if (!canInitializeAgent) {
      return;
    }

    const updateStatus = (s: 'ready' | 'needs_key' | 'error') => {
      setStatus(s);
      localStorage.setItem(STORAGE_KEY_AI_STATUS, s);
    };

    const initSession = async () => {
      try {
        // Skip health check if we already know no key is set and none was saved since
        const cachedStatus = localStorage.getItem(STORAGE_KEY_AI_STATUS);
        const savedKey = localStorage.getItem(STORAGE_KEY_API);
        if (cachedStatus === 'needs_key' && !savedKey) {
          setStatus('needs_key');
          return;
        }

        // First check if API key is configured on backend
        const healthResponse = await fetch(buildServerUrl('/server/agent/health'));
        const healthData = await healthResponse.json();

        if (healthData.api_key_configured) {
          // API key already configured on backend
          updateStatus('ready');
        } else {
          // Check if we have a saved key in localStorage (same as AgentChat)
          if (savedKey) {
            // Send the saved key to backend
            const saveResponse = await fetch(buildServerUrl('/server/agent/api-key'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                provider: localStorage.getItem(STORAGE_KEY_PROVIDER) || healthData.provider || 'anthropic',
                model: healthData.model || '',
                api_key: savedKey,
              })
            });

            const saveData = await saveResponse.json();
            if (saveData.success) {
              updateStatus('ready');
            } else {
              updateStatus('needs_key');
              return;
            }
          } else {
            updateStatus('needs_key');
            return;
          }
        }
        
        // Create shared session (via SocketContext — shared with useAgentChat)
        const sharedSessionId = await socketInitSession();
        if (sharedSessionId) {
          setSessionId(sharedSessionId);
        }
      } catch (err) {
        console.error('Failed to initialize AI session:', err);
        updateStatus('error');
      }
    };
    
    initSession();
  }, [canInitializeAgent]);

  // Register event handler via SocketContext (shared routing, no duplicate listeners)
  useEffect(() => {
    if (status !== 'ready') return;

    // Connect the centralized socket if not already connected
    connect();

    // Register our event handler (SocketContext routes agent_event to all handlers)
    const handleAgentEvent = (event: any) => {
      // Only process events while we have a pending task
      if (!currentConversationIdRef.current) return;

      // Accumulate events for conversation saving
      pendingEventsRef.current = [...pendingEventsRef.current, event];

      if (event.type === 'message' || event.type === 'result') {
        const content = stripThinkTags(event.content || '');
        if (content) {
          setLastResponse(content);
          setExecutionSteps(prev => [
            ...prev.filter(s => s.status !== 'active'),
            { id: `msg-${Date.now()}`, label: 'AI Response', status: 'done', detail: content }
          ]);
        }
      } else if (event.type === 'tool_call') {
        const params = event.tool_params ? JSON.stringify(event.tool_params, null, 2) : '';
        const detail = params
          ? `${event.content || 'Executing...'}\n${params}`
          : (event.content || 'Executing...');
        setExecutionSteps(prev => [
          ...prev.filter(s => s.status !== 'active'),
          { id: `tool-${Date.now()}`, label: event.tool_name || 'Tool Call', status: 'active', detail }
        ]);
      } else if (event.type === 'tool_result') {
        const resultDetail = event.tool_result ? JSON.stringify(event.tool_result, null, 2) : '';
        setExecutionSteps(prev => prev.map(s =>
          s.status === 'active' ? { ...s, status: 'done' as const, detail: resultDetail ? `${s.detail}\n→ ${resultDetail}` : s.detail } : s
        ));
      } else if (event.type === 'error') {
        setExecutionSteps(prev => [
          ...prev.filter(s => s.status !== 'active'),
          { id: `err-${Date.now()}`, label: 'Error', status: 'error', detail: event.content || 'An error occurred' }
        ]);
      }
    };

    registerEventHandler('aicontext', handleAgentEvent);

    // Listen for Slack messages (still on direct socket — not part of agent_event routing)
    const handleSlack = (event: any) => {
      console.log('💬 AIContext Slack Message Received:', event);
      window.dispatchEvent(new CustomEvent('agent-toast', {
        detail: {
          message: `Slack: ${event.content?.substring(0, 50)}${event.content?.length > 50 ? '...' : ''}`,
          severity: 'info'
        }
      }));
      window.dispatchEvent(new CustomEvent('slack-message-received', {
        detail: {
          content: event.content,
          slackUserId: event.slack_user_id,
          threadTs: event.thread_ts,
          source: 'slack'
        }
      }));
    };

    if (socket) {
      socket.on('slack_message', handleSlack);
      setIsConnected(socket.connected);
    }

    return () => {
      unregisterEventHandler('aicontext');
      if (socket) {
        socket.off('slack_message', handleSlack);
      }
    };
  }, [status, socket, connect, registerEventHandler, unregisterEventHandler]);

  // Complete badge UI only after the shared conversation engine has finalized.
  useEffect(() => {
    if (!isProcessing || agentChat.isProcessing) return;

    const lastAgentMessage = [...agentChat.messages].reverse().find(msg => msg.role === 'agent' && msg.content);
    const cleaned = lastAgentMessage?.content ? stripThinkTags(lastAgentMessage.content) : '';

    if (cleaned) {
      setLastResponse(cleaned);
      setExecutionSteps(prev => {
        const withoutActive = prev.filter(s => s.status !== 'active');
        const alreadyPresent = withoutActive.some(s => s.label === 'AI Response' && s.detail === cleaned);
        return alreadyPresent
          ? withoutActive
          : [...withoutActive, { id: `msg-${Date.now()}`, label: 'AI Response', status: 'done', detail: cleaned }];
      });
    }

    setProcessing(false);
    currentConversationIdRef.current = null;
    pendingEventsRef.current = [];
  }, [agentChat.isProcessing, agentChat.messages, isProcessing]);


  // Send message — delegates to the ONE conversation engine (useAgentChat via AgentChatContext)
  const sendMessage = useCallback((message: string, agentId?: string) => {
    if (agentChat.status === 'needs_key') {
      setExecutionSteps([{
        id: 'error-key', label: 'Error', status: 'error',
        detail: '⚠️ AI provider not configured. Please go to AI Agent page or Settings → AI to set the active provider key.'
      }]);
      return;
    }

    // Set badge UI state
    setActiveTask(message);
    setProcessing(true);
    setLastResponse(null);
    setExecutionSteps([
      { id: 'parse', label: 'Parse Command', status: 'active', detail: 'Understanding request...' }
    ]);

    const effectiveAgentId = agentId || selectedAgentId;
    const hosts = getAllHosts();
    const allDevices = hosts.flatMap(h =>
      (h.devices || []).map(d => ({
        host_name: h.host_name,
        device_id: d.device_id,
        device_name: d.device_name || d.device_id,
        device_model: d.device_model,
      }))
    );
    const firstHost = hosts[0];
    const firstDevice = allDevices[0];

    currentConversationIdRef.current = 'pending';
    pendingEventsRef.current = [];

    agentChat.setAgentId(effectiveAgentId);
    agentChat.setNavigationContext(
      allowAutoNavigation,
      location.pathname,
      firstHost?.host_name || '',
      firstDevice?.device_id || '',
      '',
      '',
      '',
      allDevices,
      []
    );

    // Delegate to useAgentChat — it handles everything:
    // creating conversation, sending via SocketContext, receiving events, persisting
    agentChat.sendMessage(message);
  }, [agentChat, selectedAgentId, getAllHosts, allowAutoNavigation, location.pathname]);

  // Toggle functions
  const toggleCommand = useCallback(() => setCmdOpen(prev => !prev), []);
  const togglePilot = useCallback(() => setPilotOpen(prev => !prev), []);
  const toggleLogs = useCallback(() => setLogsOpen(prev => !prev), []);
  const openCommand = useCallback(() => setCmdOpen(true), []);

  const pushFloatingButtonSuppress = useCallback(() => setFloatingSuppressCount((c) => c + 1), []);
  const popFloatingButtonSuppress = useCallback(
    () => setFloatingSuppressCount((c) => Math.max(0, c - 1)),
    []
  );
  const closeCommand = useCallback(() => setCmdOpen(false), []);
  const setTask = useCallback((task: string) => setActiveTask(task), []);

  // Keyboard Shortcut: Cmd+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (status === 'ready') {
          toggleCommand();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleCommand]);

  // Auto-close Command bar on navigation
  useEffect(() => {
    if (isCommandOpen) {
      setCmdOpen(false);
    }
  }, [location.pathname]);

  return (
    <AIContext.Provider value={{
      isCommandOpen, isPilotOpen, isLogsOpen,
      suppressFloatingButton: floatingSuppressCount > 0,
      pushFloatingButtonSuppress, popFloatingButtonSuppress,
      activeTask, isProcessing, executionSteps,
      status,
      allowAutoNavigation, setAllowAutoNavigation,
      toggleCommand, togglePilot, toggleLogs,
      openCommand, closeCommand, setTask, setProcessing,
      sendMessage, isConnected, lastResponse,
      selectedAgentId, setSelectedAgentId
    }}>
      {children}
    </AIContext.Provider>
  );
};

export const useAIContext = () => {
  const context = useContext(AIContext);
  if (!context) throw new Error("useAIContext must be used within AIProvider");
  return context;
};
