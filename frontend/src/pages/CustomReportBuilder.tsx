/**
 * Custom report builder: a TQL filter, allowlisted columns and a chart type, executed on
 * the server. Table, counts and chart all come from ONE query response, so they always
 * agree with each other and with the export. Saved reports are private to their creator.
 */

import {
  Alert,
  Box,
  Button,
  Checkbox,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormGroup,
  InputLabel,
  Link,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import React, { useEffect, useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { StatTile } from '../components/analytics/StatTile';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import { ExportMenu } from '../components/reports/ExportMenu';
import { EmptyState, QueryState } from '../components/reports/PageState';
import { RunStatusDonut, RunTrendChart } from '../components/reports/RunCharts';
import { STATUS_COLORS, STATUS_LABELS, StatusChip, formatDateTime } from '../components/reports/status';
import { describeError, runReportQuery, validateTql } from '../hooks/reports/runManagementApi';
import { useCustomReportMutations, useCustomReports, useReportScope } from '../hooks/reports/useRunManagement';
import { useToast } from '../hooks/useToast';
import { useI18n } from '../i18n/useI18n';
import {
  REPORT_CHART_LABELS,
  REPORT_CHART_TYPES,
  REPORT_COLUMNS,
  REPORT_COLUMN_LABELS,
  REPORT_FILTER_SCHEMA_VERSION,
  REPORT_GROUP_BY,
  REPORT_ROUTES,
  RUN_STATUSES,
  toRunStatus,
  type CustomReport,
  type CustomReportInput,
  type ReportChartSpec,
  type ReportColumn,
  type ReportQueryRequest,
} from '../types/reports';
import { dangerButtonSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { TYPOGRAPHY } from '../constants/typography';

const PAGE_SIZE = 100;
const CHART_EXPORT_ID = 'custom-report-chart';
const TQL_DEBOUNCE_MS = 400;

const DEFAULT_COLUMNS: ReportColumn[] = ['script_name', 'status', 'host_name', 'device_name', 'started_at'];

interface Draft {
  name: string;
  tql: string;
  columns: ReportColumn[];
  chart: ReportChartSpec;
}

const NEW_DRAFT: Draft = {
  name: 'Untitled report',
  tql: '',
  columns: DEFAULT_COLUMNS,
  chart: { type: 'status_by_day' },
};

type TqlState =
  | { state: 'valid' }
  | { state: 'checking' }
  | { state: 'invalid'; error: string; position: number | null }
  | { state: 'unavailable'; error: string };

const GROUP_BY_LABELS: Record<string, string> = {
  script_name: 'Test',
  host_name: 'Host',
  device_name: 'Device',
  userinterface_name: 'UI',
  environment: 'Environment',
};

const TQL_HELP =
  'Keys: script: (prefix* allowed) host: device: ui: env: status: milestone: label: since: until: flaky:true. ' +
  'Clauses separated by spaces are combined with AND; quote values that contain spaces, e.g. ui:"Main menu". ' +
  'since:/until: take a UTC date (2026-10-01) or a duration (7d, 24h).';

/** The query text with a caret under the reported error position. */
const caretLine = (tql: string, position: number | null): string | null => {
  if (position === null || position < 0 || position > tql.length) return null;
  return `${tql}\n${' '.repeat(position)}^`;
};

const toInput = (draft: Draft): CustomReportInput => ({
  name: draft.name.trim(),
  filter: { schema_version: REPORT_FILTER_SCHEMA_VERSION, tql: draft.tql.trim() },
  columns: draft.columns,
  chart: draft.chart.type === 'status_by_group' ? draft.chart : { type: draft.chart.type },
});

const fromReport = (report: CustomReport): Draft => ({
  name: report.name,
  tql: report.filter?.tql ?? '',
  columns: (report.columns ?? []).filter((c): c is ReportColumn => (REPORT_COLUMNS as readonly string[]).includes(c)),
  chart: report.chart ?? { type: 'status_by_day' },
});

const renderCell = (column: ReportColumn, value: string | number | boolean | null | undefined): React.ReactNode => {
  if (value === null || value === undefined || value === '') return '—';
  if (column === 'status') return <StatusChip status={toRunStatus(value)} />;
  if ((column === 'started_at' || column === 'completed_at') && typeof value === 'string') return formatDateTime(value);
  if (column === 'discard' && typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
};

const CustomReportBuilder: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const scope = useReportScope();
  const { showSuccess } = useToast();
  const reports = useCustomReports();
  const mutations = useCustomReportMutations();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(NEW_DRAFT);
  const [schemaMismatch, setSchemaMismatch] = useState<number | null>(null);
  const [storedError, setStoredError] = useState<string | null>(null);
  const [tqlState, setTqlState] = useState<TqlState>({ state: 'valid' });
  const [submitted, setSubmitted] = useState<Omit<ReportQueryRequest, 'offset'> | null>(null);
  const [offset, setOffset] = useState(0);
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsName, setSaveAsName] = useState('');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Debounced server-side TQL validation; a newer keystroke aborts the older request.
  useEffect(() => {
    const tql = draft.tql.trim();
    if (!tql) {
      setTqlState({ state: 'valid' });
      return undefined;
    }
    setTqlState({ state: 'checking' });
    const controller = new AbortController();
    const timer = setTimeout(() => {
      validateTql(tql, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) return;
          setTqlState(
            result.ok
              ? { state: 'valid' }
              : { state: 'invalid', error: result.error ?? 'Invalid query', position: result.position ?? null },
          );
        })
        .catch((error) => {
          if (controller.signal.aborted) return;
          setTqlState({ state: 'unavailable', error: describeError(error) });
        });
    }, TQL_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [draft.tql]);

  const result = useQuery({
    queryKey: ['run-management', 'report-query', scope.serverKey, scope.deviceFilter, submitted, offset],
    queryFn: () => runReportQuery({ ...(submitted as Omit<ReportQueryRequest, 'offset'>), offset }, scope),
    enabled: submitted !== null,
    placeholderData: (previous) => previous,
    retry: false,
  });

  const canRun = tqlState.state === 'valid' && draft.columns.length > 0 && schemaMismatch === null;

  const runReport = () => {
    if (!canRun) return;
    const input = toInput(draft);
    setOffset(0);
    setSubmitted({
      filter: input.filter,
      columns: input.columns,
      chart: input.chart,
      limit: PAGE_SIZE,
    });
  };

  const selectReport = (report: CustomReport) => {
    setSelectedId(report.id);
    setDraft(fromReport(report));
    setSubmitted(null);
    setActionError(null);
    // The server revalidates every stored definition on read (`valid` / `validation_error`).
    const version = report.filter?.schema_version;
    setSchemaMismatch(version === REPORT_FILTER_SCHEMA_VERSION ? null : version ?? 0);
    setStoredError(report.valid === false ? report.validation_error?.error ?? 'The saved definition is no longer valid.' : null);
  };

  const newReport = () => {
    setSelectedId(null);
    setDraft(NEW_DRAFT);
    setSubmitted(null);
    setSchemaMismatch(null);
    setStoredError(null);
    setActionError(null);
  };

  const canSave = draft.name.trim().length > 0 && tqlState.state === 'valid' && draft.columns.length > 0;

  const save = async () => {
    setActionError(null);
    try {
      const input = toInput(draft);
      const saved = selectedId
        ? await mutations.update.mutateAsync({ id: selectedId, input })
        : await mutations.create.mutateAsync(input);
      setSelectedId(saved.id);
      setSchemaMismatch(null);
      showSuccess('Report saved');
    } catch (error) {
      setActionError(describeError(error));
    }
  };

  const saveAs = async () => {
    setActionError(null);
    try {
      const saved = await mutations.create.mutateAsync(toInput({ ...draft, name: saveAsName }));
      setSelectedId(saved.id);
      setDraft((prev) => ({ ...prev, name: saved.name }));
      setSchemaMismatch(null);
      setSaveAsOpen(false);
      showSuccess('Report saved');
    } catch (error) {
      setActionError(describeError(error));
    }
  };

  const remove = async () => {
    if (!selectedId) return;
    setDeleteOpen(false);
    setActionError(null);
    try {
      await mutations.remove.mutateAsync(selectedId);
      newReport();
    } catch (error) {
      setActionError(describeError(error));
    }
  };

  const toggleColumn = (column: ReportColumn) =>
    setDraft((prev) => ({
      ...prev,
      columns: prev.columns.includes(column)
        ? prev.columns.filter((c) => c !== column)
        : REPORT_COLUMNS.filter((c) => c === column || prev.columns.includes(c)),
    }));

  const data = result.data;
  const tqlCaret = tqlState.state === 'invalid' ? caretLine(draft.tql.trim(), tqlState.position) : null;

  const buildExport = useMemo(
    () => () => ({
      title: draft.name.trim() || 'Custom report',
      summary: [
        ['Filter', submitted?.filter.tql || '(all results in scope)'],
        ['Matching results', data?.total ?? 0],
        ...RUN_STATUSES.map((status) => [STATUS_LABELS[status], data?.counts[status] ?? 0] as [string, number]),
        ['Rows exported', `${data?.rows.length ?? 0} (from offset ${offset})`],
      ] as Array<[string, string | number]>,
      headers: (data?.columns ?? []).map((c) => REPORT_COLUMN_LABELS[c] ?? c),
      rows: (data?.rows ?? []).map((row) => (data?.columns ?? []).map((c) => row[c] ?? null)),
    }),
    [data, draft.name, offset, submitted],
  );

  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 2, minWidth: 0 }}>
        <Paper variant="outlined" sx={{ p: 1.5, width: { xs: '100%', md: 260 }, flexShrink: 0 }}>
          <Typography variant="subtitle2">Saved reports</Typography>
          <Typography variant="caption" color="text.secondary" data-testid="reports-private-note">
            Visible only to you.
          </Typography>
          <QueryState loading={reports.isLoading} error={reports.error}>
            {(reports.data?.items ?? []).length === 0 ? (
              <EmptyState message={t('No saved reports yet. Pick filters, press Run, then Save.')} />
            ) : (
              <List dense>
                {(reports.data?.items ?? []).map((report) => (
                  <ListItemButton
                    key={report.id}
                    selected={report.id === selectedId}
                    onClick={() => selectReport(report)}
                  >
                    <ListItemText primary={report.name} secondary={formatDateTime(report.updated_at)} />
                  </ListItemButton>
                ))}
              </List>
            )}
          </QueryState>
          <Button size="small" onClick={newReport} sx={{ mt: 1 }}>
            New report
          </Button>
        </Paper>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            {storedError && schemaMismatch === null && (
              <Alert severity="warning" sx={{ mb: 2 }} data-testid="stored-invalid">
                This saved report no longer validates: {storedError}. Fix the definition and save it again.
              </Alert>
            )}
            {schemaMismatch !== null && (
              <Alert severity="warning" sx={{ mb: 2 }} data-testid="schema-mismatch">
                This report was saved with filter schema version {schemaMismatch}; the current version is{' '}
                {REPORT_FILTER_SCHEMA_VERSION}. Check the filter and save it again before running it.
              </Alert>
            )}
            <TextField
              label="Report name"
              size="small"
              fullWidth
              value={draft.name}
              onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
              sx={{ mb: 2 }}
            />
            <TextField
              label="Filter (TQL)"
              size="small"
              fullWidth
              value={draft.tql}
              placeholder='status:failed since:7d ui:"Main menu"'
              onChange={(event) => setDraft((prev) => ({ ...prev, tql: event.target.value }))}
              error={tqlState.state === 'invalid'}
              inputProps={{ 'aria-label': 'TQL filter', spellCheck: false }}
              helperText={
                tqlState.state === 'invalid' ? (
                  <Box component="span" data-testid="tql-error">
                    {tqlState.error}
                    {tqlState.position !== null && ` (at character ${tqlState.position + 1})`}
                    {tqlCaret && (
                      <Box
                        component="pre"
                        data-testid="tql-caret"
                        sx={{ m: 0, mt: 0.5, fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, overflowX: 'auto' }}
                      >
                        {tqlCaret}
                      </Box>
                    )}
                  </Box>
                ) : tqlState.state === 'checking' ? (
                  'Checking…'
                ) : tqlState.state === 'unavailable' ? (
                  `Could not validate the filter: ${tqlState.error}`
                ) : (
                  TQL_HELP
                )
              }
            />

            <Typography variant="subtitle2" sx={{ mt: 2 }}>
              Columns
            </Typography>
            <FormGroup row>
              {REPORT_COLUMNS.map((column) => (
                <FormControlLabel
                  key={column}
                  control={
                    <Checkbox
                      size="small"
                      checked={draft.columns.includes(column)}
                      onChange={() => toggleColumn(column)}
                    />
                  }
                  label={REPORT_COLUMN_LABELS[column]}
                />
              ))}
            </FormGroup>

            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 2 }}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel id="report-chart-label">Chart</InputLabel>
                <Select
                  labelId="report-chart-label"
                  label="Chart"
                  value={draft.chart.type}
                  onChange={(event) =>
                    setDraft((prev) => ({
                      ...prev,
                      chart:
                        event.target.value === 'status_by_group'
                          ? { type: 'status_by_group', group_by: prev.chart.group_by ?? 'script_name' }
                          : { type: event.target.value as ReportChartSpec['type'] },
                    }))
                  }
                >
                  {REPORT_CHART_TYPES.map((type) => (
                    <MenuItem key={type} value={type}>
                      {REPORT_CHART_LABELS[type]}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {draft.chart.type === 'status_by_group' && (
                <FormControl size="small" sx={{ minWidth: 160 }}>
                  <InputLabel id="report-groupby-label">Group by</InputLabel>
                  <Select
                    labelId="report-groupby-label"
                    label="Group by"
                    value={draft.chart.group_by ?? 'script_name'}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        chart: { type: 'status_by_group', group_by: event.target.value as ReportChartSpec['group_by'] },
                      }))
                    }
                  >
                    {REPORT_GROUP_BY.map((field) => (
                      <MenuItem key={field} value={field}>
                        {GROUP_BY_LABELS[field]}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
            </Box>

            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 2 }}>
              <Button variant="contained" onClick={runReport} disabled={!canRun}>
                Run
              </Button>
              <Button
                variant="outlined"
                onClick={() => void save()}
                disabled={!canSave || mutations.create.isPending || mutations.update.isPending}
              >
                Save
              </Button>
              <Button
                variant="outlined"
                onClick={() => {
                  setSaveAsName(`${draft.name.trim()} (copy)`);
                  setSaveAsOpen(true);
                }}
                disabled={!canSave}
              >
                Save as…
              </Button>
              {selectedId && (
                <Button onClick={() => setDeleteOpen(true)} sx={dangerButtonSx(P)}>
                  Delete
                </Button>
              )}
            </Box>
            {draft.columns.length === 0 && (
              <Typography variant="caption" color="error">
                Select at least one column.
              </Typography>
            )}
            {actionError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {actionError}
              </Alert>
            )}
          </Paper>

          {submitted && (
            <QueryState loading={result.isLoading} error={result.error}>
              {data && (
                <Box sx={{ opacity: result.isFetching ? 0.6 : 1 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1, mb: 1 }}>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                      <StatTile label="Total" value={<span data-testid="report-count-total">{data.counts.total}</span>} dense />
                      {RUN_STATUSES.map((status) => (
                        <StatTile
                          key={status}
                          label={STATUS_LABELS[status]}
                          color={STATUS_COLORS[status]}
                          value={<span data-testid={`report-count-${status}`}>{data.counts[status]}</span>}
                          dense
                        />
                      ))}
                    </Box>
                    <ExportMenu
                      buildExport={buildExport}
                      chartExportId={data.chart.type === 'none' ? undefined : CHART_EXPORT_ID}
                    />
                  </Box>

                  {data.chart.type !== 'none' && (
                  <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
                    {data.chart.type === 'status_share' ? (
                      <Box sx={{ maxWidth: 420 }}>
                        <RunStatusDonut counts={data.counts} exportId={CHART_EXPORT_ID} />
                      </Box>
                    ) : data.chart.points.length === 0 ? (
                      <EmptyState message="Nothing to chart for this filter." />
                    ) : (
                      <RunTrendChart
                        points={data.chart.points}
                        xKey="x"
                        shortenDates={data.chart.type === 'status_by_day'}
                        exportId={CHART_EXPORT_ID}
                      />
                    )}
                  </Paper>
                  )}

                  {data.rows.length === 0 ? (
                    <EmptyState message="No results match this filter." />
                  ) : (
                    <TableContainer component={Paper} variant="outlined" sx={{ maxWidth: '100%', overflowX: 'auto' }}>
                      <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 200 + 130 * data.columns.length, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
                        <colgroup>
                          {data.columns.map((column, i) => (i === 0 ? <col key={column} /> : <col key={column} style={{ width: 130 }} />))}
                          <col style={{ width: 100 }} />
                        </colgroup>
                        <TableHead>
                          <TableRow>
                            {data.columns.map((column) => (
                              <TableCell key={column}>{REPORT_COLUMN_LABELS[column] ?? column}</TableCell>
                            ))}
                            <TableCell>Evidence</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {data.rows.map((row, index) => (
                            <TableRow key={row.script_result_id ?? index} data-testid="report-row">
                              {data.columns.map((column) => (
                                <TableCell key={column} sx={{ wordBreak: 'break-word' }}>
                                  {renderCell(column, row[column])}
                                </TableCell>
                              ))}
                              <TableCell>
                                {row.script_result_id ? (
                                  <Link component={RouterLink} to={REPORT_ROUTES.summary('script', row.script_result_id)}>
                                    Summary
                                  </Link>
                                ) : (
                                  '—'
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                    <Typography variant="caption" color="text.secondary">
                      {data.total === 0
                        ? 'No rows'
                        : `Rows ${offset + 1}–${offset + data.rows.length} of ${data.total}`}
                    </Typography>
                    <Button
                      size="small"
                      disabled={offset === 0}
                      onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
                    >
                      Previous
                    </Button>
                    <Button
                      size="small"
                      disabled={offset + data.rows.length >= data.total}
                      onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
                    >
                      Next
                    </Button>
                  </Box>
                </Box>
              )}
            </QueryState>
          )}
        </Box>
      </Box>

      <StyledDialog open={saveAsOpen} onClose={() => setSaveAsOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Save as a new report</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            size="small"
            label="Name"
            value={saveAsName}
            onChange={(event) => setSaveAsName(event.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSaveAsOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={() => void saveAs()} disabled={!saveAsName.trim()}>
            Save
          </Button>
        </DialogActions>
      </StyledDialog>

      <ConfirmDialog
        open={deleteOpen}
        title="Delete report"
        message={`Delete the saved report "${draft.name}"? Test results are not affected.`}
        confirmText="Delete"
        confirmColor="error"
        onConfirm={() => void remove()}
        onCancel={() => setDeleteOpen(false)}
      />
    </Box>
  );
};

export default CustomReportBuilder;
