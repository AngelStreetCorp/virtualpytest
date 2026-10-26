import React, { useEffect, useState } from 'react';
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
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { useCodeDeployment } from '../../hooks/platformUpdate/useCodeDeployment';
import type { MigrationsState, RunStep, StepState, UpdateRun } from '../../hooks/platformUpdate/usePlatformUpdateRun';
import { useScript } from '../../hooks/script/useScript';
import { useServerManager } from '../../hooks/useServerManager';
import { useBundleSources } from '../../hooks/platformUpdate/useBundleSources';
import { BundleBuilder, type CoreKind, type OverlayKind } from './BundleBuilder';
import { ExecutePanel, RollbackPanel, SourcePanel, TargetsPanel } from './CodeDeployPanels';
import { DeploymentView, type DeployVersions } from './DeploymentView';
import { DeployControls, ImpactPanel } from './DeployRollback';
import { useDeployImpact } from '../../hooks/platformUpdate/useDeployImpact';
import { CheckList } from './PrerequisitesBadge';
import { CommandBox } from './CommandBox';
import { RestoreFile } from './RestoreFile';
import type { PrerequisitesResult } from '../../hooks/platformUpdate/usePrerequisites';
import { TYPOGRAPHY } from '../../constants/typography';

type StepCall = (index: number, body: Record<string, unknown>) => Promise<UpdateRun | undefined>;

export interface StepContext {
  run: UpdateRun | null;
  busy: boolean;
  stepCall: StepCall;
  /** Reload the run now (after a pause / abort / roll back call that is not a step call). */
  refresh: () => Promise<void>;
  migrations: MigrationsState | null;
  refreshMigrations: () => Promise<void>;
  migrationCall: (path: string, body: Record<string, unknown>) => Promise<unknown>;
  /** Prerequisites (TASK-101): titles of the REQUIRED checks that are KO; empty = a deploy may start. */
  prereqBlocking: string[];
  prereqChecked: boolean;
  onSourcesChange: (core: CoreKind, overlay: OverlayKind, tag: string) => void;
  /** Core/overlay candidates, loaded once by the page. */
  bundleSources: ReturnType<typeof useBundleSources>;
  /** Versions per machine before the deploy and now (for the deployment cards). */
  versions: DeployVersions;
  /** `installed → target`, recorded with the close message. */
  fromTo: string;
  /** The sources picked in step 2: step 0 checks the prerequisites for them. */
  sources: { core: CoreKind; overlay: OverlayKind };
}

/** Short subtitle under each step title (6 words at most). */
export const STEP_SUMMARY: Record<number, string> = {
  0: 'Check the machines are ready.',
  1: 'Back up the database and .env files.',
  2: 'Build the update zip.',
  3: 'Send the zip everywhere.',
  4: 'Apply pending database changes.',
  5: 'Health check and smoke test.',
  6: 'Close and tell users.',
};

export const StateWord: React.FC<{ state: StepState }> = ({ state }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const map: Record<StepState, { label: string; color: string; Icon: React.ElementType }> = {
    pending: { label: 'Not started', color: P.textMuted, Icon: RadioButtonUncheckedIcon },
    waiting: { label: 'Your turn', color: P.accentText, Icon: PlayCircleOutlineIcon },
    running: { label: 'Running', color: P.accentText, Icon: HourglassEmptyIcon },
    done: { label: 'Done', color: P.success, Icon: CheckCircleOutlineIcon },
    failed: { label: 'Failed', color: P.error, Icon: ErrorOutlineIcon },
  };
  const { label, color, Icon } = map[state];
  return (
    <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color }}>
      <Icon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color }}>{t(label)}</Typography>
    </Box>
  );
};

const ResultLine: React.FC<{ ok: boolean; label: string; detail?: string }> = ({ ok, label, detail }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const color = ok ? P.success : P.error;
  return (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'baseline', py: 0.25 }}>
      {ok ? <CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.body.size, color }} /> : <ErrorOutlineIcon sx={{ fontSize: TYPOGRAPHY.body.size, color }} />}
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color }}>{ok ? t('ok') : t('failed')}</Typography>
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textPrimary }}>{label}</Typography>
      {detail ? (
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace' }}>{detail}</Typography>
      ) : null}
    </Box>
  );
};

