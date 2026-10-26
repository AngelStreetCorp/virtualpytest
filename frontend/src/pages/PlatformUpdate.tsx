import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Chip, Link, TextField, Tooltip, Typography } from '@mui/material';

import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PageTitle, StatTiles, pageSurfaceSx } from '../components/common/PageChrome';
import {
  CodeSteps,
  STEP_SUMMARY,
  StateWord,
  Step0,
  Step5,
  Step6,
  StepBackup,
  StepMigrations,
  type StepContext,
} from '../components/platformUpdate/PlatformUpdateSteps';
import { differingMachines, formatDeployVersion, useInstalledVersions, versionsBeforeOf } from '../components/platformUpdate/versions';
import { PlatformUpdateSettings } from '../components/platformUpdate/PlatformUpdateSettings';
import { PrerequisitesBadge } from '../components/platformUpdate/PrerequisitesBadge';
import { findCoreTag, useBundleSources } from '../hooks/platformUpdate/useBundleSources';
import { usePlatformUpdateRun, type RunStep } from '../hooks/platformUpdate/usePlatformUpdateRun';
import { usePrerequisites, type CoreSource, type OverlaySource } from '../hooks/platformUpdate/usePrerequisites';
import { useI18n } from '../i18n/useI18n';
import { apiClient } from '../utils/apiClient';
import { TYPOGRAPHY } from '../constants/typography';

const DOCS_PATH = '/docs/user-guide/platform-update';

