/**
 * Expanded body of a running Deployments row: percent bar + step chips on the left, a compact
 * "Step N of M" panel with the last 3 steps, the next scheduled run and a link to the live page
 * on the right. Same feed as the live run page (GET /server/script/liveProgress).
 */
import { Box, Typography } from '@mui/material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useLiveRunSteps } from '../../hooks/reports/useLiveRunSteps';
import { useI18n } from '../../i18n/useI18n';
import { REPORT_ROUTES } from '../../types/reports';
import { RunNowPanel } from './RunNowPanel';
import { StepLine } from './StepsPanel';
import { splitLabel } from './runLiveModel';

interface DeploymentLiveRowProps {
  hostName?: string | null;
  deviceId?: string | null;
  /** Execution id of the run: the server task of a scheduled run is `dep-<execution id>`. */
  executionId?: string | null;
  /** Formatted time of the deployment's next scheduled run, when known. */
  nextRun?: string | null;
}

export const DeploymentLiveRow: React.FC<DeploymentLiveRowProps> = ({ hostName, deviceId, executionId, nextRun }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  // Scheduled runs have a server task named after the execution; without an id the feed
  // answers with the script now running on this device.
  const live = useLiveRunSteps(executionId ? `dep-${executionId}` : '', hostName, deviceId, true);
  const last = live.steps[live.steps.length - 1];
  const headline = live.steps.length === 0
    ? (live.message || (live.polled && !live.taskId ? t('No live steps for this run') : t('Waiting for the first step…')))
    : t('Step {n} of {m} · {label}', {
      n: live.steps.length + 1,
      m: live.totalSteps ?? '?',
      label: live.message || splitLabel(last.label).text,
    });
  return (
    <Box data-testid="deployment-live-row" sx={{ display: 'flex', gap: 3, flexWrap: 'wrap', py: 1 }}>
      <Box sx={{ flex: '2 1 320px', minWidth: 0 }}>
        <RunNowPanel steps={live.steps} totalSteps={live.totalSteps} running message={live.message} />
      </Box>
      <Box sx={{ flex: '1 1 240px', minWidth: 0, borderLeft: `1px solid ${P.borderColor}`, pl: 2 }}>
        <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size, overflowWrap: 'anywhere' }}>{headline}</Typography>
        <Box sx={{ my: 0.5 }}>
          {live.steps.slice(-3).map((s) => <StepLine key={s.number} step={s} />)}
        </Box>
        {nextRun ? (
          <Typography variant="caption" sx={{ display: 'block', color: P.textSecondary }}>{t('Next run {time}', { time: nextRun })}</Typography>
        ) : null}
        {live.taskId ? (
          <Typography
            component={RouterLink}
            to={REPORT_ROUTES.live(live.taskId)}
            variant="caption"
            sx={{ display: 'inline-block', mt: 0.5, color: P.accentText, fontWeight: 600, textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
          >
            {t('Open live →')}
          </Typography>
        ) : null}
      </Box>
    </Box>
  );
};
