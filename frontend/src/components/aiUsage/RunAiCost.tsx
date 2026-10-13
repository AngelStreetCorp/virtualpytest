/**
 * One line on a run report: the AI requests, tokens and cost the run caused (ai_calls by script_result_id).
 * Renders nothing when the run made no AI request, or when the user cannot see the numbers.
 */
import { Box, Typography } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import { RunCost, fetchRunCost } from './api';
import { fmtCost, fmtCount, fmtTokens } from './format';

export const RunAiCost: React.FC<{ scriptResultIds: string[] }> = ({ scriptResultIds }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [data, setData] = useState<RunCost | null>(null);
  const key = scriptResultIds.slice(0, 200).join(',');

  useEffect(() => {
    if (!key) {
      setData(null);
      return;
    }
    let live = true;
    fetchRunCost(key.split(','))
      .then((d) => live && setData(d))
      .catch(() => live && setData(null));
    return () => {
      live = false;
    };
  }, [key]);

  if (!data || data.calls === 0) return null;
  const cost = fmtCost(data.cost);
  return (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'baseline', flexWrap: 'wrap', mb: 1.5 }} data-testid="run-ai-cost">
      <Typography sx={{ fontSize: '0.75rem', color: P.textMuted }}>{t('AI used by this run')}</Typography>
      <Typography sx={{ fontSize: '0.85rem', fontVariantNumeric: 'tabular-nums' }}>
        {fmtCount(data.calls)} {t('requests')} · {fmtTokens(data.tokens_in + data.tokens_out)} {t('tokens')} ·{' '}
        {cost ?? t('no price')}
        {data.priced_calls > 0 && data.priced_calls < data.calls && ` (${t('partly priced')})`}
        {data.errors > 0 && ` · ${fmtCount(data.errors)} ${t('failed')}`}
      </Typography>
    </Box>
  );
};