const toLocalInput = (date: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const PlatformUpdate: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, tn, formatDate } = useI18n();
  const u = usePlatformUpdateRun();
  const { run } = u;
  const [sources, setSources] = useState<{ core: CoreSource; overlay: OverlaySource; tag: string }>({ core: 'github', overlay: 'none', tag: '' });
  const onSourcesChange = useCallback(
    (core: CoreSource, overlay: OverlaySource, tag: string) =>
      setSources((prev) => (prev.core === core && prev.overlay === overlay && prev.tag === tag ? prev : { core, overlay, tag })),
    []
  );
  // Once step 2 has built, the bundle's own sources decide which checks are required.
  const built = run?.steps[2]?.state === 'done' ? (run.steps[2].data.spec as { core?: CoreSource; overlay?: OverlaySource } | undefined) : undefined;
  const pre = usePrerequisites(built?.core ?? sources.core, built?.overlay ?? sources.overlay);

  // ?to=<build> (Release Notes → Roll out): shown in the header at once, resolved to a core release tag once the list is loaded.
  const bundleSources = useBundleSources();
  const { load: loadBundleSources } = bundleSources;
  useEffect(() => {
    void loadBundleSources();
  }, [loadBundleSources]);
  const [searchParams] = useSearchParams();
  const wanted = searchParams.get('to');
  const coreRefs = bundleSources.sources?.core.github.refs;
  const coreUsable = Boolean(bundleSources.sources?.core.github.usable);
  const wantedTag = findCoreTag(coreRefs ?? [], wanted);
  const unpublished = Boolean(wanted && coreUsable && !wantedTag && !sources.tag);
  const coreRemote = bundleSources.sources?.core.github.remote ?? '';

  const installed = useInstalledVersions();
  const before = versionsBeforeOf(run);
  const builtVersion = run?.steps[2]?.state === 'done' ? String(run.steps[2].data.version ?? '') : '';
  const fromVersion = formatDeployVersion(before?.server || installed.server);
  const toVersion = formatDeployVersion(builtVersion || sources.tag || wantedTag || (wanted ? t('build {number}', { number: wanted }) : ''));
  const differing = differingMachines(installed);
  const fromTo = `${fromVersion || '—'} → ${toVersion || '—'}`;

  const [windowStart, setWindowStart] = useState(() => toLocalInput(new Date()));
  const [windowEnd, setWindowEnd] = useState(() => toLocalInput(new Date(Date.now() + 60 * 60 * 1000)));
  const [note, setNote] = useState('');
  const [openSteps, setOpenSteps] = useState<Record<number, boolean>>({});
  const logRef = useRef<HTMLDivElement | null>(null);

  const active = run?.status === 'active';
  const currentIndex = useMemo(() => {
    if (!run) return -1;
    const step = run.steps.find((s) => s.state !== 'done');
    return step ? step.index : 6;
  }, [run]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [run?.log.length]);

  const stepCtx: StepContext = {
    run,
    busy: u.busyStep !== null,
    stepCall: u.stepCall,
    refresh: u.refresh,
    migrations: u.migrations,
    refreshMigrations: u.refreshMigrations,
    migrationCall: u.migrationCall,
    prereqBlocking: pre.blocking.map((c) => t(c.title)),
    prereqChecked: pre.result !== null,
    onSourcesChange,
    bundleSources,
    versions: { before, now: installed },
    fromTo: fromVersion && toVersion ? fromTo : '',
    sources: { core: built?.core ?? sources.core, overlay: built?.overlay ?? sources.overlay },
  };

  const downloadLog = async () => {
    if (!u.logUrl || !run) return;
    const response = await apiClient(u.logUrl);
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `platform-update-${run.id}.log`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const when = (iso: string) => formatDate(new Date(iso), { dateStyle: 'short', timeStyle: 'short' });
  const placeholderStep = (index: number): RunStep => ({
    index, key: '', title: '', state: 'pending', detail: null, data: {}, started_at: null, finished_at: null,
  });
  const steps: RunStep[] = run ? run.steps : Array.from({ length: 7 }, (_, i) => placeholderStep(i));
  const titles = ['Prerequisites', 'Backup', 'Bundle', 'Deploy', 'Migrations', 'Testing', 'Close'];

  const renderStep = (index: number, body: React.ReactNode) => {
    const step = steps[index];
    const isCurrent = active && index === currentIndex;
    const expanded = openSteps[index] ?? isCurrent;
    return (
      <Box
        key={index}
        sx={{
          border: `1px solid ${isCurrent ? P.accent : P.borderColor}`,
          bgcolor: isCurrent ? `${P.accent}14` : P.surface,
          borderRadius: 1.5,
          mb: 1,
        }}
      >
        <Box
          onClick={() => setOpenSteps((prev) => ({ ...prev, [index]: !expanded }))}
          sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 1.5, py: 1, cursor: 'pointer', flexWrap: 'wrap' }}
        >
          <Typography sx={{ fontWeight: 600, color: isCurrent ? P.accentText : P.textMuted, minWidth: 18 }}>{index}</Typography>
          <Box sx={{ flex: 1, minWidth: 200 }}>
            <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.navbarItem.size }}>{t(titles[index])}</Typography>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t(STEP_SUMMARY[index])}</Typography>
          </Box>
          <Link
            href={`${DOCS_PATH}#step-${index}`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
            sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.accentText }}
          >
            {t('How this step works')}
          </Link>
          <StateWord state={step.state} />
        </Box>
        {expanded ? <Box sx={{ px: 1.5, pb: 1.5, pt: 0.5 }}>{body}</Box> : null}
      </Box>
    );
  };

  const startRun = () =>
    void u.startRun(new Date(windowStart).toISOString(), new Date(windowEnd).toISOString(), note);
  const windowValid = windowStart && windowEnd && new Date(windowEnd) > new Date(windowStart);

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title={
          <>
            {t('Platform update')}
            <PrerequisitesBadge result={pre.result} loading={pre.loading} error={pre.error} onRecheck={() => void pre.recheck()} />
            <PlatformUpdateSettings onSaved={() => void pre.recheck()} />
          </>
        }
        subtitle={t('Update this install in 7 steps.')}
        right={
          <Link
            href={DOCS_PATH}
            target="_blank"
            rel="noopener noreferrer"
            sx={{ fontSize: TYPOGRAPHY.body.size, color: P.accentText }}
          >
            {t('Read the guide')}
          </Link>
        }
      />

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5, flexWrap: 'wrap' }}>
        <Typography sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.body.size, color: P.textPrimary }}>{fromTo}</Typography>
        {unpublished && !builtVersion ? (
          <Tooltip title={t('Build {number} has no release tag on {remote}. Pick a published build or use a zip.', { number: wanted ?? '', remote: coreRemote })}>
            <Chip size="small" variant="outlined" label={t('not published')} sx={{ color: P.warning, borderColor: P.warning, fontSize: TYPOGRAPHY.caption.size }} />
          </Tooltip>
        ) : null}
        {differing.length > 0 ? (
          <Tooltip
            title={differing.map(([name, version]) => `${name} → ${version}`).join('\n')}
            slotProps={{ tooltip: { sx: { whiteSpace: 'pre-line' } } }}
          >
            <Chip
              size="small"
              variant="outlined"
              label={tn(differing.length, '{count} machine differs', '{count} machines differ', { count: differing.length })}
              sx={{ color: P.warning, borderColor: P.warning, fontSize: TYPOGRAPHY.caption.size }}
            />
          </Tooltip>
        ) : null}
      </Box>

      {u.error ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => u.setError(null)}>
          {u.error}
        </Alert>
      ) : null}

      {!run ? (
        <Box sx={{ border: `1px solid ${P.borderColor}`, bgcolor: P.surface, borderRadius: 1.5, p: 1.5, mb: 2 }}>
          <Typography component="h6" sx={{ fontWeight: 600, mb: 1 }}>{t('Start an update')}</Typography>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
            <TextField size="small" type="datetime-local" label={t('Window start')} value={windowStart} onChange={(e) => setWindowStart(e.target.value)} InputLabelProps={{ shrink: true }} />
            <TextField size="small" type="datetime-local" label={t('Window end')} value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
            <TextField size="small" label={t('Note (optional)')} value={note} onChange={(e) => setNote(e.target.value)} sx={{ minWidth: 260, flex: '1 1 260px' }} />
            <Button variant="contained" size="small" onClick={startRun} disabled={!u.loaded || !windowValid || u.busyStep !== null} sx={{ ml: 'auto', whiteSpace: 'nowrap' }}>
              {t('Start update')}
            </Button>
          </Box>
        </Box>
      ) : (
        <>
          <StatTiles
            tiles={[
              { label: t('Status'), value: t(run.status === 'active' ? 'Open' : run.status === 'ok' ? 'Succeeded' : run.status === 'rolled_back' ? 'Rolled back' : 'Failed'), color: run.status === 'active' ? P.warning : run.status === 'ok' ? P.success : P.error },
              { label: t('Window'), value: `${when(run.window_start)} - ${when(run.window_end)}` },
              { label: t('Started by'), value: run.started_by },
              { label: t('Current step'), value: active ? t(titles[currentIndex]) : t('Closed') },
            ]}
          />
          {!active ? (
            <Box sx={{ mb: 1.5 }}>
              <Button variant="outlined" size="small" onClick={u.leaveRun}>{t('Start another update')}</Button>
            </Box>
          ) : null}
        </>
      )}

      {run?.legacy && active ? (
        <Alert
          severity="warning"
          sx={{ mt: 1 }}
          action={
            <Button color="inherit" size="small" onClick={() => void u.closeRun('failed', t('Closed: older update format'))}>
              {t('Close update')}
            </Button>
          }
        >
          {t('This update was started before the 7-step change; close it and start a new one')}
        </Alert>
      ) : null}

      {run?.legacy ? null : (
        <Box sx={{ mt: 1 }}>
          {renderStep(0, <Step0 step={steps[0]} ctx={stepCtx} />)}
          {renderStep(1, <StepBackup step={steps[1]} ctx={stepCtx} />)}
          <CodeSteps steps={steps} ctx={stepCtx} render={renderStep} />
          {renderStep(4, <StepMigrations step={steps[4]} ctx={stepCtx} active={Boolean(active) && (openSteps[4] ?? currentIndex === 4)} />)}
          {renderStep(5, <Step5 step={steps[5]} ctx={stepCtx} />)}
          {renderStep(6, <Step6 step={steps[6]} ctx={stepCtx} onClose={(s, m) => void u.closeRun(s, m)} onDownload={() => void downloadLog()} />)}
        </Box>
      )}

      {run ? (
        <Box sx={{ border: `1px solid ${P.borderColor}`, bgcolor: P.surface, borderRadius: 1.5, p: 1.5, mt: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
            <Typography component="h6" sx={{ fontWeight: 600, flex: 1 }}>{t('Log')}</Typography>
            <Button variant="text" size="small" onClick={() => void downloadLog()}>{t('Download the log')}</Button>
          </Box>
          <Box
            ref={logRef}
            sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, whiteSpace: 'pre-wrap', maxHeight: 320, overflowY: 'auto', color: P.textSecondary, bgcolor: P.hoverBg, borderRadius: 1, p: 1 }}
          >
            {run.log.join('\n')}
          </Box>
        </Box>
      ) : null}
    </Box>
  );
};

export default PlatformUpdate;
