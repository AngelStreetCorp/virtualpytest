import { Box, Typography } from '@mui/material';
import React, { useContext } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { createPortal } from 'react-dom';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';
import { useI18n } from '../../../i18n/useI18n';
import { fmtCost } from '../../aiUsage/format';
import { StatusDot, type StatusDotTone } from '../../common/StatusDot';
import { CardHeaderSlot, KpiTile, Meter, NEW_TAB, NoData, RowLink, StatLink } from '../DashCard';
import type { CardBodyProps, CardDefinition } from '../dashboardLayout';
import type { VmRow, VmStatus } from '../dashboardTypes';
import { DASH_LINKS } from '../dashboardLinks';
import { PAGED_LIST_ROW_HEIGHT, PagedList } from '../PagedList';

/** Fill level tone: 80 % and up warns, 90 % and up is an error. Always printed next to the bar with a word. */
export const levelTone = (value: number): StatusDotTone => (value >= 90 ? 'error' : value >= 80 ? 'warning' : 'success');

const LevelRow: React.FC<{ label: string; value: number }> = ({ label, value }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const tone = levelTone(value);
  const color = tone === 'error' ? P.error : tone === 'warning' ? P.warning : P.success;
  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: TYPOGRAPHY.caption.size }}>
        <span>{label}</span>
        <StatusDot tone={tone} word={`${Math.round(value)} % ${tone === 'error' ? t('critical') : tone === 'warning' ? t('high') : t('ok')}`} />
      </Box>
      <Meter pct={value} color={color} />
    </Box>
  );
};

const StorageBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const s = data.system!.storage;
  if (!s) return <NoData text={t('No data')} />;
  return (
    <>
      <LevelRow label={t('Disk')} value={s.disk_pct} />
      <LevelRow label={t('Inodes')} value={s.inode_pct} />
    </>
  );
};

const MonitoringBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const m = data.system!.monitoring;
  const P = useAgentChatPalette();
  const slot = useContext(CardHeaderSlot);
  if (!m) return <NoData text={t('No data')} />;
  const ratio = (
    <StatLink to={DASH_LINKS.status} value={`${m.hosts_ok} / ${m.hosts_total}`} color={m.problems.length > 0 ? P.warning : undefined} />
  );
  return (
    <>
      {slot && createPortal(ratio, slot)}
      <PagedList
        rows={m.problems}
        getKey={(r) => r.host_name}
        renderRow={(r) => <RowLink to={DASH_LINKS.status} lead={<StatusDot tone="error" />} name={r.host_name} detail={r.detail} mono />}
      />
    </>
  );
};

const metricColor = (value: number | null, P: ReturnType<typeof useAgentChatPalette>): string | undefined => {
  if (value === null) return undefined;
  const tone = levelTone(value);
  return tone === 'error' ? P.error : tone === 'warning' ? P.warning : undefined;
};

const VM_COLUMNS = 'minmax(0, 1.4fr) 84px repeat(4, minmax(0, 1fr))';
const VM_TONE: Record<VmStatus, StatusDotTone> = { ok: 'success', warning: 'warning', error: 'error', stale: 'muted' };

/** One compact table of every machine: status dot + word, CPU, load, RAM, disk. Same sources as the /status VM summary. */
const VmsBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const vms = data.system!.vms;
  if (!vms || vms.length === 0) return <NoData text={t('No data')} />;
  const word: Record<VmStatus, string> = { ok: t('ok'), warning: t('high'), error: t('critical'), stale: t('stale') };
  const num = (v: number | null, unit = ' %') => (v === null ? '—' : `${Math.round(v * 10) / 10}${unit}`);
  const right = { fontSize: TYPOGRAPHY.caption.size, textAlign: 'right' as const };
  const head = { ...right, fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted };
  return (
    <Box data-testid="vm-table" sx={{ flex: 1, minHeight: 0 }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: VM_COLUMNS, height: PAGED_LIST_ROW_HEIGHT, alignItems: 'center' }}>
        <Typography sx={{ ...head, textAlign: 'left' }}>{t('Machine')}</Typography>
        <Typography sx={{ ...head, textAlign: 'left' }}>{t('Status')}</Typography>
        <Typography sx={head}>{t('CPU')}</Typography>
        <Typography sx={head}>{t('Load')}</Typography>
        <Typography sx={head}>{t('RAM')}</Typography>
        <Typography sx={head}>{t('Disk')}</Typography>
      </Box>
      {vms.map((vm) => (
        <Box
          key={vm.id}
          component={RouterLink}
          to={DASH_LINKS.status}
          {...NEW_TAB}
          data-testid={`vm-row-${vm.id}`}
          sx={{ display: 'grid', gridTemplateColumns: VM_COLUMNS, height: PAGED_LIST_ROW_HEIGHT, alignItems: 'center', borderTop: `1px solid ${P.borderColor}`, color: P.textPrimary, textDecoration: 'none', '&:hover': { color: P.accentText } }}
        >
          <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size }}>{vm.name}</Typography>
          <StatusDot tone={VM_TONE[vm.status]} word={word[vm.status]} />
          <Typography sx={{ ...right, color: metricColor(vm.cpu, P) }}>{num(vm.cpu)}</Typography>
          <Typography sx={right}>{num(vm.load1, '')}</Typography>
          <Typography sx={{ ...right, color: metricColor(vm.ram, P) }}>{num(vm.ram)}</Typography>
          <Typography sx={{ ...right, color: metricColor(vm.disk, P) }}>{num(vm.disk)}</Typography>
        </Box>
      ))}
    </Box>
  );
};

