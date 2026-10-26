import React, { useEffect, useState } from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, TextField, Typography } from '@mui/material';

import { AppIcon } from '../../constants/icons';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { usePlatformUpdateSettings, type SettingKey } from '../../hooks/platformUpdate/usePlatformUpdateSettings';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';
import { CommandBox } from './CommandBox';
import { FrontendSetup } from './FrontendSetup';

interface FieldDef {
  key: SettingKey;
  label: string;
  placeholder: string;
}


interface Props {
  /** Called after a successful save so the prerequisites run again. */
  onSaved: () => void;
}

/** "Settings" button + dialog (TASK-128 G1/G2): what used to be typed into the server .env, plus the DB backup set-up. */
export const PlatformUpdateSettings: React.FC<Props> = ({ onSaved }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const s = usePlatformUpdateSettings();
  const { settings, load, loadKey } = s;
  const FIELDS: FieldDef[] = [
    { key: 'frontend_deploy_host', label: t('Frontend host'), placeholder: 'host, IP, local or none' },
    { key: 'frontend_deploy_ssh_user', label: t('SSH user'), placeholder: 'deploy' },
    { key: 'frontend_deploy_ssh_key', label: t('SSH key path'), placeholder: '/home/vpt_user/.ssh/id_ed25519' },
    { key: 'db_dsn', label: t('Database connection'), placeholder: 'postgresql://user:password@host:5432/postgres' },
    { key: 'database_agent', label: t('Database agent'), placeholder: 'host:9110' },
    { key: 'github_token', label: t('GitHub token'), placeholder: 'ghp_… / github_pat_…' },
  ];
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Partial<Record<SettingKey, string>>>({});
  const [command, setCommand] = useState('');
  const [copied, setCopied] = useState(false);
  const [recheck, setRecheck] = useState<{ ok: boolean; detail: string } | null>(null);

  useEffect(() => {
    if (open) {
      void load();
      void loadKey();
    }
  }, [open, load, loadKey]);

  const close = () => {
    setOpen(false);
    setDraft({});
    setCommand('');  // the token is shown once: it is gone when the dialog closes
    setRecheck(null);
    setCopied(false);
  };

  const shown = (key: FieldDef['key']): string => draft[key] ?? (settings?.[key].secret ? '' : settings?.[key].value ?? '');
  const hint = (key: FieldDef['key']): string => {
    const v = settings?.[key];
    if (!v) return '';
    if (v.secret) return v.set ? `${t('set')} (${v.source === 'env' ? '.env' : t('saved here')})` : t('not set');
    return v.source === 'env' ? t('From .env') : '';
  };

  const save = async () => {
    if (!settings) return;
    const changes: Partial<Record<SettingKey, string>> = {};
    FIELDS.forEach(({ key }) => {
      const typed = draft[key];
      if (typed !== undefined && (settings[key].secret ? true : typed !== (settings[key].value ?? ''))) changes[key] = typed.trim();
    });
    if (Object.keys(changes).length === 0 || (await s.save(changes))) {
      setDraft({});
      onSaved();
    }
  };

  const generate = async () => {
    if (settings?.vm_agent_action_token.set && !window.confirm(t('A new token replaces the old one. The database VM must run the command again.'))) return;
    const res = await s.generateToken();
    if (res) {
      setCommand(res.command);
      setRecheck(null);
      setCopied(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <>
      <Button size="small" variant="outlined" onClick={() => setOpen(true)} sx={{ ml: 1, textTransform: 'none', ...neutralButtonSx(P) }}>
        {t('Settings')}
      </Button>
      <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
        <DialogTitle>{t('Settings')}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1.5 }}>
            {t('Saved on the server. The .env is only used where nothing is saved here.')}
          </Typography>
          {s.storage ? (
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: s.storage === 'db' ? P.textSecondary : P.warning, mb: 1 }}>
              {s.storage === 'db'
                ? t('Stored in the database, for this server.')
                : t('Stored in a file on the server: the database table is not created yet.')}
            </Typography>
          ) : null}
          {s.error ? <Alert severity="error" sx={{ mb: 1 }}>{s.error}</Alert> : null}
          {!settings ? <CircularProgress size={18} /> : null}
          {settings ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {FIELDS.map(({ key, label, placeholder }) => (
                <Box key={key} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
                  <TextField
                    fullWidth
                    size="small"
                    label={label}
                    type={settings[key].secret ? 'password' : 'text'}
                    autoComplete="off"
                    value={shown(key)}
                    placeholder={settings[key].secret && settings[key].set ? t('set') : placeholder}
                    helperText={hint(key) || undefined}
                    onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                  />
                  {settings[key].secret && settings[key].source === 'store' ? (
                    <Button size="small" sx={{ mt: 0.5, ...neutralButtonSx(P) }} onClick={() => setDraft((d) => ({ ...d, [key]: '' }))}>
                      {t('Clear')}
                    </Button>
                  ) : null}
                </Box>
              ))}
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                {t('GitLab instances are set in')}{' '}
                <Box component="a" href="/monitoring/gitlab" sx={{ color: 'primary.main' }}>{t('Plugins → GitLab')}</Box>
              </Typography>
              <Box sx={{ borderTop: `1px solid ${P.borderColor}`, pt: 1.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <Typography sx={{ flex: 1, fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>{t('Server key')}</Typography>
                  {s.serverKey && !s.serverKey.exists ? (
                    <Button
                      size="small"
                      variant="outlined"
                      sx={neutralButtonSx(P)}
                      disabled={s.busy}
                      onClick={async () => { if (await s.createKey()) onSaved(); }}
                    >
                      {t('Create key')}
                    </Button>
                  ) : null}
                </Box>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1 }}>
                  {s.serverKey?.exists
                    ? `${t('The server logs in to the frontend VM with this key')}: ${s.serverKey.path}`
                    : `${t('No key yet. Create it here; the server uses it to log in to the frontend VM.')}${s.serverKey ? ` (${s.serverKey.path})` : ''}`}
                </Typography>
                {s.serverKey?.exists ? (
                  <>
                    <CommandBox caption={t('Public key')} text={s.serverKey.public_key} />
                    <CommandBox caption={t('authorized_keys line')} hint={t('One line in authorized_keys of the deploy account on the frontend VM.')} text={s.serverKey.authorized_keys_line} />
                    <CommandBox caption={t('Command for the frontend VM')} hint={t('Run as root on the frontend VM. It creates the deploy account and installs the line and the sudo rights.')} text={s.serverKey.frontend_command} />
                  </>
                ) : null}
              </Box>
              <Box sx={{ borderTop: `1px solid ${P.borderColor}`, pt: 1.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <Typography sx={{ flex: 1, fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>{t('Frontend VM')}</Typography>
                  <FrontendSetup onDone={() => { void load(); void loadKey(); onSaved(); }} />
                </Box>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                  {t('Creates the deploy account, installs the server key and the sudo rights, and saves the settings above.')}
                </Typography>
              </Box>
              <Box sx={{ borderTop: `1px solid ${P.borderColor}`, pt: 1.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <Typography sx={{ flex: 1, fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>{t('DB backup')}</Typography>
                  <Button size="small" variant="outlined" sx={neutralButtonSx(P)} onClick={() => void generate()} disabled={s.busy}>
                    {settings.vm_agent_action_token.set ? t('Regenerate token') : t('Set up DB backup')}
                  </Button>
                </Box>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1 }}>
                  {`${t('Agent token')}: ${settings.vm_agent_action_token.set ? t('set') : t('not set')}`}
                </Typography>
                {command ? (
                  <>
                    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 0.5 }}>
                      {t('Run as root on the database VM. Keep your existing --containers value. Shown once.')}
                    </Typography>
                    <Box
                      component="pre"
                      sx={{ m: 0, mb: 1, p: 1, bgcolor: P.hoverBg, borderRadius: 1, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: P.textPrimary }}
                    >
                      {command}
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <Button size="small" variant="outlined" sx={neutralButtonSx(P)} startIcon={<AppIcon name="copy" />} onClick={() => void copy()}>
                        {copied ? t('Copied') : t('Copy')}
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        sx={neutralButtonSx(P)}
                        disabled={s.busy}
                        onClick={async () => { const r = await s.checkAgent(); if (r) { setRecheck(r); if (r.ok) onSaved(); } }}
                      >
                        {t('Re-check')}
                      </Button>
                      {recheck ? <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: recheck.ok ? P.success : P.error }}>{recheck.detail}</Typography> : null}
                    </Box>
                  </>
                ) : settings.vm_agent_action_token.set ? (
                  <Button
                    size="small"
                    variant="outlined"
                    sx={neutralButtonSx(P)}
                    disabled={s.busy}
                    onClick={async () => { const r = await s.checkAgent(); if (r) { setRecheck(r); if (r.ok) onSaved(); } }}
                  >
                    {t('Re-check')}
                  </Button>
                ) : null}
                {!command && recheck ? <Typography sx={{ mt: 0.5, fontSize: TYPOGRAPHY.caption.size, color: recheck.ok ? P.success : P.error }}>{recheck.detail}</Typography> : null}
              </Box>
            </Box>
          ) : null}
        </DialogContent>
        <DialogActions sx={{ px: 3 }}>
          <Button size="small" onClick={close}>{t('Close')}</Button>
          <Button size="small" variant="contained" sx={primaryButtonSx(P)} onClick={() => void save()} disabled={s.busy || !settings}>
            {t('Save')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};
