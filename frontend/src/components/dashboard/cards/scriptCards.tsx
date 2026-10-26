import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';
import { useI18n } from '../../../i18n/useI18n';
import { rateColor } from '../../common/PageChrome';
import { StatusDot } from '../../common/StatusDot';
import { DASH_CHART_BODY, Meter, NoData, RowLink, StatLink } from '../DashCard';
import { formatAgo, formatWhen, pct } from '../dashboardFormat';
import { ALL_ROLES, type CardBodyProps, type CardDefinition } from '../dashboardLayout';
import { DASH_LINKS } from '../dashboardLinks';
import { PagedList } from '../PagedList';
import { TrendChart } from '../TrendChart';

const RunningBody: React.FC<CardBodyProps> = ({ data, now }) => {
  const { t } = useI18n();
  return (
    <PagedList
      rows={data.summary!.running.items}
      getKey={(r) => r.result_id}
      renderRow={(r) => (
        <RowLink
          to={DASH_LINKS.report(r.result_id)}
          lead={<StatusDot tone="muted" />}
          name={r.script_name}
          detail={`${r.device_id} · ${formatAgo(r.started_at, now, t)}`}
          mono
        />
      )}
    />
  );
};

const ResultsBody: React.FC<CardBodyProps> = ({ data, range }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const r = data.summary!.results;
  if (r.total === 0) return <NoData />;
  const rate = pct(r.passed, r.total);
  return (
    <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', gap: 2, minWidth: 0 }}>
      <StatLink to={DASH_LINKS.reports({ status: 'passed', range })} value={r.passed} label={t('passed')} color={P.success} big />
      <StatLink to={DASH_LINKS.reports({ status: 'failed', range })} value={r.failed} label={t('failed')} color={r.failed > 0 ? P.error : undefined} big />
      <StatLink to={DASH_LINKS.reports({ status: 'aborted', range })} value={r.aborted} label={t('aborted')} big />
      <Box sx={{ flex: 1, minWidth: 40 }}>
        <Meter pct={rate} color={rateColor(rate, P)} />
      </Box>
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{rate} %</Typography>
    </Box>
  );
};

const TrendBody: React.FC<CardBodyProps> = ({ data, range }) => {
  const { trend, total } = data.summary!.results;
  // With fewer than two points there is no trend to draw: a centred dash, not axes with a lone dot.
  if (total === 0 || trend.filter((b) => b.total > 0).length < 2) return <NoData />;
  return <TrendChart trend={trend} range={range} />;
};

const FailingBody: React.FC<CardBodyProps> = ({ data, now }) => {
  const { t } = useI18n();
  return (
    <PagedList
      rows={data.summary!.failing}
      getKey={(r) => r.script_name}
      renderRow={(r) => (
        <RowLink
          to={DASH_LINKS.report(r.last_result_id)}
          lead={<StatusDot tone={r.last_verdict === 'failed' ? 'error' : 'success'} />}
          name={r.script_name}
          detail={[t('{failed} of {runs} failed', { failed: r.failed, runs: r.runs }), formatAgo(r.last_at, now, t)].filter(Boolean).join(' · ')}
          mono
        />
      )}
    />
  );
};

const FlakyBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  return (
    <PagedList
      rows={data.summary!.flaky}
      getKey={(r) => r.script_name}
      renderRow={(r) => (
        <RowLink
          to={DASH_LINKS.flaky()}
          lead={<StatusDot tone="warning" />}
          name={r.script_name}
          detail={t('{failed} of {runs} failed', { failed: r.failed, runs: r.runs })}
          mono
        />
      )}
    />
  );
};

const DeploymentsBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  return (
    <PagedList
      rows={data.summary!.deployments.items}
      getKey={(r) => r.name}
      renderRow={(r) => (
        <RowLink
          to={DASH_LINKS.deployments}
          lead={<StatusDot tone={r.state === 'active' ? 'success' : 'muted'} />}
          name={r.name}
          detail={[r.state, r.next_run_at ? t('next {when}', { when: formatWhen(r.next_run_at) }) : ''].filter(Boolean).join(' · ')}
        />
      )}
    />
  );
};

const RUNNERS: CardDefinition['roles'] = ['admin', 'manager', 'developer', 'tester'];

const card = (
  id: string,
  titleKey: string,
  descriptionKey: string,
  roles: CardDefinition['roles'],
  tabs: CardDefinition['tabs'],
  layout: CardDefinition['layout'],
  href: string,
  Component: CardDefinition['Component'],
): CardDefinition => ({ id, titleKey, descriptionKey, roles, tabs, layout, source: 'summary', href, Component });

/** Order = screen order. Scripts: results band, trend + failing scripts, then running / flaky / deployments. */
export const scriptCards: CardDefinition[] = [
  card('results', 'Results', 'Passed, failed and aborted runs in the chosen period', ALL_ROLES, ['scripts'], 'band', DASH_LINKS.reports(), ResultsBody),
  { ...card('trend', 'Trend', 'How the pass rate moved over the chosen period', ALL_ROLES, ['overview', 'scripts'], 'half', DASH_LINKS.reports(), TrendBody), bodyHeight: DASH_CHART_BODY },
  card('failing', 'Failing scripts', 'Scripts with failed runs, one row per script with fails, runs and the last run', RUNNERS, ['scripts'], 'half', DASH_LINKS.reports({ status: 'failed' }), FailingBody),
  card('running', 'Running', 'The runs in progress', ALL_ROLES, ['scripts'], 'third', DASH_LINKS.running, RunningBody),
  card('flaky', 'Flaky', 'Scripts with mixed verdicts over their last runs', ['admin', 'manager', 'developer'], ['scripts'], 'third', DASH_LINKS.flaky(), FlakyBody),
  card('deployments', 'Deployments', 'Scheduled and running deployments with their next run', RUNNERS, ['scripts'], 'third', DASH_LINKS.deployments, DeploymentsBody),
];
