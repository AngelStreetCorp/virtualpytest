import { Box, Card, CardContent, Link, Typography } from '@mui/material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAnalyticsSection, useProjectMetrics } from '../../hooks/pages/useAnalytics';
import {
  AlertsSection,
  DevicesSection,
  IncidentsSection,
  KpiSection,
  OverviewSection,
  Ranked,
  SystemSection,
} from '../../types/pages/Analytics_Types';

import { CodeTreemap, Donut, HBar, StackedBar, useMode } from './Charts';
import ChartCard from './ChartCard';
import {
  categorical,
  colorForNames,
  DEVICE_STATUS,
  OUTCOME,
  REACHABILITY,
  SEVERITY,
  seriesColor,
  STATUS,
} from './palette';
import StatTile from './StatTile';
import { bottomN, topN } from './topN';

/**
 * One component per tab. Each owns its own fetch, so opening the page costs exactly
 * one section — see MonitoringAnalytics.tsx for why that matters.
 */

const Row: React.FC<{ children: React.ReactNode; mb?: number }> = ({ children, mb = 2 }) => (
  <Box sx={{ display: 'flex', gap: 2, mb, alignItems: 'stretch', flexWrap: 'wrap' }}>{children}</Box>
);

const asRanked = (record: Record<string, number> | undefined): Ranked[] =>
  Object.entries(record || {}).map(([name, value]) => ({ name, value }));

const pct = (value: number | null | undefined) => (value == null ? '—' : `${value}%`);

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

/**
 * One floor for every headline tile, not a per-tile number.
 *
 * The tiles used to carry hand-picked minWidths (110/150/120/120/110). Those summed to
 * 610px, and with the 32px gaps that consumed the whole 738px container, so flex had no
 * free space left to hand out and each tile was pinned to its own floor — which is what
 * made the gaps read as 35/67/37/46px instead of one value. Worse, the floors had drifted
 * away from the content: "Devices" reserved 150px for a 114px number and opened a 36px
 * hole after itself. One shared floor lets `grow` do the aligning; it only has to be wide
 * enough for the widest label ("OPEN INCIDENTS") so nothing clips or wraps.
 */
const KPI_TILE_MIN_WIDTH = 120;

