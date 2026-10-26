/**
 * TASK-113 — PR-E: cross-server HLS stream URL.
 *
 * Resolves the HLS playlist URL for a device on its home server.
 * The existing `ensureHostSession` (frontend/src/utils/buildUrlUtils.ts:144-171)
 * mints the short-lived host-session cookie at the URL's own origin
 * — a peer HLS URL mints the cookie at the peer's origin, not at
 * the currently selected server. This hook just builds the URL;
 * the host-session refresh is the caller's job (or the existing
 * `useHostSession` hook's).
 *
 * The hook returns the resolved URL plus a helper that triggers
 * a host-session mint before the URL is usable.
 */
import { useMemo } from 'react';
import { ensureHostSession } from '../../utils/buildUrlUtils';

export interface UseCrossServerStreamOptions {
  /** The device's home server URL. */
  homeServerUrl: string;
  /** The host's name (`host_name` from the catalog). */
  hostName: string;
  /** The host's stream endpoint, default `/host/<name>/stream/stream.m3u8`. */
  endpoint?: string;
}

export interface UseCrossServerStreamReturn {
  /** The resolved URL on the device's home server. */
  url: string | null;
  /** Mint the host-session cookie and return whether the URL is usable. */
  prime: () => Promise<boolean>;
}

const defaultEndpoint = (hostName: string): string => `/host/${hostName}/stream/stream.m3u8`;

/**
 * Compute the HLS URL on the device's home server. The URL is
 * returned even before the host-session cookie is minted; the
 * consumer must call `prime()` before passing the URL to an HLS
 * player, otherwise the proxy's `auth_request` gate will 401 the
 * first segment.
 */
export const useCrossServerStream = (
  options: UseCrossServerStreamOptions,
): UseCrossServerStreamReturn => {
  const { homeServerUrl, hostName, endpoint } = options;
  const url = useMemo<string | null>(() => {
    if (!homeServerUrl || !hostName) return null;
    const ep = endpoint ?? defaultEndpoint(hostName);
    // The host's `/host/<name>/...` path is relative on the home
    // server's proxy; we prefix the home server's origin. Any
    // existing absolute URL is returned as-is.
    if (ep.startsWith('http://') || ep.startsWith('https://')) return ep;
    return `${homeServerUrl.replace(/\/+$/, '')}${ep.startsWith('/') ? ep : `/${ep}`}`;
  }, [homeServerUrl, hostName, endpoint]);

  return {
    url,
    prime: async () => {
      if (!url) return false;
      return ensureHostSession(url);
    },
  };
};
