/**
 * TASK-113 — PR-E: cross-server device control.
 *
 * The single hook that opens a control socket to a device's HOME
 * server, regardless of which server the browser is currently loaded
 * from. The handshake auth is per-server: `createServerSocket`
 * (`frontend/src/utils/serverSocket.ts:65-72`) resolves the JWT for
 * the target server through the existing `getAccessTokenForServer`
 * (TASK-18) and sends it as the socket.io `auth: { token }` payload.
 *
 * Architectural invariant (binding): the control socket for a
 * device on server B is opened to `wss://B/agent`, never to the
 * currently selected server. The native WebSocket header
 * limitation does not apply — socket.io carries the token in the
 * CONNECT frame's `auth` payload, not in headers.
 *
 * The hook exposes the same surface as the existing single-server
 * control flow (`send`, `live`, `status`); a parent passes the
 * `homeServerUrl` from the row's `server_url` field.
 */
import { useEffect, useRef } from 'react';
import { io, Socket } from 'socket.io-client';
import {
  buildSocketAuth,
  type SocketOptions,
} from '../../utils/serverSocket';

export type CrossServerStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'needs-auth'
  | 'offline'
  | 'error';

export interface UseCrossServerControlOptions {
  /** The device's home server URL. */
  homeServerUrl: string;
  /** Socket.IO namespace, default '/agent'. */
  namespace?: string;
  /** Whether the hook should open a socket. When false, the hook is a no-op. */
  enabled?: boolean;
  /** Custom socket options (passes through to `io()`). */
  socketOptions?: SocketOptions;
}

export interface UseCrossServerControlReturn {
  /** The underlying socket, or null when not connected. */
  socket: Socket | null;
  /** Current connection status. */
  status: CrossServerStatus;
  /** Send a keypress / control event. */
  send: (event: string, payload: unknown) => void;
  /** Tear down the socket. */
  disconnect: () => void;
}

/**
 * Open and tear down a control socket for one device. The socket
 * is recreated when `homeServerUrl` changes; the parent is
 * responsible for keeping `enabled` in sync with the device's
 * visible tile so that we don't keep a socket open for an
 * off-screen device (the per-device budget rewrite §5.5).
 */
export const useCrossServerControl = (
  options: UseCrossServerControlOptions,
): UseCrossServerControlReturn => {
  const { homeServerUrl, namespace = '/agent', enabled = true, socketOptions } = options;
  const socketRef = useRef<Socket | null>(null);
  const statusRef = useRef<CrossServerStatus>('idle');

  useEffect(() => {
    if (!enabled || !homeServerUrl) {
      socketRef.current?.disconnect();
      socketRef.current = null;
      statusRef.current = 'idle';
      return undefined;
    }

    statusRef.current = 'connecting';
    const socket = io(`${homeServerUrl}${namespace}`, {
      ...socketOptions,
      auth: buildSocketAuth(homeServerUrl),
    });
    socketRef.current = socket;

    socket.on('connect', () => {
      statusRef.current = 'connected';
    });
    socket.on('disconnect', () => {
      statusRef.current = 'offline';
    });
    socket.on('connect_error', (err: Error & { data?: { status?: number } }) => {
      if (err.data?.status === 401 || err.data?.status === 403) {
        statusRef.current = 'needs-auth';
      } else {
        statusRef.current = 'error';
      }
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
      statusRef.current = 'idle';
    };
  }, [homeServerUrl, namespace, enabled, socketOptions]);

  return {
    get socket() {
      return socketRef.current;
    },
    get status() {
      return statusRef.current;
    },
    send: (event: string, payload: unknown) => {
      socketRef.current?.emit(event, payload);
    },
    disconnect: () => {
      socketRef.current?.disconnect();
      socketRef.current = null;
      statusRef.current = 'idle';
    },
  };
};
