import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Typography,
} from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import {
  confirmRollbackRestart,
  requestDeployControl,
  requestLeavePartial,
  requestMigrationRollback,
  requestRollback,
  type DeployControlAction,
  type DeployImpact,
} from '../../hooks/platformUpdate/platformUpdateActions';
import type { RunStep, UpdateRun } from '../../hooks/platformUpdate/usePlatformUpdateRun';
import { dangerButtonSx, neutralButtonSx } from '../common/PageChrome';
import { CommandBox } from './CommandBox';

type Confirm = null | 'abort' | 'rollback' | 'partial' | 'migrations';

/** Runs one admin call, keeps its error, then lets the page reload the run. */
const useCall = (onChanged: () => void) => {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const call = async (work: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await work();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Request failed'));
      return false;
    } finally {
      setBusy(false);
      onChanged();
    }
  };
  return { busy, error, setError, call };
};

const ConfirmDialog: React.FC<{
  open: boolean; title: string; busy: boolean; error: string | null; label: string; needsTick?: string;
  onCancel: () => void; onConfirm: () => void; children: React.ReactNode;
}> = ({ open, title, busy, error, label, needsTick, onCancel, onConfirm, children }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [ticked, setTicked] = useState(false);
  return (
    <Dialog open={open} onClose={busy ? undefined : onCancel} fullWidth maxWidth="sm" TransitionProps={{ onExited: () => setTicked(false) }}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {children}
        {needsTick ? (
          <FormControlLabel control={<Checkbox size="small" checked={ticked} onChange={(_, v) => setTicked(v)} />} label={needsTick} />
        ) : null}
        {error ? <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert> : null}
      </DialogContent>
      <DialogActions>
        <Button size="small" onClick={onCancel} disabled={busy}>{t('Cancel')}</Button>
        <Button size="small" variant="outlined" sx={dangerButtonSx(P)} disabled={busy || (Boolean(needsTick) && !ticked)} onClick={onConfirm}>
          {busy ? <CircularProgress size={14} color="inherit" /> : label}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

const Line: React.FC<{ children: React.ReactNode; muted?: boolean }> = ({ children, muted }) => {
  const P = useAgentChatPalette();
  return <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: muted ? P.textMuted : P.textSecondary, mb: 0.5 }}>{children}</Typography>;
};

/**
 * Pause / Resume / Abort of a running pull deploy (TASK-128 G12). The server reads the flags between machines only, so a
 * request is taken after the machine in progress finishes; the banner says what was asked and what happens.
 */
export const DeployControls: React.FC<{ run: UpdateRun; step: RunStep; onChanged: () => void }> = ({ run, step, onChanged }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { busy, error, call } = useCall(onChanged);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const job = step.data.job as { mode?: string; state?: string } | undefined;
  if (step.state !== 'running' || job?.mode !== 'pull' || (job.state !== 'running' && job.state !== 'paused')) return null;
  const paused = job.state === 'paused';
  const send = (action: DeployControlAction) => call(() => requestDeployControl(run.id, action));

  return (
    <Box sx={{ mb: 1 }}>
      {paused ? (
        <Alert severity="info" sx={{ mb: 1 }}>
          {t('Paused. The machine in progress was finished; nothing else is updated until you resume.')}
        </Alert>
      ) : run.control?.abort ? (
        <Alert severity="warning" sx={{ mb: 1 }}>{t('Abort requested. The deploy stops after the machine in progress.')}</Alert>
      ) : run.control?.pause ? (
        <Alert severity="info" sx={{ mb: 1 }}>{t('Pause requested. The deploy waits after the machine in progress.')}</Alert>
      ) : null}
      <Box sx={{ display: 'flex', gap: 1 }}>
        {paused ? (
          <Button size="small" variant="contained" disabled={busy} onClick={() => void send('resume')}>{t('Resume')}</Button>
        ) : (
          <Button size="small" variant="outlined" sx={neutralButtonSx(P)} disabled={busy || Boolean(run.control?.pause)} onClick={() => void send('pause')}>
            {t('Pause')}
          </Button>
        )}
        <Button size="small" variant="outlined" sx={dangerButtonSx(P)} disabled={busy || Boolean(run.control?.abort)} onClick={() => setConfirm('abort')}>
          {t('Abort')}
        </Button>
      </Box>
      {error && confirm === null ? <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert> : null}
      <ConfirmDialog
        open={confirm === 'abort'} title={t('Abort the deploy?')} busy={busy} error={error} label={t('Abort')}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void send('abort').then((ok) => { if (ok) setConfirm(null); })}
      >
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>
          {t('The deploy stops before the next machine. Machines already updated stay on the new version until you roll them back.')}
        </Typography>
      </ConfirmDialog>
    </Box>
  );
};

