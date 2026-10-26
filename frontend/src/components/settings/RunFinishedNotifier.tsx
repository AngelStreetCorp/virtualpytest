import React, { useEffect } from 'react';
import { Socket } from 'socket.io-client';

import { NOTIFY_RUNS_KEY, loadFlag } from '../../constants/uiPrefs';
import { useI18n } from '../../i18n/useI18n';
import { getServerBaseUrl } from '../../utils/buildUrlUtils';
import { createServerSocket } from '../../utils/serverSocket';

const TERMINAL = new Set(['completed', 'failed', 'aborted', 'skipped']);

/**
 * "Notify me when my runs finish" (Settings → Appearance). Listens read-only to the existing
 * execution_update feed on /system; for a run this tab saw start, a browser Notification is shown
 * when it ends while the tab is hidden. The feed carries no starter id, so teammates' runs on the
 * same team that this tab saw start are included. The switch is read on each event.
 */
const RunFinishedNotifier: React.FC = () => {
  const { t } = useI18n();

  useEffect(() => {
    const seen = new Set<string>();
    let socket: Socket | null = null;
    try {
      socket = createServerSocket(getServerBaseUrl() || window.location.origin, '/system', {
        transports: ['websocket'],
        reconnection: true,
      });
    } catch {
      return undefined;
    }
    socket.on('system_update', (event: any) => {
      if (event?.type !== 'execution_update' || !event.execution_id) return;
      if (event.status === 'running') {
        seen.add(event.execution_id);
        return;
      }
      if (!TERMINAL.has(event.status) || !seen.delete(event.execution_id)) return;
      if (!document.hidden || !loadFlag(NOTIFY_RUNS_KEY)) return;
      if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
      const failed = event.status === 'failed' || Boolean(event.error);
      try {
        new Notification(failed ? t('Run failed') : t('Run finished'), {
          body: [event.host_name, event.device_id].filter(Boolean).join(' · '),
        });
      } catch {
        /* notifications blocked by the browser */
      }
    });
    return () => {
      socket?.disconnect();
    };
  }, [t]);

  return null;
};

export default RunFinishedNotifier;
