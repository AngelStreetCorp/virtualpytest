import React from 'react';
import { Chip, Tooltip } from '@mui/material';
import { useNavigate } from 'react-router-dom';

import { useActiveProblems } from '../../contexts/notificationStore';
import { useI18n } from '../../i18n/useI18n';

/** Persistent "Monitoring problem" chip: stays while a monitoring problem is open, opens the failing host on Status.
 *  Text only — no icon. The badge row next to it (the "N in error" / "N in warning" chips) is text
 *  only as well: the icons used to be the only thing separating the red chip from the amber one, and
 *  they got it wrong (the red chip wore the amber warning triangle). The colour and the words carry
 *  the meaning, which is enough.
 */
export const MonitoringProblemChip: React.FC = () => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const problems = useActiveProblems();
  if (problems.length === 0) return null;
  const first = problems[0];
  return (
    <Tooltip title={problems.map((p) => p.message).join(' · ')}>
      <Chip
        label={problems.length > 1 ? t('Monitoring problem ({count})', { count: problems.length }) : t('Monitoring problem')}
        size="small"
        color="error"
        variant="outlined"
        clickable
        onClick={() => navigate(problems.length > 1 ? '/status' : first.to)}
        data-testid="monitoring-problem-chip"
      />
    </Tooltip>
  );
};

export default MonitoringProblemChip;
