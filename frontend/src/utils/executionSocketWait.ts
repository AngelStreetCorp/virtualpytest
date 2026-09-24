import { Socket } from 'socket.io-client';
import { createServerSocket } from '../utils/serverSocket';
import { getServerBaseUrl } from './buildUrlUtils';

export interface ExecutionSocketEvent {
  type?: string;
  domain?: string;
  execution_type?: string;
  execution_id?: string;
  status?: string;
  host_name?: string;
  device_id?: string;
  team_id?: string;
  progress?: number;
  message?: string;
  result?: any;
  error?: string;
  timestamp?: number;
}

export const waitForExecutionSocketEvent = (
  executionId: string,
  expectedTypes: string[],
  timeoutMs: number,
  abortSignal?: AbortSignal,
  onProgress?: (event: ExecutionSocketEvent) => void,
): Promise<ExecutionSocketEvent> =>
  new Promise((resolve, reject) => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let socket: Socket | null = null;
    let abortListener: (() => void) | null = null;
    let lastConnectError: string | null = null;

    const cleanup = () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
      if (socket) {
        socket.disconnect();
        socket = null;
      }
      if (abortSignal && abortListener) {
        abortSignal.removeEventListener('abort', abortListener);
        abortListener = null;
      }
    };

    timeoutId = setTimeout(() => {
      cleanup();
      reject(
        new Error(
          lastConnectError
            ? `Execution timeout for ${executionId}; last socket error: ${lastConnectError}`
            : `Execution timeout for ${executionId}`
        )
      );
    }, timeoutMs);

    const serverBaseUrl = getServerBaseUrl() || window.location.origin;
    socket = createServerSocket(serverBaseUrl, '/system', {
      transports: ['polling', 'websocket'],
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });

    if (abortSignal) {
      abortListener = () => {
        cleanup();
        reject(new DOMException('Execution aborted', 'AbortError'));
      };

      if (abortSignal.aborted) {
        abortListener();
        return;
      }

      abortSignal.addEventListener('abort', abortListener, { once: true });
    }

    socket.on('system_update', (event: ExecutionSocketEvent) => {
      if (event?.type !== 'execution_update') {
        return;
      }
      if (event.execution_id !== executionId) {
        return;
      }
      if (!expectedTypes.includes(String(event.execution_type || ''))) {
        return;
      }
      if (!event.status || event.status === 'running') {
        if (onProgress) {
          try {
            onProgress(event);
          } catch (err) {
            console.warn('[@socket:executionWait] onProgress callback threw:', err);
          }
        }
        return;
      }
      cleanup();
      resolve(event);
    });

    socket.on('connect_error', (err: any) => {
      // Keep waiting and let Socket.IO reconnect until timeout/abort.
      lastConnectError = err?.message || 'Socket connection error';
      console.warn('[@socket:executionWait] /system connect_error:', lastConnectError);
    });

    socket.on('reconnect_failed', () => {
      // All reconnection attempts exhausted — reject so polling fallback can start immediately.
      cleanup();
      reject(new Error(`Socket reconnection failed for ${executionId}: ${lastConnectError || 'unknown'}`));
    });
  });
