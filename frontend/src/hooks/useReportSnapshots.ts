/**
 * Report snapshot sharing (TASK-49): create, list and revoke expiring share links
 * for one test report. The config is fetched once per session and cached.
 */

import { useCallback } from 'react';

import { APP_CONFIG } from '../config/constants';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

export interface ReportSnapshotConfig {
  enabled: boolean;
  can_share: boolean;
  expiry_choices: number[];
  default_expires_in: number;
}

export interface CreateSnapshotPayload {
  script_result_id: string;
  expires_in: number;
  password?: string;
  include_video: boolean;
}

export interface CreatedSnapshot {
  id: string;
  path: string;
  delete_path: string;
  expires_at: string;
  size_bytes: number;
}

export interface ReportSnapshot {
  id: string;
  created_by: string | null;
  created_at: string;
  expires_at: string;
  has_password: boolean;
  include_video: boolean;
  size_bytes: number;
  view_count: number;
  last_viewed_at: string | null;
}

export type TeamSnapshotStatus = 'active' | 'expired' | 'revoked' | 'all';

export interface TeamSnapshot extends ReportSnapshot {
  script_result_id: string;
  revoked_at: string | null;
  purged_at: string | null;
  script_name: string | null;
  device_name: string | null;
  host_name: string | null;
  script_started_at: string | null;
  report_url: string | null;
  created_by_name: string | null;
  can_revoke: boolean;
}

export interface TeamSnapshotList {
  snapshots: TeamSnapshot[];
  quota: { used_bytes: number; limit_bytes: number };
}

// Session-wide cache. A failed fetch is not cached so a later call can retry.
let configPromise: Promise<ReportSnapshotConfig> | null = null;

export const useReportSnapshots = () => {
  const getConfig = useCallback((): Promise<ReportSnapshotConfig> => {
    if (!configPromise) {
      configPromise = api
        .get<ReportSnapshotConfig>(buildServerUrl('/server/report-snapshots/config'))
        .catch((err) => {
          configPromise = null;
          throw err;
        });
    }
    return configPromise;
  }, []);

  const createSnapshot = useCallback(
    (payload: CreateSnapshotPayload): Promise<CreatedSnapshot> =>
      api.post<CreatedSnapshot>(buildServerUrl('/server/report-snapshots'), {
        ...payload,
        team_id: APP_CONFIG.DEFAULT_TEAM_ID,
      }),
    [],
  );

  const listSnapshots = useCallback(async (scriptResultId: string): Promise<ReportSnapshot[]> => {
    const data = await api.get<{ snapshots: ReportSnapshot[] }>(
      buildServerUrl(
        `/server/report-snapshots?script_result_id=${encodeURIComponent(scriptResultId)}`,
      ),
    );
    return data.snapshots || [];
  }, []);

  const listTeamSnapshots = useCallback(
    (status: TeamSnapshotStatus): Promise<TeamSnapshotList> =>
      api.get<TeamSnapshotList>(
        buildServerUrl(`/server/report-snapshots/team?status=${encodeURIComponent(status)}`),
      ),
    [],
  );

  const revokeSnapshot = useCallback(async (id: string): Promise<void> => {
    await api.delete(buildServerUrl(`/server/report-snapshots/${encodeURIComponent(id)}`));
  }, []);

  return { getConfig, createSnapshot, listSnapshots, listTeamSnapshots, revokeSnapshot };
};

export default useReportSnapshots;
