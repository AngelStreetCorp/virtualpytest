import { useCallback, useState } from 'react';

import { APP_CONFIG } from '../../config/constants';
import { notify } from '../../contexts/notificationStore';
import { useI18n } from '../../i18n/useI18n';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { formatSize } from '../platformUpdate/FreeSpace';

interface CleanupResult {
  success?: boolean;
  error?: string;
  freed_bytes: number;
  files: number;
  disk_before: number;
  disk_after: number | null;
}

interface Pending {
  host: string;
  dry: CleanupResult;
}

const cleanup = (host: string, dryRun: boolean) =>
  api.post<CleanupResult>(buildServerUrl('/server/system/hostDiskCleanup'), {
    host_name: host,
    dry_run: dryRun,
    team_id: APP_CONFIG.DEFAULT_TEAM_ID,
  });

/**
 * "Fix now" on a host disk problem: dry run first, confirm with the figure, then delete expired capture files on that
 * host, toast "Freed X, disk A % -> B %" and refresh the dashboard. Rules: shared/src/lib/utils/host_disk_cleanup.py.
 */
export const useHostDiskFix = (onDone: () => void) => {
  const { t } = useI18n();
  const [pending, setPending] = useState<Pending | null>(null);

  const fail = useCallback(
    (host: string, err: unknown) => {
      const message = err instanceof Error && err.message ? err.message : t('Cleanup failed');
      notify({ id: `disk-fix-${host}`, category: 'action', severity: 'error', message: `${host}: ${message}` });
    },
    [t],
  );

  const request = useCallback(
    async (host: string) => {
      try {
        const dry = await cleanup(host, true);
        if (dry?.success === false) throw new Error(dry.error);
        if (dry.files === 0) {
          notify({ id: `disk-fix-${host}`, category: 'action', severity: 'info', message: t('Nothing expired to delete on {host}', { host }) });
          return;
        }
        setPending({ host, dry });
      } catch (err) {
        fail(host, err);
      }
    },
    [fail, t],
  );

  const run = useCallback(async () => {
    if (!pending) return;
    const { host } = pending;
    setPending(null);
    try {
      const res = await cleanup(host, false);
      if (res?.success === false) throw new Error(res.error);
      notify({
        id: `disk-fix-${host}`,
        category: 'action',
        severity: 'success',
        message: t('Freed {size} on {host}, disk {before} % -> {after} %', {
          size: formatSize(res.freed_bytes),
          host,
          before: Math.round(res.disk_before),
          after: Math.round(res.disk_after ?? res.disk_before),
        }),
      });
      onDone();
    } catch (err) {
      fail(host, err);
    }
  }, [pending, onDone, fail, t]);

  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      title={t('Free disk space')}
      message={
        pending
          ? t('Delete expired captures, thumbnails and reports on {host}? About {size} ({files} files) will be freed. Recordings in use are kept.', {
              host: pending.host,
              size: formatSize(pending.dry.freed_bytes),
              files: pending.dry.files,
            })
          : ''
      }
      confirmText={t('Fix now')}
      cancelText={t('Cancel')}
      onConfirm={run}
      onCancel={() => setPending(null)}
    />
  );

  return { request, dialog };
};
