import { useEffect, useState } from 'react';

import { api } from '../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../frontend/src/utils/buildUrlUtils';

import type { CompanionResult } from './types';

// The service updates its result every second at most, the identify call every ~20 s.
const POLL_MS = 2000;

/** Latest companion result for one device while `enabled`; null when there is none. */
export function useCompanion(hostName: string, deviceId: string, enabled: boolean): CompanionResult | null {
  const [result, setResult] = useState<CompanionResult | null>(null);

  useEffect(() => {
    if (!enabled || !hostName || !deviceId) {
      setResult(null);
      return;
    }
    let alive = true;
    const poll = async () => {
      try {
        const data = await api.post<{ success?: boolean; companion?: CompanionResult | null }>(
          buildServerUrl('/server/companion/latest'),
          { host_name: hostName, device_id: deviceId },
        );
        if (alive) setResult(data?.success ? data.companion ?? null : null);
      } catch {
        if (alive) setResult(null);
      }
    };
    void poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [enabled, hostName, deviceId]);

  return result;
}
