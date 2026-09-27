import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { usePermissionContext } from './auth/PermissionContext';
import { Socket } from 'socket.io-client';
import { createServerSocket } from '../utils/serverSocket';
import { getServerBaseUrl, buildServerUrl } from '../utils/buildUrlUtils';

// Event handler registered by consumers (AIContext, useAgentChat)
type AgentEventHandler = (event: any) => void;

// Room every page listens in: background agents (Sherlock analysis etc.) publish there.
const BACKGROUND_ROOM = 'background_tasks';

// Rebuild backoff after a refused handshake (connect_error). socket.io-client destroys the
// namespace socket on CONNECT_ERROR and never retries it, so the retry has to be ours.
const REBUILD_DELAY_MIN_MS = 1000;
const REBUILD_DELAY_MAX_MS = 30000;

interface SocketContextType {
  // Socket
  socket: Socket | null;
  isConnected: boolean;
  connect: () => void;
  disconnect: () => void;

  // Shared session (single session for all agent communication)
  sessionId: string | null;
  initSession: () => Promise<string | null>;

  // Subscribe this page to a session's event room. The room is remembered and re-joined on
  // every (re)connect, so a chat keeps listening to the session its message was sent in
  // even if the transport drops mid-answer.
  joinSession: (sessionId: string) => void;

  // Event routing — consumers register handlers, SocketContext routes events
  registerEventHandler: (id: string, handler: AgentEventHandler) => void;
  unregisterEventHandler: (id: string) => void;

  // Shared send — both Cmd+K and Agent Chat use this. sessionIdOverride lets a
  // caller send on a specific (e.g. per-conversation) session instead of the
  // shared one.
  emitSendMessage: (message: string, agentId: string, context?: Record<string, any>, sessionIdOverride?: string) => boolean;

  // Hard-recycle the socket (disconnect + reconnect + rejoin rooms). Used when
  // the connection is suspected half-dead (claims connected but nothing flows).
  forceReconnect: () => void;
}

const SocketContext = createContext<SocketContextType | undefined>(undefined);

