/** Step list of a live run (icon, action tag, label, duration). Shared by the page and the dialog. */
import { Box, Typography } from '@mui/material';
import React, { useEffect, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import type { LiveRunStep } from '../../hooks/script/useLiveScriptProgress';
import { formatElapsed, splitLabel, stepState } from './runLiveModel';

const StepIcon: React.FC<{ step: LiveRunStep }> = ({ step }) => {
  const P = useAgentChatPalette();
  const state = stepState(step);
  if (state === 'skipped') return <AppIcon name="pending" color={P.textMuted} />;
  return <AppIcon name={state === 'done' ? 'success' : 'error'} />;
};

export const StepLine: React.FC<{
  step: LiveRunStep;
  withDuration?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  maxChars?: number;
  selected?: boolean;
}> = ({ step, withDuration, expanded, onToggle, maxChars = 55, selected }) => {
  const P = useAgentChatPalette();
  const { tag, text } = splitLabel(step.label);
  return (
    <Box
      onClick={onToggle}
      sx={{
        display: 'flex', alignItems: expanded ? 'flex-start' : 'center', gap: 0.75, py: 0.4, px: 0.5, borderRadius: 1,
        cursor: onToggle ? 'pointer' : 'default', minWidth: 0, bgcolor: selected ? P.hoverBg : 'transparent',
        '&:hover': onToggle ? { bgcolor: P.hoverBg } : undefined,
      }}
    >
      <Box sx={{ pt: expanded ? 0.25 : 0, display: 'inline-flex' }}><StepIcon step={step} /></Box>
      {tag ? (
        <Typography component="span" sx={{ fontSize: TYPOGRAPHY.microMeta.size, px: 0.75, borderRadius: 1, bgcolor: P.hoverBg, color: P.textSecondary, flexShrink: 0 }}>{tag}</Typography>
      ) : null}
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography
          variant="caption"
          sx={{ display: 'block', ...(expanded ? { overflowWrap: 'anywhere' } : { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }) }}
        >
          {expanded || text.length <= maxChars ? text : `${text.slice(0, maxChars).trimEnd()}…`}
        </Typography>
        {step.error && !step.success ? (
          <Typography variant="caption" sx={{ display: 'block', color: P.error, overflowWrap: 'anywhere' }}>{step.error}</Typography>
        ) : null}
      </Box>
      {withDuration && step.durationMs != null ? (
        <Typography variant="caption" sx={{ color: P.textMuted, whiteSpace: 'nowrap', minWidth: 36, textAlign: 'right', flexShrink: 0 }}>{formatElapsed(step.durationMs)}</Typography>
      ) : null}
    </Box>
  );
};

interface StepsPanelProps {
  steps: LiveRunStep[];
  running: boolean;
  maxHeight?: number | string;
  resetKey?: string;
  selectedNumber?: number | null;
  onSelect?: (step: LiveRunStep) => void;
}

/** Scrolls to the newest step as steps arrive; a click expands a long label. */
export const StepsPanel: React.FC<StepsPanelProps> = ({ steps, running, maxHeight = 180, resetKey, selectedNumber, onSelect }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [steps.length, resetKey]);
  return (
    <Box ref={listRef} data-testid="steps-panel" sx={{ maxHeight, overflowY: 'auto', scrollbarGutter: 'stable', pr: 0.5 }}>
      {steps.length === 0 ? (
        <Typography variant="body2" sx={{ color: P.textSecondary }}>{t('Waiting for the first step…')}</Typography>
      ) : steps.map((step) => (
        <StepLine
          key={step.number}
          step={step}
          withDuration
          expanded={expanded === step.number}
          selected={selectedNumber === step.number}
          onToggle={() => { setExpanded((cur) => (cur === step.number ? null : step.number)); onSelect?.(step); }}
        />
      ))}
      {running && steps.length > 0 ? (
        <Typography variant="caption" sx={{ color: P.textMuted, px: 0.5, display: 'flex', alignItems: 'center', gap: 0.75, py: 0.4 }}>
          <AppIcon name="running" /> {t('Running…')}
        </Typography>
      ) : null}
    </Box>
  );
};
