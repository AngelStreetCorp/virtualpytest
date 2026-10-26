import { Box } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { AppIcon } from '../../../constants/icons';
import { TYPOGRAPHY } from '../../../constants/typography';
import { useDeviceFavorites } from '../../../hooks/useDeviceFavorites';
import { useI18n } from '../../../i18n/useI18n';
import { StatusDot } from '../../common/StatusDot';
import { RowLink } from '../DashCard';
import { buildAttention } from '../dashboardAttention';
import { ALL_ROLES, type CardBodyProps, type CardDefinition } from '../dashboardLayout';
import { DASH_LINKS } from '../dashboardLinks';
import type { DashboardSummary } from '../dashboardTypes';
import { FavouriteChips, type FavouriteChip } from '../FavouriteChips';
import { PagedList } from '../PagedList';

/** "All clear": a check icon and two words, centred in the card. */
export const AllClear: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Box data-testid="all-clear" sx={{ alignSelf: 'center', display: 'inline-flex', alignItems: 'center', gap: 0.75, color: P.success, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>
      <AppIcon name="success" />
      <span>{t('All clear')}</span>
    </Box>
  );
};

const AttentionBody: React.FC<CardBodyProps> = ({ data }) => {
  const { t } = useI18n();
  const items = buildAttention(data, t);
  if (items.length === 0) return <AllClear />;
  return (
    <PagedList
      rows={items}
      getKey={(r) => r.id}
      renderRow={(r) => <RowLink to={r.to} lead={<StatusDot tone={r.tone} />} name={r.name} detail={r.detail} mono />}
    />
  );
};

/** A starred device's state from the summary: down (its host is offline), locked, or free. */
export const favouriteState = (summary: DashboardSummary, host: string, deviceId: string): 'down' | 'locked' | 'free' | null => {
  const hostRow = summary.devices.hosts.find((h) => h.host_name === host);
  if (!hostRow) return null;
  if (summary.devices.down_items.some((d) => d.host_name === host && d.device_id === deviceId)) return 'down';
  if (summary.devices.locked_items.some((d) => d.host_name === host && d.device_id === deviceId)) return 'locked';
  return 'free';
};

export const useFavouriteChips = (summary: DashboardSummary | null): FavouriteChip[] => {
  const { items } = useDeviceFavorites();
  const { t } = useI18n();
  if (!summary) return [];
  return items.flatMap((f) => {
    const state = favouriteState(summary, f.host_name, f.device_id);
    if (!state) return [];
    return [{
      key: `${f.host_name}/${f.device_id}`,
      label: `${f.device_id} · ${f.host_name}`,
      tone: state === 'down' ? 'error' : state === 'locked' ? 'warning' : 'success',
      word: state === 'down' ? t('down') : state === 'locked' ? t('locked') : t('free'),
      to: DASH_LINKS.device(f.host_name, f.device_id),
    } as FavouriteChip];
  });
};

const FavouritesBody: React.FC<CardBodyProps> = ({ data }) => {
  const chips = useFavouriteChips(data.summary);
  return (
    <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', minWidth: 0 }}>
      <FavouriteChips chips={chips} />
    </Box>
  );
};

/** The favourites card exists only for a user who has starred devices that are visible in the data. */
const useHasFavourites = (): boolean => useDeviceFavorites().count > 0;

export const overviewCards: CardDefinition[] = [
  {
    id: 'attention',
    titleKey: 'Needs attention',
    descriptionKey: 'Devices down, hosts and machines in trouble, scripts that keep failing: worst first',
    roles: ALL_ROLES,
    tabs: ['overview'],
    layout: 'half',
    source: 'summary',
    href: DASH_LINKS.reports({ status: 'failed' }),
    Component: AttentionBody,
  },
  {
    id: 'favourites',
    titleKey: 'My favourites',
    descriptionKey: 'Your starred devices with their state',
    roles: ALL_ROLES,
    tabs: ['overview'],
    layout: 'band',
    source: 'summary',
    href: DASH_LINKS.favourites,
    Component: FavouritesBody,
    useVisible: useHasFavourites,
  },
];
