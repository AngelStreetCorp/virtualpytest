import { useState, useEffect, useRef, useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api, apiClient } from '../../utils/apiClient';
import { useSocket } from '../../contexts/SocketContext';
import { useAuthContext } from '../../contexts/auth/AuthContext';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useServerManager } from '../useServerManager';
import { isAllServersSentinel } from '../../lib/allServer/scope';
import { buildTurnAuth } from '../../lib/allServer/turnCredential';
import { buildTurnScope } from '../../lib/allServer/turnScope';
import { isAuthEnabled } from '../../lib/supabase';
import { APP_CONFIG, getEnv } from '../../config/constants';
import { AGENT_CHAT_LAYOUT } from '../../constants/agentChatTheme';
import { dedupeEvents, getEventDedupKey } from '../../utils/agentChatUtils';

// --- Constants ---

const STORAGE_KEY_CONVERSATIONS = 'virtualpytest_agent_conversations';
const STORAGE_KEY_ACTIVE_CONVERSATION = 'virtualpytest_active_conversation';

// --- Types ---

export interface AgentEvent {
  type: string;
  agent: string;
  content: string;
  timestamp: string;
  tool_name?: string;
  tool_params?: Record<string, unknown>;
  tool_result?: unknown;
  success?: boolean;
  error?: string;
  metrics?: {
    duration_ms: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens?: number;
    cache_creation_tokens?: number;
    /** TASK-175: the server handed the turn to this agent (Atlas → Forge). */
    handoff_to?: string;
    handoff_name?: string;
    /** TASK-175: another agent is the better one for this ask (a button beside the answer). */
    suggest_agent?: string;
    suggest_name?: string;
    match_source?: string;
  };
  // Background task fields (from dry-run events)
  task_id?: string;
  task_type?: string;
  task_data?: Record<string, unknown>;
  queue_name?: string;
  dry_run?: boolean;

  // Debug fields
  system_prompt?: string;
  conversation_context?: string;
}

// Generic background task - works for any agent with background_queues
export interface BackgroundTask {
  id: string;
  agentId: string;
  agentNickname: string;
  title: string;           // Script name, incident type, etc.
  subtitle?: string;       // Host name, device, etc.
  status: 'in_progress' | 'completed';
  severity?: string;       // For alerts: critical, high, normal, low
  classification?: string; // For analysis: VALID_PASS, BUG, etc.
  conversationId: string;
  startedAt: string;
  completedAt?: string;
  viewed: boolean;
  taskType?: string;       // script, alert, incident, etc.
}

// Background agent info (loaded from API)
export interface BackgroundAgentInfo {
  id: string;
  nickname: string;
  queues: string[];
  dryRun: boolean;
  color?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'agent';
  content: string;
  agent?: string;
  timestamp: string;
  events?: AgentEvent[];
  // Wall-clock timing for the agent turn that produced this message.
  // - `answer_elapsed_ms` is the total time from user send to terminal event
  //   (session_ended / complete / user-stopped), regardless of how many chunks
  //   streamed in. Includes first-token latency and any silence gaps.
  // - `thinking_elapsed_ms` is the wall-clock span from the first thinking
  //   event of the turn to the last thinking event (or to terminal if thinking
  //   was still streaming). Captures how long the model spent reasoning before
  //   it produced the answer — independent of token counts.
  // - `thinking_chunks` is the per-chunk arrival timestamp (ms since
  //   `turn_started_at`) plus the chunk length — useful for replaying the
  //   reasoning timeline and finding pauses the model inserted on purpose.
  timing?: {
    turn_started_at?: number;
    first_thinking_started_at?: number;
    last_thinking_at?: number;
    answer_elapsed_ms?: number;
    thinking_elapsed_ms?: number;
    thinking_chunks?: Array<{ at_ms: number; length: number }>;
  };
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
}

export interface Session {
  id: string;
  mode?: string;
  active_agent?: string;
}

export type Status = 'checking' | 'ready' | 'needs_key' | 'error';

// --- Utilities ---

