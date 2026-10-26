import React, { useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { type InstalledVersions } from './versions';
import type { DeployCard, DeploymentView as View, PhaseName } from '../../hooks/platformUpdate/usePlatformUpdateRun';
import type { DeployImpact, ImpactMachine, MachineOutcome } from '../../hooks/platformUpdate/platformUpdateActions';
import { TYPOGRAPHY } from '../../constants/typography';

const PHASES: PhaseName[] = ['rsync', 'install', 'restart', 'health'];
type Shown = 'waiting' | 'running' | 'ok' | 'failed' | 'skipped';

export const formatDuration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined) return '-';
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
};

const PhaseIcon: React.FC<{ state: Shown }> = ({ state }) => {
  const P = useAgentChatPalette();
  const map: Record<Shown, { Icon: React.ElementType; color: string }> = {
    waiting: { Icon: RadioButtonUncheckedIcon, color: P.textMuted },
    running: { Icon: HourglassEmptyIcon, color: P.accentText },
    ok: { Icon: CheckCircleOutlineIcon, color: P.success },
    failed: { Icon: ErrorOutlineIcon, color: P.error },
    skipped: { Icon: RemoveCircleOutlineIcon, color: P.textMuted },
  };
  const { Icon, color } = map[state];
  return <Icon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, color }} />;
};

const useBarSx = () => {
  const P = useAgentChatPalette();
  return (color: string) => ({ height: 4, borderRadius: 2, bgcolor: P.hoverBg, '& .MuiLinearProgress-bar': { bgcolor: color } });
};

/** One machine: four fixed phase rows and a reserved bar slot, so a state change never moves the card. */
export interface DeployVersions {
  before: InstalledVersions | null;
  now: InstalledVersions;
}

const pick = (v: InstalledVersions | null, card: DeployCard): string =>
  !v ? '' : card.role === 'server' ? v.server : card.role === 'frontend' ? v.frontend : v.hosts[card.host] ?? '';

/** before = what the machine ran when the deploy started; after = the version its health check reported, else its current one once done. */
const cardVersions = (card: DeployCard, versions?: DeployVersions): { before: string; after: string } => {
  if (!versions) return { before: '', after: '' };
  const before = pick(versions.before, card);
  const reported = /^version (\S+)/.exec(card.phases.health?.detail || '')?.[1];
  const after = reported && reported !== '?' ? reported : card.state === 'ok' ? pick(versions.now, card) : '';
  return { before, after };
};

/** After an abort, a failed deploy or a roll back (TASK-128 G12) the card says where its machine ended up. */
const OUTCOME_LABEL: Record<MachineOutcome, string> = {
  new: 'on new version', rolled_back: 'rolled back', untouched: 'untouched', failed: 'update failed',
};

const Card: React.FC<{ card: DeployCard; versions?: DeployVersions; machine?: ImpactMachine; onOpen: () => void }> = ({ card, versions, machine, onOpen }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const barSx = useBarSx();
  const phaseLabel: Record<PhaseName, string> = {
    rsync: t('Copy files'), install: t('Install'), restart: t('Restart'), health: t('Health check'),
  };
  const running = card.state === 'running';
  const failed = card.state === 'failed';
  const fromView = cardVersions(card, versions);
  const ver = machine ? { before: machine.before, after: machine.now } : fromView;
  const outcomeColor = !machine ? P.textMuted
    : machine.state === 'failed' ? P.error : machine.state === 'new' ? P.warning : machine.state === 'rolled_back' ? P.accentText : P.textMuted;
  return (
    <Box
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onOpen(); }}
      sx={{
        border: `1px solid ${failed ? P.error : P.borderColor}`, bgcolor: P.surface, borderRadius: 1.5,
        p: 1.25, cursor: 'pointer', height: 196, display: 'flex', flexDirection: 'column', boxSizing: 'border-box',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mb: 0.75 }}>
        <Typography noWrap sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.navbarItem.size, flex: 1 }}>{card.host}</Typography>
        {machine ? <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: outcomeColor, fontWeight: 600 }}>{t(OUTCOME_LABEL[machine.state])}</Typography> : null}
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{card.role}</Typography>
      </Box>
      <Typography noWrap title={`${ver.before || '-'} → ${ver.after || '-'}`} sx={{ fontSize: TYPOGRAPHY.caption.size, height: 18, mb: 0.25, color: P.textMuted, fontFamily: 'monospace' }}>
        {ver.before || ver.after ? `${ver.before || '-'}${ver.after ? ` → ${ver.after}` : ''}` : ''}
      </Typography>
      {PHASES.map((name) => {
        const phase = card.phases[name];
        const state: Shown = phase ? phase.state : 'waiting';
        return (
          <Box key={name} sx={{ display: 'flex', alignItems: 'center', gap: 0.75, height: 22 }}>
            <PhaseIcon state={state} />
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, flex: 1, color: state === 'waiting' ? P.textMuted : P.textPrimary }}>{phaseLabel[name]}</Typography>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace' }}>
              {phase && phase.state !== 'running' ? formatDuration(phase.duration_s) : ''}
            </Typography>
          </Box>
        );
      })}
      <Box sx={{ height: 4, mt: 'auto' }}>{running ? <LinearProgress sx={barSx(P.accent)} /> : null}</Box>
      <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, height: 18, mt: 0.5, color: P.error }} title={card.error}>
        {failed ? card.error || t('failed') : ''}
      </Typography>
    </Box>
  );
};