const ROLE_LABEL: Record<string, string> = { host: 'host', frontend: 'frontend', server: 'server' };

/**
 * After an abort or a failed deploy: what changed, and the three ways out (TASK-128 G12): roll back (each updated machine goes
 * back to its backup, the server last), undo the migrations of this run (second confirm), or leave it partial on purpose.
 */
export const ImpactPanel: React.FC<{ run: UpdateRun; step: RunStep; impact: DeployImpact; onChanged: () => void }> = ({
  run, step, impact, onChanged,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { busy, error, setError, call } = useCall(onChanged);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const rb = impact.rollback;
  const mig = impact.migrations;
  const awaiting = step.state === 'running';      // the deploy itself is waiting for the server restart
  const close = () => { setConfirm(null); setError(null); };
  const missing = mig.plan.filter((m) => !m.has_rollback);

  return (
    <Box sx={{ mt: 1.5, pt: 1, borderTop: `1px solid ${P.borderColor}` }}>
      <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size, mb: 0.5 }}>
        {impact.aborted ? t('Deploy aborted') : t('Impact of this deploy')}
      </Typography>
      {impact.partial ? (
        <Alert severity="warning" sx={{ mb: 1 }}>{t('Left partial on purpose: {list}', { list: impact.partial.summary })}</Alert>
      ) : impact.mixed ? (
        <Alert severity="warning" sx={{ mb: 1 }}>{t('Mixed versions: {list}', { list: impact.mixed_summary })}</Alert>
      ) : null}
      {impact.rollback_order.length && !awaiting && !rb ? (
        <Line>{t('Roll back order: {list}', { list: impact.rollback_order.map((o) => `${o.name} (${t(ROLE_LABEL[o.role] ?? o.role)})`).join(', ') })}</Line>
      ) : null}

      {rb ? (
        <Box sx={{ mb: 1 }}>
          {rb.state === 'running' ? <Line>{t('Rolling back...')}</Line> : null}
          {rb.state === 'done' ? <Alert severity="success" sx={{ mb: 0.5 }}>{t('Rolled back. Every updated machine is on its previous version.')}</Alert> : null}
          {rb.state === 'failed' ? <Alert severity="error" sx={{ mb: 0.5 }}>{rb.error || t('The roll back stopped on a machine. Fix it, then roll back again: finished machines are skipped.')}</Alert> : null}
          {rb.actions.map((a) => (
            <Typography key={`${a.role}-${a.name}`} sx={{ fontSize: TYPOGRAPHY.caption.size, color: a.state === 'failed' ? P.error : P.textSecondary }}>
              {a.name} ({t(ROLE_LABEL[a.role] ?? a.role)}): {a.state === 'ok' ? t('rolled back') : a.state === 'failed' ? t('failed') : t('running')}
              {a.detail ? ` - ${a.detail}` : ''}
            </Typography>
          ))}
          {rb.state === 'awaiting_confirmation' ? (
            <Alert severity="info" sx={{ mt: 0.5 }}>
              {t('Server restarting on its previous version. Confirm once this page is back.')}
              <Box sx={{ mt: 1 }}>
                <Button size="small" variant="contained" disabled={busy} onClick={() => void call(() => confirmRollbackRestart(run.id))}>
                  {t('Confirm roll back')}
                </Button>
              </Box>
            </Alert>
          ) : null}
        </Box>
      ) : null}

      {mig.plan.length ? (
        <Box sx={{ mb: 1 }}>
          <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.caption.size, mb: 0.25 }}>{t('Migrations applied in this run')}</Typography>
          {mig.plan.map((m) => (
            <Typography key={m.file} sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', color: m.has_rollback ? P.textSecondary : P.warning }}>
              {m.file}{m.has_rollback ? '' : ` - ${t('no rollback file')}`}
            </Typography>
          ))}
          {mig.needs_dump_restore || missing.length ? (
            <Box sx={{ mt: 0.75 }}>
              <Line>{t('A migration without a rollback file cannot be undone here. Restore the database dump saved in step 1 (it replaces the whole database).')}</Line>
              {mig.restore_command ? <CommandBox caption={t('Database VM')} text={mig.restore_command} /> : null}
            </Box>
          ) : null}
        </Box>
      ) : null}
      {error && confirm === null ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        {impact.can_rollback ? (
          <Button size="small" variant="outlined" sx={dangerButtonSx(P)} disabled={busy} onClick={() => setConfirm('rollback')}>
            {rb?.state === 'failed' ? t('Roll back again') : t('Roll back')}
          </Button>
        ) : null}
        {mig.plan.length ? (
          <Button size="small" variant="outlined" sx={dangerButtonSx(P)} disabled={busy || rb?.state === 'running'} onClick={() => setConfirm('migrations')}>
            {t('Undo migrations')}
          </Button>
        ) : null}
        {impact.mixed && !impact.partial && rb?.state !== 'running' && rb?.state !== 'awaiting_confirmation' ? (
          <Button size="small" variant="outlined" sx={neutralButtonSx(P)} disabled={busy} onClick={() => setConfirm('partial')}>
            {t('Leave partial')}
          </Button>
        ) : null}
      </Box>

      <ConfirmDialog
        open={confirm === 'rollback'} title={t('Roll back the update?')} busy={busy} error={error} label={t('Roll back')}
        onCancel={close} onConfirm={() => void call(() => requestRollback(run.id)).then((ok) => { if (ok) close(); })}
      >
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, mb: 1 }}>
          {t('Each updated machine goes back to the copy saved before it was updated, in this order:')}
        </Typography>
        {impact.rollback_order.map((o, i) => (
          <Typography key={`${o.role}-${o.name}`} sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace' }}>
            {i + 1}. {o.name} ({t(ROLE_LABEL[o.role] ?? o.role)}){o.role === 'server' ? ` - ${t('restarts this server')}` : ''}
          </Typography>
        ))}
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mt: 1 }}>
          {t('Settings files (.env) stay as they are. Data written by the new version is not undone. Migrations are undone separately.')}
        </Typography>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirm === 'migrations'} title={t('Undo the migrations of this run?')} busy={busy} error={error} label={t('Undo migrations')}
        needsTick={t('I confirm running these rollback files')}
        onCancel={close}
        onConfirm={() => void call(() => requestMigrationRollback(run.id, mig.plan.map((m) => m.file))).then((ok) => { if (ok) close(); })}
      >
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, mb: 1 }}>{t('These files run on the database in this order (newest first):')}</Typography>
        {mig.plan.map((m) => (
          <Typography key={m.file} sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', color: m.has_rollback ? P.textPrimary : P.warning }}>
            {m.has_rollback ? m.rollback_file : `${m.file}: ${t('no rollback file, it stops here')}`}
          </Typography>
        ))}
        {missing.length ? (
          <Alert severity="warning" sx={{ mt: 1 }}>
            {t('It stops at the first migration without a rollback file. Then restore the step 1 database dump by hand.')}
          </Alert>
        ) : null}
      </ConfirmDialog>

      <ConfirmDialog
        open={confirm === 'partial'} title={t('Leave the update partial?')} busy={busy} error={error} label={t('Leave partial')}
        needsTick={t('I know the machines run different versions')}
        onCancel={close} onConfirm={() => void call(() => requestLeavePartial(run.id)).then((ok) => { if (ok) close(); })}
      >
        <Alert severity="warning">{t('Mixed versions: {list}', { list: impact.mixed_summary })}</Alert>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mt: 1 }}>
          {t('The deploy step is closed as failed. Nothing is changed on any machine.')}
        </Typography>
      </ConfirmDialog>
    </Box>
  );
};