const Hint: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const P = useAgentChatPalette();
  return <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1 }}>{children}</Typography>;
};

const Code: React.FC<{ children: string }> = ({ children }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      component="pre"
      sx={{
        m: 0, mb: 1, p: 1, bgcolor: P.hoverBg, borderRadius: 1, fontSize: TYPOGRAPHY.caption.size,
        fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: P.textPrimary,
      }}
    >
      {children}
    </Box>
  );
};

/** The only filled gold button of a step. */
const Action: React.FC<{ onClick: () => void; disabled?: boolean; busy?: boolean; children: React.ReactNode }> = ({
  onClick, disabled, busy, children,
}) => (
  <Button variant="contained" size="small" onClick={onClick} disabled={disabled || busy}>
    {busy ? <CircularProgress size={16} color="inherit" /> : children}
  </Button>
);

// ---------------------------------------------------------------------------------------------
// Step 0: run the prerequisite checks (the same list as the badge dialog)
// ---------------------------------------------------------------------------------------------
export const Step0: React.FC<{ step: RunStep; ctx: StepContext }> = ({ step, ctx }) => {
  const { t } = useI18n();
  const result = step.data.prerequisites as PrerequisitesResult | undefined;
  const locked = step.state === 'done' || step.state === 'running' || !ctx.run;
  return (
    <>
      <Box sx={{ mb: 1 }}>
        <Action
          busy={ctx.busy}
          disabled={locked}
          onClick={() => void ctx.stepCall(0, { action: 'check', core: ctx.sources.core, overlay: ctx.sources.overlay })}
        >
          {t('Run checks')}
        </Action>
      </Box>
      {result ? (
        <CheckList
          checks={result.checks}
          onRecheck={locked || ctx.busy ? undefined : () => void ctx.stepCall(0, { action: 'check', core: ctx.sources.core, overlay: ctx.sources.overlay })}
        />
      ) : null}
      {step.state === 'failed' && step.detail && !result ? <ResultLine ok={false} label={step.detail} /> : null}
    </>
  );
};

// ---------------------------------------------------------------------------------------------
// Step 1: ask the database VM for a backup, save the .env files, then confirm the VM snapshots
// ---------------------------------------------------------------------------------------------
interface BackupItem {
  id: string;
  label: string;
  status: 'ok' | 'ko' | 'na';
  detail: string;
  size: number;
  fix: string;
  /** The saved `.env` files with a Restore button (TASK-128 G7); absent in a backup made before it. */
  restore?: { file: string; name: string }[];
  /** Database item only: the command for the database VM. The app never restores a dump. */
  restore_command?: string;
}

