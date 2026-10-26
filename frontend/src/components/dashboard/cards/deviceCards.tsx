import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';
import { useI18n } from '../../../i18n/useI18n';
import { StatusDot } from '../../common/StatusDot';
import { Meter, NoData, RowLink, StatLink } from '../DashCard';
import { buildDeviceAttention } from '../dashboardAttention';
import { pct } from '../dashboardFormat';
import { ALL_ROLES, type CardBodyProps, type CardDefinition } from '../dashboardLayout';
import { DASH_LINKS } from '../dashboardLinks';
import { PagedList } from '../PagedList';
import { AllClear } from './overviewCards';

const DevicesBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const d = data.summary!.devices;
  if (d.total === 0) return <NoData />;
  const up = pct(d.total - d.down, d.total);
  return (
    <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', gap: 2, minWidth: 0 }}>
      <StatLink to={DASH_LINKS.devices} value={d.free} label={t('free')} big />
      <StatLink to={DASH_LINKS.devices} value={d.locked} label={t('locked')} big />
      <StatLink to={DASH_LINKS.devices} value={d.down} label={t('down')} color={d.down > 0 ? P.error : undefined} big />
      <Box sx={{ flex: 1, minWidth: 40 }}>
        <Meter pct={up} color={d.down > 0 ? P.warning : P.success} />
      </Box>
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{d.total - d.down} / {d.total}</Typography>
    </Box>
  );
};

const DeviceAttentionBody: React.FC<CardBodyProps> = ({ data, now }) => {
  const { t } = useI18n();
  const items = buildDeviceAttention(data.summary!, now, t);
  if (items.length === 0) return <AllClear />;
  return (
    <PagedList
      rows={items}
      getKey={(r) => r.id}
      renderRow={(r) => <RowLink to={r.to} lead={<StatusDot tone={r.tone} />} name={r.name} detail={r.detail} mono />}
    />
  );
};

/** Per-host rows: host with its state dot, devices up of total, locked count. Each row opens the device page. */
const HostsBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  return (
    <PagedList
      rows={data.summary!.devices.hosts}
      getKey={(h) => h.host_name}
      renderRow={(h) => (
        <RowLink
          to={DASH_LINKS.host(h.host_name)}
          lead={<StatusDot tone={h.down > 0 ? 'error' : 'success'} />}
          name={h.host_name}
          detail={[`${h.total - h.down} / ${h.total} ${t('up')}`, h.locked > 0 ? `${h.locked} ${t('locked')}` : ''].filter(Boolean).join(' · ')}
          mono
        />
      )}
    />
  );
};

const devCard = (
  id: string,
  titleKey: string,
  descriptionKey: string,
  roles: CardDefinition['roles'],
  layout: CardDefinition['layout'],
  Component: CardDefinition['Component'],
  extra: Partial<CardDefinition> = {},
): CardDefinition => ({ id, titleKey, descriptionKey, roles, tabs: ['devices'], layout, source: 'summary', href: DASH_LINKS.devices, Component, ...extra });

/** Devices tab: summary band, then down / locked devices beside the per-host rows. */
export const deviceCards: CardDefinition[] = [
  devCard('devices', 'Devices', 'Free, locked and down devices with the share that is up', ALL_ROLES, 'band', DevicesBody),
  devCard('device-attention', 'Down and locked', 'Devices that are down and who holds a lock, for how long', ALL_ROLES, 'half', DeviceAttentionBody),
  devCard('hosts-table', 'Hosts', 'Devices up and locked, per host', ALL_ROLES, 'half', HostsBody),
];