const Detail: React.FC<{ card: DeployCard | null; onClose: () => void }> = ({ card, onClose }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Dialog open={card !== null} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{card ? `${card.host} (${card.role})` : ''}</DialogTitle>
      <DialogContent>
        {card ? (
          <>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1 }}>
              {t('Total {duration}', { duration: formatDuration(card.duration_s) })}
            </Typography>
            <Box sx={{ mb: 1.5 }}>
              {PHASES.map((name) => {
                const phase = card.phases[name];
                return (
                  <Box key={name} sx={{ display: 'flex', gap: 1, alignItems: 'center', py: 0.25 }}>
                    <PhaseIcon state={phase ? phase.state : 'waiting'} />
                    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, width: 80 }}>{name}</Typography>
                    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', width: 90, color: P.textMuted }}>
                      {phase && phase.state !== 'running' ? formatDuration(phase.duration_s) : '-'}
                    </Typography>
                    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: phase?.state === 'failed' ? P.error : P.textMuted }}>{phase?.detail || ''}</Typography>
                  </Box>
                );
              })}
            </Box>
            <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.caption.size, mb: 0.5 }}>{t('Log of this machine')}</Typography>
            <Box sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 320, overflowY: 'auto', bgcolor: P.hoverBg, borderRadius: 1, p: 1, color: P.textSecondary }}>
              {card.log.length ? card.log.join('\n') : t('No log lines for this machine.')}
            </Box>
          </>
        ) : null}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>{t('Close')}</Button></DialogActions>
    </Dialog>
  );
};

/** Step 2: overall bar on top, one card per (role, host) below. */
const EMPTY_VIEW: View = { hosts: [], state: 'pending', started: null, ended: null, duration_s: null, phases_done: 0, phases_total: 0 };

/** A machine the impact view knows but the log has no line for (never reached): an empty card, so "untouched" is visible. */
const placeholder = (m: ImpactMachine): DeployCard => ({
  host: m.name, role: m.role, state: 'pending', started: null, ended: null, duration_s: null, phases: {}, log: [], error: '',
});

export const DeploymentView: React.FC<{ view: View | null; versions?: DeployVersions; impact?: DeployImpact | null }> = ({ view: given, versions, impact }) => {
  const view = given ?? EMPTY_VIEW;
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const barSx = useBarSx();
  const [open, setOpen] = useState<string | null>(null);
  const key = (c: DeployCard) => `${c.role}/${c.host}`;
  const machines = impact?.machines ?? [];
  const byKey = new Map(machines.map((m) => [`${m.role}/${m.name}`, m]));
  const cards = [...view.hosts, ...machines.filter((m) => !view.hosts.some((c) => key(c) === `${m.role}/${m.name}`)).map(placeholder)];
  const percent = view.phases_total ? (view.phases_done / view.phases_total) * 100 : 0;
  const barColor = view.state === 'failed' ? P.error : view.state === 'ok' ? P.success : P.accent;
  return (
    <Box sx={{ mt: 1.5 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
          {t('{done} of {total} phases finished', { done: view.phases_done, total: view.phases_total })}
        </Typography>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace' }}>{formatDuration(view.duration_s)}</Typography>
      </Box>
      <LinearProgress variant="determinate" value={percent} sx={{ ...barSx(barColor), mb: 1.5 }} />
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 1.25, alignItems: 'start' }}>
        {cards.map((card) => <Card key={key(card)} card={card} versions={versions} machine={byKey.get(key(card))} onOpen={() => setOpen(key(card))} />)}
      </Box>
      <Detail card={cards.find((c) => key(c) === open) ?? null} onClose={() => setOpen(null)} />
    </Box>
  );
};
