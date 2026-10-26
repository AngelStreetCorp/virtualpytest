/**
 * Run Summary — one script execution, one campaign execution or one run group.
 *
 * Counts come from the server over ALL children; the children list is paged
 * independently. Tab, child status filter and page live in the URL. A child without
 * recorded evidence stays `unknown`; nothing is inferred.
 */

import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Link,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  Tabs,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import React, { useCallback, useMemo, useState } from 'react';
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { RunAiCost } from '../components/aiUsage/RunAiCost';
import ChartCard from '../components/analytics/ChartCard';
import StatTile from '../components/analytics/StatTile';
import { segmentedSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import AssignmentDialog from '../components/reports/AssignmentDialog';
import DefectsPanel from '../components/reports/DefectsPanel';
import { ExportMenu, type ExportPayload } from '../components/reports/ExportMenu';
import { QueryState, ReportPage, EmptyState } from '../components/reports/PageState';
import { RunStatusDonut, RunTrendChart } from '../components/reports/RunCharts';
import { RunHeader } from '../components/reports/RunHeader';
import RunLivePanel from '../components/reports/RunLivePanel';
import { ShareDialog } from '../components/reports/ShareDialog';
import {
  STATUS_COLORS,
  STATUS_LABELS,
  StatusChip,
  formatDateTime,
  formatDurationMs,
} from '../components/reports/status';
import { useReportPermissions, useRunSummary } from '../hooks/reports/useRunManagement';
import { openR2Url } from '../utils/infrastructure/cloudflareUtils';
import {
  REPORT_ROUTES,
  RUN_STATUSES,
  SUMMARY_TREND_DAYS,
  isRunKind,
  toRunStatus,
  type RunChild,
  type RunIdentity,
  type RunStatus,
  type RunStatusCounts,
  type RunSummaryResponse,
} from '../types/reports';

export const CHILDREN_PAGE_SIZE = 25;
const TABS = ['tests', 'statistics', 'defects'] as const;
type SummaryTab = (typeof TABS)[number];

const parseTab = (raw: string | null): SummaryTab =>
  raw && (TABS as readonly string[]).includes(raw) ? (raw as SummaryTab) : 'tests';

const parseStatus = (raw: string | null): RunStatus | null =>
  raw && (RUN_STATUSES as readonly string[]).includes(raw) ? toRunStatus(raw) : null;

const parsePage = (raw: string | null): number => {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : 0;
};

// Same-test history window. The server counts UTC days, so 24 h and 48 h are 1 and 2 days.
const TREND_RANGES = [
  { value: '24h', days: 1, label: '24 h' },
  { value: '48h', days: 2, label: '48 h' },
  { value: '7d', days: 7, label: '7 d' },
  { value: '30d', days: 30, label: '30 d' },
] as const;
const DEFAULT_TREND_RANGE = TREND_RANGES[3];

const parseRange = (raw: string | null) => TREND_RANGES.find((r) => r.value === raw) ?? DEFAULT_TREND_RANGE;

const windowText = (days: number): string => (days <= 2 ? `last ${days * 24} hours` : `last ${days} days`);

const percent = (value: number, total: number): string =>
  total > 0 ? `${((value / total) * 100).toFixed(1)}%` : '—';

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

const CountTiles: React.FC<{ counts: RunStatusCounts }> = ({ counts }) => (
  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mb: 2 }} data-testid="count-tiles">
    <StatTile label="Total" value={<span data-testid="count-total">{counts.total}</span>} dense />
    {RUN_STATUSES.map((status) => (
      <StatTile
        key={status}
        label={STATUS_LABELS[status]}
        value={<span data-testid={`count-${status}`}>{counts[status]}</span>}
        color={counts[status] ? STATUS_COLORS[status] : undefined}
        dense
      />
    ))}
  </Box>
);

