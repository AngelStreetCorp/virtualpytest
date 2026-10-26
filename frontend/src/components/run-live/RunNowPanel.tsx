/**
 * "Now: step N · label", the percent, the bar and the step / stage chips of a live run.
 * Shared by the live run page and the Run Tests live dialog (compact).
 */
import { Box, LinearProgress, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import type { LiveRunStep } from '../../hooks/script/useLiveScriptProgress';
import { buildChips, formatElapsed, percentDone, splitLabel, type ChipState } from './runLiveModel';

interface RunNowPanelProps {
  steps: LiveRunStep[];
  totalSteps: number | null;
  running: boolean;
  /** Message of the latest progress event, shown when no step was recorded yet. */
  message?: string | null;
  etaMs?: number | null;
  compact?: boolean;
}

export const RunNowPanel: React.FC<RunNowPanelProps> = ({ steps, totalSteps, running, message, etaMs, compact }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const last = steps[steps.length - 1];
  const percent = percentDone(steps.length, totalSteps, !running);
  const chipColors: Record<ChipState, { fg: string; bg: string; border: string }> = {
    done: { fg: P.textSecondary, bg: 'transparent', border: P.borderColor },
    now: { fg: P.selectedText, bg: P.selectedBg, border: P.selectedBorder },
    failed: { fg: P.error, bg: 'transparent', border: P.error },
    skipped: { fg: P.textMuted, bg: 'transparent', border: P.borderColor },
    pending: { fg: P.textMuted, bg: 'transparent', border: P.borderColor },
  };
  const dotColor: Record<ChipState, string> = { done: P.success, now: P.accentText, failed: P.error, skipped: P.textMuted, pending: P.textMuted };
  const chips = buildChips(steps, totalSteps, running, (n) => t('Step {n}', { n }));

  let headline: string;
  if (running) {
    headline = steps.length === 0
      ? (message || t('Waiting for the first step…'))
      : t('Now: step {n} · {label}', { n: steps.length + 1, label: message || t('running') });
  } else {
    headline = last
      ? t('Last: step {n} · {label}', { n: last.number, label: splitLabel(last.label).text })
      : t('No step was recorded');
  }
  const sub = [
    running && etaMs != null ? t('about {time} left', { time: formatElapsed(etaMs) }) : null,
    totalSteps ? t('{done} of {total} steps', { done: steps.length, total: totalSteps }) : null,
  ].filter(Boolean).join(' · ');

  return (
    <Box data-testid="run-now-panel">
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, minWidth: 0 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size, overflowWrap: 'anywhere' }}>{headline}</Typography>
          {sub ? <Typography variant="caption" sx={{ color: P.textSecondary }}>{sub}</Typography> : null}
        </Box>
        {percent != null ? (
          <Typography sx={{ fontSize: compact ? TYPOGRAPHY.body.size : '1.5rem', fontWeight: 600, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
            {percent} %
          </Typography>
        ) : null}
      </Box>
      <LinearProgress
        variant={percent != null ? 'determinate' : running ? 'indeterminate' : 'determinate'}
        value={percent ?? 0}
        aria-label={t('progress')}
        sx={{ my: 1.25, height: 4, borderRadius: 2 }}
      />
      {chips.length > 0 && !compact ? (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
          {chips.map((c) => (
            <Box
              key={c.key}
              title={c.label}
              sx={{
                display: 'inline-flex', alignItems: 'center', gap: 0.75, maxWidth: 220, px: 1, py: 0.25,
                borderRadius: 999, fontSize: TYPOGRAPHY.caption.size, color: chipColors[c.state].fg,
                bgcolor: chipColors[c.state].bg, border: `1px solid ${chipColors[c.state].border}`,
              }}
            >
              <Box component="span" sx={{ width: 6, height: 6, borderRadius: '50%', flexShrink: 0, bgcolor: c.state === 'pending' ? 'transparent' : dotColor[c.state], border: `1px solid ${dotColor[c.state]}` }} />
              <Box component="span" sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.label}</Box>
            </Box>
          ))}
        </Box>
      ) : null}
    </Box>
  );
};
