import React, { useState } from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { requestCleanup, type CleanupResult } from '../../hooks/platformUpdate/platformUpdateActions';
import { dangerButtonSx, neutralButtonSx } from '../common/PageChrome';

export const formatSize = (bytes: number): string => {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
};

/**
 * "Free space" on the Disk space check (TASK-128 G6). It first asks the server for a dry run and lists what would go
 * (update backups, built bundles, kept previous trees, beyond the newest five of each), then deletes only after the admin
 * confirms. It frees the server only: hosts are not touched.
 */
export const FreeSpace: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [plan, setPlan] = useState<CleanupResult | null>(null);
  const [freed, setFreed] = useState<CleanupResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Request failed'));
    } finally {
      setBusy(false);
    }
  };

  const open = () => guard(async () => { setFreed(null); setPlan(await requestCleanup(true)); });
  const confirm = () => guard(async () => { setFreed(await requestCleanup(false)); setPlan(null); onDone(); });
  const groups = plan?.groups.filter((g) => g.delete.length > 0) ?? [];

  return (
    <Box sx={{ mb: 0.75 }}>
      <Button size="small" variant="outlined" sx={neutralButtonSx(P)} disabled={busy} onClick={() => void open()}>
        {busy && !plan ? <CircularProgress size={14} color="inherit" /> : t('Free space')}
      </Button>
      {!plan && error ? <Alert severity="error" sx={{ mt: 0.75 }}>{error}</Alert> : null}
      {freed ? (
        <Alert severity={freed.errors.length ? 'warning' : 'success'} sx={{ mt: 0.75 }}>
          {t('Freed {size} on the server ({n} folders deleted).', { size: formatSize(freed.freed_bytes), n: freed.deleted })}
          {freed.errors.map((e) => ` ${e.path}: ${e.error}`).join('')}
        </Alert>
      ) : null}
      <Dialog open={Boolean(plan)} onClose={() => setPlan(null)} fullWidth maxWidth="sm">
        <DialogTitle>{t('Free space on the server')}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary, mb: 1 }}>
            {t('Keeps the newest {n} of each kind. Hosts are not touched.', { n: plan?.keep_newest ?? 5 })}
          </Typography>
          {groups.length === 0 ? <Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>{t('Nothing to delete: there are no older backups or bundles.')}</Typography> : null}
          {groups.map((g) => (
            <Box key={g.kind} sx={{ mb: 1 }}>
              <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>
                {t(g.label)}: {g.delete.length} · {formatSize(g.delete.reduce((sum, i) => sum + i.bytes, 0))}
              </Typography>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace', wordBreak: 'break-all' }}>
                {g.dir}
              </Typography>
              {g.delete.map((i) => (
                <Typography key={i.path} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, fontFamily: 'monospace' }}>
                  {i.name} ({formatSize(i.bytes)})
                </Typography>
              ))}
            </Box>
          ))}
          {groups.length > 0 ? (
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>
              {t('Total: {size}', { size: formatSize(plan?.total_bytes ?? 0) })}
            </Typography>
          ) : null}
          {error ? <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert> : null}
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setPlan(null)} disabled={busy}>{t('Cancel')}</Button>
          {groups.length > 0 ? (
            <Button size="small" variant="outlined" sx={dangerButtonSx(P)} disabled={busy} onClick={() => void confirm()}>
              {busy ? <CircularProgress size={14} color="inherit" /> : t('Delete these folders')}
            </Button>
          ) : null}
        </DialogActions>
      </Dialog>
    </Box>
  );
};
