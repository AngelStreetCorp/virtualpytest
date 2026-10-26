import {
  Close as ExitKioskIcon,
  Fullscreen as KioskIcon,
  Refresh as RefreshIcon,
  Settings as GearIcon,
  Star as StarIcon,
  StarBorder as StarBorderIcon,
} from '@mui/icons-material';
import { Box, IconButton, Tab, Tabs, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { DashboardCardGrid } from '../components/dashboard/DashboardCardGrid';
import { CustomizeDrawer } from '../components/dashboard/CustomizeDrawer';
import { CARD_REGISTRY } from '../components/dashboard/cards/registry';
import { useDashboardAlerts } from '../components/dashboard/dashboardAlerts';
import { useHostDiskFix } from '../components/dashboard/useHostDiskFix';
import { formatAgo } from '../components/dashboard/dashboardFormat';
import {
  allowedTabs,
  EMPTY_LAYOUT,
  normaliseLayout,
  resolveFavouriteTab,
  resolveTabCards,
  type DashTabId,
  type StoredLayout,
} from '../components/dashboard/dashboardLayout';
import { DASH_GRID_GAP } from '../components/dashboard/DashCard';
import { DashFilterSlot } from '../components/dashboard/dashboardSlots';
import { DASH_RANGES, type DashRange } from '../components/dashboard/dashboardTypes';
import HostsDevicesView from '../components/dashboard/HostsDevicesView';
import { useDashboardData } from '../components/dashboard/useDashboardData';
import { pageSurfaceSx, PageTitle, segmentedSx, toggleSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { STORAGE_KEYS } from '../config/constants';
import { FONT_SIZE_SCALE, TYPOGRAPHY } from '../constants/typography';
import { useAuthContext } from '../contexts/auth/AuthContext';
import { usePermissionContext } from '../contexts/auth/PermissionContext';
import { usePersistedState } from '../hooks/usePersistedState';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useI18n } from '../i18n/useI18n';
import type { Role } from '../types/auth';

export const KIOSK_ROTATE_MS = 30_000;

/** Wall-screen mode: no app chrome, tabs rotate every 30 s, Esc or the small exit button leaves. */
const useKiosk = () => {
  const [params, setParams] = useSearchParams();
  const kiosk = params.get('kiosk') === '1';
  const setKiosk = useCallback(
    (on: boolean) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (on) next.set('kiosk', '1');
          else next.delete('kiosk');
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return { kiosk, setKiosk };
};

const Dashboard: React.FC = () => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const { isMobile } = useResponsiveMode();
  const { role: profileRole, hasRole } = usePermissionContext();
  const { profile } = useAuthContext();
  const userId = profile?.id ?? 'anonymous';
  // Open mode (no auth configured) is effectively admin; a role still loading is the least privileged.
  const role: Role = hasRole('admin') ? 'admin' : (profileRole ?? 'viewer');

  const tabs = useMemo(() => allowedTabs(role), [role]);
  const [storedLayout, setLayout] = usePersistedState<StoredLayout>(`${STORAGE_KEYS.DASHBOARD_LAYOUT}_${userId}`, EMPTY_LAYOUT);
  const layout = useMemo(() => normaliseLayout(storedLayout), [storedLayout]);
  const [storedRange, setRange] = usePersistedState<DashRange>(`${STORAGE_KEYS.DASHBOARD_LAYOUT}_range`, '24h');
  const range: DashRange = DASH_RANGES.includes(storedRange) ? storedRange : '24h';

  const favouriteTab = resolveFavouriteTab(role, layout.favouriteTab);
  const [selectedTab, setSelectedTab] = useState<DashTabId | null>(null);
  const { kiosk, setKiosk } = useKiosk();
  const [kioskIndex, setKioskIndex] = useState(0);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [filterSlot, setFilterSlot] = useState<HTMLElement | null>(null);

  const picked = selectedTab && tabs.some((tab) => tab.id === selectedTab) ? selectedTab : favouriteTab;
  const activeTab: DashTabId = kiosk ? tabs[kioskIndex % tabs.length].id : picked;

  const { data, generatedAt, refresh } = useDashboardData(range, role === 'admin');
  const diskFix = useHostDiskFix(refresh);
  useDashboardAlerts(data, diskFix.request);

  // "Updated 12 s ago" and every relative time on the cards share one clock.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(id);
  }, []);

  // Kiosk: rotate through the visible tabs and refresh the data on each rotation.
  useEffect(() => {
    if (!kiosk) return;
    setKioskIndex(Math.max(0, tabs.findIndex((tab) => tab.id === picked)));
    const id = window.setInterval(() => {
      setKioskIndex((i) => (i + 1) % tabs.length);
      refresh();
    }, KIOSK_ROTATE_MS);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setKiosk(false);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('keydown', onKey);
    };
    // Restart the rotation only when kiosk is switched on or the visible tabs change.
  }, [kiosk, tabs.length, refresh, setKiosk]);

  const overrides = layout.tabs[activeTab];
  const resolved = useMemo(() => resolveTabCards(activeTab, role, CARD_REGISTRY, overrides), [activeTab, role, overrides]);

  const setTabOverride = (id: string, patch: { on?: boolean }) =>
    setLayout((prev) => ({
      ...prev,
      tabs: { ...prev.tabs, [activeTab]: { ...prev.tabs[activeTab], [id]: { ...prev.tabs[activeTab]?.[id], ...patch } } },
    }));
  const resetTab = () => setLayout((prev) => ({ ...prev, tabs: { ...prev.tabs, [activeTab]: undefined } }));

  const tabTitle = (id: DashTabId) => t(tabs.find((tab) => tab.id === id)?.titleKey ?? '');
  const isCardTab = activeTab !== 'hosts';
  const showsRange = activeTab === 'overview' || activeTab === 'scripts';
  const updatedAgo = generatedAt ? formatAgo(new Date(generatedAt).toISOString(), now, t) : '';

  const headerActions = (
    <>
      <Typography data-testid="dash-updated" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, minWidth: 90, textAlign: 'right' }}>
        {updatedAgo ? t('Updated {ago} ago', { ago: updatedAgo }) : ''}
      </Typography>
      <Tooltip title={t('Refresh')}>
        <IconButton size="small" aria-label={t('Refresh')} onClick={refresh} sx={toggleSx(P, false)}>
          <RefreshIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title={t('Full-screen display')}>
        <IconButton size="small" aria-label={t('Full-screen display')} onClick={() => setKiosk(true)} sx={toggleSx(P, false)}>
          <KioskIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title={isCardTab ? t('Customize') : t('Nothing to customize on this tab')}>
        <span>
          <IconButton
            size="small"
            aria-label={t('Customize')}
            disabled={!isCardTab}
            onClick={() => setCustomizeOpen(true)}
            sx={toggleSx(P, customizeOpen)}
          >
            <GearIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
    </>
  );

  const tabStrip = (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: DASH_GRID_GAP }}>
      <Tabs
        value={activeTab}
        onChange={(_, v: DashTabId) => setSelectedTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ flex: 1, minWidth: 0, minHeight: 36, border: 'none', boxShadow: 'none', bgcolor: 'transparent', '& .MuiTab-root': { minHeight: 36, py: 0 } }}
      >
        {tabs.map((tab) => {
          const isFav = favouriteTab === tab.id;
          const label = isFav ? t('Opens first') : t('Open this tab first');
          return (
            <Tab
              key={tab.id}
              value={tab.id}
              label={
                <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                  {t(tab.titleKey)}
                  <Tooltip title={label}>
                    <Box
                      component="span"
                      role="button"
                      tabIndex={0}
                      aria-label={label}
                      aria-pressed={isFav}
                      data-testid={`dash-fav-${tab.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setLayout((prev) => ({ ...prev, favouriteTab: tab.id }));
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.stopPropagation();
                          e.preventDefault();
                          setLayout((prev) => ({ ...prev, favouriteTab: tab.id }));
                        }
                      }}
                      sx={{ display: 'inline-flex', color: isFav ? P.accentText : P.textMuted, '&:hover': { color: P.accentText } }}
                    >
                      {isFav ? <StarIcon sx={{ fontSize: FONT_SIZE_SCALE.lg }} /> : <StarBorderIcon sx={{ fontSize: FONT_SIZE_SCALE.lg }} />}
                    </Box>
                  </Tooltip>
                </Box>
              }
            />
          );
        })}
      </Tabs>
      {/* The right-hand slot of the row: the filter controls on Hosts and devices (portalled in by that view),
          the time-range toggle elsewhere. Never both. */}
      <Box ref={setFilterSlot} data-testid="dash-filter-slot" sx={{ display: activeTab === 'hosts' ? 'flex' : 'none', alignItems: 'center', gap: 1, flexWrap: 'wrap', justifyContent: 'flex-end', minWidth: 0 }} />
      <ToggleButtonGroup
        exclusive
        size="small"
        value={range}
        aria-label={t('Time range')}
        onChange={(_, v: DashRange | null) => v && setRange(v)}
        sx={{ ...segmentedSx(P, 'sm'), display: activeTab === 'hosts' ? 'none' : 'inline-flex', visibility: showsRange ? 'visible' : 'hidden' }}
      >
        <ToggleButton value="24h">{t('24 h')}</ToggleButton>
        <ToggleButton value="7d">{t('7 d')}</ToggleButton>
        <ToggleButton value="30d">{t('30 d')}</ToggleButton>
      </ToggleButtonGroup>
    </Box>
  );

  const body = activeTab === 'hosts'
    ? <DashFilterSlot.Provider value={filterSlot}><HostsDevicesView /></DashFilterSlot.Provider>
    : <DashboardCardGrid cards={resolved} data={data} range={range} now={now} />;

  if (kiosk) {
    return (
      <Box
        data-testid="dash-kiosk"
        sx={{ position: 'fixed', inset: 0, zIndex: 1250, bgcolor: P.background, overflow: 'auto', p: 2, ...(pageSurfaceSx(P) as object) }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 600 }}>{tabTitle(activeTab)}</Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
              {updatedAgo ? t('Updated {ago} ago', { ago: updatedAgo }) : ''}
            </Typography>
            <Tooltip title={t('Exit full-screen display')}>
              <IconButton size="small" aria-label={t('Exit full-screen display')} onClick={() => setKiosk(false)} sx={toggleSx(P, false)}>
                <ExitKioskIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>
        {body}
      </Box>
    );
  }

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle title={t('Dashboard')} right={headerActions} mb={0.5} />
      {tabStrip}
      {body}
      {diskFix.dialog}
      <CustomizeDrawer
        open={customizeOpen && isCardTab}
        onClose={() => setCustomizeOpen(false)}
        tabTitle={tabTitle(activeTab)}
        cards={resolved}
        onToggle={(id, on) => setTabOverride(id, { on })}
        onReset={resetTab}
        isMobile={isMobile}
      />
    </Box>
  );
};

export default Dashboard;
