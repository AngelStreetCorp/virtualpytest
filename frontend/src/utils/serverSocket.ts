/**
 * One place that opens a Socket.IO connection to a backend server (BUG-0156).
 *
 * The server authenticates the socket handshake now, and a browser WebSocket cannot set
 * headers — so the credentials installFetchAuth.ts puts on every HTTP request have to travel
 * in the handshake `auth` payload instead. Every namespace the app connects to needs the
 * same three, which is why this is a helper and not ten copies: `/system` alone had nine
 * call sites, none of them sending anything.
 *
 * The payload mirrors the fetch path exactly:
 *   - `token`      the Supabase access token of the TARGET server's identity (TASK-18)
 *   - `server_key` the weak published SERVER_PUBLIC_KEY, for no-Supabase deployments
 *   - `auto_sign`  the agent/E2E bypass token, when one is in play
 *
 * `auth` is a callback rather than a fixed object so every reconnect re-reads it: a socket
 * that reconnects after a token refresh, or after the user switches servers, must not
 * present a stale token or one minted for a different Supabase.
 */
import { io, Socket } from 'socket.io-client';

import { getEnv } from '../config/constants';
import { getAutoSignHeaderToken } from '../lib/autoSign';
import { getAccessTokenForServer } from '../lib/serverIdentity';

type SocketOptions = Parameters<typeof io>[1];

export const buildSocketAuth =
  (serverBaseUrl: string) =>
  (cb: (data: Record<string, unknown>) => void): void => {
    const payload: Record<string, unknown> = {};

    const serverKey = getEnv('VITE_SERVER_PUBLIC_KEY') || '';
    if (serverKey) payload.server_key = serverKey;

    const autoSign = getAutoSignHeaderToken();
    if (autoSign) payload.auto_sign = autoSign;

    void getAccessTokenForServer(serverBaseUrl)
      .then((token) => {
        if (token) payload.token = token;
        cb(payload);
      })
      // A missing token is not a failure here: the server decides. An open-mode deployment
      // admits the connection anyway, and a closed one refuses it with a connect_error,
      // which is the same answer the fetch path gives.
      .catch(() => cb(payload));
  };

/**
 * Connect to `namespace` on `serverBaseUrl` with the handshake credentials attached.
 * Everything else behaves exactly like calling `io()` directly.
 */
export const createServerSocket = (
  serverBaseUrl: string,
  namespace: string,
  options: SocketOptions = {},
): Socket =>
  io(`${serverBaseUrl}${namespace}`, {
    ...options,
    auth: buildSocketAuth(serverBaseUrl),
  });
