import { useEffect, useRef } from 'react';

import { APP_CONFIG } from '../../../config/constants';
import { getServerBaseUrl } from '../../../utils/buildUrlUtils';
import { createServerSocket } from '../../../utils/serverSocket';
import { SYSTEM_UPDATE_EVENT } from '../constants';
import { fetchSnapshot } from '../data/modsApi';
import { mapSystemUpdate } from '../mappers';
import type { ModEventEnvelope } from '../types';

/**
 * Listen to the /system socket and hand every mapped event to `onEvent`; no socket while no
 * mod is on. On every (re)connect the current state is replayed first (runs already going,
 * held locks, who is online), so a page opened mid-run is not empty until the next change.
 */
export const useModSystemEvents = (onEvent: (envelope: ModEventEnvelope) => void, active: boolean): void => {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!active) return undefined;
    const handle = (event: unknown) => {
      const envelope = mapSystemUpdate(event, APP_CONFIG.DEFAULT_TEAM_ID);
      if (envelope) onEventRef.current(envelope);
    };

    const socket = createServerSocket(getServerBaseUrl(), '/system', {
      transports: ['websocket'],
      reconnection: true,
    });
    socket.on('connect', () => {
      fetchSnapshot()
        .then((events) => events.forEach(handle))
        .catch((err) => console.warn('[@mods] snapshot failed', err));
    });
    socket.on(SYSTEM_UPDATE_EVENT, handle);
    return () => {
      socket.disconnect();
    };
  }, [active]);
};