const generateId = () => `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

const extractTitle = (messages: Message[]): string => {
  const firstUserMsg = messages.find(m => m.role === 'user');
  if (!firstUserMsg) return 'New Chat';
  // Take first 40 chars, truncate at word boundary
  const text = firstUserMsg.content.slice(0, 50);
  return text.length < firstUserMsg.content.length ? text.replace(/\s+\S*$/, '...') : text;
};

// --- Hook ---

export const useAgentChat = () => {
  // Conversations state
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);

  // Current conversation messages (derived)
  const activeConversation = conversations.find(c => c.id === activeConversationId);
  const messages = activeConversation?.messages || [];
  
  // 🆕 NEW: Device control state for AI agent tool calls
  // Callback ref to notify parent when AI takes/releases control
  const onDeviceControlChangeRef = useRef<((host: string, deviceId: string, isActive: boolean) => void) | null>(null);
  // Track the current device under agent control so we can clear the panel when needed
  const activeDeviceControlRef = useRef<{ host: string; deviceId: string } | null>(null);

  // Set callback for device control changes (called by parent - AgentChat.tsx)
  const setOnDeviceControlChange = useCallback((callback: (host: string, deviceId: string, isActive: boolean) => void) => {
    onDeviceControlChangeRef.current = callback;
  }, []);

  // 🆕 NEW: UI action callbacks for agent-driven UI updates
  const onUIActionRef = useRef<((action: string, payload: any) => void) | null>(null);

  // Set callback for UI actions (called by parent - AgentChat.tsx)
  const setOnUIAction = useCallback((callback: (action: string, payload: any) => void) => {
    onUIActionRef.current = callback;
  }, []);

  // Use centralized socket
  const { socket, connect, isConnected, initSession: sharedInitSession, joinSession, registerEventHandler, unregisterEventHandler, emitSendMessage: sharedEmitSendMessage, forceReconnect } = useSocket();
  const { isLoading: isAuthLoading, isAuthenticated } = useAuthContext();
  const { activeWorkspace } = useWorkspaceContext();
  const { selectedServer, serverHostsData } = useServerManager();


  const clearDeviceControlPanel = useCallback(() => {
    const active = activeDeviceControlRef.current;
    if (active && onDeviceControlChangeRef.current) {
      onDeviceControlChangeRef.current(active.host, active.deviceId, false);
    }
    activeDeviceControlRef.current = null;
  }, []);
  
  useEffect(() => {
    if (activeConversationId) {
      // isProcessing reflects the ACTIVE conversation only — other threads may
      // be processing in parallel on their own sessions.
      setIsProcessing(pendingConvsRef.current.has(activeConversationId));
    }
  }, [activeConversationId]);
  
  // Session & UI state
  const [status, setStatus] = useState<Status>('checking');
  const [session, setSession] = useState<Session | null>(null);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [pendingConversationId, setPendingConversationId] = useState<string | null>(null); // Which conversation is awaiting response
  const [currentEvents, setCurrentEvents] = useState<AgentEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  // TASK-175: the last server-side hand-off (agent id + when), for the page to follow.
  const [agentHandoff, setAgentHandoff] = useState<{ agentId: string; at: number } | null>(null);
  // Message of the latest agent 'error' event (a failed tool call is recoverable: the agent
  // carries on). It is shown immediately, then cleared once the turn recovers (see handleAgentEvent).
  const recoverableErrorRef = useRef<string | null>(null);
  
  // API Key state
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [activeProvider, setActiveProvider] = useState('anthropic');
  const [activeModel, setActiveModel] = useState('');
  const [activeEndpoint, setActiveEndpoint] = useState('');
  
  // Refs
  const processingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  // True until the first event for the current send_message round-trip arrives.
  // Used to enforce a tight 30s "first answer" timeout, separate from the longer
  // stall timeout that runs once events are streaming.
  const firstEventReceivedRef = useRef<boolean>(true);
  // Ack watchdog: one transparent reconnect+resend when no event arrives in 4s
  const ackRetryTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const ackRetriedRef = useRef<boolean>(false);
  // Wall-clock timing for the active turn (the one that flipped isProcessing=true).
  // - `turnStartedAt` is the epoch ms the send_message was emitted; the UI ticks
  //   `now - turnStartedAt` to show the live "answer elapsed" counter.
  // - `firstThinkingStartedAt` is captured on the first 'thinking' event of the
  //   turn (null until then); it gates the "reasoning elapsed" counter.
  // - `lastThinkingAt` is the wall-clock ms of the last thinking chunk — lets
  //   us freeze the reasoning timer the moment reasoning stops streaming, even
  //   if the model keeps producing tool calls or the answer for a while.
  // - `thinkingChunks` is an in-memory rolling buffer of {at_ms, length} for
  //   every thinking chunk, persisted on the final Message so feedback and
  //   copyMessage can carry it.
  const turnStartedAtRef = useRef<number | null>(null);
  const firstThinkingStartedAtRef = useRef<number | null>(null);
  const lastThinkingAtRef = useRef<number | null>(null);
  const thinkingChunksRef = useRef<Array<{ at_ms: number; length: number }>>([]);
  // Mirror of the above as React state so the live-tick header / Reasoning
  // accordion can read them; we tick `now` on a 250ms interval to re-render.
  const [turnStartedAt, setTurnStartedAt] = useState<number | null>(null);
  const [firstThinkingStartedAt, setFirstThinkingStartedAt] = useState<number | null>(null);
  const [lastThinkingAt, setLastThinkingAt] = useState<number | null>(null);
  // Per-conversation sessions: each chat thread gets its own backend session so
  // parallel conversations don't collide on one shared session/room. Events are
  // routed back via their session_id (stamped by the backend).
  const conversationSessionRef = useRef<Map<string, string>>(new Map());
  const sessionConversationRef = useRef<Map<string, string>>(new Map());
  const pendingConvsRef = useRef<Set<string>>(new Set());
  const endedSessionsRef = useRef<Set<string>>(new Set());
  const activeConversationIdRef = useRef<string | null>(null);
  const pendingConversationIdRef = useRef<string | null>(null); // Track which conversation is awaiting response
  const sessionEndedRef = useRef<boolean>(false); // Track if session_ended was received (prevents premature reset)
  const disconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null); // For delayed disconnect handling
  const conversationsRef = useRef<Conversation[]>([]); // Ref copy for callbacks that don't need to re-memoize on every message
  conversationsRef.current = conversations; // Keep in sync — safe here, after the ref is declared
  const socketRef = useRef(socket);
  socketRef.current = socket;
  const sessionRef = useRef(session);
  sessionRef.current = session;

  // Generic background tasks state - keyed by agent ID
  // Loaded dynamically based on agents with background_queues config
  const [backgroundTasks, setBackgroundTasks] = useState<Record<string, {
    inProgress: BackgroundTask[];
    recent: BackgroundTask[];
  }>>({});
  
  // Background agents info (agents with background_queues) - set from parent
  const backgroundAgentsRef = useRef<Map<string, BackgroundAgentInfo>>(new Map());

  // Track script executions to conversations for background analysis correlation
  const scriptConversationMapRef = useRef<Map<string, string>>(new Map()); // script_result_id -> conversation_id

  // Set background agents (called by parent after loading from API)
  const setBackgroundAgents = useCallback((agents: BackgroundAgentInfo[]) => {
    console.log(`[useAgentChat] setBackgroundAgents called with ${agents.length} agents:`, agents.map(a => `${a.id}/${a.nickname}`));
    const map = new Map<string, BackgroundAgentInfo>();
    agents.forEach(a => {
      map.set(a.id, a);
      map.set(a.nickname, a); // Also index by nickname for event matching
      console.log(`[useAgentChat] Registered background agent: id="${a.id}", nickname="${a.nickname}"`);
    });
    backgroundAgentsRef.current = map;
    console.log(`[useAgentChat] Background agents map keys:`, Array.from(map.keys()));
    
    // Restore background tasks from existing conversations (on page refresh)
    const restoredTasks: Record<string, { inProgress: BackgroundTask[]; recent: BackgroundTask[] }> = {};
    agents.forEach(a => {
      restoredTasks[a.id] = { inProgress: [], recent: [] };
    });
    
    // Find all background conversations and convert to tasks
    setConversations(prevConvos => {
      prevConvos.forEach(convo => {
        if (!convo.id.startsWith('bg_')) return;
        
        // Extract agent ID from conversation ID: bg_{agentId}_{taskId}
        const parts = convo.id.split('_');
        if (parts.length < 3) return;
        const agentId = parts[1]; // e.g., "monitor" from "bg_monitor_xxx"
        
        // Check if this agent is in our list
        if (!restoredTasks[agentId]) return;
        
        // Parse title to extract info (format: "🌙 host-device - type" or "🌙 title")
        const titleWithoutEmoji = convo.title.replace(/^\u{1F319}\s*/u, '');
        const titleParts = titleWithoutEmoji.split(' - ');
        const title = titleParts[0] || 'Unknown';
        const subtitle = titleParts[1];
        
        // Create task from conversation
        const task: BackgroundTask = {
          id: parts.slice(2).join('_'), // taskId from conversation ID
          agentId,
          agentNickname: map.get(agentId)?.nickname || agentId,
          title,
          subtitle,
          status: 'completed', // Restored tasks are always completed
          conversationId: convo.id,
          startedAt: convo.createdAt,
          completedAt: convo.updatedAt,
          viewed: false,
          taskType: 'alert',
        };
        
        restoredTasks[agentId].recent.push(task);
      });
      
      // Sort by createdAt descending and keep only most recent N
      Object.keys(restoredTasks).forEach(agentId => {
        restoredTasks[agentId].recent.sort((a, b) => 
          new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
        );
        restoredTasks[agentId].recent = restoredTasks[agentId].recent.slice(0, AGENT_CHAT_LAYOUT.maxRecentBackgroundTasks);
      });
      
      console.log(`[useAgentChat] Restored background tasks from conversations:`, restoredTasks);
      setBackgroundTasks(restoredTasks);
      
      return prevConvos; // Don't modify conversations
    });
  }, []);

  // --- Conversation Persistence ---

  // Load conversations from localStorage
  const loadConversations = useCallback(() => {
    const savedConvos = localStorage.getItem(STORAGE_KEY_CONVERSATIONS);
    const savedActiveId = localStorage.getItem(STORAGE_KEY_ACTIVE_CONVERSATION);
    
    if (savedConvos) {
      try {
        const parsed = JSON.parse(savedConvos);
        setConversations(parsed);
        // Restore active conversation or use most recent
        if (savedActiveId && parsed.find((c: Conversation) => c.id === savedActiveId)) {
          setActiveConversationId(savedActiveId);
          activeConversationIdRef.current = savedActiveId;
        } else if (parsed.length > 0) {
          setActiveConversationId(parsed[0].id);
          activeConversationIdRef.current = parsed[0].id;
        }
      } catch (err) {
        console.error('Failed to load conversations:', err);
      }
    }
  }, []);

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // Save conversations on change (with limit to prevent localStorage bloat)
  useEffect(() => {
    if (conversations.length > 0) {
      // Keep only most recent N conversations (sorted by updatedAt)
      const sorted = [...conversations].sort((a, b) => 
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
      );
      const limited = sorted.slice(0, AGENT_CHAT_LAYOUT.maxStoredConversations);
      
      if (limited.length < conversations.length) {
        console.log(`[useAgentChat] Trimming for storage: ${conversations.length} -> ${limited.length} (max: ${AGENT_CHAT_LAYOUT.maxStoredConversations})`);
        // Note: We only save the limited version to localStorage, not update state (to avoid infinite loop)
      }
      
      localStorage.setItem(STORAGE_KEY_CONVERSATIONS, JSON.stringify(limited));
    }
  }, [conversations]);

  // Save active conversation ID and keep ref in sync
  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
    if (activeConversationId) {
      localStorage.setItem(STORAGE_KEY_ACTIVE_CONVERSATION, activeConversationId);
    }
  }, [activeConversationId]);

  // --- Conversation Management ---

  // Clear backend session for conversation isolation
  const clearBackendSession = useCallback(() => {
    socket?.emit('clear_session', { session_id: session?.id });
  }, [socket, session?.id]);

  // Reset all "in-flight message" state. Used when the user starts/switches/deletes
  // a conversation so a previously-stuck isProcessing flag from a prior chat can't
  // block new sendMessage calls.
  const resetInFlightState = useCallback(() => {
    setIsProcessing(false);
    setError(null);
    recoverableErrorRef.current = null;
    setCurrentEvents([]);
    sessionEndedRef.current = true;
    pendingConversationIdRef.current = null;
    setPendingConversationId(null);
    if (processingTimeoutRef.current) {
      clearTimeout(processingTimeoutRef.current);
      processingTimeoutRef.current = null;
    }
    // Drop live timers — the abandoned turn never gets persisted as a
    // Message, so its timing data is gone and the UI must not keep showing
    // a clock for it.
    turnStartedAtRef.current = null;
    setTurnStartedAt(null);
    firstThinkingStartedAtRef.current = null;
    setFirstThinkingStartedAt(null);
    lastThinkingAtRef.current = null;
    setLastThinkingAt(null);
    thinkingChunksRef.current = [];
  }, []);

  const createNewConversation = useCallback(() => {
    clearBackendSession(); // Fresh backend session
    resetInFlightState();
    const newConvo: Conversation = {
      id: generateId(),
      title: 'New Chat',
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    setConversations(prev => [newConvo, ...prev]);
    setActiveConversationId(newConvo.id);
    activeConversationIdRef.current = newConvo.id;
    return newConvo.id;
  }, [clearBackendSession, resetInFlightState]);

  const switchConversation = useCallback((conversationId: string) => {
    console.log(`[useAgentChat] switchConversation called with:`, conversationId);
    console.log(`[useAgentChat] Current activeConversationId:`, activeConversationIdRef.current);
    console.log(`[useAgentChat] All conversations:`, conversationsRef.current.map(c => ({ id: c.id, title: c.title, messageCount: c.messages.length })));
    clearBackendSession(); // Reset backend context so it doesn't bleed from the previous conversation
    resetInFlightState();
    setActiveConversationId(conversationId);
    activeConversationIdRef.current = conversationId;
    console.log(`[useAgentChat] Switched to conversation:`, conversationId);
  }, [clearBackendSession, resetInFlightState]);

  const deleteConversation = useCallback((conversationId: string) => {
    clearBackendSession(); // Fresh start after delete
    resetInFlightState();
    setConversations(prev => {
      const filtered = prev.filter(c => c.id !== conversationId);
      if (conversationId === activeConversationId && filtered.length > 0) {
        setActiveConversationId(filtered[0].id);
        activeConversationIdRef.current = filtered[0].id;
      } else if (filtered.length === 0) {
        setActiveConversationId(null);
        activeConversationIdRef.current = null;
      }
      if (filtered.length === 0) {
        localStorage.removeItem(STORAGE_KEY_CONVERSATIONS);
        localStorage.removeItem(STORAGE_KEY_ACTIVE_CONVERSATION);
      }
      return filtered;
    });
  }, [activeConversationId, clearBackendSession, resetInFlightState]);

  // --- Socket Connection ---

  // --- Generic Background Event Handler ---
  // Handles events from any agent with background_queues config
  
  // Track active background sessions per agent
  const backgroundSessionsRef = useRef<Map<string, { 
    conversationId: string; 
    taskId: string; 
    title: string;
    scriptName?: string;
    taskType?: string;
  }>>(new Map());
  
  const handleBackgroundEvent = useCallback((event: AgentEvent): boolean => {
    // Check if this event is from a background agent
    console.log(`[handleBackgroundEvent] Checking event.agent="${event.agent}", available agents:`, Array.from(backgroundAgentsRef.current.keys()));
    const agentInfo = backgroundAgentsRef.current.get(event.agent);
    if (!agentInfo) {
      console.log(`[handleBackgroundEvent] Agent "${event.agent}" NOT FOUND in background agents map`);
      return false; // Not a background agent event
    }
    console.log(`[handleBackgroundEvent] Agent "${event.agent}" FOUND! agentInfo:`, agentInfo);
    
    const agentId = agentInfo.id;
    const agentNickname = agentInfo.nickname;
    const isDryRun = agentInfo.dryRun;
    
    console.log(`[Background:${agentNickname}] Handling event:`, event.type, event.content?.slice(0, 50));
    
    // Extract task info from event (generic patterns)
    const taskData = event.task_data || {};
    
    // Try to extract a REAL task ID - don't use temp fallback here
    // Also check tool_params for update_execution_analysis calls
    const realTaskId = event.task_id || 
      (event.tool_params?.script_result_id as string) ||
      event.content?.match(/SCRIPT_RESULT_ID:\s*([a-f0-9-]+)/)?.[1] ||
      event.content?.match(/INCIDENT_ID:\s*([^\n]+)/)?.[1]?.trim() ||
      event.content?.match(/ALERT_ID:\s*([^\n]+)/)?.[1]?.trim() ||
      event.content?.match(/TASK_ID:\s*([^\n]+)/)?.[1]?.trim() ||
      null;
    
    // Check if there's an existing active session for this agent
    const existingSession = backgroundSessionsRef.current.get(agentId);
    
    // For non-dry-run agents (like Sherlock): only create task for MESSAGE events with real content
    // Skip intermediate events (thinking, skill_loaded, tool_call) to avoid creating multiple entries
    if (!isDryRun) {
      // Skip thinking/skill events - but extract script name if present
      if (event.type === 'thinking' || event.type === 'skill_loaded') {
        // Try to extract script name from thinking content (contains "SCRIPT: goto")
        const scriptFromThinking = event.content?.match(/SCRIPT:\s*([^\n]+)/i)?.[1]?.trim();
        const taskIdFromThinking = event.content?.match(/SCRIPT_RESULT_ID:\s*([a-f0-9-]+)/i)?.[1];
        
        if (scriptFromThinking || taskIdFromThinking) {
          console.log(`[Background:${agentNickname}] Found script info in ${event.type}: script=${scriptFromThinking}, id=${taskIdFromThinking}`);
          // Store for later use when MESSAGE arrives
          const existingInfo = backgroundSessionsRef.current.get(`${agentId}_pending_info`) as any || {};
          backgroundSessionsRef.current.set(`${agentId}_pending_info`, { 
            ...existingInfo,
            conversationId: '', 
            taskId: taskIdFromThinking || existingInfo.taskId || '', 
            title: scriptFromThinking || existingInfo.title || '',
            scriptName: scriptFromThinking || existingInfo.scriptName,
            taskType: 'script'
          } as any);
        }
        console.log(`[Background:${agentNickname}] Skipping ${event.type} event - no task creation`);
        return true; // Handled but skipped
      }
      
      // For tool_call/tool_result, add to existing session only (don't create new tasks)
      // We want the MESSAGE event to create the task since it has the actual analysis content
      if (event.type === 'tool_call' || event.type === 'tool_result') {
        if (existingSession) {
          console.log(`[Background:${agentNickname}] Adding ${event.type} to existing session`);
          // Add to existing conversation
          setConversations(prev => prev.map(c => {
            if (c.id !== existingSession.conversationId) return c;
            const lastMsg = c.messages[c.messages.length - 1];
            if (lastMsg && lastMsg.role === 'agent') {
              return {
                ...c,
                messages: [
                  ...c.messages.slice(0, -1),
                  { ...lastMsg, events: [...(lastMsg.events || []), event] }
                ],
                updatedAt: new Date().toISOString(),
              };
            }
            return c;
          }));
          return true;
        }
        // If we have a task ID from update_execution_analysis, store it for the upcoming MESSAGE event
        if (realTaskId && event.type === 'tool_call' && event.tool_name === 'update_execution_analysis') {
          // Also try to extract script name from tool params or content
          const scriptName = (event.tool_params?.script_name as string) || 
            event.content?.match(/script[:\s]+["']?([^"'\n,]+)/i)?.[1]?.trim();
          
          console.log(`[Background:${agentNickname}] Storing pending task ID: ${realTaskId}, scriptName: ${scriptName}`);
          // Store pending task ID - will be used when MESSAGE arrives
          backgroundSessionsRef.current.set(`${agentId}_pending`, { 
            conversationId: '', 
            taskId: realTaskId, 
            title: '' 
          });
          // Store additional info for title extraction
          backgroundSessionsRef.current.set(`${agentId}_pending_info`, { 
            conversationId: '', 
            taskId: realTaskId, 
            title: scriptName || '',
            scriptName: scriptName,
            taskType: 'script'
          } as any);
        }
        console.log(`[Background:${agentNickname}] Skipping ${event.type} - waiting for MESSAGE event`);
        return true; // Don't create task from tool events
      }
      
      // For session_ended, mark existing task as complete and don't create new
      if (event.type === 'session_ended') {
        if (existingSession) {
          console.log(`[Background:${agentNickname}] Session ended - marking task complete`);
          setBackgroundTasks(prev => {
            const agentTasks = prev[agentId] || { inProgress: [], recent: [] };
            const inProgressTask = agentTasks.inProgress.find(t => t.conversationId === existingSession.conversationId);
            if (!inProgressTask) return prev;
            
            const completedTask: BackgroundTask = {
              ...inProgressTask,
              status: 'completed',
              classification: 'COMPLETED',
              completedAt: new Date().toISOString(),
            };
            
            return {
              ...prev,
              [agentId]: {
                inProgress: agentTasks.inProgress.filter(t => t.conversationId !== existingSession.conversationId),
                recent: [completedTask, ...agentTasks.recent].slice(0, AGENT_CHAT_LAYOUT.maxRecentBackgroundTasks),
              }
            };
          });
          backgroundSessionsRef.current.delete(agentId);
        }
        return true; // Don't create a new task for session_ended
      }
      
      // For message events without real task ID, pending task/info, or existing session, skip
      const pendingCheck = backgroundSessionsRef.current.get(`${agentId}_pending`);
      const pendingInfoCheck = backgroundSessionsRef.current.get(`${agentId}_pending_info`);
      if (!realTaskId && !existingSession && !pendingCheck && !pendingInfoCheck && event.type === 'message') {
        console.log(`[Background:${agentNickname}] Skipping message - no task ID, pending task/info, or session`);
        return true;
      }
    }
    
    // Check for pending task ID (stored from tool_call or thinking events)
    const pendingSession = backgroundSessionsRef.current.get(`${agentId}_pending`);
    const pendingInfo = backgroundSessionsRef.current.get(`${agentId}_pending_info`) as any;
    
    // Use real task ID, pending task ID, existing session's task ID, or generate temp (only for dry-run)
    const taskId = realTaskId || pendingSession?.taskId || pendingInfo?.taskId || existingSession?.taskId || (isDryRun ? `temp_${Date.now()}` : null);
    
    // Clear pending task ID and info once used
    if (pendingSession && event.type === 'message') {
      backgroundSessionsRef.current.delete(`${agentId}_pending`);
      backgroundSessionsRef.current.delete(`${agentId}_pending_info`);
    }
    
    // If still no task ID and not dry-run, skip
    if (!taskId) {
      console.log(`[Background:${agentNickname}] Skipping event - cannot determine task ID`);
      return true;
    }
    
    // Check if there's stored script info from the tool_call
    const storedPendingInfo = backgroundSessionsRef.current.get(`${agentId}_pending_info`);
    
    const taskType: string = event.task_type || (taskData.type as string) || storedPendingInfo?.taskType || 'script';
    
    // Build title and subtitle based on task type
    // Try stored info first, then task_data, then parse from event.content
    let title = 'Script';
    let subtitle: string | undefined;
    let severity: string | undefined;
    let classification: string | undefined;
    
    // Extract script name from various formats:
    // - Stored from tool_call: storedPendingInfo.scriptName
    // - Plain text: "SCRIPT: goto"
    // - Markdown: "**Script:** `goto`" or "**Script:** goto"
    // - Markdown with newlines: "**Script:**\n`goto`"
    const scriptNameFromContent = 
      event.content?.match(/SCRIPT:\s*([^\n]+)/i)?.[1]?.trim() ||
      event.content?.match(/\*\*Script:\*\*\s*`([^`]+)`/i)?.[1]?.trim() ||
      event.content?.match(/\*\*Script:\*\*\s*(\S+)/i)?.[1]?.trim();
    
    // Detect if this is a script analysis (Sherlock always analyzes scripts)
    const isScriptAnalysis = taskType === 'script' || 
      event.content?.includes('Analysis Complete') ||
      event.content?.includes('Script:') || 
      event.content?.includes('SCRIPT:') ||
      agentId === 'analyzer'; // Sherlock/Analyzer always does script analysis
    
    if (isScriptAnalysis) {
      title = (storedPendingInfo as any)?.scriptName || scriptNameFromContent || (taskData.script_name as string) || 'Script';
      console.log(`[Background:${agentNickname}] Extracted script name: "${title}" from storedInfo: ${(storedPendingInfo as any)?.scriptName}, content: ${scriptNameFromContent}`);
    } else if (taskType === 'alert' || taskType === 'incident') {
      // For alerts: title = "host_name - device_name", subtitle = incident_type
      const hostName = (taskData.host_name as string) || event.content?.match(/HOST:\s*([^\n(]+)/)?.[1]?.trim();
      const deviceName = taskData.device_name as string;
      const incidentType = (taskData.incident_type as string) || (taskData.alert_type as string) || 
        event.content?.match(/TYPE:\s*([^\n]+)/)?.[1]?.trim();
      
      // Title: host - device (or just host if no device)
      if (hostName && deviceName) {
        title = `${hostName} - ${deviceName}`;
      } else if (hostName) {
        title = hostName;
      } else {
        title = 'Unknown device';
      }
      
      // Subtitle: incident type (freeze, blackscreen, etc.)
      subtitle = incidentType || 'alert';
      severity = taskData.severity as string | undefined;
    } else {
      title = taskType;
    }
    
    const conversationId = `bg_${agentId}_${taskId}`;
    
    // Store session info
    backgroundSessionsRef.current.set(agentId, { conversationId, taskId, title });
    
    // Create conversation for this task WITH initial message
    // Ensure event has type 'message' so AgentChat.tsx renders the content
    // (AgentChat only renders events with type 'message' or 'result')
    const renderableEvent: AgentEvent = {
      ...event,
      type: 'message', // Override to ensure rendering
    };
    
    const initialMessage = {
      id: `${Date.now()}-${Math.random()}`,
      role: 'agent' as const,
      content: event.content || `${taskType} received`,
      agent: agentNickname,
      timestamp: new Date().toISOString(),
      events: [renderableEvent],
    };
    
    const newConvo: Conversation = {
      id: conversationId,
      title: subtitle ? `${title} - ${subtitle}` : title,
      messages: [initialMessage], // Start with initial message
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    
    console.log(`[Background:${agentNickname}] Creating conversation:`, {
      conversationId,
      title: newConvo.title,
      messageContent: initialMessage.content,
      eventContent: event.content,
      originalEventType: event.type,
      convertedEventType: renderableEvent.type,
      taskData: event.task_data,
      taskId,
      isDryRun
    });
    
    setConversations(prev => {
      const exists = prev.find(c => c.id === conversationId);
      if (exists) {
        console.log(`[Background:${agentNickname}] Conversation already exists:`, conversationId);
        return prev;
      }
      console.log(`[Background:${agentNickname}] Created conversation with message:`, conversationId);
      return [newConvo, ...prev];
    });
    
    // Create task object
    const task: BackgroundTask = {
      id: taskId,
      agentId,
      agentNickname,
      title,
      subtitle,
      status: isDryRun ? 'completed' : 'in_progress', // Dry run = instant complete
      severity,
      conversationId,
      startedAt: new Date().toISOString(),
      completedAt: isDryRun ? new Date().toISOString() : undefined,
      viewed: false,
      taskType,
    };
    
    // Update tasks state
    setBackgroundTasks(prev => {
      const agentTasks = prev[agentId] || { inProgress: [], recent: [] };
      
      if (isDryRun) {
        // Dry run mode: add directly to recent
        return {
          ...prev,
          [agentId]: {
            ...agentTasks,
            recent: [task, ...agentTasks.recent].slice(0, AGENT_CHAT_LAYOUT.maxRecentBackgroundTasks),
          }
        };
      } else {
        // Normal mode: add to in-progress
        const exists = agentTasks.inProgress.find(t => t.id === taskId);
        if (exists) return prev;
        return {
          ...prev,
          [agentId]: {
            ...agentTasks,
            inProgress: [task, ...agentTasks.inProgress.filter(t => !t.id.startsWith('temp_'))],
          }
        };
      }
    });
    
    // Check for completion markers (tool calls that indicate completion)
    if (event.type === 'tool_call' && event.tool_name === 'update_execution_analysis') {
      classification = event.tool_params?.classification as string || 'UNKNOWN';
      
      setBackgroundTasks(prev => {
        const agentTasks = prev[agentId] || { inProgress: [], recent: [] };
        const inProgressTask = agentTasks.inProgress.find(t => t.conversationId === conversationId);
        if (!inProgressTask) return prev;
        
        const completedTask: BackgroundTask = {
          ...inProgressTask,
          status: 'completed',
          classification,
          completedAt: new Date().toISOString(),
        };
        
        return {
          ...prev,
          [agentId]: {
            inProgress: agentTasks.inProgress.filter(t => t.conversationId !== conversationId),
            recent: [completedTask, ...agentTasks.recent].slice(0, AGENT_CHAT_LAYOUT.maxRecentBackgroundTasks),
          }
        };
      });
    }
    
    // Handle session_ended
    if (event.type === 'session_ended') {
      const sessionInfo = backgroundSessionsRef.current.get(agentId);
      if (sessionInfo) {
        setBackgroundTasks(prev => {
          const agentTasks = prev[agentId] || { inProgress: [], recent: [] };
          const inProgressTask = agentTasks.inProgress.find(t => t.conversationId === sessionInfo.conversationId);
          if (!inProgressTask) return prev;
          
          const completedTask: BackgroundTask = {
            ...inProgressTask,
            status: 'completed',
            classification: 'COMPLETED',
            completedAt: new Date().toISOString(),
          };
          
          return {
            ...prev,
            [agentId]: {
              inProgress: agentTasks.inProgress.filter(t => t.conversationId !== sessionInfo.conversationId),
              recent: [completedTask, ...agentTasks.recent].slice(0, AGENT_CHAT_LAYOUT.maxRecentBackgroundTasks),
            }
          };
        });
        backgroundSessionsRef.current.delete(agentId);
      }
    }
    
    // Add event to conversation (for subsequent events only - initial event added with conversation)
    // Convert event to renderable type (AgentChat only renders 'message' or 'result' events)
    const subsequentRenderableEvent: AgentEvent = {
      ...event,
      type: event.type === 'session_ended' ? 'session_ended' : 'message',
    };
    
    setConversations(prev => prev.map(c => {
      if (c.id !== conversationId) return c;
      
      const lastMsg = c.messages[c.messages.length - 1];
      
      // Skip if event already exists in last message (check by task_id and timestamp to handle type conversion)
      if (lastMsg?.events?.some(e => e.task_id === event.task_id && e.timestamp === event.timestamp)) {
        console.log(`[Background:${agentNickname}] Skipping duplicate event:`, event.type, event.task_id);
        return c;
      }
      
      if (lastMsg && lastMsg.role === 'agent' && event.type !== 'session_ended') {
        console.log(`[Background:${agentNickname}] Appending event to last message:`, event.type);
        return {
          ...c,
          messages: [
            ...c.messages.slice(0, -1),
            {
              ...lastMsg,
              content: event.content || lastMsg.content,
              events: [...(lastMsg.events || []), subsequentRenderableEvent]
            }
          ],
          updatedAt: new Date().toISOString(),
        };
      } else if (event.type !== 'session_ended') {
        console.log(`[Background:${agentNickname}] Creating new message for event:`, event.type);
        return {
          ...c,
          messages: [
            ...c.messages,
            {
              id: `${Date.now()}-${Math.random()}`,
              role: 'agent',
              content: event.content || `${event.type} event`,
              agent: agentNickname,
              timestamp: new Date().toISOString(),
              events: [subsequentRenderableEvent],
            }
          ],
          updatedAt: new Date().toISOString(),
        };
      }
      
      return c;
    }));
    
    return true; // Event was handled
  }, []);

  // connectSocket replaced by shared SocketContext.connect() — kept as comment for reference
  // Was: connect() + set up listeners in useEffect below

  // Set up socket event listeners when socket becomes available
  useEffect(() => {
    if (!socket) return;

    // Room membership (shared session, background_tasks, every per-conversation
    // session) is owned by SocketContext, which re-joins them all on each connect.
    const handleConnect = () => {
      console.log('[useAgentChat] Socket connected, session:', session?.id);

      // Reset retry count on successful connection
      sendMessageRetryCountRef.current = 0;

      // Cancel any pending disconnect timeout on successful connect
      if (disconnectTimeoutRef.current) {
        clearTimeout(disconnectTimeoutRef.current);
        disconnectTimeoutRef.current = null;
      }
    };

    const handleDisconnect = (reason: string) => {
      console.warn(`[useAgentChat] Socket disconnected: ${reason}`);

      // Only consider resetting on explicit server disconnect, NOT on transport close
      // Transport close happens during normal window switching/backgrounding
      if (reason === 'io server disconnect') {
        // Even then, only reset if session_ended was actually received
        // Use a longer timeout to give reconnection a chance
        if (disconnectTimeoutRef.current) {
          clearTimeout(disconnectTimeoutRef.current);
        }

        disconnectTimeoutRef.current = setTimeout(() => {
          // Only unstick if session actually ended AND we're still "processing"
          if (pendingConversationIdRef.current && sessionEndedRef.current) {
            console.warn('[useAgentChat] Server disconnect confirmed - cleaning up');
            setIsProcessing(false);
            pendingConversationIdRef.current = null;
            setPendingConversationId(null);
          }
          // If sessionEndedRef is false, the session is still active - don't reset
        }, 5000); // Wait 5 seconds for reconnection before cleaning up
      }
      // For transport close (tab backgrounding), do nothing - socket will reconnect
    };

    // Set up listeners. (There is no socket-level 'reconnect' event in socket.io-client
    // v3+ — it lives on the Manager — so a re-established connection arrives here as a
    // plain 'connect'.)
    socket.on('connect', handleConnect);
    socket.on('disconnect', handleDisconnect);

    const handleAgentEvent = (event: AgentEvent) => {
      // Route by session when possible: events are stamped with session_id by
      // the backend, letting parallel conversations receive their own streams.
      const eventSessionId = (event as any).session_id as string | undefined;
      const eventConvId = eventSessionId ? sessionConversationRef.current.get(eventSessionId) : undefined;
      if (event.type === 'session_ended' && eventConvId) {
        pendingConvsRef.current.delete(eventConvId);
      }
      console.log('[useAgentChat] Received agent_event:', event.type, event.agent, event.content?.substring(0, 50));

      // Reset the round-trip stall timer on every event we receive.
      // - First event clears the 30s "first-answer" timeout.
      // - Subsequent events keep extending a 90s "between-events" stall
      //   timeout so a long-running agent stays alive but a fully silent
      //   socket eventually unsticks the UI.
      const isTerminal = event.type === 'session_ended' || event.type === 'complete';
      if (!isTerminal) {
        firstEventReceivedRef.current = true;
        if (waitingNoticeRef.current) {
          waitingNoticeRef.current = false;
          setError(null); // clear our own "Waiting for the server…" notice
        }
        if (ackRetryTimeoutRef.current) {
          clearTimeout(ackRetryTimeoutRef.current);
          ackRetryTimeoutRef.current = null;
        }
        if (processingTimeoutRef.current) {
          clearTimeout(processingTimeoutRef.current);
        }
        processingTimeoutRef.current = setTimeout(() => {
          console.warn('[@useAgentChat] Stall timeout (90s since last event) - auto-unsticking');
          setIsProcessing(false);
          setError('Agent stopped responding. Please try again.');
          pendingConversationIdRef.current = null;
          setPendingConversationId(null);
        }, 90 * 1000);
      }

      // 🆕 NEW: Detect AI agent device control tool RESULTS (not calls - we need to wait for success)
      // When AI successfully takes/releases control, notify parent to sync device state
      if (event.type === 'tool_result' && event.tool_name && event.success === true) {
        const toolName = event.tool_name.toLowerCase();
        const artifact = (event.tool_result as any)?.artifact;
        if (artifact?.content_type && onUIActionRef.current) {
          onUIActionRef.current('show_content', artifact);
        }
        
        // Check for take_control success (matches "take_control" or "mcp_virtualpytest_take_control")
        if (toolName === 'take_control' || toolName === 'mcp_virtualpytest_take_control') {
          console.log('[useAgentChat] 🎥 AI agent took control successfully!');
          console.log('[useAgentChat] Tool result:', event.tool_result);
          
          // Extract params from tool_result JSON string
          let hostName = '';
          let deviceId = 'device1';
          
          try {
            // Parse tool_result to get host_name and device_id
            const toolResult = event.tool_result as any;
            const resultContent = toolResult?.content?.[0]?.text;
            if (resultContent) {
              const resultData = JSON.parse(resultContent);
              hostName = resultData.host_name || '';
              deviceId = resultData.device_id || 'device1';
              console.log('[useAgentChat] Extracted from result:', { hostName, deviceId });
            }
          } catch (err) {
            console.warn('[useAgentChat] Failed to parse tool_result, trying tool_params:', err);
            // Fallback to tool_params if available
            hostName = (event.tool_params?.host_name as string) || '';
            deviceId = (event.tool_params?.device_id as string) || 'device1';
          }
          
          if (hostName && onDeviceControlChangeRef.current) {
            console.log('[useAgentChat] ✅ Notifying parent to show device panel:', { hostName, deviceId });
            onDeviceControlChangeRef.current(hostName, deviceId, true);
            activeDeviceControlRef.current = { host: hostName, deviceId };
          } else {
            console.warn('[useAgentChat] ⚠️ Missing hostName, cannot show panel');
          }
        }
        // Check for release_control success
        else if (toolName === 'release_control' || toolName === 'mcp_virtualpytest_release_control') {
          console.log('[useAgentChat] 🔌 AI agent released control successfully!');
          
          // Extract params from tool_result
          let hostName = '';
          let deviceId = 'device1';
          
          try {
            const toolResult = event.tool_result as any;
            const resultContent = toolResult?.content?.[0]?.text;
            if (resultContent) {
              const resultData = JSON.parse(resultContent);
              hostName = resultData.host_name || '';
              deviceId = resultData.device_id || 'device1';
            }
          } catch {
            hostName = (event.tool_params?.host_name as string) || '';
            deviceId = (event.tool_params?.device_id as string) || 'device1';
          }
          
          if (!hostName && activeDeviceControlRef.current) {
            hostName = activeDeviceControlRef.current.host;
          }
          if (hostName && onDeviceControlChangeRef.current) {
            console.log('[useAgentChat] ✅ Notifying parent to hide device panel:', { hostName, deviceId });
            onDeviceControlChangeRef.current(hostName, deviceId, false);
          }
          activeDeviceControlRef.current = null;
        }
      }
      
      // Helper to save current events as a message
      const saveCurrentEventsAsMessage = (agentName: string, eventsToSave: AgentEvent[]) => {
        const uniqueEventsToSave = dedupeEvents(eventsToSave);
        const messageResultEvents = uniqueEventsToSave.filter(e => 
          e.type === 'message' || e.type === 'result'
        );
        const errorEvents = uniqueEventsToSave.filter(e => e.type === 'error');
        const toolCallEvents = uniqueEventsToSave.filter(e => e.type === 'tool_call');
        
        // Nothing meaningful to save - no messages, errors, or tools
        if (messageResultEvents.length === 0 && errorEvents.length === 0 && toolCallEvents.length === 0) {
          return;
        }
        
        // Build content: prioritize error messages if present
        let accumulatedContent = '';
        if (errorEvents.length > 0) {
          // Extract error content from error events (content has the human-readable message)
          accumulatedContent = errorEvents
            .map(e => e.content || 'An error occurred')
            .filter(Boolean)
            .join('\n\n');
        } else {
          accumulatedContent = messageResultEvents
            .map(e => e.content)
            .filter(Boolean)
            .join('\n\n');
        }
        
        const newMessage: Message = {
          id: `${Date.now()}-${Math.random()}`,
          role: 'agent',
          content: accumulatedContent || `${agentName} completed`,
          agent: agentName,
          timestamp: new Date().toISOString(),
          events: uniqueEventsToSave,
          // Wall-clock timing captured at finalize. Lives on the message so it
          // survives page refresh (conversations are localStorage-persisted)
          // and is shipped with copyMessage + feedback POSTs.
          // - `answer_elapsed_ms` = Date.now() - turnStartedAt at finalize.
          //   If turnStartedAt is null (e.g. background-only path), we fall
          //   back to the message timestamp so we never log `undefined`.
          // - `thinking_elapsed_ms` = lastThinkingAt - firstThinkingStartedAt
          //   when at least one thinking chunk arrived; `null` otherwise.
          // - `thinking_chunks` is the rolling buffer (already relative to
          //   turn start) the accumulator built up live.
          timing: (() => {
            const nowMs = Date.now();
            const turnStart = turnStartedAtRef.current;
            const firstThinking = firstThinkingStartedAtRef.current;
            const lastThinking = lastThinkingAtRef.current;
            return {
              turn_started_at: turnStart ?? undefined,
              first_thinking_started_at: firstThinking ?? undefined,
              last_thinking_at: lastThinking ?? undefined,
              answer_elapsed_ms: turnStart != null ? Math.max(0, nowMs - turnStart) : undefined,
              thinking_elapsed_ms:
                firstThinking != null && lastThinking != null
                  ? Math.max(0, lastThinking - firstThinking)
                  : undefined,
              thinking_chunks: thinkingChunksRef.current.length > 0
                ? [...thinkingChunksRef.current]
                : undefined,
            };
          })(),
        };

        const targetConvoId = eventConvId ?? pendingConversationIdRef.current;
        if (targetConvoId) {
          setConversations(prev => prev.map(c => {
            if (c.id !== targetConvoId) return c;
            const updatedMessages = [...c.messages, newMessage];
            return {
              ...c,
              messages: updatedMessages,
              title: extractTitle(updatedMessages),
              updatedAt: new Date().toISOString(),
            };
          }));
        }

        // Console-log the timing so the dev console / browser log capture picks
        // it up automatically; this is the "data is gold" path the user asked
        // for — every successful turn leaves a structured timing row in the
        // session log without needing a server round-trip.
        console.log('[useAgentChat] ⏱ Turn timing', {
          conversation: targetConvoId,
          messageId: newMessage.id,
          answer_elapsed_ms: newMessage.timing?.answer_elapsed_ms,
          thinking_elapsed_ms: newMessage.timing?.thinking_elapsed_ms,
          thinking_chunks: newMessage.timing?.thinking_chunks?.length ?? 0,
        first_thinking_started_at: newMessage.timing?.first_thinking_started_at,
          last_thinking_at: newMessage.timing?.last_thinking_at,
        });
      };
      
      // Debug: Log every event received
      console.log(`[useAgentChat] Event received: type=${event.type}, agent=${event.agent}, task_id=${event.task_id}, dry_run=${event.dry_run}`);
      console.log(`[useAgentChat] Full event:`, JSON.stringify(event, null, 2));
      
      // Handle background agent events (any agent with background_queues config)
      // The handler checks if the event.agent is a background agent
      if (event.agent && handleBackgroundEvent(event)) {
        console.log(`[useAgentChat] Background event handled for agent: ${event.agent}`);

        // For interactive experience: show a brief summary message in main conversation
        // when background analysis completes, but don't show the detailed analysis
        if (event.type === 'message' && event.agent) {
          // Try to find the correct conversation for this analysis
          let targetConversationId = pendingConversationIdRef.current;

          // First try direct mapping
          if (event.task_id) {
            const mappedConversationId = scriptConversationMapRef.current.get(event.task_id);
            if (mappedConversationId) {
              targetConversationId = mappedConversationId;
              console.log(`[useAgentChat] 🎯 Found mapped conversation ${targetConversationId} for script ${event.task_id}`);
            }
          }

          // If no direct mapping, find the most recent conversation with script execution
          if (!targetConversationId || targetConversationId === pendingConversationIdRef.current) {
            const recentScriptConvo = conversations
              .filter(c => c.messages.some(m => m.content?.includes('execute_script') || m.content?.includes('script execution')))
              .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())[0];

            if (recentScriptConvo) {
              targetConversationId = recentScriptConvo.id;
              console.log(`[useAgentChat] 📋 Using most recent script conversation ${targetConversationId} for analysis`);
            }
          }

          const summaryMessage: Message = {
            id: `bg-summary-${Date.now()}`,
            role: 'agent',
            content: `**${event.agent}** analyzed the execution result`,
            agent: event.agent, // Use the actual agent nickname (e.g., 'Sherlock')
            timestamp: new Date().toISOString(),
            events: [],
          };

          setConversations(prev => prev.map(c => {
            if (c.id === targetConversationId) {
              return {
                ...c,
                messages: [...c.messages, summaryMessage],
                updatedAt: new Date().toISOString(),
              };
            }
            return c;
          }));
        }

        // Don't add the full background event details to main conversation
        return;
      } else if (event.agent) {
        console.log(`[useAgentChat] Event NOT handled as background (agent: ${event.agent})`);
      }
      
      // TASK-175: the server handed this turn to another agent (script work goes to Forge): the page
      // switches its agent so the follow-ups go there too.
      if (event.type === 'agent_delegated' && event.metrics?.handoff_to) {
        setAgentHandoff({ agentId: event.metrics.handoff_to, at: Date.now() });
      }

      // Track mode
      if (event.type === 'mode_detected') {
        setSession(prev => prev ? { ...prev, mode: event.content.split(': ')[1] } : null);
      }

      // The agent went on after a failed tool call (successful tool result or an answer): the
      // earlier error banner is stale. The failed step itself stays in the message history.
      // An error with no later success (turn failed) is never cleared here.
      const recovered = (event.type === 'tool_result' && event.success !== false) || (event.type === 'message' && !!event.content);
      if (recovered && recoverableErrorRef.current !== null) {
        const stale = recoverableErrorRef.current;
        recoverableErrorRef.current = null;
        setError(prev => (prev === stale ? null : prev));
      }

      // Accumulate events for current agent
      if (event.type !== 'session_ended' && event.type !== 'complete') {
        // Capture wall-clock timing for the reasoning stream before we push the
        // event into currentEvents, so the live "Reasoning" timer in the header
        // and the live "answer elapsed" counter are both reading consistent
        // timestamps on every render.
        // - First thinking chunk of the turn stamps `firstThinkingStartedAt`
        //   (used as the reasoning timer origin) and seeds `lastThinkingAt`.
        // - Every subsequent thinking chunk refreshes `lastThinkingAt` and
        //   appends to `thinkingChunks` so we can replay the model rhythm.
        // The accumulator block below then sees the same event; nothing else
        // needs to know about timing.
        if (event.type === 'thinking') {
          const nowMs = Date.now();
          const tsFromStart = turnStartedAtRef.current != null
            ? Math.max(0, nowMs - turnStartedAtRef.current)
            : 0;
          if (firstThinkingStartedAtRef.current == null) {
            firstThinkingStartedAtRef.current = nowMs;
            setFirstThinkingStartedAt(nowMs);
          }
          lastThinkingAtRef.current = nowMs;
          setLastThinkingAt(nowMs);
          thinkingChunksRef.current = [
            ...thinkingChunksRef.current,
            { at_ms: tsFromStart, length: (event.content || '').length },
          ];
        }

        setCurrentEvents(prev => {
          const eventKey = getEventDedupKey(event);
          if (prev.some(existing => getEventDedupKey(existing) === eventKey)) {
            console.log('[useAgentChat] Duplicate semantic event ignored:', event.type, event.tool_name || event.content?.substring(0, 50));
            return prev;
          }

          const newEvents = [...prev, event];
          console.log(`[useAgentChat] Accumulated ${newEvents.length} events for current agent`);
          return newEvents;
        });
      }

      const isTerminalEvent = event.type === 'session_ended' || event.type === 'complete';
      if (isTerminalEvent) {
        // Duplicate detection must be PER SESSION: with parallel conversations,
        // a second thread's legitimate session_ended arrived after the first
        // thread set the global flag and was discarded as a "duplicate" — its
        // answer was never saved.
        if (eventSessionId) {
          if (endedSessionsRef.current.has(eventSessionId)) {
            console.log('[useAgentChat] Duplicate terminal event ignored (session):', eventSessionId);
            return;
          }
          endedSessionsRef.current.add(eventSessionId);
        } else if (sessionEndedRef.current) {
          console.log('[useAgentChat] Duplicate terminal event ignored:', event.type);
          return;
        }
      }

      // Session ends: save any remaining events as final message
      if (isTerminalEvent) {
        console.log(`[useAgentChat] SESSION_ENDED - finalizing conversation`, eventConvId || '(unmapped)');
        const endsPendingConversation = !eventConvId || eventConvId === pendingConversationIdRef.current;
        if (endsPendingConversation) {
          sessionEndedRef.current = true; // Mark that session properly ended
          setIsProcessing(false);
          if (processingTimeoutRef.current) {
            clearTimeout(processingTimeoutRef.current);
            processingTimeoutRef.current = null;
          }
        }

        setCurrentEvents(prevEvents => {
          if (prevEvents.length > 0) {
            // Use event.agent if available, otherwise use session's active agent
            const finalAgent = event.agent || session?.active_agent || 'System';
            saveCurrentEventsAsMessage(finalAgent, prevEvents);
          }

          // Clear pending conversation only if this terminal belongs to it
          if (endsPendingConversation) {
            pendingConversationIdRef.current = null;
            setPendingConversationId(null);
            setSession(prev => prev ? { ...prev, active_agent: undefined } : null);
          }

          return [];
        });
      }
      
      // Handle ERROR events immediately - show them to user right away
      if (event.type === 'error') {
        console.error('[@useAgentChat] Agent ERROR event:', event);
        const message = event.content || 'An error occurred';
        recoverableErrorRef.current = message;
        setError(message);
        // Don't stop processing - some errors are recoverable
        // But show them immediately to the user
      }

      // Note: Don't stop processing on error events - tool errors are recoverable
      // The agent will continue and try other approaches
      // Only session_ended or complete should stop processing
    };

    // Register via SocketContext's shared event router (instead of socket.on)
    registerEventHandler('agentchat', handleAgentEvent);

    // Listen for ui_action events from AI agent
    const handleUiAction = (data: any) => {
      console.log('[useAgentChat] Received ui_action:', data);

      if (onUIActionRef.current) {
        onUIActionRef.current(data.action, data.payload);
      }
    };

    // Listen for slack messages
    const handleSlackMessage = (event: any) => {
      console.log('[useAgentChat] Slack Message Received:', event);

      // Show toast notification
      window.dispatchEvent(new CustomEvent('agent-toast', {
        detail: {
          message: `Slack: ${event.content?.substring(0, 50)}${event.content?.length > 50 ? '...' : ''}`,
          severity: 'info'
        }
      }));

      // Dispatch custom event so AgentChat can handle the message
      window.dispatchEvent(new CustomEvent('slack-message-received', {
        detail: {
          content: event.content,
          slackUserId: event.slack_user_id,
          threadTs: event.thread_ts,
          source: 'slack'
        }
      }));
    };

    const handleSocketError = (data: any) => {
      const errorMessage = data.type
        ? `${data.type}: ${data.error}`
        : data.error || 'Unknown error occurred';
      console.error('[@useAgentChat] Socket error:', errorMessage);
      setError(errorMessage);
      setIsProcessing(false);
    };

    socket.on('ui_action', handleUiAction);
    socket.on('slack_message', handleSlackMessage);
    socket.on('error', handleSocketError);

    return () => {
      socket.off('connect', handleConnect);
      socket.off('disconnect', handleDisconnect);
      unregisterEventHandler('agentchat');
      socket.off('ui_action', handleUiAction);
      socket.off('slack_message', handleSlackMessage);
      socket.off('error', handleSocketError);
    };
  }, [socket, session?.id]);

  // --- Session Management ---

  // --- Session Management ---

  const initializeSession = useCallback(async () => {
    try {
      // Use shared session from SocketContext (same session as AIContext/Cmd+K)
      const sid = await sharedInitSession();
      if (sid) {
        setSession({ id: sid } as any);
        connect(); // Ensure socket is connected
      }
    } catch (err) {
      console.error('Failed to initialize session:', err);
      setStatus('error');
    }
  }, [sharedInitSession, connect]);

  // --- Check Connectivity & Auth ---

  // Auth is "ready" once AuthContext has finished its initial pass: either a
  // Supabase session was restored (or none exists) or the auto-sign token from
  // ?auto_signed=<token> has been stored. AuthContext stores that token inside
  // its own effect, which runs AFTER this hook's effects (children first), so
  // firing the health call on mount raced it and always 401'd on prod.
  // In open mode (no Supabase configured) nothing gates the call.
  const isAuthReady = !isAuthEnabled || (!isAuthLoading && isAuthenticated);
  const connectionCheckedRef = useRef(false);
  // BUG-0350: the health check retries with bounded backoff while the server is down (restart /
  // deploy), instead of freezing the page in 'error'. attemptHealthRef lets a socket reconnect
  // trigger an immediate retry; it is null when no check is pending.
  const healthRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptHealthRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!isAuthReady || connectionCheckedRef.current) return;
    connectionCheckedRef.current = true;
    let cancelled = false;
    let attempt = 0;
    let retrying = false;

    const scheduleRetry = () => {
      // 1,2,4,8,15,15… s — keep going while mounted, same spirit as the BUG-0340 send wait.
      const delay = Math.min(1000 * 2 ** attempt, 15000);
      attempt += 1;
      retrying = true;
      setStatus('checking');
      setError('Reconnecting to the server…');
      healthRetryTimerRef.current = setTimeout(() => {
        healthRetryTimerRef.current = null;
        checkConnection();
      }, delay);
    };

    const checkConnection = async () => {
      if (cancelled) return;
      try {
        const response = await apiClient(buildServerUrl('/server/agent/health'), { method: 'GET' });
        if (cancelled) return;
        if (response.status === 401) {
          // Auth was ready when we fired, so a 401 is a real credential problem
          // (token rejected, session for another server, ...). Retrying will not
          // change the answer — surface it once and stop.
          console.warn('[useAgentChat] Agent health check rejected (401) - not retrying');
          attemptHealthRef.current = null;
          setStatus('error');
          setError('Not authorized on this server - sign in again or select an authenticated server');
          return;
        }
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        if (cancelled) return;
        attemptHealthRef.current = null;
        if (retrying) setError(null); // clear our own "Reconnecting…" notice
        retrying = false;
        setActiveProvider(data.provider || '');
        setActiveModel(data.model || '');
        setActiveEndpoint(data.endpoint || '');

        // The endpoint key is a server-side secret (Settings → AI → Endpoints); the
        // browser never stores or re-sends it.
        if (data.api_key_configured) {
          setStatus('ready');
          initializeSession();
        } else {
          setStatus('needs_key');
          if (data.error) setError(data.error);
          // Re-ask quietly: a key set elsewhere (Settings, another tab), or a one-off "no key"
          // answer, must not leave the popup up until a reload.
          healthRetryTimerRef.current = setTimeout(() => {
            healthRetryTimerRef.current = null;
            checkConnection();
          }, 15000);
        }
      } catch (err) {
        if (cancelled) return;
        console.error('Connection check failed:', err);
        if (healthRetryTimerRef.current) return; // a retry is already queued
        scheduleRetry();
      }
    };

    attemptHealthRef.current = () => {
      if (!retrying || !healthRetryTimerRef.current) return;
      clearTimeout(healthRetryTimerRef.current);
      healthRetryTimerRef.current = null;
      checkConnection();
    };
    checkConnection();

    return () => {
      cancelled = true;
      attemptHealthRef.current = null;
      if (healthRetryTimerRef.current) {
        clearTimeout(healthRetryTimerRef.current);
        healthRetryTimerRef.current = null;
      }
      connectionCheckedRef.current = false; // allow a StrictMode remount to start its own check
    };
  }, [isAuthReady, initializeSession]);

  // Cheap recovery signal: the shared socket (re)connected while the health check is still
  // retrying -> the server is back, check now instead of waiting out the backoff.
  useEffect(() => {
    if (isConnected) attemptHealthRef.current?.();
  }, [isConnected]);

  // --- Actions ---

  const saveApiKey = useCallback(async () => {
    if (!apiKeyInput.trim()) {
      setError('Invalid Key');
      return;
    }
    
    setIsValidating(true);
    setError(null);
    
    try {
      // Stores the key for the endpoint serving this agent (server default) after a live check.
      const response = await apiClient(buildServerUrl('/server/agent/api-key'), {
        method: 'POST',
        body: JSON.stringify({ api_key: apiKeyInput.trim(), agent_id: agentIdRef.current || 'assistant' }),
      });
      if (response.status === 403) {
        setError('Only the platform admin can set AI keys (Settings → AI → Endpoints).');
        setIsValidating(false);
        return;
      }
      const data = await response.json().catch(() => ({}));

      if (response.ok && data.success) {
        if (healthRetryTimerRef.current) {
          clearTimeout(healthRetryTimerRef.current);
          healthRetryTimerRef.current = null;
        }
        setApiKeyInput('');
        localStorage.setItem('virtualpytest_ai_status', 'ready');
        setActiveProvider(data.provider || activeProvider);
        setActiveModel(data.model || activeModel);
        setActiveEndpoint(data.endpoint || activeEndpoint);
        setStatus('ready');
        setIsValidating(false);
        initializeSession();
      } else {
        setError(data.error || data.message || 'Failed to validate API key');
        setIsValidating(false);
      }
    } catch (err) {
      console.error('Failed to save API key:', err);
      setError('Failed to save API key - check server connection');
      setIsValidating(false);
    }
  }, [activeEndpoint, activeModel, activeProvider, apiKeyInput, initializeSession]);

  // Track retry attempts to prevent infinite loops
  const sendMessageRetryCountRef = useRef(0);
  const RECONNECT_WAIT_MS = 60_000;
  const SESSION_CREATE_TIMEOUT_MS = 10_000;
  const SLOW_NOTICE_MS = 3_000;
  const reconnectWaitStartRef = useRef<number | null>(null);
  // BUG-0401: a send is in its session-create step (blocks a second Enter from starting a parallel loop),
  // and the "Waiting for the server…" notice (ack watchdog) is on screen.
  const sendInFlightRef = useRef(false);
  const waitingNoticeRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendMessageRef = useRef<((m?: string) => Promise<void>) | null>(null);

  // Voice audio path (TASK-140 Q5): a command a speech model already picked rides on the next send, once;
  // Atlas's quick step checks it and runs it in this session instead of asking its own model.
  const quickHintRef = useRef<{ tool: string; args: Record<string, unknown> } | null>(null);
  const setQuickHint = useCallback((hint: { tool: string; args: Record<string, unknown> } | null) => {
    quickHintRef.current = hint;
  }, []);

  const sendMessage = useCallback(async (directMessage?: string) => {
    // Guard against being wired directly to onClick/onKeyDown — React would pass
    // a SyntheticEvent as the first arg, which socket.io's hasBinary would
    // recurse into and blow the stack.
    const messageToSend = typeof directMessage === 'string' ? directMessage : input.trim();
    console.log('[useAgentChat] sendMessage called:', {
      input: messageToSend,
      isProcessing,
      sessionId: session?.id,
      socketConnected: socket?.connected,
      status,
      retryCount: sendMessageRetryCountRef.current
    });

    if (!messageToSend) {
      console.log('[useAgentChat] sendMessage blocked: no input');
      return;
    }
    // Block only if THIS conversation is still processing — other conversations
    // run on their own sessions and may proceed in parallel. (The old global
    // isProcessing guard silently dropped sends from a second chat thread.)
    const prospectiveTarget = activeConversationId && !activeConversationId.startsWith('bg_') ? activeConversationId : null;
    if (prospectiveTarget && pendingConvsRef.current.has(prospectiveTarget)) {
      console.log('[useAgentChat] sendMessage blocked: this conversation is still processing');
      setError('This chat is still processing — wait for the answer or start a New Chat.');
      return;
    }

    // Server restart / network blip: the socket (and the session id after a re-init) is briefly
    // unavailable. Keep the typed text and poll — through a ref to the LATEST sendMessage, a retry
    // closing over this render's stale socket/isConnected could never see the reconnect — for up to
    // RECONNECT_WAIT_MS, showing "Reconnecting…", then fail with a visible error.
    if (!session?.id || !socket || !isConnected || !socket.connected) {
      const startedAt = reconnectWaitStartRef.current ?? Date.now();
      reconnectWaitStartRef.current = startedAt;
      if (Date.now() - startedAt >= RECONNECT_WAIT_MS) {
        reconnectWaitStartRef.current = null;
        setError('Unable to reach the server. Your message was not sent — check the connection and press Enter to retry.');
        return;
      }
      if (!reconnectTimerRef.current) {
        setError('Reconnecting to the server… your message will be sent as soon as it is back.');
        connect(); // Ensure socket exists / reconnects
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          sendMessageRef.current?.(messageToSend);
        }, 1000);
      }
      return;
    }
    reconnectWaitStartRef.current = null;

    // Reset retry count on successful socket availability
    sendMessageRetryCountRef.current = 0;

    // Create new conversation if none exists OR if active conversation is a background/system one
    // Background conversations (bg_*) are read-only system views - user messages should go to regular chats
    let targetConvoId = activeConversationId;
    if (!targetConvoId || targetConvoId.startsWith('bg_')) {
      const newConvo: Conversation = {
        id: generateId(),
        title: 'New Chat',
        messages: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      setConversations(prev => [newConvo, ...prev]);
      setActiveConversationId(newConvo.id);
      activeConversationIdRef.current = newConvo.id; // Immediately update ref
      targetConvoId = newConvo.id;
    }

    // Ensure this conversation has its OWN backend session (parallel threads
    // must not share one session: interleaved histories + one event room).
    // Done BEFORE the bubble/pending state so a failure leaves the input intact for a resend.
    let convSessionId = conversationSessionRef.current.get(targetConvoId);
    if (!convSessionId) {
      if (sendInFlightRef.current) return; // the first Enter is still creating the session
      sendInFlightRef.current = true;
      // BUG-0401: every request is bounded (SESSION_CREATE_TIMEOUT_MS) so a server that accepts the
      // TCP connection but never answers (restart stuck in stop-sigterm) feeds the retry loop instead
      // of hanging forever, and "Reconnecting…" shows once a try is slow (SLOW_NOTICE_MS), not only
      // after it fails. Retries run inside the same RECONNECT_WAIT_MS budget as the socket wait.
      const deadline = Date.now() + RECONNECT_WAIT_MS;
      const NOTICE = 'Reconnecting to the server… your message will be sent as soon as it is back.';
      const noticeTimer = setTimeout(() => setError(NOTICE), SLOW_NOTICE_MS);
      let lastErr: unknown = null;
      try {
        for (let attempt = 0; !convSessionId && Date.now() < deadline; attempt++) {
          if (attempt > 0) {
            setError(NOTICE);
            await new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** (attempt - 1), 5000)));
          }
          const ctrl = new AbortController();
          let hangTimer: ReturnType<typeof setTimeout> | undefined;
          try {
            const hang = new Promise<never>((_, reject) => {
              hangTimer = setTimeout(() => { ctrl.abort(); reject(new Error('session create timed out')); }, SESSION_CREATE_TIMEOUT_MS);
            });
            const call = (async () => {
              const resp = await fetch(buildServerUrl('/server/agent/sessions'), { method: 'POST', signal: ctrl.signal });
              return { resp, data: await resp.json() };
            })();
            call.catch(() => {}); // the loser of the race must not surface as unhandled
            const { resp, data } = await Promise.race([call, hang]);
            if (data.success && data.session?.id) {
              convSessionId = data.session.id as string;
            } else {
              lastErr = new Error(data.error || `HTTP ${resp.status}`);
            }
          } catch (e) {
            lastErr = e;
          } finally {
            if (hangTimer) clearTimeout(hangTimer);
          }
        }
      } finally {
        clearTimeout(noticeTimer);
        sendInFlightRef.current = false;
      }
      if (!convSessionId) {
        console.error('[useAgentChat] Session create failed within budget', lastErr);
        setError('Unable to reach the server. Your message was not sent — check the connection and press Enter to retry.');
        return;
      }
      setError((prev) => (prev && prev.startsWith('Reconnecting') ? null : prev));
      conversationSessionRef.current.set(targetConvoId, convSessionId);
      sessionConversationRef.current.set(convSessionId, targetConvoId);
      // Registered with SocketContext so the room survives a reconnect mid-answer:
      // the reply is delivered to THIS session's room, not the shared one.
      joinSession(convSessionId);
    }

    const userMsg: Message = {
      id: `${Date.now()}-user`,
      role: 'user',
      content: messageToSend,
      timestamp: new Date().toISOString(),
    };

    // Add user message to conversation
    setConversations(prev => prev.map(c => {
      if (c.id !== targetConvoId) return c;
      const updatedMessages = [...c.messages, userMsg];
      return {
        ...c,
        messages: updatedMessages,
        title: extractTitle(updatedMessages),
        updatedAt: new Date().toISOString(),
      };
    }));

    // Track which conversation is awaiting response (for when user switches chats)
    pendingConversationIdRef.current = targetConvoId;
    setPendingConversationId(targetConvoId);
    pendingConvsRef.current.add(targetConvoId);

    setInput('');
    setIsProcessing(true);
    setCurrentEvents([]);
    setError(null);
    recoverableErrorRef.current = null;
    sessionEndedRef.current = false; // Reset for new message - session is active
    // Sessions are reused across messages of a conversation, so the per-session
    // terminal guard must be re-armed on every send — otherwise this turn's
    // legitimate session_ended is discarded as a duplicate of the previous
    // turn's and the answer is never finalized (stuck "..." indicator).
    if (convSessionId) endedSessionsRef.current.delete(convSessionId);
    firstEventReceivedRef.current = false; // Reset for new round-trip
    // Wall-clock timer for this turn. Captured AFTER the setIsProcessing(true)
    // so the very first frame the UI renders already has a non-null value.
    // Resets on every send (parallels firstEventReceivedRef).
    const turnStart = Date.now();
    turnStartedAtRef.current = turnStart;
    setTurnStartedAt(turnStart);
    firstThinkingStartedAtRef.current = null;
    setFirstThinkingStartedAt(null);
    lastThinkingAtRef.current = null;
    setLastThinkingAt(null);
    thinkingChunksRef.current = [];

    // Tight first-answer timeout: if the agent emits NOTHING within 30s
    // (no thinking/tool_call/tool_result/message at all), assume the
    // round-trip is dead and unstick the UI so the user isn't blocked.
    // Once the first event arrives, this timer is cleared and replaced
    // by a longer between-events stall timer (see handleAgentEvent).
    if (processingTimeoutRef.current) {
      clearTimeout(processingTimeoutRef.current);
    }
    processingTimeoutRef.current = setTimeout(() => {
      if (firstEventReceivedRef.current) return; // already streaming, nothing to do
      console.warn('[@useAgentChat] First-answer timeout (30s) - auto-unsticking');
      setIsProcessing(false);
      setError('No response from agent within 30s. Please try again.');
      pendingConversationIdRef.current = null;
      setPendingConversationId(null);
    }, 30 * 1000);

    console.log('[useAgentChat] About to emit send_message via shared SocketContext');

    // Never send a host that is not one of the selected server's hosts (stale Target after a server switch).
    // In All servers mode the host may belong to any server.
    const allServersMode = isAllServersSentinel(selectedServer);
    const serverHostNames = (allServersMode
      ? serverHostsData.flatMap((entry) => entry.hosts)
      : serverHostsData.find((entry) => entry.server_info.server_url === selectedServer)?.hosts || []
    ).map((host) => host.host_name);
    const hostInServer = !!hostNameRef.current && serverHostNames.includes(hostNameRef.current);
    // TASK-179 P4: the user's login for this turn (read fresh, sent once, never kept) and the picker's scope.
    const turnScope = buildTurnScope(selectedServer, serverHostsData, hostInServer ? hostNameRef.current : '');
    const turnAuth = await buildTurnAuth();

    const sendContext = {
      // BUG-0401: one id per user send; the ack-watchdog resend carries the same id so the server
      // processes the message once even when the first copy did arrive but its ack was lost.
      client_msg_id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      team_id: APP_CONFIG.DEFAULT_TEAM_ID,
      allow_auto_navigation: allowAutoNavigationRef.current,
      current_page: currentPageRef.current,
      host_name: hostInServer ? hostNameRef.current : '',
      device_id: hostInServer ? deviceIdRef.current : '',
      userinterface_name: userinterfaceRef.current,
      testcase_id: (allowAutoNavigationRef as any).currentTestcaseId || '',
      campaign_id: (allowAutoNavigationRef as any).currentCampaignId || '',
      workspace_id: activeWorkspace?.id || '',
      selected_server: selectedServer || '',
      selected_server_name: serverHostsData.find((entry) => entry.server_info.server_url === selectedServer)?.server_info.server_name || '',
      selected_server_hosts: serverHostNames,
      ...turnScope,
      ...(turnAuth.token || turnAuth.auto_sign ? { turn_auth: turnAuth } : {}),
      // The app's own Grafana base: lets the answer carry a link that opens, whichever server answers.
      grafana_base_url: getEnv('VITE_GRAFANA_URL'),
      available_devices: (allowAutoNavigationRef as any).availableDevices || [],
      available_userinterfaces: (allowAutoNavigationRef as any).availableUserinterfaces || [],
      // Atlas model picker: pin this session to a single profile from the chain (primary
      // or any fallback). Empty string = clear the pin and let the chain run normally.
      pinned_profile_id: pinnedProfileIdRef.current || '',
      // Atlas Companion: the page it shows right now ("Companion: Test Reports — host=…").
      companion: companionRef.current,
      ...(quickHintRef.current ? { quick_hint: quickHintRef.current } : {}),
    };
    quickHintRef.current = null;

    // Emit on this conversation's session (falls back to the shared session)
    const sent = sharedEmitSendMessage(messageToSend, agentIdRef.current || 'assistant', sendContext, convSessionId);

    if (!sent) {
      console.error('[useAgentChat] Shared socket refused send');
      setIsProcessing(false);
      setError('Agent connection is not ready yet. Please try again.');
      pendingConversationIdRef.current = null;
      setPendingConversationId(null);
      return;
    }

    // Reset retry count on successful message send
    sendMessageRetryCountRef.current = 0;

    // Ack watchdog: the backend emits an immediate 'thinking' ack, so a healthy
    // round-trip delivers the first event within ~1s. If NOTHING arrives in 4s
    // the socket is almost certainly half-dead (claims connected, downlink or
    // uplink black-holed after laptop sleep / NAT idle timeout). Recycle the
    // socket and resend once, transparently — instead of letting the 30s
    // watchdog surface an error for a self-healable condition.
    if (ackRetryTimeoutRef.current) clearTimeout(ackRetryTimeoutRef.current);
    ackRetriedRef.current = false;
    ackRetryTimeoutRef.current = setTimeout(() => {
      if (firstEventReceivedRef.current || ackRetriedRef.current) return;
      ackRetriedRef.current = true;
      console.warn('[useAgentChat] No ack within 4s — recycling socket and resending');
      waitingNoticeRef.current = true;
      setError('Waiting for the server… your message will be re-sent automatically.');
      forceReconnect();
      // Reconnecting through the proxy/Cloudflare can take several seconds —
      // retry the resend until the socket is actually up (max ~9s, still well
      // inside the 30s last-resort watchdog).
      const attemptResend = (attempt: number) => {
        if (firstEventReceivedRef.current) return; // events arrived meanwhile
        const resent = sharedEmitSendMessage(messageToSend, agentIdRef.current || 'assistant', sendContext, convSessionId);
        console.warn(`[useAgentChat] Resend attempt ${attempt}: ${resent ? 'sent' : 'socket not ready yet'}`);
        if (!resent && attempt < 6) {
          setTimeout(() => attemptResend(attempt + 1), 1500);
        }
      };
      setTimeout(() => attemptResend(1), 1500);
    }, 4000);

    console.log('[useAgentChat] Message sent to backend');
  }, [input, isProcessing, session?.id, activeConversationId, socket, isConnected, connect, joinSession, activeWorkspace?.id, selectedServer, serverHostsData]);
  sendMessageRef.current = sendMessage;

  // Allow external code to set the agent
  const agentIdRef = useRef<string>('assistant');
  const setAgentId = useCallback((agentId: string) => {
    agentIdRef.current = agentId;
  }, []);

  // Atlas model picker: pin the next turn to a single profile from the model's chain
  // (primary or any fallback). Empty string = clear the pin (use the default chain).
  // Server-side: backend_server/src/agent/core/manager.py:_resolution honours this.
  const pinnedProfileIdRef = useRef<string>('');
  const companionRef = useRef<string>('');
  const setCompanionContext = useCallback((text: string) => {
    companionRef.current = text;
  }, []);
  const setPinnedProfileId = useCallback((profileId: string) => {
    pinnedProfileIdRef.current = profileId || '';
  }, []);

  // Navigation context refs (set by parent component)
  const allowAutoNavigationRef = useRef<boolean>(false);
  const currentPageRef = useRef<string>('/');
  const hostNameRef = useRef<string>('');
  const deviceIdRef = useRef<string>('');
  const userinterfaceRef = useRef<string>('');

  const setNavigationContext = useCallback((allowAutoNavigation: boolean, currentPage: string, hostName: string = '', deviceId: string = '', userinterface: string = '', testcaseId: string = '', campaignId: string = '', availableDevices: any[] = [], availableUserinterfaces: any[] = []) => {
    allowAutoNavigationRef.current = allowAutoNavigation;
    currentPageRef.current = currentPage;
    hostNameRef.current = hostName;
    deviceIdRef.current = deviceId;
    userinterfaceRef.current = userinterface;
    // Store additional context for AI agent
    (allowAutoNavigationRef as any).currentTestcaseId = testcaseId;
    (allowAutoNavigationRef as any).currentCampaignId = campaignId;
    (allowAutoNavigationRef as any).availableDevices = availableDevices;
    (allowAutoNavigationRef as any).availableUserinterfaces = availableUserinterfaces;
  }, []);

  const handleApproval = useCallback((approved: boolean) => {
    socket?.emit('approve', { session_id: session?.id, approved });
  }, [session?.id]);

  const stopGeneration = useCallback(() => {
    if (!session?.id) return;

    // Clear timeout failsafe
    if (processingTimeoutRef.current) {
      clearTimeout(processingTimeoutRef.current);
      processingTimeoutRef.current = null;
    }

    socket?.emit('stop_generation', { session_id: session.id });

    const targetConvoId = pendingConversationIdRef.current;

    // Capture timing snapshot at the moment of the stop so the partial message
    // also carries the elapsed values — without this, a user-cancelled turn
    // would leave the persisted message with no timing at all.
    const stopTimingSnapshot = (() => {
      const nowMs = Date.now();
      const turnStart = turnStartedAtRef.current;
      const firstThinking = firstThinkingStartedAtRef.current;
      const lastThinking = lastThinkingAtRef.current;
      return {
        turn_started_at: turnStart ?? undefined,
        first_thinking_started_at: firstThinking ?? undefined,
        last_thinking_at: lastThinking ?? undefined,
        answer_elapsed_ms: turnStart != null ? Math.max(0, nowMs - turnStart) : undefined,
        thinking_elapsed_ms:
          firstThinking != null && lastThinking != null
            ? Math.max(0, lastThinking - firstThinking)
            : undefined,
        thinking_chunks: thinkingChunksRef.current.length > 0
          ? [...thinkingChunksRef.current]
          : undefined,
      };
    })();

    // Save current events as a partial message before clearing
    setCurrentEvents(prevEvents => {
      if (targetConvoId && prevEvents.length > 0) {
        const uniquePrevEvents = dedupeEvents(prevEvents);
        // Build partial message from accumulated events
        const messageResultEvents = uniquePrevEvents.filter(e =>
          e.type === 'message' || e.type === 'result'
        );
        const toolCallEvents = uniquePrevEvents.filter(e => e.type === 'tool_call');

        // Only save if we have meaningful content
        if (messageResultEvents.length > 0 || toolCallEvents.length > 0) {
          const accumulatedContent = messageResultEvents
            .map(e => e.content)
            .filter(Boolean)
            .join('\n\n');

          // Get the active agent name from events or session
          const agentName = uniquePrevEvents.find(e => e.agent)?.agent || session?.active_agent || 'Agent';

          const partialMessage: Message = {
            id: `${Date.now()}-partial`,
            role: 'agent',
            content: accumulatedContent || '(partial response)',
            agent: agentName,
            timestamp: new Date().toISOString(),
            events: uniquePrevEvents,
            timing: stopTimingSnapshot,
          };
          
          setConversations(prev => prev.map(c => {
            if (c.id !== targetConvoId) return c;
            return {
              ...c,
              messages: [...c.messages, partialMessage, {
                id: `${Date.now()}-stop`,
                role: 'agent' as const,
                agent: 'System',
                content: 'Generation stopped by user.',
                timestamp: new Date().toISOString(),
              }],
              updatedAt: new Date().toISOString(),
            };
          }));
        } else {
          // No meaningful events, just add stop message
          setConversations(prev => prev.map(c => {
            if (c.id !== targetConvoId) return c;
            return {
              ...c,
              messages: [...c.messages, {
                id: `${Date.now()}-stop`,
                role: 'agent' as const,
                agent: 'System',
                content: 'Generation stopped by user.',
                timestamp: new Date().toISOString(),
              }],
              updatedAt: new Date().toISOString(),
            };
          }));
        }
      } else if (targetConvoId) {
        // No events but we have a conversation, just add stop message
        setConversations(prev => prev.map(c => {
          if (c.id !== targetConvoId) return c;
          return {
            ...c,
            messages: [...c.messages, {
              id: `${Date.now()}-stop`,
              role: 'agent' as const,
              agent: 'System',
              content: 'Generation stopped by user.',
              timestamp: new Date().toISOString(),
            }],
            updatedAt: new Date().toISOString(),
          };
        }));
      }
      
      return []; // Clear events after saving
    });

    setIsProcessing(false);

    // Clear pending conversation
    pendingConversationIdRef.current = null;
    setPendingConversationId(null);
    // Drop the live counters so the next send starts from a clean slate. The
    // captured snapshot lives on the persisted partial message above, so no
    // information is lost; we only stop the UI from showing a stale clock.
    turnStartedAtRef.current = null;
    setTurnStartedAt(null);
    firstThinkingStartedAtRef.current = null;
    setFirstThinkingStartedAt(null);
    lastThinkingAtRef.current = null;
    setLastThinkingAt(null);
    thinkingChunksRef.current = [];
    console.log('[useAgentChat] ⏱ Turn timing (user-stopped)', {
      conversation: targetConvoId,
      answer_elapsed_ms: stopTimingSnapshot.answer_elapsed_ms,
      thinking_elapsed_ms: stopTimingSnapshot.thinking_elapsed_ms,
      thinking_chunks: stopTimingSnapshot.thinking_chunks?.length ?? 0,
    });
  }, [session?.id, session?.active_agent]);

  const clearHistory = useCallback(() => {
    clearBackendSession(); // Fresh backend session
    clearDeviceControlPanel(); // Ensure device panel is removed when clearing chats
    
    // Preserve background agent conversations (prefix: bg_)
    setConversations(prev => {
      const backgroundConversations = prev.filter(c => c.id.startsWith('bg_'));
      
      // Update localStorage with only background conversations
      if (backgroundConversations.length > 0) {
        localStorage.setItem(STORAGE_KEY_CONVERSATIONS, JSON.stringify(backgroundConversations));
      } else {
        localStorage.removeItem(STORAGE_KEY_CONVERSATIONS);
      }
      
      return backgroundConversations;
    });
    
    // Clear active conversation if it was a regular one
    setActiveConversationId(prev => {
      if (prev && prev.startsWith('bg_')) {
        return prev; // Keep background conversation active
      }
      localStorage.removeItem(STORAGE_KEY_ACTIVE_CONVERSATION);
      activeConversationIdRef.current = null;
      return null;
    });
    
    pendingConversationIdRef.current = null;
    setPendingConversationId(null);
    setIsProcessing(false);
    setCurrentEvents([]);
    // Reset live timers too — clearing all chats should not leave a stale
    // "answer elapsed" clock on the empty state.
    turnStartedAtRef.current = null;
    setTurnStartedAt(null);
    firstThinkingStartedAtRef.current = null;
    setFirstThinkingStartedAt(null);
    lastThinkingAtRef.current = null;
    setLastThinkingAt(null);
    thinkingChunksRef.current = [];
  }, [clearBackendSession, clearDeviceControlPanel]);
  
  const clearBackgroundHistory = useCallback((agentId: string) => {
    console.log(`[useAgentChat] Clearing background history for agent: ${agentId}`);

    // Remove all conversations for this background agent
    setConversations(prev => {
      const filtered = prev.filter(c => !c.id.startsWith(`bg_${agentId}_`));

      // Update localStorage
      if (filtered.length > 0) {
        localStorage.setItem(STORAGE_KEY_CONVERSATIONS, JSON.stringify(filtered));
      } else {
        localStorage.removeItem(STORAGE_KEY_CONVERSATIONS);
      }

      console.log(`[useAgentChat] Cleared ${prev.length - filtered.length} conversations for ${agentId}`);
      return filtered;
    });

    // Clear background tasks for this agent
    setBackgroundTasks(prev => ({
      ...prev,
      [agentId]: { inProgress: [], recent: [] }
    }));

    // Clear active conversation if it was from this agent
    setActiveConversationId(prev => {
      if (prev && prev.startsWith(`bg_${agentId}_`)) {
        localStorage.removeItem(STORAGE_KEY_ACTIVE_CONVERSATION);
        activeConversationIdRef.current = null;
        return null;
      }
      return prev;
    });
  }, []);

  const reloadSkills = useCallback(async () => {
    try {
      console.log('[useAgentChat] Reloading skills...');
      const data = await api.post(buildServerUrl('/server/skills/reload'));
      console.log('[useAgentChat] Skills reloaded successfully:', data);
      return data;
    } catch (error) {
      console.error('[useAgentChat] Failed to reload skills:', error);
      throw error;
    }
  }, []);

  // Handle visibility change - ensure socket reconnects when tab becomes visible
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        console.log('[useAgentChat] Tab became visible - checking socket connection');
        
        // Cancel any pending disconnect timeout
        if (disconnectTimeoutRef.current) {
          clearTimeout(disconnectTimeoutRef.current);
          disconnectTimeoutRef.current = null;
        }
        
        // If socket is disconnected but we're still processing, attempt reconnect
        if (socket && !socket.connected && pendingConversationIdRef.current) {
          console.log('[useAgentChat] Reconnecting socket after tab visibility change');
          connect();
        }
      }
    };
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Cleanup timeouts on unmount (socket cleanup handled by SocketContext)
  useEffect(() => {
    return () => {
      if (processingTimeoutRef.current) {
        clearTimeout(processingTimeoutRef.current);
      }
      if (disconnectTimeoutRef.current) {
        clearTimeout(disconnectTimeoutRef.current);
      }
    };
  }, []);

  return {
    // State
    status,
    session,
    agentHandoff,
    messages,
    input,
    isProcessing,
    currentEvents,
    error,
    apiKeyInput,
    showApiKey,
    isValidating,
    activeProvider,
    activeModel,
    activeEndpoint,

    // Live turn timing (ms epoch). `turnStartedAt` is captured when the user
    // sends and stays non-null until the turn is finalized (session_ended,
    // user-stop, error). `firstThinkingStartedAt` / `lastThinkingAt` flip on
    // the first / most-recent thinking event of the turn and stay non-null
    // until the next send. UI ticks `Date.now() - turnStartedAt` at ~4Hz to
    // render the live counter; `firstThinkingStartedAt` is the origin for
    // the Reasoning accordion's elapsed counter.
    turnStartedAt,
    firstThinkingStartedAt,
    lastThinkingAt,

    // Conversations
    conversations,
    activeConversationId,
    pendingConversationId,
    
    // Background Tasks (generic - keyed by agent ID)
    backgroundTasks,
    setBackgroundAgents,
    
    // Actions
    setInput,
    setShowApiKey,
    setApiKeyInput,
    setError,
    sendMessage,
    setQuickHint,
    saveApiKey,
    handleApproval,
    stopGeneration,
    clearHistory,
    setAgentId,
    setPinnedProfileId,
    setCompanionContext,
    setNavigationContext,
    
    // Conversation Actions
    createNewConversation,
    switchConversation,
    deleteConversation,
    clearBackgroundHistory,
    
    // 🆕 NEW: Device control callback for AI agent tool calls
    setOnDeviceControlChange,

    // 🆕 NEW: UI action callback for agent-driven UI updates
    setOnUIAction,

    // 🆕 NEW: Skills reload function for development
    reloadSkills,
  };
};
