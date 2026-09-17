import { useEffect, useState } from 'react';

import { ensureHostSession, isGatedHostPath } from '../utils/buildUrlUtils';

// Well under the 10-minute cookie TTL (server_host_session_routes.py:HOST_SESSION_TTL_SECONDS)
// so a refresh always lands before expiry, even under load.
const REFRESH_INTERVAL_MS = 4 * 60 * 1000;

/**
 * Mints (and, for long-lived players, periodically refreshes) the host-session
 * cookie the proxy's `auth_request` gate requires before a VNC iframe or HLS
 * player may navigate to a `/host/<name>/...` URL (BUG-0107 step 2). A no-op
 * for any other URL — `ensureHostSession` resolves `true` immediately without
 * a network call.
 *
 * @param url URL about to be used (iframe `src` or HLS player `streamUrl`).
 * @param keepAlive Pass `true` for HLS/live playback, which re-fetches
 *   segments for as long as it runs and would 401 mid-stream once the cookie
 *   expires. Pass `false` for VNC: the initial websocket handshake is the
 *   only request the gate ever sees: the connection persists independent of
 *   cookie expiry, so a repeating mint would be a wasted request.
 */
export function useHostSession(url: string | null | undefined, keepAlive: boolean): boolean {
  const gated = isGatedHostPath(url);
  const [mintedReady, setMintedReady] = useState(false);

  useEffect(() => {
    if (!url || !gated) {
      setMintedReady(false);
      return;
    }

    let cancelled = false;
    setMintedReady(false);
    ensureHostSession(url).then((ok) => {
      if (!cancelled) setMintedReady(ok);
    });

    let interval: ReturnType<typeof setInterval> | undefined;
    if (keepAlive) {
      interval = setInterval(() => {
        void ensureHostSession(url);
      }, REFRESH_INTERVAL_MS);
    }

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [url, gated, keepAlive]);

  if (!url) return false;
  // Ungated URLs (not proxied through a gated /host/<name>/... path) are ready
  // immediately — no mint call, no render delay for the vast majority of callers.
  return gated ? mintedReady : true;
}
