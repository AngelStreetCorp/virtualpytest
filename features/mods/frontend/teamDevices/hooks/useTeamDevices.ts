import { useEffect, useMemo } from 'react';

import { APP_CONFIG } from '../../../../../frontend/src/config/constants';
import { useWorkspaceContext } from '../../../../../frontend/src/contexts/workspace/WorkspaceContext';
import { useHostData } from '../../../../../frontend/src/hooks/useHostManager';
import { useModStore } from '../../../../../frontend/src/mods/core/hooks/useModStore';
import { api } from '../../../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../../../frontend/src/utils/buildUrlUtils';
import { buildRows, countAlerts, countFailures, totals } from '../actions';
import { ALERTS_PATH, ERRORS_OPEN_ALERTS, FAILURE_WINDOWS, REFRESH_MS, RESULTS_PATH } from '../constants';
import { fleetStore } from '../data/store';
import type { AlertRow, ErrorCounts, ErrorSource, ScriptResultRow } from '../types';

const loadErrors = async (source: ErrorSource): Promise<ErrorCounts> => {
  if (source === ERRORS_OPEN_ALERTS) {
    const data = await api.get<{ success?: boolean; alerts?: AlertRow[] }>(buildServerUrl(ALERTS_PATH), { cache: 'no-store' });
    return countAlerts(Array.isArray(data?.alerts) ? data.alerts : [], APP_CONFIG.DEFAULT_TEAM_ID);
  }
  const { windowMs, limit } = FAILURE_WINDOWS[source];
  const rows = await api.get<ScriptResultRow[]>(`${buildServerUrl(RESULTS_PATH)}&limit=${limit}`, { cache: 'no-store' });
  return countFailures(Array.isArray(rows) ? rows : [], Date.now(), windowMs);
};

/** The team's devices (workspace-filtered) with running runs and errors from the chosen source. */
export const useTeamDevices = (show: string, source: ErrorSource) => {
  const state = useModStore(fleetStore);
  const { getAllHosts } = useHostData();
  const { isDeviceAllowed } = useWorkspaceContext();

  // Errors are read while a widget is on screen, every minute.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const counts = await loadErrors(source);
        if (!cancelled) fleetStore.update((s) => ({ ...s, errors: { ...s.errors, [source]: counts } }));
      } catch (err) {
        console.warn('[@mods:team-devices] errors not loaded', err);
      }
    };
    void load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [source]);

  const errors = state.errors[source];
  const hosts = useMemo(
    () => getAllHosts().map((h) => ({ ...h, devices: (h.devices ?? []).filter((d) => isDeviceAllowed(h.host_name, d.device_id)) })),
    [getAllHosts, isDeviceAllowed],
  );
  const rows = useMemo(() => buildRows(hosts, state.running, errors, show), [hosts, state.running, errors, show]);
  const allRows = useMemo(() => buildRows(hosts, state.running, errors, 'all'), [hosts, state.running, errors]);

  return { rows, totals: totals(allRows), errorsLoaded: errors !== undefined };
};
