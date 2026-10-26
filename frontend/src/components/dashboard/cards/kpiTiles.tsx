import React from 'react';

import { useI18n } from '../../../i18n/useI18n';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { rateColor } from '../../common/PageChrome';
import { KpiTile } from '../DashCard';
import { pct } from '../dashboardFormat';
import { ALL_ROLES, type CardBodyProps, type CardDefinition } from '../dashboardLayout';
import { DASH_LINKS } from '../dashboardLinks';

/** Pass rate per bucket that had runs: the tile's sparkline. */
export const passRateSeries = (trend: Array<{ total: number; passed: number }>): number[] =>
  trend.filter((b) => b.total > 0).map((b) => pct(b.passed, b.total));

const PassRateTile: React.FC<CardBodyProps> = ({ data, range }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const r = data.summary!.results;
  const rate = pct(r.passed, r.total);
  return (
    <KpiTile
      testId="dash-card-kpi-pass"
      to={DASH_LINKS.reports({ range })}
      icon="report"
      label={t('Pass rate')}
      value={r.total > 0 ? `${rate} %` : '—'}
      color={r.total > 0 ? rateColor(rate, P) : undefined}
      spark={passRateSeries(r.trend)}
    />
  );
};

const RunningTile: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const { count, queued } = data.summary!.running;
  return (
    <KpiTile
      testId="dash-card-kpi-running"
      to={DASH_LINKS.running}
      icon="running"
      label={t('Running now')}
      value={count}
      sub={queued > 0 ? t('{n} queued', { n: queued }) : undefined}
    />
  );
};

const DevicesUpTile: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const d = data.summary!.devices;
  return (
    <KpiTile
      testId="dash-card-kpi-devices"
      to={DASH_LINKS.devices}
      icon="device"
      label={t('Devices up')}
      value={d.total > 0 ? `${d.total - d.down} / ${d.total}` : '—'}
      color={d.down > 0 ? P.warning : undefined}
      sub={d.down > 0 ? t('{n} down', { n: d.down }) : undefined}
    />
  );
};

const FailuresTile: React.FC<CardBodyProps> = ({ data, range }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const failed = data.summary!.results.failed;
  return (
    <KpiTile
      testId="dash-card-kpi-failures"
      to={DASH_LINKS.reports({ status: 'failed', range })}
      icon="error"
      label={t('Failures')}
      value={failed}
      color={failed > 0 ? P.error : undefined}
    />
  );
};

const tile = (id: string, titleKey: string, descriptionKey: string, icon: CardDefinition['icon'], href: string, Component: CardDefinition['Component']): CardDefinition => ({
  id,
  titleKey,
  descriptionKey,
  roles: ALL_ROLES,
  tabs: ['overview'],
  layout: 'tile',
  icon,
  source: 'summary',
  href,
  Component,
});

/** The quarter-width KPI row at the top of Overview. Listed first in the registry so it sits on top. */
export const kpiTiles: CardDefinition[] = [
  tile('kpi-pass', 'Pass rate', 'Pass rate of the chosen period with its trend', 'report', DASH_LINKS.reports(), PassRateTile),
  tile('kpi-running', 'Running now', 'Scripts running at this moment', 'running', DASH_LINKS.running, RunningTile),
  tile('kpi-devices', 'Devices up', 'Devices that are not down, out of all devices', 'device', DASH_LINKS.devices, DevicesUpTile),
  tile('kpi-failures', 'Failures', 'Failed runs in the chosen period', 'error', DASH_LINKS.reports({ status: 'failed' }), FailuresTile),
];