const MetadataPanel: React.FC<{ summary: RunSummaryResponse }> = ({ summary }) => {
  const meta = summary.metadata;
  const rows: Array<[string, React.ReactNode]> = [];
  if (meta.userinterface_name) rows.push(['UI', meta.userinterface_name]);
  if (meta.environment) rows.push(['Environment', meta.environment]);
  if (meta.host_name) rows.push(['Host', meta.host_name]);
  if (meta.device_name) rows.push(['Device', meta.device_name]);
  if (meta.script_type) rows.push(['Type', meta.script_type]);
  if (meta.campaign_name) rows.push(['Campaign', meta.campaign_name]);
  if (meta.executed_by) rows.push(['Executed by', meta.executed_by]);
  if (meta.milestone) {
    rows.push([
      'Milestone',
      <Link key="m" component={RouterLink} to={REPORT_ROUTES.milestone(meta.milestone.id)}>
        {meta.milestone.name}
      </Link>,
    ]);
  }
  if (meta.run_group) {
    rows.push([
      'Group',
      <Link key="g" component={RouterLink} to={REPORT_ROUTES.group(meta.run_group.id)}>
        {meta.run_group.name}
      </Link>,
    ]);
  }
  if (summary.completed_at) {
    rows.push(['Completed', formatDateTime(summary.completed_at)]);
  }
  const labels = meta.labels ?? [];
  const evidence = summary.evidence;

  return (
    <Card variant="outlined" sx={{ flex: '1 1 280px', minWidth: 0 }}>
      <CardContent>
        <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
          Details
        </Typography>
        <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.5, m: 0, mt: 1 }}>
          {rows.map(([key, value]) => (
            <React.Fragment key={key}>
              <Typography component="dt" variant="body2" color="text.secondary">
                {key}
              </Typography>
              <Typography component="dd" variant="body2" sx={{ m: 0, wordBreak: 'break-word' }}>
                {value}
              </Typography>
            </React.Fragment>
          ))}
        </Box>
        {labels.length > 0 && (
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 1 }}>
            {labels.map((label) => (
              <Chip
                key={label.id}
                size="small"
                label={label.name}
                sx={label.color ? { borderColor: label.color, color: label.color } : undefined}
                variant="outlined"
              />
            ))}
          </Box>
        )}
        {meta.error && (
          <Alert severity="error" sx={{ mt: 1, wordBreak: 'break-word' }}>
            {meta.error}
          </Alert>
        )}
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1.5 }}>
          {evidence.report_url && (
            <Button size="small" variant="outlined" onClick={() => void openR2Url(evidence.report_url as string)}>
              Open report
            </Button>
          )}
          {evidence.logs_url && (
            <Button size="small" variant="outlined" onClick={() => void openR2Url(evidence.logs_url as string)}>
              Open logs
            </Button>
          )}
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="step-evidence">
          {evidence.steps
            ? `Step evidence: ${evidence.steps.passed} passed, ${evidence.steps.failed} failed of ${evidence.steps.total}`
            : 'Step evidence not recorded for this run'}
        </Typography>
      </CardContent>
    </Card>
  );
};

