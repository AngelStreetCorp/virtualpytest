import { useCallback, useEffect, useState } from 'react';

import { Host } from '../../types/common/Host_Types';

import { useControllerApi } from './useControllerApi';

// One lookup per host per page load. An empty string is cached too: that host did not opt in.
const vncPasswordCache = new Map<string, string>();

export interface UseVncPasswordReturn {
  /** False until the host has answered, so the iframe does not load once without it. */
  vncPasswordReady: boolean;
  /** Appends `password=` for noVNC auto-connect; returns the URL unchanged when there is none. */
  withVncPassword: (url: string) => string;
}

/**
 * Fetch the host's VNC password for noVNC auto-connect. The host only returns one when it
 * has HOST_VNC_AUTOCONNECT=true; every other host answers '' and the iframe URL stays
 * password-free, as BUG-0107 requires. A direct hit on vnc_lite.html still prompts.
 */
export function useVncPassword(host: Host | null | undefined): UseVncPasswordReturn {
  const hostName = host?.host_name ?? null;
  const { postToHost } = useControllerApi(host ?? null, 'host');
  const [password, setPassword] = useState<string | null>(() =>
    hostName ? (vncPasswordCache.get(hostName) ?? null) : '',
  );

  useEffect(() => {
    if (!hostName) {
      setPassword('');
      return;
    }
    const cached = vncPasswordCache.get(hostName);
    if (cached !== undefined) {
      setPassword(cached);
      return;
    }
    let cancelled = false;
    setPassword(null);
    postToHost<{ password?: string }>('/server/system/vnc-info', {}, { includeDeviceId: false })
      .then((result) => result?.password || '')
      .catch(() => '')
      .then((value) => {
        vncPasswordCache.set(hostName, value);
        if (!cancelled) setPassword(value);
      });
    return () => {
      cancelled = true;
    };
  }, [hostName, postToHost]);

  const withVncPassword = useCallback(
    (url: string) =>
      password ? `${url}${url.includes('?') ? '&' : '?'}password=${encodeURIComponent(password)}` : url,
    [password],
  );

  return { vncPasswordReady: password !== null, withVncPassword };
}
