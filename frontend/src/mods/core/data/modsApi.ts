/** Calls to the mods feature's server routes (features/mods/backend_server). */
import { APP_CONFIG } from '../../../config/constants';
import { api } from '../../../utils/apiClient';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import { PREFERENCES_PATH, SNAPSHOT_PATH, WIDGETS_PATH } from '../constants';
import type { WidgetAreaName, WidgetInstance } from '../types';

import type { ModChoices } from './enabledMods';

/** The current state as `system_update`-shaped events (runs, locks, presence). */
export const fetchSnapshot = async (): Promise<unknown[]> => {
  const data = await api.get<{ success: boolean; events?: unknown[] }>(buildServerUrl(SNAPSHOT_PATH), { cache: 'no-store' });
  return data?.success && Array.isArray(data.events) ? data.events : [];
};

export interface ServerPreferences {
  /** A shared login (auto-sign, open mode…): choices stay in the browser. */
  shared: boolean;
  choices: ModChoices;
}

export const fetchPreferences = async (): Promise<ServerPreferences | null> => {
  const data = await api.get<{ success: boolean; shared?: boolean; choices?: ModChoices }>(
    buildServerUrl(PREFERENCES_PATH),
    { cache: 'no-store' },
  );
  return data?.success ? { shared: Boolean(data.shared), choices: data.choices ?? {} } : null;
};

export const savePreference = (modId: string, enabled: boolean) =>
  api.put(buildServerUrl(PREFERENCES_PATH), { team_id: APP_CONFIG.DEFAULT_TEAM_ID, mod_id: modId, enabled });

export interface ServerWidgetLayout {
  shared: boolean;
  /** null = this user never saved this area. */
  layout: WidgetInstance[] | null;
}

export const fetchWidgetLayout = async (area: WidgetAreaName): Promise<ServerWidgetLayout | null> => {
  const data = await api.get<{ success: boolean; shared?: boolean; layout?: WidgetInstance[] | null }>(
    `${buildServerUrl(WIDGETS_PATH)}&area=${encodeURIComponent(area)}`,
    { cache: 'no-store' },
  );
  return data?.success ? { shared: Boolean(data.shared), layout: Array.isArray(data.layout) ? data.layout : null } : null;
};

export const saveWidgetLayout = (area: WidgetAreaName, layout: WidgetInstance[]) =>
  api.put(buildServerUrl(WIDGETS_PATH), { team_id: APP_CONFIG.DEFAULT_TEAM_ID, area, layout });