const sysTile = (id: string, titleKey: string, descriptionKey: string, icon: CardDefinition['icon'], Component: CardDefinition['Component']): CardDefinition => ({
  id,
  titleKey,
  descriptionKey,
  roles: ['admin'],
  tabs: ['system'],
  layout: 'tile',
  icon,
  source: 'system',
  href: DASH_LINKS.status,
  Component,
});

const ServicesTile: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const s = data.system!.services;
  return (
    <KpiTile
      testId="dash-card-sys-services"
      to={DASH_LINKS.status}
      icon="success"
      label={t('Platform services healthy')}
      value={s ? `${s.ok} / ${s.total}` : '—'}
      color={s && s.ok < s.total ? P.warning : undefined}
    />
  );
};

const serverMetricTile = (id: string, labelKey: 'CPU' | 'RAM' | 'Disk', icon: CardDefinition['icon'], pick: (v: VmRow) => number | null): CardDefinition['Component'] => {
  const Tile: React.FC<CardBodyProps> = ({ data }) => {
    const { t } = useI18n();
    const P = useAgentChatPalette();
    const server = data.system!.vms?.find((v) => v.id === 'server');
    const value = server ? pick(server) : null;
    const tone = value === null ? null : levelTone(value);
    return (
      <KpiTile
        testId={`dash-card-${id}`}
        to={DASH_LINKS.status}
        icon={icon ?? 'info'}
        label={t('Server {metric}', { metric: t(labelKey) })}
        value={value === null ? '—' : `${Math.round(value)} %`}
        color={metricColor(value, P)}
        sub={tone === 'error' ? t('critical') : tone === 'warning' ? t('high') : undefined}
      />
    );
  };
  return Tile;
};

const AiUsageBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const ai = data.system!.ai_usage;
  if (!ai) return <NoData text={t('No data')} />;
  return (
    <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
      {/* fmtCost, not a bare formatNumber: a bare one prints three decimals
          ($22.039), which a German reader reads as twenty-two thousand. */}
      <StatLink to={DASH_LINKS.aiUsage} value={fmtCost(ai.cost_7d) ?? '—'} label={t('7 d')} big />
      {ai.top_model && <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{ai.top_model}</Typography>}
    </Box>
  );
};

const sys = (id: string, titleKey: string, descriptionKey: string, layout: CardDefinition['layout'], href: string, Component: CardDefinition['Component'], extra: Partial<CardDefinition> = {}): CardDefinition => ({
  id,
  titleKey,
  descriptionKey,
  roles: ['admin'],
  tabs: ['system'],
  layout,
  source: 'system',
  href,
  Component,
  ...extra,
});

/** System: four tiles, the VMs table, then three thirds. */
export const systemCards: CardDefinition[] = [
  sysTile('sys-services', 'Platform services healthy', 'Healthy components out of all the platform reports', 'success', ServicesTile),
  sysTile('sys-cpu', 'Server CPU', 'CPU use of the backend server', 'fast', serverMetricTile('sys-cpu', 'CPU', 'fast', (v) => v.cpu)),
  sysTile('sys-ram', 'Server RAM', 'Memory use of the backend server', 'storage', serverMetricTile('sys-ram', 'RAM', 'storage', (v) => v.ram)),
  sysTile('sys-disk', 'Server disk', 'Disk use of the backend server', 'folder', serverMetricTile('sys-disk', 'Disk', 'folder', (v) => v.disk)),
  sys('vms', 'VMs', 'Every machine with its status, CPU, load, RAM and disk', 'table', DASH_LINKS.status, VmsBody, {
    tableRows: (data) => data.system?.vms?.length ?? 0,
  }),
  sys('storage', 'Storage', 'Disk and inode use of the storage', 'third', DASH_LINKS.status, StorageBody),
  sys('monitoring', 'Monitoring', 'Hosts whose monitoring is healthy', 'third', DASH_LINKS.status, MonitoringBody),
  sys('ai-usage', 'AI usage', 'Spend and top model of the last 7 days', 'third', DASH_LINKS.aiUsage, AiUsageBody),
];
