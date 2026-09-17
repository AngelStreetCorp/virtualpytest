import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { io, Socket } from 'socket.io-client';
import { getServerBaseUrl, buildServerUrl } from '../utils/buildUrlUtils';
import { getAccessTokenForServer } from '../lib/serverIdentity';

// Event handler registered by consumers (AIContext, useAgentChat)
type AgentEventHandler = (event: any) => void;

interface SocketContextType {
  // Socket
  socket: Socket | null;
  isConnected: boolean;
  connect: () => void;
  disconnect: () => void;

  // Shared session (single session for all agent communication)
  sessionId: string | null;
  initSession: () => Promise<string | null>;

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
  const socketRef = useRef<Socket | null>(null);
  const [socketState, setSocketState] = useState<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const eventHandlersRef = useRef<Map<string, AgentEventHandler>>(new Map());
  const sessionIdRef = useRef<string | null>(null);
  const connectedServerUrlRef = useRef<string | null>(null);

  // Keep ref in sync
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);

  const connect = useCallback(() => {
    if (socketRef.current) {
      if (!socketRef.current.connected) {
        socketRef.current.connect();
      }
      return;
    }

    const serverBaseUrl = getServerBaseUrl();
    connectedServerUrlRef.current = serverBaseUrl;
    socketRef.current = io(`${serverBaseUrl}/agent`, {
      // Carry the token of THIS server's Supabase identity (TASK-18). Resolved through a
      // callback rather than a fixed value so every reconnect re-reads it: a socket that
      // reconnects after a refresh (or after the user switches servers) must not present
      // a stale token, or one minted for a different Supabase.
      auth: (cb: (data: Record<string, unknown>) => void) => {
        void getAccessTokenForServer(serverBaseUrl)
          .then((token) => cb(token ? { token } : {}))
          .catch(() => cb({}));
      },
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
      // Re-join session room on reconnect
      if (sessionIdRef.current) {
        socket.emit('join_session', { session_id: sessionIdRef.current });
        socket.emit('join_session', { session_id: 'background_tasks' });
      }
    });

    socket.on('disconnect', (reason) => {
      console.log('🔌 SocketContext: Disconnected:', reason);
      setIsConnected(false);
    });

    socket.on('connect_error', (error) => {
      console.error('🔌 SocketContext: Connection error:', error);
    });

    socket.on('reconnect', () => {
      console.log('🔌 SocketContext: Reconnected');
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
  }, []);

  const disconnect = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
      setSocketState(null);
      setIsConnected(false);
    }
  }, []);

  // Create shared session — called once, shared by AIContext + useAgentChat
  const initSession = useCallback(async (): Promise<string | null> => {
    // Return existing session if already created
    if (sessionIdRef.current) return sessionIdRef.current;

    try {
      const response = await fetch(buildServerUrl('/server/agent/sessions'), { method: 'POST' });
      const data = await response.json();
      if (data.success && data.session?.id) {
        const newSessionId = data.session.id;
        setSessionId(newSessionId);
        sessionIdRef.current = newSessionId;
        console.log('🔌 SocketContext: Session created:', newSessionId);

        // Join session room if socket connected
        if (socketRef.current?.connected) {
          socketRef.current.emit('join_session', { session_id: newSessionId });
          socketRef.current.emit('join_session', { session_id: 'background_tasks' });
        }
        return newSessionId;
      }
    } catch (e) {
      console.error('🔌 SocketContext: Failed to create session:', e);
    }
    return null;
  }, []);

  // Rebind to the newly selected server: the socket and the REST-created
  // session are both server-scoped, so a dropdown switch must tear down and
  // rebuild both — otherwise the UI shows the new server while the chat keeps
  // talking to the old one (or to a session the new server never heard of).
  useEffect(() => {
    const onServerChanged = () => {
      const newUrl = getServerBaseUrl();
      if (newUrl === connectedServerUrlRef.current) return;
      console.warn(`🔌 SocketContext: Server changed → rebinding socket + session to ${newUrl}`);
      const old = socketRef.current;
      if (old) {
        try {
          old.removeAllListeners();
          old.io?.engine?.close();
          old.disconnect();
        } catch {
          // best-effort teardown
        }
        socketRef.current = null;
        setSocketState(null);
        setIsConnected(false);
      }
      sessionIdRef.current = null;
      setSessionId(null);
      connect();
      // Fresh session on the new server; joins its room once created
      void initSession();
    };
    window.addEventListener('vpt:server-changed', onServerChanged);
    return () => window.removeEventListener('vpt:server-changed', onServerChanged);
  }, [connect, initSession]);

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
    socket.emit('send_message', {
      session_id: sid,
      message,
      agent_id: agentId,
      ...(context || {}),
    });
    return true;
  }, []);

  const forceReconnect = useCallback(() => {
    const old = socketRef.current;
    console.warn('🔌 SocketContext: Force-reconnecting socket (suspected dead connection)');
    if (old) {
      // Destroy, don't reuse: a half-dead engine can wedge socket.connect()
      // forever (observed: recycle-in-place never re-established through the
      // proxy). A fresh manager always starts from a clean transport.
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
    }
    connect(); // builds a fresh socket + handlers; 'connect' re-joins rooms
  }, [connect]);

  // Self-heal on tab wake (ported from main's useAgentChat, centralized here):
  // after laptop sleep / long backgrounding, the websocket is often half-open —
  // socket.io still reports connected:true but nothing flows. On visibility we
  // probe liveness with join_session (server replies 'joined'); no reply in 3s
  // → hard recycle. A dead-for-real socket (connected:false) reconnects
  // immediately.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      const socket = socketRef.current;
      if (!socket || !socket.connected) {
        console.log('🔌 SocketContext: Tab visible, socket down — reconnecting');
        if (socket) socket.connect();
        else connect();
        return;
      }
      // Liveness probe on a "connected" socket
      let alive = false;
      const onJoined = () => { alive = true; };
      socket.once('joined', onJoined);
      socket.emit('join_session', { session_id: sessionIdRef.current || 'background_tasks' });
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
    return () => { disconnect(); };
  }, [disconnect]);

  const value: SocketContextType = {
    socket: socketState,
    isConnected,
    connect,
    disconnect,
    sessionId,
    initSession,
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
