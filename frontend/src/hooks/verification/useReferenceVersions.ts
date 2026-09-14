import { useCallback, useState } from 'react';

import { useToastContext } from '../../contexts/ToastContext';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

/**
 * Reference version history (Grafana-style restore).
 *
 * Every overwrite of a reference snapshots the PREVIOUS {image + area} into
 * verifications_reference_versions (newest 10 kept). This hook lists those
 * versions for one reference and restores a chosen one. Restore is undoable:
 * the server snapshots the current live state first, so it becomes the new
 * top version and the user can restore again to step back.
 */
export interface ReferenceVersion {
  id: string;
  reference_id: string;
  version_number: number;
  reference_type: 'reference_image' | 'reference_text';
  r2_path: string | null;
  r2_url: string | null;
  area: any;
  created_at: string;
}

export const useReferenceVersions = () => {
  const { showError, showSuccess } = useToastContext();
  const [versions, setVersions] = useState<ReferenceVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [restoringId, setRestoringId] = useState<string | null>(null);

  const list = useCallback(
    async (referenceId: string) => {
      setLoading(true);
      try {
        const res = await api.post<{
          success?: boolean;
          versions?: ReferenceVersion[];
          message?: string;
        }>(buildServerUrl('/server/verification/getReferenceVersions'), {
          reference_id: referenceId,
        });
        if (!res.success) throw new Error(res.message || 'Failed to load versions');
        setVersions(res.versions || []);
      } catch (err) {
        showError(`Failed to load history: ${err instanceof Error ? err.message : 'Unknown error'}`);
        setVersions([]);
      } finally {
        setLoading(false);
      }
    },
    [showError],
  );

  const restore = useCallback(
    async (referenceId: string, versionId: string): Promise<boolean> => {
      setRestoringId(versionId);
      try {
        const res = await api.post<{
          success?: boolean;
          restored_version?: number;
          message?: string;
        }>(buildServerUrl('/server/verification/restoreReferenceVersion'), {
          reference_id: referenceId,
          version_id: versionId,
        });
        if (!res.success) throw new Error(res.message || 'Failed to restore');
        showSuccess(`Restored reference to v${res.restored_version}`);
        return true;
      } catch (err) {
        showError(`Restore failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
        return false;
      } finally {
        setRestoringId(null);
      }
    },
    [showError, showSuccess],
  );

  return { versions, loading, restoringId, list, restore };
};

export type UseReferenceVersionsType = ReturnType<typeof useReferenceVersions>;
