import React, { useState } from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { requestHostUpdateOnce, type HostCoreUpdate } from '../../hooks/platformUpdate/platformUpdateActions';
import { neutralButtonSx } from '../common/PageChrome';

interface Props {
  host: string;
  /** Called after a successful update so the checks run again (the host restarts a few seconds later). */
  onDone: () => void;
}

/**
 * "Update host once" on the host version KO row (TASK-128 G11). Confirms, then brings an old host to a pull-capable version
 * through the shared-source update it already has. When the host cannot reach the shared source the error says so and the
 * manual commands above stay the way.
 */
export const UpdateHostOnce: React.FC<Props> = ({ host, onDone }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<HostCoreUpdate | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setDone(await requestHostUpdateOnce(host));
      setConfirming(false);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Request failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ mb: 0.75 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: P.textPrimary }}>{host}</Typography>
        <Button size="small" variant="outlined" sx={neutralButtonSx(P)} disabled={busy || !!done} onClick={() => { setError(null); setConfirming(true); }}>
          {t('Update host once')}
        </Button>
      </Box>
      {error && !confirming ? <Alert severity="error" sx={{ mt: 0.5 }}>{error}</Alert> : null}
      {done ? (
        <Alert severity="success" sx={{ mt: 0.5 }}>
          {t('{host} updated from {before} to {after}. Its service restarts now: press Re-check in a few seconds.', {
            host, before: done.version_before ?? '?', after: done.version_after ?? '?',
          })}
        </Alert>
      ) : null}
      <Dialog open={confirming} onClose={() => setConfirming(false)} fullWidth maxWidth="xs">
        <DialogTitle>{t('Update {host} once?', { host })}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, mb: 1 }}>
            {t('This host is too old to pull updates. It copies the code from the shared source it already has (a backup is kept on the host), then restarts its service. The .env file is not touched.')}
          </Typography>
          {error ? <Alert severity="error">{error}</Alert> : null}
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setConfirming(false)} disabled={busy}>{t('Cancel')}</Button>
          <Button size="small" variant="outlined" sx={neutralButtonSx(P)} disabled={busy} onClick={() => void run()}>
            {busy ? <CircularProgress size={14} color="inherit" /> : t('Update host once')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
