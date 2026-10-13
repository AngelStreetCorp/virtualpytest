/**
 * Shared layout for the tabs of the Quality page (flaky, slow, not executed in window):
 * section title, window selector (URL-keyed `window` param), the sample/window indicator that
 * every quality answer carries, the workspace scope note and the loading/error gates.
 */

import { Alert, Box, FormControl, InputLabel, MenuItem, Select, Typography } from '@mui/material';
import React, { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useReportScope } from '../../hooks/reports/useRunManagement';
import { QUALITY_WINDOW_OPTIONS, type QualityIdentity, type QualityWindow } from '../../types/reports';
import { QueryState } from './PageState';

/** "script · UI · env · host/device" — the full comparable identity of a quality row. */
export const identityLabel = (identity: QualityIdentity): string =>
  [
    identity.script_name,
    identity.userinterface_name ?? 'no UI',
    identity.environment ?? 'no environment',
    `${identity.host_name ?? 'unknown host'}/${identity.device_name ?? 'unknown device'}`,
  ].join(' · ');

const isWindowOption = (value: number): boolean => (QUALITY_WINDOW_OPTIONS as readonly number[]).includes(value);

/** The `window` URL parameter in days, falling back to the page default. */
export const useQualityWindow = (defaultDays: number): [number, (days: number) => void] => {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get('window'));
  const windowDays = Number.isInteger(raw) && isWindowOption(raw) ? raw : defaultDays;
  const setWindowDays = useCallback(
    (days: number) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (days === defaultDays) next.delete('window');
          else next.set('window', String(days));
          return next;
        },
        { replace: true },
      );
    },
    [defaultDays, setSearchParams],
  );
  return [windowDays, setWindowDays];
};

const formatDay = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString();
};

export const QualityWindowIndicator: React.FC<{ window: QualityWindow }> = ({ window }) => (
  <Typography variant="body2" color="text.secondary" data-testid="quality-window-indicator">
    Window: {formatDay(window.window_start)}–{formatDay(window.window_end)} ({window.window_days} days) · Sample:{' '}
    {window.sample_size} eligible attempts · Minimum {window.min_attempts} attempts per test · Discarded and
    unfinished attempts excluded
  </Typography>
);

export interface QualityPageShellProps {
  title: string;
  description: React.ReactNode;
  windowDays: number;
  onWindowChange: (days: number) => void;
  loading: boolean;
  error: unknown;
  /** Present once a response has arrived. */
  window?: QualityWindow | null;
  actions?: React.ReactNode;
  children: React.ReactNode;
}

export const QualityPageShell: React.FC<QualityPageShellProps> = ({
  title,
  description,
  windowDays,
  onWindowChange,
  loading,
  error,
  window,
  actions,
  children,
}) => {
  const scope = useReportScope();
  return (
    <Box sx={{ width: '100%', maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, alignItems: 'flex-start', mb: 1 }}>
        <Box sx={{ flex: '1 1 260px', minWidth: 0 }}>
          <Typography component="h2" sx={{ fontSize: '1rem', fontWeight: 600 }}>
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {description}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel id="quality-window-label">Window</InputLabel>
            <Select
              labelId="quality-window-label"
              label="Window"
              value={windowDays}
              onChange={(event) => onWindowChange(Number(event.target.value))}
            >
              {QUALITY_WINDOW_OPTIONS.map((days) => (
                <MenuItem key={days} value={days}>
                  {days} days
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {actions}
        </Box>
      </Box>
      {scope.hostFilter && (
        <Alert severity="info" sx={{ mb: 1 }} data-testid="quality-scope-note">
          Limited to the active workspace: {scope.hostFilter.join(', ')}
        </Alert>
      )}
      {window && (
        <Box sx={{ mb: 2 }}>
          <QualityWindowIndicator window={window} />
        </Box>
      )}
      <QueryState loading={loading} error={error}>
        {children}
      </QueryState>
    </Box>
  );
};