export const SocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { hasPermission } = usePermissionContext();
  const socketRef = useRef<Socket | null>(null);
  const [socketState, setSocketState] = useState<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const eventHandlersRef = useRef<Map<string, AgentEventHandler>>(new Map());
  const sessionIdRef = useRef<string | null>(null);
  // In-flight POST /server/agent/sessions, shared by concurrent initSession() callers.
  const sessionInitRef = useRef<Promise<string | null> | null>(null);
  const connectedServerUrlRef = useRef<string | null>(null);
  // Every room this page wants to be in. Re-joined wholesale on each 'connect'.
  const roomsRef = useRef<Set<string>>(new Set([BACKGROUND_ROOM]));
  const rebuildTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rebuildDelayRef = useRef(REBUILD_DELAY_MIN_MS);
  const unmountedRef = useRef(false);

  // Keep ref in sync
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);

  const joinAllRooms = useCallback((socket: Socket) => {
    for (const room of roomsRef.current) {
      socket.emit('join_session', { session_id: room });
    }
  }, []);

  // Destroy the current socket outright. A half-dead engine can wedge socket.connect()
  // forever (observed: recycle-in-place never re-established through the proxy), so
  // recovery always builds a fresh manager instead of reusing this one.
  const teardown = useCallback(() => {
    const old = socketRef.current;
    if (!old) return;
    try {
      old.removeAllListeners();
      old.io?.engine?.close();
      old.disconnect();
    } catch {
      // best-effort teardown of an already-broken socket
    }
    socketRef.current = null;
    setSocketState(null);
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (socketRef.current) {
      // `active` is true while the socket is connected OR still handshaking/reconnecting.
      // Calling socket.connect() in that window is not a no-op: socket.io-client re-runs
      // the auth callback and sends a SECOND CONNECT packet on the same engine
      // connection, which python-socketio refuses with `44 "Unable to connect"` — and on
      // that CONNECT_ERROR the client destroys the namespace socket. Several consumers
      // (AIContext, AgentActivityContext, useAIOrchestrator, useAgentChat) call connect()
      // during page load, all inside that window.
      if (!socketRef.current.active) {
        socketRef.current.connect();
      }
      return;
    }

    const serverBaseUrl = getServerBaseUrl();
    connectedServerUrlRef.current = serverBaseUrl;
    // createServerSocket attaches the handshake credentials (TASK-18 token, plus the
    // server key and auto-sign token the fetch path already sends). It used to send the
    // token only, which was enough while nothing checked it and not enough once the
    // server started refusing unauthenticated sockets on no-Supabase deployments.
    socketRef.current = createServerSocket(serverBaseUrl, '/agent', {
      transports: ['polling', 'websocket'],
      reconnection: true,
      // Never give up: a capped attempt count (was 5) meant a tab whose laptop
      // slept through a server restart stopped reconnecting FOREVER — sends
      // then went into a dead socket while `connected` still read true.
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 10000,
    });
    setSocketState(socketRef.current);
    // Test hook for browser-level probes (stale-socket simulation)
    (window as any).__vptSocket = socketRef.current;

    const socket = socketRef.current;

    socket.on('connect', () => {
      console.log('🔌 SocketContext: Connected to /agent namespace');
      setIsConnected(true);
      rebuildDelayRef.current = REBUILD_DELAY_MIN_MS;
      // Every (re)connect is a fresh server-side sid with no rooms: re-join them all.
      joinAllRooms(socket);
    });

    socket.on('disconnect', (reason) => {
      console.log('🔌 SocketContext: Disconnected:', reason);
      setIsConnected(false);
    });

    socket.on('connect_error', (error) => {
      // The client library has already torn the namespace socket down (its subscriptions
      // are gone, so it will never see 'disconnect' and `connected` may still read true).
      // Treat it as dead and rebuild with backoff — the auth callback re-reads the token,
      // so a refusal caused by a not-yet-restored Supabase session heals on its own.
      console.error('🔌 SocketContext: Connection error:', error?.message || error);
      setIsConnected(false);
      if (rebuildTimerRef.current || unmountedRef.current) return;
      const delay = rebuildDelayRef.current;
      rebuildDelayRef.current = Math.min(delay * 2, REBUILD_DELAY_MAX_MS);
      rebuildTimerRef.current = setTimeout(() => {
        rebuildTimerRef.current = null;
        if (unmountedRef.current || socketRef.current !== socket) return;
        console.warn(`🔌 SocketContext: Rebuilding socket after connect_error (waited ${delay}ms)`);
        teardown();
        connect();
      }, delay);
    });

    // 'reconnect' is a Manager event; a namespace socket never emits it. 'connect' above
    // already fires for every re-established connection and re-joins the rooms.
    socket.io.on('reconnect', (attempt) => {
      console.log(`🔌 SocketContext: Reconnected (attempt ${attempt})`);
    });

    // Single event listener — routes to all registered handlers
    socket.on('agent_event', (event: any) => {
      for (const handler of eventHandlersRef.current.values()) {
        try {
          handler(event);
        } catch (e) {
          console.error('🔌 SocketContext: Event handler error:', e);
        }
      }
    });
  }, [joinAllRooms, teardown]);

  const disconnect = useCallback(() => {
    if (rebuildTimerRef.current) {
      clearTimeout(rebuildTimerRef.current);
      rebuildTimerRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
      setSocketState(null);
      setIsConnected(false);
    }
  }, []);

  const joinSession = useCallback((id: string) => {
    if (!id) return;
    roomsRef.current.add(id);
    const socket = socketRef.current;
    if (socket?.connected) {
      socket.emit('join_session', { session_id: id });
    }
    // Not connected yet: the 'connect' handler joins everything in roomsRef.
  }, []);

  // Create shared session — called once, shared by AIContext + useAgentChat
  const initSession = useCallback(async (): Promise<string | null> => {
    // Return existing session if already created
    if (sessionIdRef.current) return sessionIdRef.current;
    // AIContext and useAgentChat both call this during page load, before the first
    // POST has answered; without sharing the in-flight request each caller minted
    // its own session (three "shared" sessions per page load were observed).
    if (sessionInitRef.current) return sessionInitRef.current;

    // The agent is a tester+ feature. This used to fire for anyone merely logged in,
    // so every page load by a viewer POSTed /server/agent/sessions and collected a 403
    // — correct enforcement, pointless request. Gated here rather than at each call
    // site: AIContext, useAgentChat and the server-changed handler all come through
    // this one function. hasPermission() is true when auth is disabled entirely, so a
    // no-login deployment is unaffected.
    if (!hasPermission('ai_agent:view')) return null;

    const request = (async (): Promise<string | null> => {
      try {
        const response = await fetch(buildServerUrl('/server/agent/sessions'), { method: 'POST' });
        const data = await response.json();
        if (data.success && data.session?.id) {
          const newSessionId = data.session.id;
          setSessionId(newSessionId);
          sessionIdRef.current = newSessionId;
          console.log('🔌 SocketContext: Session created:', newSessionId);
          joinSession(newSessionId);
          return newSessionId;
        }
      } catch (e) {
        console.error('🔌 SocketContext: Failed to create session:', e);
      } finally {
        sessionInitRef.current = null;
      }
      return null;
    })();
    sessionInitRef.current = request;
    return request;
  }, [hasPermission, joinSession]);

  // Rebind to the newly selected server: the socket and the REST-created
  // session are both server-scoped, so a dropdown switch must tear down and
  // rebuild both — otherwise the UI shows the new server while the chat keeps
  // talking to the old one (or to a session the new server never heard of).
  useEffect(() => {
    const onServerChanged = () => {
      const newUrl = getServerBaseUrl();
      if (newUrl === connectedServerUrlRef.current) return;
      console.warn(`🔌 SocketContext: Server changed → rebinding socket + session to ${newUrl}`);
      teardown();
      // Sessions and their rooms belong to the old server.
      sessionIdRef.current = null;
      sessionInitRef.current = null;
      setSessionId(null);
      roomsRef.current = new Set([BACKGROUND_ROOM]);
      connect();
      // Fresh session on the new server; joins its room once created
      void initSession();
    };
    window.addEventListener('vpt:server-changed', onServerChanged);
    return () => window.removeEventListener('vpt:server-changed', onServerChanged);
  }, [connect, initSession, teardown]);

  // Register event handler (e.g., 'aicontext', 'agentchat')
  const registerEventHandler = useCallback((id: string, handler: AgentEventHandler) => {
    eventHandlersRef.current.set(id, handler);
  }, []);

  const unregisterEventHandler = useCallback((id: string) => {
    eventHandlersRef.current.delete(id);
  }, []);

  // Shared send message — both Cmd+K and Agent Chat use this
  const emitSendMessage = useCallback((message: string, agentId: string, context?: Record<string, any>, sessionIdOverride?: string) => {
    const socket = socketRef.current;
    const sid = sessionIdOverride || sessionIdRef.current;
    if (!socket?.connected || !sid) {
      console.warn('🔌 SocketContext: Cannot send — socket not connected or no session');
      return false;
    }
    // Sending is an implicit join server-side; remember the room so a reconnect
    // mid-answer keeps this page in it.
    roomsRef.current.add(sid);
    socket.emit('send_message', {
      session_id: sid,
      message,
      agent_id: agentId,
      ...(context || {}),
    });
    return true;
  }, []);

  const forceReconnect = useCallback(() => {
    console.warn('🔌 SocketContext: Force-reconnecting socket (suspected dead connection)');
    teardown();
    connect(); // builds a fresh socket + handlers; 'connect' re-joins rooms
  }, [connect, teardown]);

  // Self-heal on tab wake (ported from main's useAgentChat, centralized here):
  // after laptop sleep / long backgrounding, the websocket is often half-open —
  // socket.io still reports connected:true but nothing flows. On visibility we
  // probe liveness with join_session (server replies 'joined'); no reply in 3s
  // → hard recycle. A dead-for-real socket reconnects immediately.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      const socket = socketRef.current;
      if (!socket) {
        connect();
        return;
      }
      if (!socket.connected) {
        // Still handshaking or auto-reconnecting: leave the manager to it. Only a
        // destroyed socket (after a CONNECT_ERROR) needs a nudge.
        if (!socket.active) {
          console.log('🔌 SocketContext: Tab visible, socket down — reconnecting');
          connect();
        }
        return;
      }
      // Liveness probe on a "connected" socket
      let alive = false;
      const onJoined = () => { alive = true; };
      socket.once('joined', onJoined);
      socket.emit('join_session', { session_id: sessionIdRef.current || BACKGROUND_ROOM });
      setTimeout(() => {
        socket.off('joined', onJoined);
        if (!alive) {
          console.warn('🔌 SocketContext: Liveness probe failed after tab wake');
          forceReconnect();
        }
      }, 3000);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [connect, forceReconnect]);

  // Cleanup on unmount
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      disconnect();
    };
  }, [disconnect]);

  const value: SocketContextType = {
    socket: socketState,
    isConnected,
    connect,
    disconnect,
    sessionId,
    initSession,
    joinSession,
    registerEventHandler,
    unregisterEventHandler,
    emitSendMessage,
    forceReconnect,
  };

  return (
    <SocketContext.Provider value={value}>
      {children}
    </SocketContext.Provider>
  );
};

export const useSocket = () => {
  const context = useContext(SocketContext);
  if (!context) {
    throw new Error('useSocket must be used within SocketProvider');
  }
  return context;
};
