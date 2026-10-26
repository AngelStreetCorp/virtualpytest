import React, { useState } from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, TextField, Typography } from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { StatusText } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { requestFrontendSetup, type FrontendSetupResult } from '../../hooks/platformUpdate/platformUpdateActions';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';

interface Props {
  /** Called after a run that saved the settings, so the prerequisites run again. */
  onDone: () => void;
}

/**
 * "Set up frontend VM" (TASK-128 G13): the admin types the frontend VM's address, an admin account and its password once.
 * The server logs in, creates the deploy account, installs its key and sudo rights, saves the settings and forgets the
 * password. The password lives in this component's state only until the call returns (cleared on every outcome).
 */
export const FrontendSetup: React.FC<Props> = ({ onDone }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [host, setHost] = useState('');
  const [admin, setAdmin] = useState('root');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FrontendSetupResult | null>(null);

  const close = () => {
    setOpen(false);
    setPassword('');
    setError(null);
    setResult(null);
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await requestFrontendSetup(host.trim(), admin.trim(), password);
      setResult(res);
      if (res.steps.some((s) => s.name === 'save settings' && s.ok)) onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Request failed'));
    } finally {
      setPassword('');   // never kept, whatever happened
      setBusy(false);
    }
  };

  return (
    <>
      <Button size="small" variant="outlined" sx={neutralButtonSx(P)} onClick={() => setOpen(true)}>
        {t('Set up frontend VM')}
      </Button>
      <Dialog open={open} onClose={busy ? undefined : close} fullWidth maxWidth="xs">
        <DialogTitle>{t('Set up frontend VM')}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1.5 }}>
            {t('Root, or an account that can use sudo with its password. The password is used once and is not kept.')}
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <TextField size="small" label={t('Frontend VM address')} placeholder="192.168.0.20" autoComplete="off" value={host} onChange={(e) => setHost(e.target.value)} />
            <TextField size="small" label={t('Admin user')} autoComplete="off" value={admin} onChange={(e) => setAdmin(e.target.value)} />
            <TextField size="small" type="password" label={t('Password')} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Box>
          {error ? <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert> : null}
          {result ? (
            <Box sx={{ mt: 1.5 }}>
              {result.steps.map((s) => (
                <Box key={s.name} sx={{ mb: 0.75 }}>
                  <StatusText ok={s.ok}>{s.name}</StatusText>
                  {s.detail ? (
                    <Box
                      component="pre"
                      sx={{ m: 0, mt: 0.25, p: 1, bgcolor: P.hoverBg, borderRadius: 1, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: P.textSecondary, maxHeight: 160, overflowY: 'auto' }}
                    >
                      {s.detail}
                    </Box>
                  ) : null}
                </Box>
              ))}
            </Box>
          ) : null}
        </DialogContent>
        <DialogActions sx={{ px: 3 }}>
          <Button size="small" onClick={close} disabled={busy}>{t('Close')}</Button>
          <Button size="small" variant="contained" sx={primaryButtonSx(P)} disabled={busy || !host.trim() || !admin.trim() || !password} onClick={() => void run()}>
            {busy ? <CircularProgress size={14} color="inherit" /> : t('Set up')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};
