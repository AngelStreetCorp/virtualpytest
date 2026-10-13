/** This month's AI spend of the team against its budget, with the linear month-end forecast. */
import { Box, Card, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import { fetchBudget } from './api';
import { fmtCost, fmtPct } from './format';
import { PanelError } from './PanelError';
import { useAiLoad } from './useAiLoad';

export const BudgetPanel: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { data, failed, reload } = useAiLoad('budget', fetchBudget, []);

  if (failed) return <PanelError what={t('the budget')} onRetry={reload} />;
  if (!data) return null;
  const b = data.budget;
  if (!b) return null; // no budget set: the Cost tile already says what was spent
  const color = !b ? P.accent : b.state === 'over' ? P.error : b.state === 'warn' ? P.warning : P.success;
  return (
    <Card sx={{ p: 1.5, bgcolor: P.surface }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap', mb: 0.75 }}>
        <Typography sx={{ fontSize: '0.75rem', color: P.textMuted }}>{t('This month')}</Typography>
        <Typography sx={{ fontSize: '0.8rem', fontVariantNumeric: 'tabular-nums', color: P.textSecondary }}>
          {t('Forecast for the month end')}: {fmtCost(data.forecast) ?? '–'}
          {b && ` · ${t('Budget')}: ${fmtCost(b.limit)} (${b.mode === 'block' ? t('blocks when used up') : t('warning only')})`}
        </Typography>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mb: 0.75 }}>
        <Typography sx={{ fontSize: '1.25rem', fontWeight: 600, fontVariantNumeric: 'tabular-nums', color }}>
          {fmtCost(data.spent) ?? '$0.00'}
        </Typography>
        {b && (
          <Typography sx={{ fontSize: '0.8rem', color: P.textMuted }}>
            {fmtPct(b.share)} {t('of the budget')}
            {b.state === 'over' && ` · ${t('budget used up')}`}
            {b.state === 'warn' && ` · ${t('on course to pass the budget')}`}
          </Typography>
        )}
      </Box>
      {b && (
        <Box sx={{ height: 8, borderRadius: 1, bgcolor: P.hoverBg }}>
          <Box sx={{ height: '100%', width: `${Math.min(100, Math.max(1, b.share * 100))}%`, borderRadius: 1, bgcolor: color }} />
        </Box>
      )}
    </Card>
  );
};
