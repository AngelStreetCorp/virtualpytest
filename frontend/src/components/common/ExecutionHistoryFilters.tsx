import React from 'react';
import { Box, MenuItem, Select, TextField, ToggleButton, ToggleButtonGroup } from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { TYPOGRAPHY } from '../../constants/typography';
import type { ExecutionHistoryFilterState, HistoryRange } from '../../hooks/executions/useExecutionHistoryFilters';
import { segmentedSx } from './PageChrome';

/** Search, time range and All / Passed / Failed pills for a Last Executions table. */
export const ExecutionHistoryFilters: React.FC<{ filters: ExecutionHistoryFilterState }> = ({ filters }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
      <TextField
        size="small"
        value={filters.search}
        onChange={(e) => filters.setSearch(e.target.value)}
        placeholder={t('Search script, device, run id')}
        inputProps={{ 'aria-label': t('Search script, device, run id') }}
        sx={{ width: 220, '& .MuiInputBase-input': { py: 0.5, fontSize: TYPOGRAPHY.caption.size } }}
      />
      <Select
        size="small"
        value={filters.range}
        onChange={(e) => filters.setRange(e.target.value as HistoryRange)}
        inputProps={{ 'aria-label': t('Time range') }}
        sx={{ fontSize: TYPOGRAPHY.caption.size, '& .MuiSelect-select': { py: 0.5 } }}
      >
        <MenuItem value="all">{t('All time')}</MenuItem>
        <MenuItem value="1h">{t('Last hour')}</MenuItem>
        <MenuItem value="24h">{t('Last 24 hours')}</MenuItem>
        <MenuItem value="7d">{t('Last 7 days')}</MenuItem>
      </Select>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={filters.resultFilter}
        onChange={(_e, v) => v !== null && filters.setResultFilter(v)}
        sx={segmentedSx(P, 'sm')}
      >
        <ToggleButton value="all">{t('All')} {filters.searchedRows.length}</ToggleButton>
        <ToggleButton value="success" disabled={!filters.hasSuccessful}>{t('Passed')} {filters.passedCount}</ToggleButton>
        <ToggleButton value="failure" disabled={!filters.hasFailed}>{t('Failed')} {filters.failedCount}</ToggleButton>
      </ToggleButtonGroup>
    </Box>
  );
};

export default ExecutionHistoryFilters;