export const OverviewPanel: React.FC = () => {
  const { data, loading, refreshing, error } = useAnalyticsSection<OverviewSection>('overview');
  const mode = useMode();
  const t = data?.tiles;

  const severitySeries = (data?.incident_severities || []).map((s) => ({
    key: s,
    label: s,
    color: SEVERITY[s] || seriesColor(mode, 0),
  }));

  return (
    <Box>
      <Card variant="outlined" sx={{ mb: 2 }}>
        <CardContent sx={{ display: 'flex', gap: 4, py: 2, pb: '16px !important', flexWrap: 'wrap' }}>
          <StatTile label="Robots" value={t ? `${t.hosts_reporting} / ${t.hosts_total}` : '—'} sub="reporting" minWidth={KPI_TILE_MIN_WIDTH} grow />
          <StatTile
            label="Devices"
            value={t ? `${t.devices_up} / ${t.devices_total}` : '—'}
            sub={t ? `up · ${t.devices_issue} with issues` : ''}
            color={t && t.devices_issue > 0 ? STATUS.warning : undefined}
            minWidth={KPI_TILE_MIN_WIDTH}
            grow
          />
          <StatTile label="Open incidents" value={t?.incidents_open ?? '—'} sub="unresolved" color={t && t.incidents_open > 0 ? STATUS.serious : undefined} minWidth={KPI_TILE_MIN_WIDTH} grow />
          <StatTile label="Active alerts" value={t?.alerts_active ?? '—'} sub="not yet resolved" color={t && t.alerts_active > 0 ? STATUS.critical : undefined} minWidth={KPI_TILE_MIN_WIDTH} grow />
          <StatTile label="Pass rate" value={pct(t?.pass_rate)} sub="last 30 days" minWidth={KPI_TILE_MIN_WIDTH} grow />
        </CardContent>
      </Card>

      <Row mb={0}>
        <ChartCard title="Fleet status" loading={loading} refreshing={refreshing} error={error} flex="0 0 320px" minHeight={180}>
          <Donut
            data={(['up', 'issue', 'down'] as const).map((k) => ({
              name: k === 'issue' ? 'service issue' : k,
              value: data?.device_counts?.[k] ?? 0,
            }))}
            colors={(row) => DEVICE_STATUS[row.name === 'service issue' ? 'issue' : row.name]}
            centerValue={t ? `${Math.round((t.devices_up / Math.max(t.devices_total, 1)) * 100)}%` : '—'}
            centerLabel="healthy"
            size={124}
          />
        </ChartCard>

        <ChartCard title="Incidents per day" subtitle="last 14 days" loading={loading} refreshing={refreshing} error={error} empty={!data?.incidents_timeline?.length} flex="1 1 380px" minHeight={180}>
          <StackedBar data={data?.incidents_timeline || []} xKey="day" series={severitySeries} height={168} />
        </ChartCard>

        <ChartCard title="Test runs per day" subtitle="pass vs fail" loading={loading} refreshing={refreshing} error={error} empty={!data?.kpi_timeline?.length} flex="1 1 380px" minHeight={180}>
          <StackedBar
            data={data?.kpi_timeline || []}
            xKey="day"
            series={[
              { key: 'failed', label: 'failed', color: OUTCOME.failed },
              { key: 'passed', label: 'passed', color: OUTCOME.passed },
            ]}
            height={168}
          />
        </ChartCard>
      </Row>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

const diskColor = (row: Ranked) =>
  row.value >= 90 ? STATUS.critical : row.value >= 80 ? STATUS.warning : undefined;

export const SystemPanel: React.FC = () => {
  const { data, loading, refreshing, error } = useAnalyticsSection<SystemSection>('system');
  const mode = useMode();
  const gate = { loading, refreshing, error };

  return (
    <Box>
      <Row>
        <ChartCard title="Disk usage" {...gate} flex="1 1 320px">
          <HBar data={data?.disk || []} color={(row) => diskColor(row) || seriesColor(mode, 0)} unit="%" max={100} labelWidth={96} />
        </ChartCard>
        <ChartCard title="Memory usage" {...gate} flex="1 1 320px">
          <HBar data={data?.memory || []} color={seriesColor(mode, 2)} unit="%" max={100} labelWidth={96} />
        </ChartCard>
        <ChartCard title="CPU load" {...gate} flex="1 1 320px">
          <HBar data={data?.cpu || []} color={seriesColor(mode, 1)} unit="%" max={100} labelWidth={96} />
        </ChartCard>
      </Row>

      <Row mb={0}>
        <ChartCard title="Devices per robot" {...gate} flex="1 1 300px">
          <HBar data={data?.devices_per_host || []} color={seriesColor(mode, 3)} labelWidth={110} />
        </ChartCard>
        <ChartCard title="Uptime" subtitle="days" {...gate} flex="1 1 300px">
          <HBar data={data?.uptime_days || []} color={seriesColor(mode, 2)} unit="d" labelWidth={110} decimals={1} />
        </ChartCard>
        <ChartCard title="Reachability" {...gate} flex="0 0 300px">
          <Donut
            data={asRanked(data?.reachability)}
            colors={(row) => REACHABILITY[row.name] || STATUS.warning}
            centerValue={data?.reachability?.reporting ?? '—'}
            centerLabel="reporting"
            size={116}
          />
        </ChartCard>
      </Row>

    </Box>
  );
};

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------

export const DevicesPanel: React.FC = () => {
  const { data, loading, refreshing, error } = useAnalyticsSection<DevicesSection>('devices');
  const mode = useMode();
  const gate = { loading, refreshing, error };

  const availabilityColor = (row: Ranked) =>
    row.value < 50 ? STATUS.critical : row.value < 98 ? STATUS.warning : STATUS.good;


  return (
    <Box>
      <Row>
        <ChartCard title="Fleet status" {...gate} flex="0 0 320px" minHeight={200}>
          <Donut
            data={(['up', 'issue', 'down'] as const).map((k) => ({
              name: k === 'issue' ? 'service issue' : k,
              value: data?.counts?.[k] ?? 0,
            }))}
            colors={(row) => DEVICE_STATUS[row.name === 'service issue' ? 'issue' : row.name]}
            centerValue={data ? `${data.counts.up} / ${data.total}` : '—'}
            centerLabel="up"
            size={130}
          />
        </ChartCard>

        <ChartCard
          title="Capture availability"
          subtitle={data?.availability_day ? `worst first · ${data.availability_day}` : 'worst first'}
          {...gate}
          empty={!data?.availability_worst?.length}
          flex="1 1 460px"
          minHeight={200}
        >
          <HBar data={bottomN(data?.availability_worst || [], 10)} color={availabilityColor} unit="%" max={100} labelWidth={150} decimals={1} />
        </ChartCard>
      </Row>

      <Row mb={0}>
        <ChartCard title="Devices by model" {...gate} flex="1 1 300px">
          <HBar data={topN(data?.by_model || [], 10)} color={seriesColor(mode, 0)} labelWidth={130} />
        </ChartCard>
        <ChartCard title="Fleet availability over time" subtitle="last 30 days" {...gate} empty={!data?.availability_timeline?.length} flex="1 1 460px">
          <StackedBar
            data={data?.availability_timeline || []}
            xKey="day"
            series={[{ key: 'availability_percent', label: 'availability %', color: STATUS.good }]}
            height={180}
          />
        </ChartCard>
      </Row>

    </Box>
  );
};

// ---------------------------------------------------------------------------
// KPI
// ---------------------------------------------------------------------------

export const KpiPanel: React.FC = () => {
  const { data, loading, refreshing, error } = useAnalyticsSection<KpiSection>('kpi');
  const mode = useMode();
  const gate = { loading, refreshing, error };
  const envNames = Object.keys(data?.by_environment || {});

  return (
    <Box>
      <Row>
        <ChartCard title="Runs per day" subtitle="last 30 days" {...gate} empty={!data?.timeline?.length} flex="1 1 520px" minHeight={210}>
          <StackedBar
            data={data?.timeline || []}
            xKey="day"
            series={[
              { key: 'failed', label: 'failed', color: OUTCOME.failed },
              { key: 'passed', label: 'passed', color: OUTCOME.passed },
            ]}
            height={198}
          />
        </ChartCard>

        <ChartCard title="Pass rate" subtitle="last 30 days" {...gate} flex="0 0 260px" minHeight={210}>
          <Box sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', height: '100%' }}>
            <Typography variant="h3" sx={{ fontWeight: 600, lineHeight: 1 }}>
              {pct(data?.pass_rate)}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
              {data ? `${data.passed.toLocaleString()} of ${data.total_runs.toLocaleString()} runs` : ''}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2 }}>
              {data ? `${data.failed.toLocaleString()} failed` : ''}
            </Typography>
          </Box>
        </ChartCard>
      </Row>

      <Row mb={0}>
        <ChartCard title="Busiest scripts" subtitle="top 10 by run count" {...gate} empty={!data?.by_script?.length} flex="1 1 520px">
          <HBar data={data?.by_script || []} color={seriesColor(mode, 0)} labelWidth={170} />
        </ChartCard>
        <ChartCard title="Runs by environment" {...gate} flex="0 0 300px">
          <Donut
            data={asRanked(data?.by_environment)}
            colors={colorForNames(mode, envNames)}
            centerValue={data?.total_runs?.toLocaleString() ?? '—'}
            centerLabel="runs"
            size={116}
          />
        </ChartCard>
      </Row>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Incidents
// ---------------------------------------------------------------------------

export const IncidentsPanel: React.FC = () => {
  const { data, loading, refreshing, error } = useAnalyticsSection<IncidentsSection>('incidents');
  const mode = useMode();
  const gate = { loading, refreshing, error };

  const severitySeries = (data?.severities || []).map((s) => ({
    key: s,
    label: s,
    color: SEVERITY[s] || seriesColor(mode, 0),
  }));

  return (
    <Box>
      <Row>
        <ChartCard title="Incidents per day" subtitle="by severity, last 30 days" {...gate} empty={!data?.timeline?.length} flex="1 1 520px" minHeight={210}>
          <StackedBar data={data?.timeline || []} xKey="day" series={severitySeries} height={198} />
        </ChartCard>
        <ChartCard title="By severity" {...gate} flex="0 0 300px" minHeight={210}>
          <Donut
            data={asRanked(data?.by_severity)}
            colors={(row) => SEVERITY[row.name] || seriesColor(mode, 0)}
            centerValue={data?.total?.toLocaleString() ?? '—'}
            centerLabel="total"
            size={120}
          />
        </ChartCard>
      </Row>

      <Row mb={0}>
        <ChartCard title="Noisiest devices" subtitle="top 10" {...gate} empty={!data?.by_device?.length} flex="1 1 420px">
          <HBar data={data?.by_device || []} color={STATUS.serious} labelWidth={150} />
        </ChartCard>
        <ChartCard title="By component" {...gate} flex="1 1 260px">
          <HBar data={asRanked(data?.by_component)} color={seriesColor(mode, 1)} labelWidth={80} />
        </ChartCard>
        <ChartCard title="Mean time to resolve" {...gate} flex="0 0 220px">
          <Box sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', height: '100%' }}>
            <Typography variant="h4" sx={{ fontWeight: 600, lineHeight: 1 }}>
              {data?.mttr_minutes ?? '—'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              minutes, 30-day average
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 600, mt: 2, color: STATUS.serious, lineHeight: 1 }}>
              {data?.open ?? '—'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              still open
            </Typography>
          </Box>
        </ChartCard>
      </Row>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export const AlertsPanel: React.FC = () => {
  const { data, loading, refreshing, error } = useAnalyticsSection<AlertsSection>('alerts');
  const mode = useMode();
  const gate = { loading, refreshing, error };

  const typeColors = colorForNames(mode, data?.types || []);
  const typeSeries = (data?.types || []).map((t) => ({
    key: t,
    label: t.replace('_', ' '),
    color: typeColors[t],
  }));

  const review = data?.review;

  return (
    <Box>
      <Row>
        <ChartCard title="Alerts per day" subtitle="by type, last 30 days" {...gate} empty={!data?.timeline?.length} flex="1 1 520px" minHeight={210}>
          <StackedBar data={data?.timeline || []} xKey="day" series={typeSeries} height={198} />
        </ChartCard>
        <ChartCard title="By type" {...gate} flex="0 0 300px" minHeight={210}>
          <Donut
            data={asRanked(data?.by_type)}
            colors={typeColors}
            centerValue={data?.total?.toLocaleString() ?? '—'}
            centerLabel="total"
            size={120}
          />
        </ChartCard>
      </Row>

      <Row mb={0}>
        <ChartCard title="Alerts per device" subtitle="top 10" {...gate} empty={!data?.by_device?.length} flex="1 1 460px">
          <HBar data={data?.by_device || []} color={seriesColor(mode, 0)} labelWidth={150} />
        </ChartCard>

        {/* Three numbers, not a bar chart: today this reads 1017 / 0 / 0, and a chart
            of that is a single bar. */}
        <ChartCard title="Review state" {...gate} flex="1 1 320px">
          <Box sx={{ display: 'flex', gap: 4, alignItems: 'flex-start' }}>
            <StatTile label="Unreviewed" value={review?.unreviewed?.toLocaleString() ?? '—'} color={review && review.unreviewed > 0 ? STATUS.warning : undefined} minWidth={90} />
            <StatTile label="Checked" value={review?.checked?.toLocaleString() ?? '—'} minWidth={80} />
            <StatTile label="Discarded" value={review?.discarded?.toLocaleString() ?? '—'} minWidth={80} />
          </Box>
        </ChartCard>
      </Row>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Project — no database at all
// ---------------------------------------------------------------------------

export const ProjectPanel: React.FC = () => {
  const { data, loading, missing, error } = useProjectMetrics();
  const mode = useMode();
  const gate = {
    loading,
    error: error || (missing ? 'Not generated yet — run scripts/docs/build_project_metrics.py' : null),
  };

  const releases = data?.releases || [];
  // The axis only has room for the build number; the tooltip carries the full name
  // the footer shows, so a bar can be matched to the build someone is running.
  const releaseLabel = (build: string) => {
    const r = releases.find((x) => x.build === build);
    return r ? `${r.name}${r.unreleased ? ' (unreleased)' : ''}` : build;
  };
  const openBugs = data?.bugs?.open || [];
  const severityOrder = ['Critical', 'High', 'Medium', 'Low', 'Unspecified'];
  const bugsBySeverity = severityOrder
    .filter((s) => data?.bugs?.by_severity?.[s])
    .map((s) => ({ name: s, value: data!.bugs.by_severity[s] }));

  return (
    <Box>
      <Row>
        <ChartCard
          title="Code size by area"
          subtitle={data ? `${data.loc.total.toLocaleString()} lines in ${data.loc.files.toLocaleString()} source files` : undefined}
          {...gate}
          empty={!data?.loc?.by_area?.length}
          flex="1 1 560px"
          minHeight={250}
        >
          <CodeTreemap data={data?.loc?.by_area || []} colors={categorical(mode)} height={246} />
        </ChartCard>

        <ChartCard
          title="Shipped per build"
          subtitle={data?.build_name ? `features vs bug fixes · running ${data.build_name}` : 'features vs bug fixes'}
          {...gate} empty={!releases.length} flex="1 1 380px" minHeight={250}>
          <StackedBar
            data={releases}
            xKey="build"
            series={[
              { key: 'fixes', label: 'bug fixes', color: seriesColor(mode, 1) },
              { key: 'features', label: 'features', color: seriesColor(mode, 0) },
            ]}
            height={238}
            shortenDates={false}
            tooltipLabel={releaseLabel}
          />
        </ChartCard>
      </Row>

      <Row>
        <ChartCard title="Bug reports by severity" subtitle={data ? `${data.bugs.total} total` : undefined} {...gate} empty={!bugsBySeverity.length} flex="1 1 320px">
          <HBar
            data={bugsBySeverity}
            color={(row) => SEVERITY[row.name.toLowerCase()] || seriesColor(mode, 0)}
            labelWidth={90}
          />
        </ChartCard>

        <ChartCard title="Bugs fixed per release" {...gate} empty={!releases.length} flex="1 1 320px">
          <HBar
            data={releases.map((r) => ({ name: releaseLabel(r.build), value: r.bugs_fixed })).sort((a, b) => b.value - a.value)}
            color={seriesColor(mode, 1)}
            labelWidth={210}
          />
        </ChartCard>

        <ChartCard title="Bug status" {...gate} flex="0 0 280px">
          <Donut
            data={asRanked(data?.bugs?.by_status)}
            colors={colorForNames(mode, Object.keys(data?.bugs?.by_status || {}))}
            centerValue={data?.bugs?.total ?? '—'}
            centerLabel="reports"
            size={116}
          />
        </ChartCard>
      </Row>

      <Row mb={0}>
        <ChartCard title="Open bugs" subtitle={`${openBugs.length} open or in progress`} {...gate} empty={!openBugs.length} flex="1 1 100%">
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75, width: '100%' }}>
            {openBugs.map((b) => (
              <Box key={b.id} sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5, minWidth: 0 }}>
                <Link component={RouterLink} to={b.doc} underline="hover" sx={{ fontSize: '0.75rem', fontWeight: 600, flexShrink: 0 }}>
                  {b.id}
                </Link>
                <Typography
                  variant="caption"
                  title={b.title}
                  sx={{ flexGrow: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {b.title}
                </Typography>
                <Typography variant="caption" sx={{ flexShrink: 0, color: SEVERITY[b.severity.toLowerCase()] || 'text.secondary' }}>
                  {b.severity}
                </Typography>
                <Typography variant="caption" sx={{ flexShrink: 0, width: 72, color: 'text.secondary' }}>
                  {b.status}
                </Typography>
              </Box>
            ))}
          </Box>
        </ChartCard>
      </Row>
    </Box>
  );
};