const formatBytes = (n: number): string => (n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`);

const BackupRow: React.FC<{ item: BackupItem; folder?: string; locked?: boolean }> = ({ item, folder, locked }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const color = item.status === 'ok' ? P.success : item.status === 'ko' ? P.error : P.textMuted;
  const label = item.id === 'database' ? t('Database')
    : item.id === 'server' ? t('Server .env')
    : item.id === 'frontend' ? t('Frontend .env')
    : item.label;
  const machine = item.id === 'server' ? t('the server') : item.id === 'frontend' ? t('the frontend VM') : item.id.replace(/^host:/, '');
  return (
    <Box sx={{ py: 0.25 }}>
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'baseline' }}>
        <Typography sx={{ width: 32, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color }}>
          {item.status === 'ok' ? 'OK' : item.status === 'ko' ? 'KO' : 'N/A'}
        </Typography>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textPrimary }}>{label}</Typography>
        {item.status === 'ok' ? (
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace' }}>
            {item.id === 'database' ? item.detail : formatBytes(item.size)}
          </Typography>
        ) : null}
      </Box>
      {item.status !== 'ok' && item.detail ? (
        <Typography sx={{ pl: 5, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{item.detail}</Typography>
      ) : null}
      {item.status === 'ko' && item.fix ? (
        <Typography sx={{ pl: 5, fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{item.fix}</Typography>
      ) : null}
      {item.status === 'ok' && folder
        ? (item.restore ?? []).map((r) => (
            <RestoreFile key={r.file} folder={folder} itemId={item.id} file={r.file} name={r.name} machine={machine} disabled={locked} />
          ))
        : null}
      {item.status === 'ok' && item.id === 'database' && item.restore_command ? (
        <Box sx={{ pl: 5, pt: 0.5 }}>
          <CommandBox
            caption={t('Restore the database')}
            hint={t('Run as root on the database VM. It replaces the whole database with this dump, so the app never does it.')}
            text={item.restore_command}
          />
        </Box>
      ) : null}
    </Box>
  );
};

export const StepBackup: React.FC<{ step: RunStep; ctx: StepContext }> = ({ step, ctx }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const backup = step.data.backup as { ok: boolean; folder: string; path: string; items: BackupItem[] } | undefined;
  const done = step.state === 'done';
  const saved = Boolean(backup?.ok);
  const locked = !ctx.run || step.state === 'pending' || done || saved;
  return (
    <>
      <Box sx={{ mb: 1 }}>
        <Action busy={ctx.busy} disabled={locked} onClick={() => void ctx.stepCall(1, { action: 'backup' })}>
          {t('Back up')}
        </Action>
      </Box>
      {backup ? (
        <Box sx={{ mb: 1 }}>
          {backup.items.map((item) => (
            <BackupRow key={item.id} item={item} folder={saved ? backup.folder : undefined} locked={ctx.busy} />
          ))}
          {saved ? (
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace', mt: 0.5, wordBreak: 'break-all' }}>
              {backup.path}
            </Typography>
          ) : null}
        </Box>
      ) : null}
      <FormControlLabel
        control={
          <Checkbox
            size="small"
            checked={done}
            disabled={!saved || done || ctx.busy}
            onChange={(_, v) => { if (v) void ctx.stepCall(1, { action: 'confirm', snapshotted: true }); }}
          />
        }
        label={t('I snapshotted the VMs')}
      />
    </>
  );
};

// ---------------------------------------------------------------------------------------------
// Steps 2 and 3: build the bundle from any source, deploy exactly that bundle (TASK-99)
// ---------------------------------------------------------------------------------------------
const Advanced: React.FC<{ title: string; locked?: boolean; onOpen?: () => void; children: React.ReactNode }> = ({ title, locked, onOpen, children }) => {
  const P = useAgentChatPalette();
  const [open, setOpen] = useState(false);
  return (
    <Box sx={{ mt: 2, borderTop: `1px solid ${P.borderColor}`, pt: 1 }}>
      <Button size="small" variant="text" onClick={() => { if (!open) onOpen?.(); setOpen(!open); }} sx={{ px: 0, color: P.textSecondary }}>
        {open ? '- ' : '+ '}{title}
      </Button>
      {open ? (
        <Box sx={{ mt: 1, opacity: locked ? 0.6 : 1, pointerEvents: locked ? 'none' : 'auto' }}>{children}</Box>
      ) : null}
    </Box>
  );
};

export const CodeSteps: React.FC<{ steps: RunStep[]; ctx: StepContext; render: (index: number, body: React.ReactNode) => React.ReactNode }> = ({
  steps, ctx, render,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [version, setVersion] = useState('');
  const [overlay, setOverlay] = useState('');
  const [replaceCheckout, setReplaceCheckout] = useState(false);
  const code = useCodeDeployment({
    onFinished: (action, results, ok) => {
      if (!ctx.run) return;
      if (action === 'deploy') {
        void ctx.stepCall(3, { action: 'report', ok, targets: results, detail: ok ? '' : 'a target failed' });
      } else {
        void ctx.stepCall(3, { action: 'rolled_back', targets: results, detail: ok ? 'rolled back' : 'rollback failed' });
      }
    },
  });
  const detected = code.sourceVersionInfo.current || '';
  const shownVersion = version || detected;
  const stepBundle = steps[2];
  const stepDeploy = steps[3];
  const bundleLocked = !ctx.run || stepBundle.state === 'pending' || stepBundle.state === 'done';
  const deployLocked = !ctx.run || stepDeploy.state === 'pending';
  const bundle = stepBundle.data.bundle as { name: string; sha256: string } | undefined;
  const job = stepDeploy.data.job as { command?: string; state?: string } | undefined;
  const deployment = ctx.run?.deployment ?? null;
  const { impact } = useDeployImpact(ctx.run, stepDeploy, steps[4]);
  const deployRunning = stepDeploy.state === 'running' && job?.state === 'running';
  const awaiting = stepDeploy.state === 'running' && job?.state === 'awaiting_confirmation';
  const blocked = ctx.prereqBlocking.length > 0;
  const canDeploy = !deployLocked && stepBundle.state === 'done' && Boolean(bundle) && stepDeploy.state !== 'running' && stepDeploy.state !== 'done';
  const frontendVersion = ctx.versions.now.frontend;
  const hostWarnings = ((stepDeploy.data.hosts as Array<{ host: string; warnings?: string[] }> | undefined) ?? []).filter((h) => h.warnings?.length);

  return (
    <>
      {code.error ? <Alert severity="error" sx={{ mb: 1 }}>{code.error}</Alert> : null}
      {code.info ? <Alert severity="info" sx={{ mb: 1 }}>{code.info}</Alert> : null}
      {render(
        2,
        <>
          <BundleBuilder
            run={ctx.run}
            step={stepBundle}
            locked={bundleLocked}
            busy={ctx.busy}
            build={(body) => ctx.stepCall(2, body)}
            bundleSources={ctx.bundleSources}
            onSourcesChange={ctx.onSourcesChange}
          />
          <Advanced title={t('Advanced: prepared source')} locked={bundleLocked} onOpen={() => void code.detectSource()}>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1 }}>
              <TextField size="small" label={t('Version (PIN)')} value={shownVersion} onChange={(e) => setVersion(e.target.value)} />
              <TextField size="small" label={t('Overlay project')} value={overlay} onChange={(e) => setOverlay(e.target.value)} />
            </Box>
            <Box sx={{ mb: 1 }}>
              <SourcePanel d={code} />
            </Box>
            <Action
              busy={ctx.busy}
              disabled={bundleLocked || !shownVersion || !code.sourceReady}
              onClick={() =>
                void ctx.stepCall(2, {
                  action: 'report', ok: true, source: code.sourceMode, version: shownVersion, overlay,
                })
              }
            >
              {t('Source is ready')}
            </Action>
            {!code.sourceReady && !bundleLocked ? (
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, mt: 0.5, color: 'text.secondary' }}>
                {t('Prepare the source first.')}
              </Typography>
            ) : null}
          </Advanced>
        </>
      )}
      {render(
        3,
        <>
          {bundle ? (
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', mb: 1 }}>{bundle.name}</Typography>
          ) : (
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: 'text.secondary', mb: 1 }}>{t('Build the bundle first.')}</Typography>
          )}
          {blocked ? (
            <Alert severity="error" sx={{ mb: 1 }}>
              {t('Prerequisites failed: {list}', { list: ctx.prereqBlocking.join(', ') })}
            </Alert>
          ) : null}
          <Box sx={{ mb: 1 }}>
            <Action
              busy={ctx.busy}
              disabled={!canDeploy || blocked || !ctx.prereqChecked}
              onClick={() => void ctx.stepCall(3, { action: 'deploy_pull', frontend_version: frontendVersion })}
            >
              {t('Deploy')}
            </Action>
          </Box>
          {awaiting ? (
            <Alert severity="info" sx={{ mb: 1 }}>
              {t('Server restarting. Confirm once this page is back.')}
              <Box sx={{ mt: 1 }}>
                <Action busy={ctx.busy} onClick={() => void ctx.stepCall(3, { action: 'confirm_pull' })}>
                  {t('Confirm restart')}
                </Action>
              </Box>
            </Alert>
          ) : null}
          {ctx.run ? <DeployControls run={ctx.run} step={stepDeploy} onChanged={() => void ctx.refresh()} /> : null}
          {stepDeploy.state === 'failed' && stepDeploy.detail ? <Alert severity="error" sx={{ mb: 1 }}>{stepDeploy.detail}</Alert> : null}
          {deployment || impact ? <DeploymentView view={deployment} versions={ctx.versions} impact={impact} /> : null}
          {ctx.run && impact ? <ImpactPanel run={ctx.run} step={stepDeploy} impact={impact} onChanged={() => void ctx.refresh()} /> : null}
          {hostWarnings.map((h) => (
            <Typography key={h.host} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.warning, mt: 0.5 }}>
              {h.host}: {h.warnings?.join('; ')}
            </Typography>
          ))}
          {deployRunning && !deployment ? (
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: 'text.secondary' }}>{t('Waiting for progress...')}</Typography>
          ) : null}
          <Advanced title={t('Advanced: deploy node')} locked={deployLocked}>
            <Hint>
              {t('Skips the prerequisites. Run the command on the deploy node if the script is not here.')}
            </Hint>
            <FormControlLabel
              control={<Checkbox size="small" checked={replaceCheckout} onChange={(_, v) => setReplaceCheckout(v)} disabled={!canDeploy} />}
              label={t('Replace git checkout (backed up)')}
            />
            <Box sx={{ mb: 1 }}>
              <Button
                variant="outlined"
                size="small"
                disabled={!canDeploy || ctx.busy}
                onClick={() => void ctx.stepCall(3, { action: 'deploy_bundle', replace_checkout: replaceCheckout, frontend_version: frontendVersion })}
              >
                {t('Deploy via deploy node')}
              </Button>
            </Box>
            {job?.command ? <Code>{job.command}</Code> : null}
          </Advanced>
          <Advanced title={t('Advanced: per-target deploy')} locked={deployLocked}>
            <TargetsPanel d={code} />
            <ExecutePanel d={code} />
            <RollbackPanel d={code} />
            {stepDeploy.data.targets?.length ? (
              <Box sx={{ mt: 1 }}>
                {(stepDeploy.data.targets as any[]).map((r, i) => (
                  <ResultLine key={`${r.target}-${i}`} ok={Boolean(r.success)} label={String(r.target)} detail={r.message || r.error} />
                ))}
              </Box>
            ) : null}
          </Advanced>
        </>
      )}
    </>
  );
};

// ---------------------------------------------------------------------------------------------
// Step 4: migrations
// ---------------------------------------------------------------------------------------------
export const StepMigrations: React.FC<{ step: RunStep; ctx: StepContext; active: boolean }> = ({ step, ctx, active }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { migrations: m, refreshMigrations, migrationCall, stepCall } = ctx;
  const [dialog, setDialog] = useState<null | 'apply' | 'tracker' | 'baseline'>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [upTo, setUpTo] = useState('');

  useEffect(() => {
    if (active) void refreshMigrations();
  }, [active, refreshMigrations, step.state]);

  const locked = !ctx.run || step.state === 'pending' || step.state === 'done';
  const close = () => {
    setDialog(null);
    setConfirmed(false);
    setUpTo('');
  };

  return (
    <>
      {!m ? (
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('Status not available yet.')}</Typography>
      ) : m.tracker === 'missing' ? (
        <>
          <ResultLine ok={false} label={t('No migration tracker yet.')} />
          <Hint>{t('Creates the tracker table ({file}).', { file: m.tracker_file })}</Hint>
          {!m.can_apply ? (
            <Hint>
              {t('No database connection (PLATFORM_UPDATE_DB_URI).')}
            </Hint>
          ) : null}
          <Button variant="outlined" size="small" disabled={locked || !m.can_apply} onClick={() => setDialog('tracker')}>
            {t('Create tracker')}
          </Button>
        </>
      ) : (
        <>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 0.5 }}>
            {t('{applied} of {total} applied, {pending} pending.', {
              applied: m.applied, total: m.total, pending: m.pending.length,
            })}
          </Typography>
          {m.applied === 0 || m.pending.length > 20 ? (
            <Hint>
              {t('Already applied here? Mark them as applied.')}
            </Hint>
          ) : null}
          {m.pending.length > 0 ? (
            <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, maxHeight: 220, overflowY: 'auto', mb: 1 }}>
              {m.pending.map((name) => (
                <Typography key={name} sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, px: 1, py: 0.25, borderBottom: `1px solid ${P.borderColor}` }}>
                  {name}
                </Typography>
              ))}
            </Box>
          ) : null}
          {!m.can_apply ? (
            <Hint>
              {t('No database connection (PLATFORM_UPDATE_DB_URI).')}
            </Hint>
          ) : null}
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {m.pending.length > 0 ? (
              <Action busy={ctx.busy} disabled={locked || !m.can_apply} onClick={() => setDialog('apply')}>
                {t('Apply {count} migrations', { count: m.pending.length })}
              </Action>
            ) : (
              <Action busy={ctx.busy} disabled={locked} onClick={() => void stepCall(4, { action: 'check' })}>
                {t('Mark step done')}
              </Action>
            )}
            <Button variant="outlined" size="small" disabled={locked || !m.can_apply || m.pending.length === 0} onClick={() => setDialog('baseline')} title={m.can_apply ? undefined : t('No database connection: list only.')}>
              {t('Mark as already applied')}
            </Button>
            <Button variant="text" size="small" onClick={() => void refreshMigrations()}>
              {t('Reload')}
            </Button>
          </Box>
        </>
      )}
      {step.detail && step.state === 'failed' ? <ResultLine ok={false} label={step.detail} /> : null}
      {step.data.applied?.length ? <ResultLine ok label={t('{count} applied in this run', { count: step.data.applied.length })} /> : null}

      <Dialog open={dialog !== null} onClose={close} maxWidth="sm" fullWidth>
        <DialogTitle>
          {dialog === 'apply'
            ? t('Apply the pending migrations?')
            : dialog === 'tracker'
              ? t('Create the migration tracker?')
              : t('Mark migrations as already applied?')}
        </DialogTitle>
        <DialogContent>
          {dialog === 'apply' && m ? (
            <>
              <Hint>{t('Runs these files in order. Cannot be undone.')}</Hint>
              <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, maxHeight: 240, overflowY: 'auto' }}>
                {m.pending.map((name) => (
                  <Typography key={name} sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, px: 1, py: 0.25 }}>{name}</Typography>
                ))}
              </Box>
            </>
          ) : null}
          {dialog === 'tracker' && m ? <Hint>{t('Runs {file} once.', { file: m.tracker_file })}</Hint> : null}
          {dialog === 'baseline' && m ? (
            <>
              <Hint>{t('Only records them as applied; nothing is run.')}</Hint>
              <TextField select fullWidth size="small" label={t('Up to and including')} value={upTo} onChange={(e) => setUpTo(e.target.value)}>
                {m.pending.map((name) => (
                  <MenuItem key={name} value={name} sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size }}>{name}</MenuItem>
                ))}
              </TextField>
            </>
          ) : null}
          <FormControlLabel
            sx={{ mt: 1 }}
            control={<Checkbox size="small" checked={confirmed} onChange={(_, v) => setConfirmed(v)} />}
            label={t('I confirm')}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={close}>{t('Cancel')}</Button>
          <Button
            variant="contained"
            disabled={!confirmed || ctx.busy || (dialog === 'baseline' && !upTo)}
            onClick={async () => {
              if (dialog === 'apply' && m) await stepCall(4, { action: 'apply', confirm: true, filenames: m.pending });
              if (dialog === 'tracker') await migrationCall('/tracker', { confirm: true });
              if (dialog === 'baseline') await migrationCall('/baseline', { confirm: true, up_to: upTo });
              await refreshMigrations();
              close();
            }}
          >
            {dialog === 'apply' ? t('Apply') : dialog === 'tracker' ? t('Create') : t('Mark as applied')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

// ---------------------------------------------------------------------------------------------
// Step 5
// ---------------------------------------------------------------------------------------------
export const Step5: React.FC<{ step: RunStep; ctx: StepContext }> = ({ step, ctx }) => {
  const { t } = useI18n();
  const { serverHostsData } = useServerManager();
  const { executeScript } = useScript();
  const hosts = serverHostsData.flatMap((s) => s.hosts.map((h) => h.host_name));
  const [host, setHost] = useState('');
  const [device, setDevice] = useState('device1');
  const [script, setScript] = useState('');
  const [running, setRunning] = useState(false);
  const [smokeError, setSmokeError] = useState<string | null>(null);
  const locked = !ctx.run || step.state === 'pending' || step.state === 'done';
  const healthOk = step.data.health_ok === true;
  const healthHosts: any[] = step.data.health_hosts || [];

  const runSmoke = async () => {
    setRunning(true);
    setSmokeError(null);
    let ok = false;
    let taskId = '';
    let detail = '';
    try {
      const result: any = await executeScript(script.trim(), host, device.trim());
      ok = result?.success !== false;
      taskId = result?.task_id || '';
    } catch (e) {
      detail = e instanceof Error ? e.message : 'failed';
      setSmokeError(detail);
    }
    await ctx.stepCall(5, { action: 'smoke', ok, script_name: script.trim(), task_id: taskId, detail });
    setRunning(false);
  };

  return (
    <>
      {healthHosts.map((h) => (
        <ResultLine key={h.host} ok={Boolean(h.ok)} label={h.host} detail={h.detail} />
      ))}
      <Box sx={{ mb: 1.5 }}>
        <Action busy={ctx.busy && !running} disabled={locked || running} onClick={() => void ctx.stepCall(5, { action: 'health' })}>
          {healthOk ? t('Check health again') : t('Check health')}
        </Action>
      </Box>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1, opacity: healthOk ? 1 : 0.6 }}>
        <TextField select size="small" label={t('Host')} value={host} onChange={(e) => setHost(e.target.value)} sx={{ minWidth: 160 }} disabled={!healthOk || locked}>
          {hosts.map((name) => (
            <MenuItem key={name} value={name}>{name}</MenuItem>
          ))}
        </TextField>
        <TextField size="small" label={t('Device')} value={device} onChange={(e) => setDevice(e.target.value)} disabled={!healthOk || locked} />
        <TextField size="small" label={t('Smoke script')} value={script} onChange={(e) => setScript(e.target.value)} disabled={!healthOk || locked} />
      </Box>
      <Button
        variant="outlined"
        size="small"
        disabled={!healthOk || locked || running || !host || !device.trim() || !script.trim()}
        onClick={() => void runSmoke()}
      >
        {running ? <CircularProgress size={16} color="inherit" /> : t('Run the smoke script')}
      </Button>
      {step.data.smoke ? <ResultLine ok={Boolean(step.data.smoke.ok)} label={step.data.smoke.script_name || ''} detail={step.detail || undefined} /> : null}
      {smokeError ? <ResultLine ok={false} label={smokeError} /> : null}
      {step.state === 'failed' && !healthOk && step.detail ? <ResultLine ok={false} label={step.detail} /> : null}
    </>
  );
};

// ---------------------------------------------------------------------------------------------
// Step 6
// ---------------------------------------------------------------------------------------------
export const Step6: React.FC<{
  step: RunStep;
  ctx: StepContext;
  onClose: (status: 'ok' | 'failed' | 'rolled_back', message: string) => void;
  onDownload: () => void;
}> = ({ step, ctx, onClose, onDownload }) => {
  const { t } = useI18n();
  const [status, setStatus] = useState<'ok' | 'failed' | 'rolled_back'>('ok');
  const [message, setMessage] = useState('');
  const run = ctx.run;
  const closed = !run || run.status !== 'active';
  return (
    <>
      <Hint>
        {t('Turns the banner off and notifies users.')}{ctx.fromTo ? ` ${ctx.fromTo}` : ''}
      </Hint>
      {!closed ? (
        <>
          <TextField select size="small" label={t('Result')} value={status} onChange={(e) => setStatus(e.target.value as typeof status)} sx={{ minWidth: 180, mb: 1, mr: 1 }}>
            <MenuItem value="ok">{t('Succeeded')}</MenuItem>
            <MenuItem value="failed">{t('Failed')}</MenuItem>
            <MenuItem value="rolled_back">{t('Rolled back')}</MenuItem>
          </TextField>
          <TextField
            fullWidth size="small" label={t('Message (optional)')} value={message}
            onChange={(e) => setMessage(e.target.value)} sx={{ mb: 1 }}
          />
          <Action busy={ctx.busy} onClick={() => onClose(status, ctx.fromTo ? [ctx.fromTo, message.trim()].filter(Boolean).join(' · ') : message)}>
            {t('Close update')}
          </Action>
        </>
      ) : (
        <ResultLine ok={run?.status === 'ok'} label={t(run?.status === 'ok' ? 'Closed: succeeded' : run?.status === 'rolled_back' ? 'Closed: rolled back' : 'Closed: failed')} />
      )}
      {run ? (
        <Box sx={{ mt: 1 }}>
          <Button variant="outlined" size="small" onClick={onDownload}>
            {t('Download the log')}
          </Button>
        </Box>
      ) : null}
      {step.state === 'done' ? null : null}
    </>
  );
};