const ChildrenTable: React.FC<{ items: RunChild[]; showAttempts: boolean }> = ({ items, showAttempts }) => (
  <Box sx={{ overflowX: 'auto' }}>
    <Table size="small" data-testid="children-table" sx={{ tableLayout: 'fixed', minWidth: 820, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col style={{ width: '40%' }} /><col style={{ width: 110 }} /><col style={{ width: 260 }} />{showAttempts && <col style={{ width: 90 }} />}<col style={{ width: 190 }} /><col style={{ width: 100 }} /></colgroup>
      <TableHead>
        <TableRow>
          <TableCell>Test</TableCell>
          <TableCell>Status</TableCell>
          <TableCell>Target</TableCell>
          {showAttempts && <TableCell>Attempts</TableCell>}
          <TableCell>Started</TableCell>
          <TableCell>Duration</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {items.map((child, index) => (
          <TableRow
            key={child.script_result_id ?? `missing-${index}`}
            data-testid="child-row"
            sx={{ opacity: child.discard ? 0.5 : 1 }}
          >
            <TableCell sx={{ maxWidth: 320, wordBreak: 'break-word' }}>
              {child.script_result_id ? (
                <Link component={RouterLink} to={REPORT_ROUTES.summary('script', child.script_result_id)}>
                  {child.name}
                </Link>
              ) : (
                <>
                  {child.name}
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                    No result recorded{child.skip_reason || child.unknown_reason ? ` — ${child.skip_reason ?? child.unknown_reason}` : ''}
                  </Typography>
                </>
              )}
            </TableCell>
            <TableCell>
              <StatusChip status={child.status} />
            </TableCell>
            <TableCell sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              <span title={[child.host_name, child.device_name].filter(Boolean).join(' · ')}>
                {[child.host_name, child.device_name].filter(Boolean).join(' · ') || '—'}
              </span>
            </TableCell>
            {showAttempts && <TableCell>{child.attempts ?? '—'}</TableCell>}
            <TableCell>{formatDateTime(child.started_at)}</TableCell>
            <TableCell>{formatDurationMs(child.execution_time_ms)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </Box>
);

// The one card every summary tab body sits on. Colours come from the active theme palette.
const TabCard: React.FC<{ children: React.ReactNode; testId?: string }> = ({ children, testId }) => {
  const P = useAgentChatPalette();
  return (
    <Card
      variant="outlined"
      data-testid={testId}
      sx={{ borderRadius: 3, borderColor: P.borderColor, bgcolor: P.surface, boxShadow: 'none' }}
    >
      <CardContent>{children}</CardContent>
    </Card>
  );
};

const StatisticsTable: React.FC<{ counts: RunStatusCounts }> = ({ counts }) => (
  <Box sx={{ overflowX: 'auto' }}>
    <Table size="small" data-testid="statistics-table" sx={{ tableLayout: 'fixed', minWidth: 360, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 100 }} /><col style={{ width: 140 }} /></colgroup>
      <TableHead>
        <TableRow>
          <TableCell>Status</TableCell>
          <TableCell align="right">Count</TableCell>
          <TableCell align="right">Share of {counts.total}</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {RUN_STATUSES.map((status) => (
          <TableRow key={status}>
            <TableCell>{STATUS_LABELS[status]}</TableCell>
            <TableCell align="right">{counts[status]}</TableCell>
            <TableCell align="right">{percent(counts[status], counts.total)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </Box>
);

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const RunSummary: React.FC = () => {
  const { kind, id } = useParams<{ kind: string; id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { canShare, canEdit } = useReportPermissions();
  const P = useAgentChatPalette();
  const [shareOpen, setShareOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);

  const identity: RunIdentity | null = useMemo(
    () => (isRunKind(kind) && id ? { kind, id } : null),
    [kind, id],
  );
  const tab = parseTab(searchParams.get('tab'));
  const statusFilter = parseStatus(searchParams.get('status'));
  const page = parsePage(searchParams.get('page'));
  const range = parseRange(searchParams.get('range'));
  const taskId = searchParams.get('task');

  const params = useMemo(
    () => ({
      limit: CHILDREN_PAGE_SIZE,
      offset: page * CHILDREN_PAGE_SIZE,
      status: statusFilter,
      trendDays: range.days,
    }),
    [page, statusFilter, range.days],
  );
  const summary = useRunSummary(identity, params);

  const updateParams = useCallback(
    (changes: Record<string, string | null>) =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(changes)) {
            if (value === null || value === '') next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace: true },
      ),
    [setSearchParams],
  );

  const handleLiveCompleted = useCallback(
    (scriptResultId: string | null) => {
      updateParams({ task: null });
      if (scriptResultId && !(identity?.kind === 'script' && identity.id === scriptResultId)) {
        navigate(REPORT_ROUTES.summary('script', scriptResultId));
      } else {
        void summary.refetch();
      }
    },
    [identity, navigate, summary, updateParams],
  );

  if (!identity) {
    return (
      <ReportPage>
        <Alert severity="error" data-testid="state-invalid">
          Unknown run type. Open a run from{' '}
          <Link component={RouterLink} to={REPORT_ROUTES.testReports}>
            Test Reports
          </Link>
          .
        </Alert>
      </ReportPage>
    );
  }

  const data = summary.data;

  const buildExport = (): ExportPayload => {
    const d = data as RunSummaryResponse;
    return {
      title: d.title,
      summary: [
        ['Status', STATUS_LABELS[d.status]],
        ['Total', d.counts.total],
        ...RUN_STATUSES.map((s) => [STATUS_LABELS[s], d.counts[s]] as [string, number]),
        ['Rows', `${d.children.offset + 1}–${d.children.offset + d.children.items.length} of ${d.children.total}`],
      ],
      headers: ['Test', 'Status', 'UI', 'Environment', 'Host', 'Device', 'Started', 'Duration (ms)'],
      rows: d.children.items.map((c) => [
        c.name,
        STATUS_LABELS[c.status],
        c.userinterface_name,
        c.environment,
        c.host_name,
        c.device_name,
        c.started_at,
        c.execution_time_ms,
      ]),
    };
  };

  const trendEmpty = !data || data.trend.points.every((p) => p.total === 0);
  const trendDays = data?.trend.window_days || SUMMARY_TREND_DAYS;
  const childIds = (data?.children.items ?? [])
    .map((c) => c.script_result_id)
    .filter((v): v is string => Boolean(v));

  return (
    <ReportPage>
      {taskId && (
        <Box sx={{ mb: 2 }}>
          <RunLivePanel taskId={taskId} onCompleted={handleLiveCompleted} />
        </Box>
      )}
      <QueryState loading={summary.isLoading} error={summary.error}>
        {data && (
          <>
            <RunHeader
              kind={identity.kind}
              title={data.title}
              status={data.status}
              startedAt={data.started_at}
              durationMs={data.execution_time_ms}
              actions={
                <>
                  {identity.kind === 'script' && canEdit && (
                    <Button size="small" variant="outlined" onClick={() => setAssignOpen(true)}>
                      Assign
                    </Button>
                  )}
                  {canShare && (
                    <Button size="small" variant="outlined" onClick={() => setShareOpen(true)}>
                      Share
                    </Button>
                  )}
                  <ExportMenu buildExport={buildExport} chartExportId="run-summary-trend" />
                </>
              }
            />

            <CountTiles counts={data.counts} />
            <RunAiCost scriptResultIds={identity.kind === 'script' ? [identity.id] : childIds} />

            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={range.value}
                aria-label="Trend time range"
                onChange={(_e, value: string | null) => value && updateParams({ range: value === DEFAULT_TREND_RANGE.value ? null : value })}
                sx={segmentedSx(P, 'sm')}
              >
                {TREND_RANGES.map((r) => (
                  <ToggleButton key={r.value} value={r.value}>
                    {r.label}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </Box>

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 2 }}>
              <ChartCard title="Status" minHeight={140} flex="1 1 260px">
                <RunStatusDonut counts={data.counts} exportId="run-summary-donut" />
              </ChartCard>
              <ChartCard
                title={`Trend · ${windowText(trendDays)}`}
                subtitle="same test, UTC days"
                minHeight={180}
                flex="2 1 320px"
                empty={trendEmpty}
                emptyMessage={`No attempts in the ${windowText(trendDays)}`}
              >
                <RunTrendChart points={data.trend.points} exportId="run-summary-trend" />
              </ChartCard>
              <MetadataPanel summary={data} />
            </Box>

            <Tabs
              value={tab}
              onChange={(_e, value: SummaryTab) => updateParams({ tab: value === 'tests' ? null : value })}
              variant="scrollable"
              allowScrollButtonsMobile
              sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}
            >
              <Tab value="tests" label="Tests" />
              <Tab value="statistics" label="Statistics" />
              <Tab value="defects" label="Defects" />
            </Tabs>

            {tab === 'tests' && (
              <TabCard testId="tab-card-tests">
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1 }}>
                  <Chip
                    size="small"
                    label={`All (${data.counts.total})`}
                    color={statusFilter === null ? 'primary' : 'default'}
                    onClick={() => updateParams({ status: null, page: null })}
                  />
                  {RUN_STATUSES.map((status) => (
                    <Chip
                      key={status}
                      size="small"
                      label={`${STATUS_LABELS[status]} (${data.counts[status]})`}
                      color={statusFilter === status ? 'primary' : 'default'}
                      variant={statusFilter === status ? 'filled' : 'outlined'}
                      onClick={() => updateParams({ status, page: null })}
                    />
                  ))}
                </Box>
                {data.children.items.length === 0 ? (
                  <EmptyState
                    message={statusFilter ? `No ${STATUS_LABELS[statusFilter].toLowerCase()} tests in this run.` : 'This run has no recorded tests.'}
                  />
                ) : (
                  <>
                    <ChildrenTable items={data.children.items} showAttempts={identity.kind === 'group'} />
                    <TablePagination
                      component="div"
                      count={data.children.total}
                      page={page}
                      rowsPerPage={CHILDREN_PAGE_SIZE}
                      rowsPerPageOptions={[CHILDREN_PAGE_SIZE]}
                      onPageChange={(_e, next) => updateParams({ page: next ? String(next) : null })}
                    />
                  </>
                )}
              </TabCard>
            )}

            {tab === 'statistics' && (
              <TabCard testId="tab-card-statistics">
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'flex-start' }}>
                  <Box sx={{ flex: '1 1 280px', minWidth: 0 }}>
                    <StatisticsTable counts={data.counts} />
                  </Box>
                  <Box sx={{ flex: '2 1 320px', minWidth: 0 }}>
                    <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
                      {`Pass / fail per day · ${windowText(trendDays)}`}
                    </Typography>
                    {trendEmpty ? (
                      <EmptyState message={`No attempts in the ${windowText(trendDays)}`} />
                    ) : (
                      <RunTrendChart points={data.trend.points} height={220} exportId="run-summary-trend-stats" />
                    )}
                  </Box>
                </Box>
              </TabCard>
            )}


            {tab === 'defects' && (
              <TabCard testId="tab-card-defects">
                <DefectsPanel
                  scriptResultIds={identity.kind === 'script' ? [identity.id] : childIds}
                  caption={identity.kind === 'script' ? undefined : 'Defects linked to results on this page'}
                />
              </TabCard>
            )}

            <ShareDialog open={shareOpen} identity={identity} onClose={() => setShareOpen(false)} />
            {identity.kind === 'script' && (
              <AssignmentDialog
                open={assignOpen}
                resultIds={[identity.id]}
                initial={{
                  milestone_id: data.metadata.milestone?.id ?? null,
                  run_group_id: data.metadata.run_group?.id ?? null,
                  label_ids: (data.metadata.labels ?? []).map((l) => l.id),
                }}
                onClose={() => setAssignOpen(false)}
                onDone={() => {
                  setAssignOpen(false);
                  void summary.refetch();
                }}
              />
            )}
          </>
        )}
      </QueryState>
    </ReportPage>
  );
};

export default RunSummary;
