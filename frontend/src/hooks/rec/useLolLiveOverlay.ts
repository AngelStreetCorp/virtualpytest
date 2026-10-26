import { useEffect, useState } from 'react';

import { Host } from '../../types/common/Host_Types';
import { LolLiveData } from '../../types/game/LolOverlay_Types';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

const POLL_INTERVAL_MS = 500;
/** The bot rewrites the file every tick; older than this = the bot is not running. */
const STALE_AFTER_MS = 5000;

export interface LolLiveOverlayState {
  data: LolLiveData | null;
  /** Browser time (ms) the data was received, to age recent_inputs between polls. */
  receivedAt: number;
}

/** Polls the host's lol-overlay-live.json (written by the LoL bot every tick) while `enabled`. */
export const useLolLiveOverlay = (host: Host, enabled: boolean): LolLiveOverlayState => {
  const [state, setState] = useState<LolLiveOverlayState>({ data: null, receivedAt: 0 });

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, receivedAt: 0 });
      return;
    }
    let cancelled = false;
    const poll = async () => {
      if (document.visibilityState === 'hidden') return;
      try {
        // Through the server: a host route needs the host API key, which the browser does not have.
        const body = await api.post<{ data: LolLiveData | null; age_s: number | null }>(buildServerUrl('/server/lol-overlay/live'), {
          host_name: host.host_name,
        });
        if (cancelled) return;
        // The route answers {success, data, age_s}; data null = no file yet.
        const ageS = body?.age_s;
        const fresh = body?.data && typeof ageS === 'number' && ageS * 1000 < STALE_AFTER_MS;
        setState(fresh ? { data: body.data as LolLiveData, receivedAt: Date.now() - ageS * 1000 } : { data: null, receivedAt: 0 });
      } catch {
        if (!cancelled) setState({ data: null, receivedAt: 0 });
      }
    };
    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [host, enabled]);

  return state;
};
