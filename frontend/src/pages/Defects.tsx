/**
 * Team defects (local-first). Filters are kept in the URL; status changes and Jira push
 * reuse the DefectsPanel components.
 */

import { Box, Button, MenuItem, TextField, Typography } from '@mui/material';
import React, { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { CreateDefectDialog, DefectTable, RESOLVE_NOTE } from '../components/reports/DefectsPanel';
import { EmptyState, QueryState } from '../components/reports/PageState';
import { useDefects, useReportPermissions } from '../hooks/reports/useRunManagement';
import { useI18n } from '../i18n/useI18n';
import {
  DEFECT_SEVERITIES,
  DEFECT_STATUSES,
  type DefectSeverity,
  type DefectStatus,
} from '../types/reports';

const parseOne = <T extends string>(raw: string | null, allowed: readonly T[]): T | null =>
  raw && (allowed as readonly string[]).includes(raw) ? (raw as T) : null;

const Defects: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const status = parseOne<DefectStatus>(searchParams.get('status'), DEFECT_STATUSES);
  const severity = parseOne<DefectSeverity>(searchParams.get('severity'), DEFECT_SEVERITIES);
  const { canEditDefects } = useReportPermissions();
  const [createOpen, setCreateOpen] = useState(false);
  const { t } = useI18n();
  const defects = useDefects({ status, severity });

  const setFilter = (key: 'status' | 'severity', value: string) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );

  const items = defects.data?.items ?? [];

  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Box>
          <Typography variant="caption" color="text.secondary">
            {RESOLVE_NOTE}
          </Typography>
        </Box>
        {canEditDefects && (
          <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
            New defect
          </Button>
        )}
      </Box>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
        <TextField
          select
          size="small"
          label="Status"
          value={status ?? ''}
          onChange={(event) => setFilter('status', event.target.value)}
          sx={{ minWidth: 150 }}
        >
          <MenuItem value="">All</MenuItem>
          {DEFECT_STATUSES.map((value) => (
            <MenuItem key={value} value={value}>
              {value.replace('_', ' ')}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label="Severity"
          value={severity ?? ''}
          onChange={(event) => setFilter('severity', event.target.value)}
          sx={{ minWidth: 150 }}
        >
          <MenuItem value="">All</MenuItem>
          {DEFECT_SEVERITIES.map((value) => (
            <MenuItem key={value} value={value}>
              {value}
            </MenuItem>
          ))}
        </TextField>
      </Box>
      <QueryState loading={defects.isLoading} error={defects.error}>
        {items.length === 0 ? (
          status || severity ? (
            <EmptyState message={t('No defects match these filters.')} />
          ) : (
            <EmptyState message={t('No defects yet.')}>
              {canEditDefects && (
                <Button variant="outlined" size="small" sx={{ mt: 1 }} onClick={() => setCreateOpen(true)}>
                  {t('Log the first defect')}
                </Button>
              )}
            </EmptyState>
          )
        ) : (
          <DefectTable defects={items} />
        )}
      </QueryState>
      <CreateDefectDialog open={createOpen} scriptResultIds={[]} onClose={() => setCreateOpen(false)} />
    </Box>
  );
};

export default Defects;
