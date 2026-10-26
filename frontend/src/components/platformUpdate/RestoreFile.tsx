import React, { useState } from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { requestRestore, type RestoreResult } from '../../hooks/platformUpdate/platformUpdateActions';
import { dangerButtonSx } from '../common/PageChrome';
import { CommandBox } from './CommandBox';

interface Props {
  /** Backup folder name (step 1 result), the item id (`server`, `host:<name>`, `frontend`) and the stored file. */
  folder: string;
  itemId: string;
  file: string;
  /** The file's real name on its machine, e.g. `.env`. */
  name: string;
  /** Where it goes: the item's label (server, a host name, the frontend VM). */
  machine: string;
  disabled?: boolean;
}

/**
 * One saved `.env` of the step 1 result with a Restore button (TASK-128 G7). The button asks for a confirmation, writes the
 * file back (the current one is kept as `.bak-<timestamp>`) and then shows the exact command that makes it take effect.
 * The app never restarts a service.
 */
export const RestoreFile: React.FC<Props> = ({ folder, itemId, file, name, machine, disabled }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<RestoreResult | null>(null);

  const restore = async () => {
    setBusy(true);
    setError(null);
    try {
      setDone(await requestRestore(folder, itemId, file));
      setConfirming(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Request failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ pl: 5, py: 0.25 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, fontFamily: 'monospace' }}>{name}</Typography>
        <Button size="small" variant="outlined" sx={dangerButtonSx(P)} disabled={disabled || busy} onClick={() => { setError(null); setConfirming(true); }}>
          {t('Restore')}
        </Button>
      </Box>
      {error && !confirming ? <Alert severity="error" sx={{ mt: 0.5 }}>{error}</Alert> : null}
      {done ? (
        <Box sx={{ mt: 0.5 }}>
          <Alert severity="success" sx={{ mb: 0.75 }}>
            {t('Restored {name} on {machine}.', { name: done.restored, machine })}
            {done.backup_of_current ? ` ${t('The previous file is kept as {file}.', { file: done.backup_of_current })}` : ''}
          </Alert>
          <CommandBox
            caption={done.restart.machine}
            hint={`${t('Restart the service to apply it. The app does not do it.')}${done.note ? ` ${done.note}` : ''}`}
            text={done.restart.command}
          />
        </Box>
      ) : null}
      <Dialog open={confirming} onClose={() => setConfirming(false)} fullWidth maxWidth="xs">
        <DialogTitle>{t('Restore {name}?', { name })}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, mb: 1 }}>
            {t('This replaces {name} on {machine} with the copy saved in this backup. The current file is kept next to it as .bak-<timestamp>. Nothing is restarted.', { name, machine })}
          </Typography>
          {error ? <Alert severity="error">{error}</Alert> : null}
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setConfirming(false)} disabled={busy}>{t('Cancel')}</Button>
          <Button size="small" variant="outlined" sx={dangerButtonSx(P)} disabled={busy} onClick={() => void restore()}>
            {busy ? <CircularProgress size={14} color="inherit" /> : t('Restore')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
