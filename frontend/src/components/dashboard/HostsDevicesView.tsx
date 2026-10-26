import React, { useState, useCallback, useContext, useMemo, useEffect, useRef } from 'react';
import MonitoringProblemChip from '../notifications/MonitoringProblemChip';
import { useActiveProblems } from '../../contexts/notificationStore';
import { createPortal } from 'react-dom';
import { buildServerUrl, buildServerUrlForServer } from '../../utils/buildUrlUtils';
import { formatToLocalTime } from '../../utils/dateUtils';

import {
  Computer as ComputerIcon,
  Devices as DevicesIcon,
  Phone as PhoneIcon,
  Tv as TvIcon,
  ExpandMore as ExpandMoreIcon,
  ChevronRight as CollapsedIcon,
  RestartAlt as RestartServiceIcon,
  PowerSettingsNew as RebootIcon,
  VideoSettings as RestartStreamIcon,
  AutoFixHigh as AutofixIcon,
  ErrorOutline as VersionMismatchIcon,
  Star as StarIcon,
} from '@mui/icons-material';
import {
  Box,
  Grid,
  Card,
  CardContent,
  Typography,
  Chip,
  Alert,
  IconButton,
  Tooltip,
  CircularProgress,
  Paper,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Collapse,
} from '@mui/material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { dangerButtonSx, neutralButtonSx } from '../common/PageChrome';

import { ConfirmDialog } from '../common/ConfirmDialog';
import { DeviceFavoriteStar } from '../common/DeviceFavoriteStar';
import { DeviceFilterBar } from '../common/DeviceFilterBar';
import { featureDeviceLinks } from '../../config/features';
import { HostServicesAccordion } from './HostServicesAccordion';
import { DISK_ERROR_PERCENT, DISK_WARNING_PERCENT, hostHealth, hostHasError, hostHasWarning, hostWarningReasons, isVersionMismatch, type HostWarningReason } from './hostHealth';
import { ActionsMenu } from './ActionsMenu';
import { DASH_LINKS } from './dashboardLinks';
import { DashFilterSlot } from './dashboardSlots';
import { FavouriteChips, type FavouriteChip } from './FavouriteChips';
import { ServiceLogsModal } from '../common/ServiceLogsModal';
import { useConfirmDialog } from '../../hooks/useConfirmDialog';
import { useHostData } from '../../hooks/useHostManager';
import { useDeviceFlags } from '../../hooks/useDeviceFlags';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { useServerManager } from '../../hooks/useServerManager';
import { isAllServersSentinel } from '../../lib/allServer/scope';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { usePermissionContext } from '../../contexts/auth/PermissionContext';
import { DeviceMaintenanceBadge } from '../common/DeviceMaintenanceBadge';
import { useRec } from '../../hooks/pages/useRec';
import { useToast } from '../../hooks/useToast';
import { DeviceKey, useDeviceFavorites } from '../../hooks/useDeviceFavorites';
import { countMonitorProfiles, getDeviceMonitorProfile, getDeviceTargetLabel, reachableFilterOptions, useDeviceFilters, usePruneDeviceFilters } from '../../hooks/useDeviceFilters';
import { usePersistedState } from '../../hooks/usePersistedState';
import { useI18n } from '../../i18n/useI18n';
import { STORAGE_KEYS } from '../../config/constants';
import { Device, Host } from '../../types/common/Host_Types';
import { api } from '../../utils/apiClient';
import { WidgetAddButton, WidgetArea } from '../../mods/core/components/widgets/WidgetArea';
import { FONT_SIZE_SCALE, TYPOGRAPHY } from '../../constants/typography';

const finiteMetric = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/** Keep dense host/device cards readable without changing API identifiers. */
const formatDashboardLabel = (value?: string | null): string => {
  const trimmed = value?.trim() || '';
  const hostSuffix = trimmed.match(/_Host$/i);
  return (hostSuffix ? hostSuffix[0].slice(1) : trimmed).toLocaleLowerCase();
};

/** The host / device view of the Dashboard (first tab): hosts, services, device cards, filters. */
/** One amber host, with the reasons the badge and the tooltip talk about. */
interface WarningHost {
  /** Server URL + host name: the same host name can exist on two servers. */
  key: string;
  hostName: string;
  serverDisplay: string;
  hostVersion?: string | null;
  serverVersion?: string | null;
  reasons: HostWarningReason[];
  diskPercent: number | null;
}

const HostsDevicesView: React.FC = () => {
  const monitoringProblems = useActiveProblems();
  const { t, tn } = useI18n();
  const P = useAgentChatPalette();
  const { isMobile, isTablet } = useResponsiveMode();
  const { getAllHosts } = useHostData();
  const { serverHostsData, selectedServer, isLoading: loading, error, refreshServerData } = useServerManager();
  const { isDeviceAllowed } = useWorkspaceContext();
  const { hasPermission } = usePermissionContext();
  // Host controls (start/stop/restart a service, restart vpt-host, reboot, restart
  // streams) all map to backend routes gated by `system.services:restart`. Anyone
  // without it can still see host status / service health, just not the buttons
  // that would 403 them. Keeping a single local flag rather than sprinkling
  // hasPermission() through the render.
  const canControlHosts = hasPermission('system.services:restart');
  const rawAvailableHosts = useMemo(() => getAllHosts(), [getAllHosts]);
  // Drop workspace-filtered devices from each host, then drop hosts with no
  // remaining devices — restart/reboot actions only operate on what the user
  // can see.
  const availableHosts = useMemo(() => {
    return rawAvailableHosts
      .map((h) => ({
        ...h,
        devices: (h.devices || []).filter((d) => isDeviceAllowed(h.host_name, d.device_id)),
      }))
      .filter((h) => (h.devices?.length ?? 0) > 0);
  }, [rawAvailableHosts, isDeviceAllowed]);
  const { restartHostStream, restartAllStreams, isRestarting } = useRec();
  const { deviceFlags, uniqueFlags, isLoading: isFlagsLoading } = useDeviceFlags();
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();
  const { showSuccess, showError } = useToast();

  // A host "has errors" / "has warnings" per ./hostHealth, which derives the
  // verdict from the same model the Services card renders. `hostHasError` /
  // `hostHasWarning` drive the header badges, the "errors only" filter, the
  // favourite chips and the Auto-fix button — see hostHealth.ts for why the
  // badge must never fire without a red row on the card.

  // Show only the selected server's data (every server for "All servers"),
  // with workspace device filter applied.
  const selectedServerData = useMemo(() => {
    const base = selectedServer && !isAllServersSentinel(selectedServer)
      ? serverHostsData.filter((sd) => sd.server_info.server_url === selectedServer)
      : serverHostsData;
    return base
      .map((sd) => ({
        ...sd,
        hosts: sd.hosts
          .map((host) => ({
            ...host,
            devices: host.devices.filter((d) => isDeviceAllowed(host.host_name, d.device_id)),
          }))
          .filter((host) => host.devices.length > 0)
          .sort((a, b) =>
            a.host_name.localeCompare(b.host_name, undefined, { numeric: true }),
          ),
      }))
      .filter((sd) => sd.hosts.length > 0);
  }, [serverHostsData, selectedServer, isDeviceAllowed]);

  // Target/model/tag filters — persisted and shared with the Device Control page.
  const {
    targetFilter,
    setTargetFilter,
    deviceModelFilter,
    setDeviceModelFilter,
    profileFilter,
    setProfileFilter,
    flagFilter,
    setFlagFilter,
    flagMatchMode,
    setFlagMatchMode,
  } = useDeviceFilters();
  // "Errors only" toggle — driven by the error badge in the header. When on,
  // the dashboard shows only hosts currently in an error/degraded state.
  const [errorOnly, setErrorOnly] = usePersistedState<boolean>(
    `${STORAGE_KEYS.DASHBOARD_FILTERS}_errorOnly`,
    false,
  );
  // "Warnings only" toggle — driven by the amber badge. Not persisted: the
  // amber count moves with every deploy (a host that was behind catches up),
  // so a stale toggle would open the dashboard on an empty list. It is also
  // mutually exclusive with the errors-only toggle: a host is either red or
  // amber, never both, so the two filters would fight over the same list.
  const [warningOnly, setWarningOnly] = useState(false);

  // Starred devices (TASK-99, server side per user) are shown as chips on one line; they are not a filter.
  const { isFavorite, count: favoriteCount } = useDeviceFavorites();
  const filterSlot = useContext(DashFilterSlot);

  const hasAttributeFilters =
    targetFilter.length > 0 ||
    deviceModelFilter.length > 0 ||
    profileFilter.length > 0 ||
    flagFilter.length > 0;
  const hasActiveFilters = hasAttributeFilters || errorOnly || warningOnly;

  const clearFilters = useCallback(() => {
    setTargetFilter([]);
    setDeviceModelFilter([]);
    setProfileFilter([]);
    setFlagFilter([]);
    setErrorOnly(false);
    setWarningOnly(false);
  }, []);

  // Drop every filter when the user picks a different server in the Server
  // dropdown. The "All Targets / Models / Tags" picks and the "errors only"
  // toggle are all server-scoped (a target on vpt-pi1 is not a target on
  // vpt-pi3), so carrying the old selection over leaves the new server with
  // an empty result set and no obvious way back. Skipped on the very first
  // mount so the persisted state survives a page reload.
  const previousServerRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (
      previousServerRef.current !== undefined &&
      previousServerRef.current !== selectedServer
    ) {
      clearFilters();
    }
    previousServerRef.current = selectedServer;
  }, [selectedServer, clearFilters]);

  // Compute unique values for filter controls
  const { uniqueProfiles } = useMemo(
    () =>
      countMonitorProfiles(
        selectedServerData.flatMap((serverData) =>
          serverData.hosts.flatMap((host) => host.devices.map((device) => ({ host, device }))),
        ),
      ),
    [selectedServerData],
  );

  const { targetOptions, targetKeys, uniqueDeviceModels } = useMemo(() => {
    const targets = new Set<string>();
    const keys: Record<string, DeviceKey> = {};
    const deviceModels = new Set<string>();

    selectedServerData.forEach((serverData) => {
      serverData.hosts.forEach((host) => {
        host.devices.forEach((device) => {
          const label = getDeviceTargetLabel(host, device);
          targets.add(label);
          keys[label] = { host_name: host.host_name, device_id: device.device_id };
          if (device.device_model) deviceModels.add(device.device_model);
        });
      });
    });

    return {
      targetOptions: Array.from(targets).sort(),
      targetKeys: keys,
      uniqueDeviceModels: Array.from(deviceModels).sort(),
    };
  }, [selectedServerData]);

  // Drop persisted filter picks that belong to another server or workspace
  // (the selection is shared through localStorage). Only once the selected
  // server's hosts are on screen — the cached list may still hold another
  // server's data mid-switch, which would wipe a legitimately restored filter.
  usePruneDeviceFilters(
    { setTargetFilter, setDeviceModelFilter, setFlagFilter, setProfileFilter },
    { targetOptions, uniqueDeviceModels, uniqueFlags, uniqueProfiles },
    !loading && selectedServerData.length > 0,
    !isFlagsLoading,
  );

  // One predicate for "does this device satisfy every active attribute filter",
  // shared by the filtered host list below and the reachability pool further
  // down (BUG-0829). Two copies of the AND would drift apart, and the one that
  // drifted would let the filter bar offer a combination that empties the page.
  const matchesAttributeFilters = useCallback(
    (host: Host, device: Device) => {
      if (targetFilter.length > 0 && !targetFilter.includes(getDeviceTargetLabel(host, device))) return false;
      if (deviceModelFilter.length > 0 && (!device.device_model || !deviceModelFilter.includes(device.device_model))) return false;
      if (profileFilter.length > 0 && !profileFilter.includes(getDeviceMonitorProfile(host, device))) return false;
      if (flagFilter.length > 0) {
        const df = deviceFlags.find((f: any) => f.host_name === host.host_name && f.device_id === device.device_id);
        const deviceTags: string[] = df?.flags || [];
        const matches =
          flagMatchMode === 'AND'
            ? flagFilter.every((f) => deviceTags.includes(f))
            : flagFilter.some((f) => deviceTags.includes(f));
        if (!matches) return false;
      }
      return true;
    },
    [targetFilter, deviceModelFilter, profileFilter, flagFilter, flagMatchMode, deviceFlags],
  );

  // Apply the target/model/flag filters (everything except the error toggle).
  const attributeFilteredServerHostsData = useMemo(() => {
    if (!hasAttributeFilters) return selectedServerData;

    return selectedServerData.map((serverData) => ({
      ...serverData,
      hosts: serverData.hosts.filter((host) => {
        // Targets are device labels (shared with Device Control): a host stays
        // when at least one of its devices matches every active filter.
        const hasMatchingDevice = host.devices.some((device) => matchesAttributeFilters(host, device));

        return hasMatchingDevice;
      }),
    })).filter((serverData) => serverData.hosts.length > 0);
  }, [selectedServerData, hasAttributeFilters, matchesAttributeFilters]);

  // What Models / Profiles / Tags may still offer (BUG-0829). The pool is the
  // devices that survive every active attribute filter — the same AND the list
  // above applies — so an option only shows while one surviving device still
  // has it. Picking anything on offer therefore always leaves at least one
  // host on the page, which is what "No hosts match the selected filters" was
  // missing. The target filter is a union and needs no such guard; see
  // DeviceFilterBar for why it is deliberately left alone.
  const reachableOptions = useMemo(() => {
    const pool = selectedServerData.flatMap((serverData) =>
      serverData.hosts.flatMap((host) =>
        host.devices.map((device) => ({ host, device })),
      ),
    );
    return reachableFilterOptions(
      pool,
      { targetFilter, deviceModelFilter, profileFilter, flagFilter, flagMatchMode },
      (hostName, deviceId) =>
        deviceFlags.find((f: any) => f.host_name === hostName && f.device_id === deviceId)?.flags ?? [],
    );
  }, [selectedServerData, targetFilter, deviceModelFilter, profileFilter, flagFilter, flagMatchMode, deviceFlags]);

  // Count of hosts currently in error within the attribute-filtered scope.
  // Computed before the error toggle so the badge number stays stable whether
  // or not the toggle is on.
  const errorHostCount = useMemo(() => {
    let count = 0;
    attributeFilteredServerHostsData.forEach((serverData) =>
      serverData.hosts.forEach((host) => {
        if (hostHasError(host, serverData.server_info.deployed_version)) count++;
      }),
    );
    return count;
  }, [attributeFilteredServerHostsData]);

  // The amber hosts in the current scope, each with the reason it is amber.
  // The badge counts these hosts and the tooltip names them, so the number on
  // the chip can always be reconciled with the cards below it.
  const warningHosts = useMemo(() => {
    const out: WarningHost[] = [];
    attributeFilteredServerHostsData.forEach((serverData) => {
      const serverVersion = serverData.server_info.deployed_version;
      serverData.hosts.forEach((host) => {
        const reasons = hostWarningReasons(host, serverVersion);
        if (reasons.length === 0) return;
        out.push({
          key: `${serverData.server_info.server_url}:${host.host_name}`,
          hostName: host.host_name,
          serverDisplay: serverData.server_info.server_url_display,
          hostVersion: host.deployed_version,
          serverVersion,
          reasons,
          diskPercent: hostHealth(host, serverVersion).diskPercent,
        });
      });
    });
    return out;
  }, [attributeFilteredServerHostsData]);

  // Same scope, softer problems: a host running a different build than its
  // server, or one the backend reports degraded. Amber, not red — a deploy to
  // schedule is not a broken host, and it must never sit in the error filter.
  const warningHostCount = warningHosts.length;

  // The "errors only" toggle is persisted, so it outlives the errors that
  // justified it — once every host recovers it would leave the page empty with
  // no cards and no obvious way back. Drop it automatically instead. Only once
  // hosts have actually loaded and the attribute-filtered scope is non-empty,
  // so an empty scope (still loading, or narrowed away by the other filters)
  // isn't mistaken for "all clear".
  useEffect(() => {
    if (loading) return;
    if (!errorOnly) return;
    const hasHostsInScope = attributeFilteredServerHostsData.some((sd) => sd.hosts.length > 0);
    if (hasHostsInScope && errorHostCount === 0) {
      setErrorOnly(false);
    }
  }, [loading, errorOnly, attributeFilteredServerHostsData, errorHostCount]);

  // Same idea for the amber filter: a host that was behind the server catches
  // up on the next deploy, and the filter would then hide every card.
  useEffect(() => {
    if (loading) return;
    if (!warningOnly) return;
    const hasHostsInScope = attributeFilteredServerHostsData.some((sd) => sd.hosts.length > 0);
    if (hasHostsInScope && warningHostCount === 0) {
      setWarningOnly(false);
    }
  }, [loading, warningOnly, attributeFilteredServerHostsData, warningHostCount]);

  // Final dashboard data: optionally narrowed to the hosts in error or the
  // hosts in warning. The two toggles are exclusive (see `warningOnly`), so
  // one filter decides which verdict is kept.
  const filteredServerHostsData = useMemo(() => {
    if (!errorOnly && !warningOnly) return attributeFilteredServerHostsData;
    return attributeFilteredServerHostsData
      .map((serverData) => ({
        ...serverData,
        hosts: serverData.hosts.filter((host) =>
          errorOnly
            ? hostHasError(host, serverData.server_info.deployed_version)
            : hostHasWarning(host, serverData.server_info.deployed_version),
        ),
      }))
      .filter((serverData) => serverData.hosts.length > 0);
  }, [attributeFilteredServerHostsData, errorOnly, warningOnly]);
  
  // Per-host pending action: hostName -> { type, startedAt }. While set,
  // ALL 3 host action buttons are disabled and a background poll keeps
  // host data fresh until the host comes back (max 2 min).
  type PendingHostActionType = 'service' | 'reboot' | 'stream';
  const [pendingHostActions, setPendingHostActions] = useState<
    Map<string, { type: PendingHostActionType; startedAt: number }>
  >(new Map());
  const isHostBusy = useCallback(
    (hostName: string) => pendingHostActions.has(hostName),
    [pendingHostActions]
  );
  const getHostActionType = useCallback(
    (hostName: string) => pendingHostActions.get(hostName)?.type,
    [pendingHostActions]
  );
  const markHostBusy = useCallback((hostName: string, type: PendingHostActionType) => {
    setPendingHostActions((prev) => {
      const next = new Map(prev);
      next.set(hostName, { type, startedAt: Date.now() });
      return next;
    });
  }, []);
  const clearHostBusy = useCallback((hostName: string) => {
    setPendingHostActions((prev) => {
      if (!prev.has(hostName)) return prev;
      const next = new Map(prev);
      next.delete(hostName);
      return next;
    });
  }, []);
  // Global loading states (for "all hosts" buttons)
  const [isRestartingService, setIsRestartingService] = useState(false);
  const [isRebooting, setIsRebooting] = useState(false);

  // Frontend's own deployed version. This page is served by the deployed
  // bundle, so its version is the Vite build-time __APP_VERSION__ constant
  // with a /version.txt HTTP fallback (same as CodeDeployment/Footer). We
  // compare it against the server version below — the server is the source
  // of truth, so a mismatch is flagged in red.
  const embeddedFrontendVersion =
    typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'unknown';
  const [frontendVersion, setFrontendVersion] = useState(embeddedFrontendVersion);
  useEffect(() => {
    if (embeddedFrontendVersion && embeddedFrontendVersion !== 'unknown') {
      setFrontendVersion(embeddedFrontendVersion);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch('/version.txt', {
          cache: 'no-store',
          headers: { 'Cache-Control': 'no-cache' },
        });
        if (!response.ok) return;
        const text = await response.text();
        const lines = text.split(/\r?\n/).map((line) => line.trim());
        const currentLine = lines.find((line) => /^current\s*:/i.test(line));
        const nextVersion = currentLine
          ? currentLine.split(':').slice(1).join(':').trim()
          : lines.find((line) => line.length > 0);
        if (!cancelled && nextVersion) setFrontendVersion(nextVersion);
      } catch {
        // Keep the embedded fallback.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [embeddedFrontendVersion]);

  // Fetch with system stats once on mount. ServerManager's socket + 30s timer keeps host data fresh.
  useEffect(() => {
    refreshServerData(true);
     
  }, []);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshServerData(true);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [refreshServerData]);

  // Background-poll while any per-host action is pending so we can detect
  // when the host comes back.
  const hasPendingHostActions = pendingHostActions.size > 0;
  useEffect(() => {
    if (!hasPendingHostActions) return;
    const intervalId = window.setInterval(() => {
      refreshServerData(true);
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [hasPendingHostActions, refreshServerData]);

  // Clear pending state when the host's last_seen updates after the action
  // started (host is back), or after a 2-min safety timeout.
  useEffect(() => {
    setPendingHostActions((prev) => {
      if (prev.size === 0) return prev;
      // Matches the server's 180s stale-host eviction: a reboot can take
      // 1-2 min, so a shorter safety timeout would clear the spinner while
      // the host is still down.
      const ACTION_TIMEOUT_MS = 180_000;
      const RECOVERY_GRACE_MS = 5_000;
      const now = Date.now();
      const next = new Map(prev);
      let changed = false;
      prev.forEach((action, hostName) => {
        const elapsed = now - action.startedAt;
        if (elapsed > ACTION_TIMEOUT_MS) {
          next.delete(hostName);
          changed = true;
          return;
        }
        if (elapsed < RECOVERY_GRACE_MS) return;
        const host = availableHosts.find((h) => h.host_name === hostName);
        if (!host) return;
        const operationalStatus =
          host.system_stats?.operational_status ?? (host.status === 'online' ? 'online' : 'error');
        const lastSeenSec = toUnixSeconds(host.last_seen);
        const lastSeenMs = lastSeenSec !== null ? lastSeenSec * 1000 : 0;
        if (operationalStatus === 'online' && lastSeenMs > action.startedAt + RECOVERY_GRACE_MS) {
          next.delete(hostName);
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [availableHosts]);

  // System control handlers for HOSTS
  // One host-level POST (one host = one call). Returns success.
  const postHostSystemAction = useCallback(
    async (endpoint: string, hostName: string, label: string): Promise<boolean> => {
      try {
        const response = await fetch(buildServerUrl(endpoint), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ host_name: hostName }),
        });
        const result = await response.json();
        if (result.success) {
          console.log(`${label} succeeded on ${hostName}`);
          return true;
        }
        console.error(`${label} failed on ${hostName}:`, result.error);
        return false;
      } catch (error) {
        console.error(`${label} request failed on ${hostName}:`, error);
        return false;
      }
    },
    [],
  );

  // Restart vpt-host on a single host. Keep it busy until the recovery
  // effect detects it is back (2-min timeout); only clear on request failure.
  const restartHostService = useCallback(async (hostName: string) => {
    if (isHostBusy(hostName)) return;
    markHostBusy(hostName, 'service');
    const ok = await postHostSystemAction('/server/system/restartHostService', hostName, 'Restart vpt-host');
    if (!ok) clearHostBusy(hostName);
  }, [postHostSystemAction, isHostBusy, markHostBusy, clearHostBusy]);

  // Restart vpt-host on every host, once per host.
  const restartAllServices = useCallback(async () => {
    if (isRestartingService) return;
    setIsRestartingService(true);
    try {
      for (const host of availableHosts) {
        await postHostSystemAction('/server/system/restartHostService', host.host_name, 'Restart vpt-host');
      }
    } finally {
      setIsRestartingService(false);
    }
  }, [postHostSystemAction, availableHosts, isRestartingService]);

  // Reboot a single host (one call).
  const rebootHost = useCallback(async (hostName: string) => {
    if (isHostBusy(hostName)) return;
    markHostBusy(hostName, 'reboot');
    const ok = await postHostSystemAction('/server/system/rebootHost', hostName, 'Reboot host');
    if (!ok) clearHostBusy(hostName);
  }, [postHostSystemAction, isHostBusy, markHostBusy, clearHostBusy]);

  // Reboot every host, once per host.
  const rebootAllHosts = useCallback(async () => {
    if (isRebooting) return;
    setIsRebooting(true);
    try {
      for (const host of availableHosts) {
        await postHostSystemAction('/server/system/rebootHost', host.host_name, 'Reboot host');
      }
    } finally {
      setIsRebooting(false);
    }
  }, [postHostSystemAction, availableHosts, isRebooting]);

  const handleRestartStreams = useCallback(async (hostName: string) => {
    if (isHostBusy(hostName)) return;
    markHostBusy(hostName, 'stream');
    let failed = false;
    try {
      await restartHostStream(hostName);
    } catch (error) {
      console.error('Error restarting stream:', error);
      failed = true;
    } finally {
      if (failed) clearHostBusy(hostName);
    }
  }, [restartHostStream, isHostBusy, markHostBusy, clearHostBusy]);

  // Services that matter for this host and are currently down — the red rows of
  // the Services card, which is also what the badge counts (hostHealth.ts).
  // vpt-host itself is excluded: it is recovered via the dedicated restart/reboot
  // buttons, not via Auto-fix.
  const getDownHostServices = useCallback((host: Host, serverVersion?: string | null) => hostHealth(host, serverVersion).downServices, []);

  // Poll cache-bypassed host data until `serviceName` reports `expected`
  // (or attempts run out). systemctl returns before a unit settles, so
  // callers use this to confirm the real post-action state. Returns true
  // if `expected` was reached.
  const waitForServiceStatus = useCallback(
    async (
      hostName: string,
      serviceName: string,
      resolvedName: string,
      expected: string,
      attempts = 6,
    ): Promise<boolean> => {
      for (let i = 0; i < attempts; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        try {
          const hostsResp = await fetch(
            buildServerUrl(
              '/server/system/getAllHosts?include_system_stats=true&force_refresh=true',
            ),
          );
          const hostsData = await hostsResp.json();
          const fresh = (hostsData.hosts || []).find(
            (h: any) => h.host_name === hostName,
          );
          const fs = (fresh?.system_stats?.service_health?.services || []).find(
            (s: any) => s.name === serviceName || s.resolved_name === resolvedName,
          );
          if (fs && fs.status === expected) return true;
        } catch {
          // Transient error mid-poll — keep trying.
        }
      }
      return false;
    },
    [],
  );

  // Per-service start/stop/restart. Keyed `${hostName}::${service.name}` so
  // only the acted-on row shows a spinner; the host stays online throughout
  // (none of these units serve the request) so no host-busy bookkeeping.
  // Server sections the user folded away (keyed by server_url, per browser).
  const [collapsedServers, setCollapsedServers] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem('hostsDevices:collapsedServers') || '[]'));
    } catch {
      return new Set();
    }
  });
  const toggleServerCollapsed = useCallback((serverUrl: string) => {
    setCollapsedServers((prev) => {
      const next = new Set(prev);
      if (next.has(serverUrl)) next.delete(serverUrl);
      else next.add(serverUrl);
      try {
        localStorage.setItem('hostsDevices:collapsedServers', JSON.stringify([...next]));
      } catch {
        // storage unavailable: keep the in-memory state only
      }
      return next;
    });
  }, []);
  const [pendingService, setPendingService] = useState<string | null>(null);

  // Optimistic status override, keyed `${hostName}::${serviceName}`. A
  // start/stop/restart is effectively synchronous (it works or it errors),
  // so on success we flip the displayed status immediately instead of
  // making the user wait for the next poll/refresh. Pruned once fresh
  // server data has landed (and the action is no longer pending) so the
  // real status takes back over.
  const [optimisticStatus, setOptimisticStatus] = useState<Record<string, string>>({});
  useEffect(() => {
    setOptimisticStatus((prev) => {
      const keys = Object.keys(prev);
      if (keys.length === 0) return prev;
      // Drop an override only once the live data has caught up to the same
      // value (seamless hand-off, no revert flicker). Until then the
      // optimistic value stays so the chip never bounces back.
      const liveStatus = (hostName: string, serviceName: string): string | undefined => {
        for (const sd of serverHostsData) {
          const h = sd.hosts?.find((x: any) => x.host_name === hostName);
          if (!h) continue;
          const svc = (h.system_stats?.service_health?.services || []).find(
            (s: any) => s.name === serviceName || s.resolved_name === serviceName,
          );
          return svc?.status;
        }
        return undefined;
      };
      const next: Record<string, string> = {};
      for (const k of keys) {
        const [hostName, serviceName] = k.split('::');
        if (liveStatus(hostName, serviceName) !== prev[k]) next[k] = prev[k];
      }
      return Object.keys(next).length === keys.length ? prev : next;
    });
  }, [serverHostsData]);

  // Which service's journal logs are open (rendered by <ServiceLogsModal/>).
  const [logsModal, setLogsModal] = useState<{
    open: boolean;
    serviceLabel: string;
    logService: string;
    logHostName?: string;
    // vpt-stream logs are per-device ffmpeg files; pass the host's devices
    // so the modal can render one tab per device.
    streamDevices?: { device_id: string; device_name?: string }[];
  }>({ open: false, serviceLabel: '', logService: '' });
  const couldNotText = (hostName: string, action: 'start' | 'stop' | 'restart', service: string): string =>
    action === 'start'
      ? t('{host}: could not start {service}', { host: hostName, service })
      : action === 'stop'
        ? t('{host}: could not stop {service}', { host: hostName, service })
        : t('{host}: could not restart {service}', { host: hostName, service });
  const controlService = useCallback(
    async (
      hostName: string,
      service: { name: string; resolved_name?: string; label: string },
      action: 'start' | 'stop' | 'restart',
    ) => {
      if (pendingService || isHostBusy(hostName)) return;
      const key = `${hostName}::${service.name}`;
            setPendingService(key);
      try {
        const resp = await fetch(buildServerUrl('/server/system/controlHostService'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            host_name: hostName,
            service: service.resolved_name || service.name,
            action,
          }),
        });
        const result = await resp.json();
        if (!result.success) {
          showError(
            `${couldNotText(hostName, action, service.label)}${result.error ? ` — ${result.error}` : ''}`,
          );
          return;
        }
        showSuccess(
          action === 'start'
            ? t('{host}: started {service}', { host: hostName, service: service.label })
            : action === 'stop'
              ? t('{host}: stopped {service}', { host: hostName, service: service.label })
              : t('{host}: restarted {service}', { host: hostName, service: service.label }),
        );
        // Flip the displayed status now — don't make the user refresh/wait.
        setOptimisticStatus((p) => ({
          ...p,
          [key]: action === 'stop' ? 'stopped' : 'active',
        }));

        // systemctl returns before the unit settles, and an immediate
        // refresh can coalesce onto an older in-flight /getAllHosts, so
        // wait until the service reflects the action before syncing state.
        await waitForServiceStatus(
          hostName,
          service.name,
          service.resolved_name || service.name,
          action === 'stop' ? 'stopped' : 'active',
        );
      } catch (error) {
        console.error('Service control error:', error);
        showError(couldNotText(hostName, action, service.label), {
          id: `service-${hostName}-${service.name}`,
          category: 'host',
          scope: { host_name: hostName },
          action: { label: t('Show'), to: `/status?host=${encodeURIComponent(hostName)}` },
        });
      } finally {
        setPendingService(null);
        refreshServerData(true);
      }
    },
    [pendingService, isHostBusy, showSuccess, showError, refreshServerData, waitForServiceStatus, t],
  );

  // Autofix: restart each down service one at a time. The spinner moves
  // to the service currently being fixed (via pendingService) and a
  // toast reports each service's result — not a single host-wide one.
  const [autofixHost, setAutofixHost] = useState<string | null>(null);
  const handleAutofix = useCallback(
    async (host: Host) => {
      if (autofixHost || pendingService || isHostBusy(host.host_name)) return;
      const down = getDownHostServices(host);
      if (down.length === 0) return;

      setAutofixHost(host.host_name);
      try {
        for (const svc of down) {
          const target = svc.resolved_name || svc.name;
          setPendingService(`${host.host_name}::${svc.name}`);
          let fixed = false;
          try {
            const resp = await fetch(buildServerUrl('/server/system/controlHostService'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                host_name: host.host_name,
                service: target,
                action: 'restart',
              }),
            });
            const result = await resp.json();
            if (result.success) {
              setOptimisticStatus((p) => ({ ...p, [`${host.host_name}::${svc.name}`]: 'active' }));
              fixed = await waitForServiceStatus(host.host_name, svc.name, target, 'active');
            }
          } catch (error) {
            console.error('Autofix error:', error);
          }
          if (fixed) showSuccess(t('{host}: fixed {service}', { host: host.host_name, service: svc.label }));
          else showError(t('{host}: could not fix {service}', { host: host.host_name, service: svc.label }), {
            id: `autofix-${host.host_name}-${svc.name}`,
            category: 'host',
            scope: { host_name: host.host_name },
            action: { label: t('Show'), to: `/status?host=${encodeURIComponent(host.host_name)}` },
          });
        }
      } finally {
        setPendingService(null);
        setAutofixHost(null);
        refreshServerData(true);
      }
    },
    [
      autofixHost,
      pendingService,
      isHostBusy,
      getDownHostServices,
      showSuccess,
      showError,
      refreshServerData,
      waitForServiceStatus,
    ],
  );

  // System control handlers for SERVER
  const [isRestartingServerService, setIsRestartingServerService] = useState(false);
  const handleRestartServerService = useCallback(async (serverUrl: string) => {
    if (isRestartingServerService) return;
    
    setIsRestartingServerService(true);
    try {
      // Admin-gated server-side (server_system_routes.py) — must go through the
      // authenticated client so the JWT reaches whichever server VM answers this.
      const result = await api.post(buildServerUrlForServer(serverUrl, '/server/system/restartServerService'), {});
      if (result.success) {
        console.log(`Successfully restarted vpt-server service on server ${serverUrl}`);
      } else {
        console.error(`Failed to restart vpt-server service on server ${serverUrl}:`, result.error);
      }
    } catch (error) {
      console.error('Error restarting vpt-server service:', error);
    } finally {
      setIsRestartingServerService(false);
    }
  }, [isRestartingServerService]);

  const [isRebootingServer, setIsRebootingServer] = useState(false);
  const handleRebootServer = useCallback(async (serverUrl: string) => {
    if (isRebootingServer) return;
    
    setIsRebootingServer(true);
    try {
      const response = await fetch(buildServerUrlForServer(serverUrl, '/server/system/rebootServer'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      
      const result = await response.json();
      if (result.success) {
        console.log(`Successfully initiated reboot on server ${serverUrl}`);
      } else {
        console.error(`Failed to reboot server ${serverUrl}:`, result.error);
      }
    } catch (error) {
      console.error('Error rebooting server:', error);
    } finally {
      setIsRebootingServer(false);
    }
  }, [isRebootingServer]);

  // Reboot is destructive — gate every reboot action behind the custom
  // confirmation dialog before the request is fired.
  const confirmRebootHost = useCallback((hostName: string) => {
    confirm({
      title: t('Reboot'),
      message: t('Reboot "{name}"?\n\nIt will be unreachable for ~1-2 minutes while it restarts.', { name: hostName }),
      confirmText: t('Reboot'),
      confirmColor: 'error',
      onConfirm: () => {
        void rebootHost(hostName);
      },
    });
  }, [confirm, rebootHost, t]);

  const confirmRebootAllHosts = useCallback(() => {
    confirm({
      title: t('Reboot All Hosts'),
      message: t('Reboot ALL hosts?\n\nEvery host will be unreachable for ~1-2 minutes while it restarts.'),
      confirmText: t('Reboot'),
      confirmColor: 'error',
      onConfirm: () => {
        void rebootAllHosts();
      },
    });
  }, [confirm, rebootAllHosts, t]);

  const confirmRebootServer = useCallback((serverUrl: string) => {
    confirm({
      title: t('Reboot Server'),
      message: t('Reboot server "{name}"?\n\nThe server will be unreachable for ~1-2 minutes while it restarts.', { name: serverUrl }),
      confirmText: t('Reboot'),
      confirmColor: 'error',
      onConfirm: () => {
        void handleRebootServer(serverUrl);
      },
    });
  }, [confirm, handleRebootServer, t]);

  const getDeviceIcon = (deviceModel: string) => {
    switch (deviceModel) {
      case 'android_mobile':
        return <PhoneIcon color="primary" sx={{ fontSize: TYPOGRAPHY.pageSubtitle.size }} />;
      case 'android_tv':
        return <TvIcon color="secondary" sx={{ fontSize: TYPOGRAPHY.pageSubtitle.size }} />;
      default:
        return <ComputerIcon sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.pageSubtitle.size }} />;
    }
  };

  const toUnixSeconds = (value: unknown): number | null => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value > 1e12 ? Math.floor(value / 1000) : value;
    }

    if (typeof value === 'string') {
      const numericValue = Number(value);
      if (Number.isFinite(numericValue)) {
        return numericValue > 1e12 ? Math.floor(numericValue / 1000) : numericValue;
      }

      const parsedDate = Date.parse(value);
      if (!Number.isNaN(parsedDate)) {
        return Math.floor(parsedDate / 1000);
      }
    }

    return null;
  };

  const formatLastSeen = (timestamp: unknown) => {
    const parsedTimestamp = toUnixSeconds(timestamp);
    if (parsedTimestamp === null) {
      return t('Unknown');
    }

    const now = Date.now() / 1000;
    const diff = Math.max(0, now - parsedTimestamp);

    if (diff < 60) return t('Just now');
    if (diff < 3600) return t('{count}m ago', { count: Math.floor(diff / 60) });
    if (diff < 86400) return t('{count}h ago', { count: Math.floor(diff / 3600) });
    return t('{count}d ago', { count: Math.floor(diff / 86400) });
  };

  // Strip the "current:" prefix VERSION.txt carries so only the build string
  // (e.g. "debug-2026.05.21-8731") is shown. A missing version renders as
  // an em-dash rather than the literal "unknown" string — the latter looks
  // like a developer leak and made every server chip turn red on Render
  // before _read_local_deployed_version was taught to look under /app.
  const displayVersion = (value?: string | null): string => {
    if (!value) return '—';
    return value.trim().replace(/^current\s*:/i, '') || '—';
  };

  // Why each amber host is amber, one sentence per host. The badge's tooltip
  // used to claim "version mismatch" for every amber host, so a host that was
  // amber for a full disk was announced as a version mismatch, and a count the
  // user could not reconcile with the screen.
  const warningReasonText = (w: WarningHost): string =>
    w.reasons
      .map((reason: HostWarningReason) => {
        if (reason === 'version') {
          return t('runs build {version}, server runs {serverVersion}', {
            version: displayVersion(w.hostVersion),
            serverVersion: displayVersion(w.serverVersion),
          });
        }
        if (reason === 'degraded') return t('backend reports the host degraded');
        return t('disk at {pct} %', { pct: Math.round(w.diskPercent ?? 0) });
      })
      .join(' · ');

  // The tooltip of the amber badge: what the number means and which hosts it
  // counts, so clicking it is an informed choice.
  const warningTooltip = warningOnly ? (
    t('Showing only hosts with warnings — click to show all')
  ) : (
    <Box sx={{ maxWidth: 420, whiteSpace: 'normal' }}>
      <Typography variant="caption" sx={{ display: 'block', fontWeight: 600 }}>
        {t('{count} hosts in warning — click to show only them', { count: warningHostCount })}
      </Typography>
      {warningHosts.map((w) => (
        <Typography key={w.key} variant="caption" sx={{ display: 'block' }}>
          {w.hostName} ({w.serverDisplay}) — {warningReasonText(w)}
        </Typography>
      ))}
    </Box>
  );

  // Render a "<label>: <version>" caption (label optional). When the version
  // differs from `reference`, it turns amber with a warning badge whose tooltip
  // names the differing side (`referenceLabel`). A build that is behind (or
  // ahead of) the server is a deploy to schedule, not a broken host — it used to
  // be red, which read as an error next to the real one. The line is centred with a
  // small top margin so it reads as the card's footer, not a stray row stuck
  // to the bottom of the Details accordion.
  const renderVersionLine = (
    label: string,
    version?: string | null,
    reference?: string | null,
    referenceLabel = 'Server',
  ) => {
    const mismatch = isVersionMismatch(version, reference);
    return (
      <Box display="flex" alignItems="center" justifyContent="center" gap={0.5} sx={{ pt: 0.5 }}>
        {label && (
          <Typography color="textSecondary" variant="caption">
            {label}:
          </Typography>
        )}
        <Typography
          variant="caption"
          sx={{
            fontFamily: 'monospace',
            color: mismatch ? 'warning.main' : 'text.secondary',
            fontWeight: mismatch ? 700 : 400,
          }}
        >
          {displayVersion(version)}
        </Typography>
        {mismatch && (
          <Tooltip
            title={t('{reference} version differs ({version})', { reference: t(referenceLabel), version: displayVersion(reference) })}
            componentsProps={{
              tooltip: {
                sx: { whiteSpace: 'nowrap', maxWidth: 'none' },
              },
            }}
          >
            <VersionMismatchIcon color="warning" sx={{ fontSize: TYPOGRAPHY.body.size }} />
          </Tooltip>
        )}
      </Box>
    );
  };

  const formatRegisteredAt = (dateString: unknown) => {
    if (typeof dateString !== 'string' || dateString.trim() === '') {
      return t('Unknown');
    }

    const formatted = formatToLocalTime(dateString);
    if (!formatted || formatted === '-' || formatted.toLowerCase() === 'invalid date') {
      return t('Unknown');
    }

    return formatted;
  };

  const getUsageColor = (percentage: number) => {
    if (percentage >= 90) return 'error';
    if (percentage >= 75) return 'warning';
    return 'success';
  };

  // Disk uses the host-health lines so the bar and the badge never disagree (TASK-156).
  const getDiskColor = (percentage: number) =>
    percentage >= DISK_ERROR_PERCENT ? 'error' : percentage >= DISK_WARNING_PERCENT ? 'warning' : 'success';

  const getOperationalStatusColor = (status: string): 'success' | 'warning' | 'error' | 'default' => {
    if (status === 'online') return 'success';
    if (status === 'degraded') return 'warning';
    if (status === 'error') return 'error';
    return 'default';
  };

  const getServiceStatusColor = (
    status: string,
    optional: boolean
  ): 'success' | 'warning' | 'error' | 'default' => {
    if (status === 'active') return 'success';
    if (status === 'stuck' || status === 'unknown') return optional ? 'default' : 'warning';
    // 'not_installed' is the worst outcome (the binary literally does not exist
    // on the host) — it is not the same as 'stopped' (installed but not running).
    // Always red so it is impossible to miss on the card, regardless of optional.
    if (
      status === 'stopped' ||
      status === 'error' ||
      status === 'not_installed' ||
      status === 'failed'
    ) {
      return optional ? 'default' : 'error';
    }
    return 'default';
  };

  // Shorten raw server-side status strings to a tidier chip label. We still
  // keep the raw string in the tooltip so it is not lost. 'not_installed' is
  // hidden behind an em-dash — the chip is already red, the literal word
  // "not_installed" on a card reads as developer noise to a tester. The same
  // treatment covers 'failed' which previously printed as a raw verb.
  const statusText = (status: string): string => {
    switch (status) {
      case 'online': return t('online');
      case 'degraded': return t('degraded');
      case 'error': return t('error');
      case 'unknown': return t('unknown');
      case 'active': return t('active');
      case 'inactive': return t('inactive');
      case 'stopped': return t('stopped');
      case 'stuck': return t('stuck');
      case 'failed': return t('failed');
      case 'offline': return t('offline');
      default: return status;
    }
  };
  const getServiceStatusLabel = (status: string): string => {
    if (status === 'not_installed') return '—';
    return statusText(status);
  };

  // Server services as a tile grid: status dot, name, status word. Stopped/failed tiles carry a tinted border.
  const renderServiceTiles = (
    services: Array<{ name: string; label: string; status: string; optional: boolean; detail?: string }>,
    keyPrefix: string,
  ) => {
    const tone = { success: P.success, warning: P.warning, error: P.error, default: P.textMuted };
    return (
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 1, py: 0.5 }}>
        {services.map((service) => {
          const c = tone[getServiceStatusColor(service.status, service.optional)];
          const bad = c === P.error || c === P.warning;
          return (
            <Tooltip key={`${keyPrefix}-${service.name}`} title={service.detail || service.status}>
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  px: 1.25,
                  py: 0.9,
                  borderRadius: 2,
                  bgcolor: P.surface,
                  border: `1px solid ${bad ? c : P.borderColor}`,
                }}
              >
                <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: c, flexShrink: 0 }} />
                <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 500, flex: 1, overflowWrap: 'anywhere' }}>
                  {service.label}
                </Typography>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: c, flexShrink: 0 }}>
                  {getServiceStatusLabel(service.status)}
                </Typography>
              </Box>
            </Tooltip>
          );
        })}
      </Box>
    );
  };

  const SystemStatsDisplay: React.FC<{ stats: Host['system_stats']; compact?: boolean }> = ({
    stats: systemStats,
    compact = false,
  }) => {
    // The lightweight /getAllHosts payload carries a partial system_stats
    // (platform/hardware_encode/archive_video, no usage numbers) — treat it as absent.
    if (!systemStats || typeof systemStats.cpu_percent !== 'number') {
      return (
        <Typography variant="caption" color="error">
          {t('No system stats available')}
        </Typography>
      );
    }

    if (systemStats.error) {
      return (
        <Typography variant="caption" color="error">
          {systemStats.error}
        </Typography>
      );
    }

    // Telemetry can be briefly partial while a host/server is restarting during
    // deployment. Treat absent metrics as unavailable instead of crashing the
    // whole Dashboard on `undefined.toFixed()`.
    const cpuPercent = finiteMetric(systemStats.cpu_percent);
    const memoryPercent = finiteMetric(systemStats.memory_percent);
    const diskPercent = finiteMetric(systemStats.disk_percent);
    const loadAverage = finiteMetric(systemStats.load_average_1m);

    return (
      <Box display="grid" gridTemplateColumns="1fr 1fr" gap={0.5}>
        {/* CPU */}
        <Box display="flex" alignItems="center" gap={0.5}>
          <Typography variant="caption" color="textSecondary">CPU: {/* i18n-ignore */}</Typography>
          <Typography variant="caption" fontWeight="bold" sx={{ minWidth: 32, textAlign: 'right' }}>
            {cpuPercent === null ? '—' : `${cpuPercent.toFixed(0)}%`}
          </Typography>
          <Box sx={{ width: 30, height: 3, backgroundColor: P.borderColor, borderRadius: 1 }}>
            <Box
              sx={{
                width: `${Math.min(cpuPercent ?? 0, 100)}%`,
                height: '100%',
                backgroundColor: `${getUsageColor(cpuPercent ?? 0)}.main`,
                borderRadius: 1,
              }}
            />
          </Box>
        </Box>

        {/* Memory */}
        <Box display="flex" alignItems="center" gap={0.5}>
          <Typography variant="caption" color="textSecondary">RAM: {/* i18n-ignore */}</Typography>
          <Typography variant="caption" fontWeight="bold" sx={{ minWidth: 32, textAlign: 'right' }}>
            {memoryPercent === null ? '—' : `${memoryPercent.toFixed(0)}%`}
          </Typography>
          <Box sx={{ width: 30, height: 3, backgroundColor: P.borderColor, borderRadius: 1 }}>
            <Box
              sx={{
                width: `${Math.min(memoryPercent ?? 0, 100)}%`,
                height: '100%',
                backgroundColor: `${getUsageColor(memoryPercent ?? 0)}.main`,
                borderRadius: 1,
              }}
            />
          </Box>
        </Box>

        {!compact && (
          <>
            {/* Disk */}
            <Box display="flex" alignItems="center" gap={0.5}>
              <Typography variant="caption" color="textSecondary">{t('Disk:')}</Typography>
              <Typography
                variant="caption"
                fontWeight="bold"
                sx={{ minWidth: 32, textAlign: 'right' }}
                title={
                  systemStats.disk_worst_mount
                    ? t('Fullest monitored mount: {mount}', { mount: systemStats.disk_worst_mount })
                    : undefined
                }
              >
                {diskPercent === null ? '—' : `${diskPercent.toFixed(0)}%`}
              </Typography>
              <Box sx={{ width: 30, height: 3, backgroundColor: P.borderColor, borderRadius: 1 }}>
                <Box
                  sx={{
                    width: `${Math.min(diskPercent ?? 0, 100)}%`,
                    height: '100%',
                    backgroundColor: `${getDiskColor(diskPercent ?? 0)}.main`,
                    borderRadius: 1,
                  }}
                />
              </Box>
            </Box>

            {/* Load Average */}
            {loadAverage !== null && (
              <Box display="flex" alignItems="center" gap={0.5}>
                <Typography variant="caption" color="textSecondary">{t('Load:')}</Typography>
                <Typography variant="caption" fontWeight="bold" sx={{ minWidth: 32, textAlign: 'right' }}>
                  {loadAverage.toFixed(1)}
                </Typography>
              </Box>
            )}
          </>
        )}
      </Box>
    );
  };

  // The System Stats header answers "what machine is this?". A vpt-host running
  // in Docker Desktop on a Windows PC reports platform 'Linux' — that is the
  // container kernel, not the PC under it — so a bare "Linux (x86_64)" actively
  // misleads. Show the physical OS, and badge the container runtime so it is
  // obvious *why* a Windows box looks Linux. Hosts with no detection data (older
  // hosts, or a bare-metal box) fall back to the plain label.
  const PlatformLabel: React.FC<{ stats?: Host['system_stats'] }> = ({ stats }) => {
    if (!stats) return null;
    const physical = stats.physical_platform || stats.platform;
    const runtime = stats.container_runtime;
    const label = `${physical} (${stats.architecture})`;
    if (!stats.in_container) {
      return (
        <Typography variant="caption" color="textSecondary">
          {label}
        </Typography>
      );
    }
    const runtimeName = runtime ? runtime.charAt(0).toUpperCase() + runtime.slice(1) : 'Container';
    const hint = stats.os_mismatch
      ? t('The host machine runs {os}, with vpt-host running in a {runtime} container.', {
          os: physical,
          runtime: runtimeName,
        })
      : t('vpt-host runs in a {runtime} container on this host.', { runtime: runtimeName });
    return (
      <Box display="flex" alignItems="center" gap={0.75} sx={{ minWidth: 0 }}>
        <Tooltip title={hint}>
          <Chip
            label={runtimeName}
            size="small"
            variant="outlined"
            sx={{ height: 18, fontSize: TYPOGRAPHY.microMeta.size, flexShrink: 0 }}
          />
        </Tooltip>
        <Typography variant="caption" color="textSecondary" noWrap>
          {label}
        </Typography>
      </Box>
    );
  };

  /**
   * How many browser test runs this host carries right now, and how many it can carry.
   *
   * Browser-isolated web scripts each drive a Chrome of their own (their own debug port
   * and profile), so the host - not the device - is what runs out. The chip says so before
   * the user starts a seventh run, which would otherwise wait for a slot (TASK-146).
   */
  const BrowserRunsChip: React.FC<{ stats?: Host['system_stats'] }> = ({ stats }) => {
    const runs = stats?.browser_runs;
    if (!runs) return null;
    const running = Number(runs.running || 0);
    const waiting = Number(runs.waiting || 0);
    const cap = Number(runs.cap || 0);
    if (!cap || (!running && !waiting)) return null;
    const label = waiting > 0
      ? t('{running}/{cap} browsers · {waiting} waiting', { running, cap, waiting })
      : t('{running}/{cap} browsers', { running, cap });
    const hint = running >= cap
      ? t('This host runs {running} of its {cap} browser test slots. A browser test started now waits for a free slot.', { running, cap })
      : t('Browser tests running on this host: {running} of {cap}. Each one drives a Chrome of its own.', { running, cap });
    return (
      <Tooltip title={hint}>
        <Chip
          label={label}
          size="small"
          variant="outlined"
          sx={{ height: 18, fontSize: TYPOGRAPHY.microMeta.size, flexShrink: 0 }}
        />
      </Tooltip>
    );
  };

  const renderHostCard = (host: Host, serverVersion?: string | null) => (
    <Card variant="outlined" sx={{ height: '100%', borderRadius: 3, borderColor: P.borderColor, bgcolor: P.surface }}>
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        {(() => {
          const services = host.system_stats?.service_health?.services || [];
          const downServices = getDownHostServices(host, serverVersion);
          return (
            <>
        {/* Host Header — host_api_url moves to a hover tooltip on the host name, freeing the
            line that used to render the URL under the title. The platform label (Linux /
            x86_64, container chip, …) sits at the right of the host name — the System
            Stats block that used to host it was dropped (CPU / RAM / Disk / Load are
            repeated on every card and rarely actionable from the host grid). */}
        <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} sx={{ mb: 1.5, minWidth: 0 }}>
          <Tooltip title={host.host_api_url || host.host_url || ''} placement="bottom-start" disableHoverListener={!host.host_api_url && !host.host_url}>
            <Box display="flex" alignItems="center" gap={1} sx={{ minWidth: 0, cursor: 'help', flex: '1 1 auto' }}>
              <ComputerIcon sx={{ color: P.accentText, fontSize: TYPOGRAPHY.pageTitle.size, flexShrink: 0 }} />
              <Typography variant="h6" component="div" noWrap sx={{ fontSize: TYPOGRAPHY.navbarItem.size, textTransform: 'lowercase' }}>
                {formatDashboardLabel(host.host_name)}
              </Typography>
            </Box>
          </Tooltip>
          <Box display="flex" alignItems="center" gap={0.75} sx={{ flexShrink: 0, minWidth: 0 }}>
            <BrowserRunsChip stats={host.system_stats} />
            <PlatformLabel stats={host.system_stats} />
          </Box>
        </Box>

        {/* Devices - Collapsible Accordion */}
        <Accordion
          sx={{
            mb: 1.5,
            boxShadow: 'none',
            border: `1px solid ${P.borderColor}`, borderRadius: '8px',
            backgroundColor: P.background,
            '&:before': { display: 'none' },
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon />}
            sx={{
              // Tighter summary row — the old 32 px / 2 px margin stacked a lot of
              // empty space above and below the section title; the 24 px / 0 px
              // here keeps the chevron + title on one tight line.
              minHeight: '24px',
              backgroundColor: 'transparent',
              '& .MuiAccordionSummary-content': { margin: '0px' },
              '& .MuiAccordionSummary-content.Mui-expanded': { margin: '0px' },
              '& .MuiAccordionSummary-root.Mui-expanded': { minHeight: '24px' },
              px: 1,
            }}
          >
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
              {t('Devices ({count})', { count: host.device_count })}
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0, pb: 0, px: 1, backgroundColor: 'transparent', '&.MuiAccordionDetails-root': { pt: 0 } }}>
            <Box sx={{ maxHeight: '150px', overflowY: 'auto', overflowX: 'hidden', backgroundColor: 'transparent' }}>
              {host.devices.map((device) => (
                <Box
                  key={device.device_id}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    py: 0.2,
                    px: 0,
                    borderRadius: 1,
                    backgroundColor: 'transparent',
                  }}
                >
                  {getDeviceIcon(device.device_model)}
                  {/* Device name + maintenance badge on one line, takes the flex space and
                      truncates with an ellipsis if the row is narrow. The `minWidth: '70px'`
                      that was here forced a wrap (e.g. "france 24 (1080p)" broke before
                      "(1080p)"). The DeviceInfoTooltipIcon and per-device IpIcon were
                      removed — info is on the Devices page, IP is on the host card tooltip. */}
                  <Typography
                    variant="body2"
                    noWrap
                    sx={{ flex: 1, minWidth: 0, fontWeight: 400, fontSize: TYPOGRAPHY.caption.size, textTransform: 'lowercase' }}
                  >
                    {formatDashboardLabel(device.device_name)}
                    <DeviceMaintenanceBadge hostName={host.host_name} deviceId={device.device_id} size={14} />
                  </Typography>
                  <Chip
                    label={device.device_model?.toLocaleLowerCase()}
                    size="small"
                    variant="outlined"
                    sx={{ flexShrink: 0, fontSize: TYPOGRAPHY.microMeta.size, height: '17px', textTransform: 'lowercase' }}
                  />
                  {/* Optional-feature per-device shortcuts (docs/technical/FEATURES.md) */}
                  {featureDeviceLinks().map((link) => (
                    <Tooltip key={link.label} title={link.label}>
                      <IconButton
                        size="small"
                        sx={{ p: 0.25, color: 'text.secondary' }}
                        onClick={() => window.open(link.path(host.host_name, device.device_id), '_blank', 'noopener,noreferrer')}
                      >
                        {link.icon}
                      </IconButton>
                    </Tooltip>
                  ))}
                  {/* Favorite star, always visible, right edge of the device row (TASK-99).
                      Now the only thing on the right (no IpIcon before it). */}
                  <Box sx={{ ml: 'auto', display: 'flex' }}>
                    <DeviceFavoriteStar hostName={host.host_name} deviceId={device.device_id} />
                  </Box>
                </Box>
              ))}
            </Box>
          </AccordionDetails>
        </Accordion>

        {/* Services — grouped by role, state from the device monitoring profiles (hostServices.ts) */}
        <HostServicesAccordion
          hostName={host.host_name}
          services={services}
          profiles={{
            monitorProfiles: host.system_stats?.monitor_profiles,
            profileServices: host.system_stats?.monitor_profile_services,
            deviceCount: host.devices?.length ?? 0,
          }}
          optimisticStatus={optimisticStatus}
          pending={!!pendingService?.startsWith(`${host.host_name}::`)}
          busy={isHostBusy(host.host_name) || pendingService !== null}
          canControl={canControlHosts}
          onLogs={(service) =>
            setLogsModal({
              open: true,
              serviceLabel: service.label,
              logService: service.name,
              logHostName: host.host_name,
              streamDevices:
                service.name === 'vpt-stream'
                  ? (host.devices || []).map((d) => ({ device_id: d.device_id, device_name: d.device_name }))
                  : undefined,
            })
          }
          onAction={(service, action) => controlService(host.host_name, service, action)}
          onRestartHostApi={() => restartHostService(host.host_name)}
        />

        {/* Details accordion — collapsed by default. Holds the destructive host controls
            (admin-only) plus the two meta lines (Last seen / Registered) that don't
            need to be visible at a glance. The deployed version stays OUTSIDE this
            accordion, at the bottom of the card, because a version mismatch is the
            one thing on the card that always needs to be readable. */}
        <Accordion
          sx={{
            mb: 1.5,
            boxShadow: 'none',
            border: `1px solid ${P.borderColor}`, borderRadius: '8px',
            backgroundColor: P.background,
            '&:before': { display: 'none' },
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon />}
            sx={{
              // Same tightening as the Devices accordion: 24 px min height, 0 px
              // content margin, so the Details title sits on one tight line
              // instead of looking like it has 16 px of empty space above and below.
              minHeight: '24px',
              backgroundColor: 'transparent',
              '& .MuiAccordionSummary-content': { margin: '0px' },
              '& .MuiAccordionSummary-content.Mui-expanded': { margin: '0px' },
              '& .MuiAccordionSummary-root.Mui-expanded': { minHeight: '24px' },
              px: 1,
            }}
          >
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>{t('Details')}</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0, pb: 0, px: 1, backgroundColor: 'transparent', '&.MuiAccordionDetails-root': { pt: 0 } }}>
            {/* Per-Host System Controls — viewers see the host card with status but
                not the row of destructive buttons (restart vpt-host, reboot, restart
                streams, auto-fix). Each button hits a backend route that is admin-only
                anyway, so hiding for non-admin is consistent with the server. */}
            {canControlHosts && (
              <Box display="flex" alignItems="center" justifyContent="center" gap={0.5} sx={{ py: 0.25 }}>
                <Tooltip title={t('Restart vpt-host service')}>
                  <span>
                    <IconButton
                      onClick={() => restartHostService(host.host_name)}
                      disabled={isHostBusy(host.host_name)}
                      size="small" sx={neutralButtonSx(P)}
                    >
                      {getHostActionType(host.host_name) === 'service' ? <CircularProgress size={18} color="warning" /> : <RestartServiceIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={t('Reboot')}>
                  <span>
                    <IconButton
                      onClick={() => confirmRebootHost(host.host_name)}
                      disabled={isHostBusy(host.host_name)}
                      size="small" sx={dangerButtonSx(P)}
                    >
                      {getHostActionType(host.host_name) === 'reboot' ? <CircularProgress size={18} color="error" /> : <RebootIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={t('Restart streams')}>
                  <span>
                    <IconButton
                      onClick={() => handleRestartStreams(host.host_name)}
                      disabled={isHostBusy(host.host_name)}
                      size="small"
                      sx={{ color: P.textSecondary }}
                    >
                      {getHostActionType(host.host_name) === 'stream' ? <CircularProgress size={18} sx={{ color: P.accent }} /> : <RestartStreamIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip
                  title={
                    downServices.length > 0
                      ? tn(
                          downServices.length,
                          'Auto-fix {count} down service: {services}',
                          'Auto-fix {count} down services: {services}',
                          { services: downServices.map((s) => s.label).join(', ') },
                        )
                      : t('All services healthy')
                  }
                >
                  <span>
                    <IconButton
                      onClick={() => handleAutofix(host)}
                      disabled={
                        autofixHost !== null ||
                        pendingService !== null ||
                        isHostBusy(host.host_name) ||
                        downServices.length === 0
                      }
                      size="small" sx={neutralButtonSx(P)}
                    >
                      {autofixHost === host.host_name ? <CircularProgress size={18} color="success" /> : <AutofixIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
            )}
            <Typography color="textSecondary" variant="caption" display="block" sx={{ pt: 0.25 }}>
              {t('Last seen: {time}', { time: formatLastSeen(host.last_seen) })}
            </Typography>
            <Typography color="textSecondary" variant="caption" display="block">
              {t('Registered: {time}', { time: formatRegisteredAt(host.registered_at) })}
            </Typography>
          </AccordionDetails>
        </Accordion>

        {/* Deployed version stays at the bottom of the card, outside the Details
            accordion — a version mismatch is the one signal that always needs to be
            visible at a glance. */}
        {renderVersionLine('', host.deployed_version, serverVersion)}
            </>
          );
        })()}
      </CardContent>
    </Card>
  );

  // Starred devices of the server on screen: chips on ONE line, "+N" for the ones that do not fit.
  const favouriteChips: FavouriteChip[] = selectedServerData.flatMap((sd) =>
    sd.hosts.flatMap((host) =>
      host.devices
        .filter((d) => isFavorite(host.host_name, d.device_id))
        .map((d): FavouriteChip => {
          const down = hostHasError(host, sd.server_info.deployed_version);
          return {
            key: `${host.host_name}/${d.device_id}`,
            label: `${formatDashboardLabel(d.device_name)} · ${host.host_name}`,
            tone: down ? 'error' : 'success',
            word: down ? t('error') : t('ok'),
            to: DASH_LINKS.device(host.host_name, d.device_id),
          };
        }),
    ),
  );
  const favouriteStrip = favoriteCount > 0 && favouriteChips.length > 0 && (
    <Box data-testid="favourites-strip" sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, minWidth: 0 }}>
      <StarIcon sx={{ fontSize: FONT_SIZE_SCALE.md, color: P.accentText, flexShrink: 0 }} />
      <FavouriteChips chips={favouriteChips} />
    </Box>
  );

  const filterBar = (
    <DeviceFilterBar
      targetFilter={targetFilter}
      onTargetFilterChange={setTargetFilter}
      deviceModelFilter={deviceModelFilter}
      onDeviceModelFilterChange={setDeviceModelFilter}
      profileFilter={profileFilter}
      onProfileFilterChange={setProfileFilter}
      uniqueProfiles={uniqueProfiles}
      flagFilter={flagFilter}
      onFlagFilterChange={setFlagFilter}
      flagMatchMode={flagMatchMode}
      onFlagMatchModeChange={setFlagMatchMode}
      targetOptions={targetOptions}
      targetKeys={targetKeys}
      uniqueDeviceModels={uniqueDeviceModels}
      uniqueFlags={uniqueFlags}
      hasActiveFilters={hasActiveFilters}
      onClearFilters={clearFilters}
      reachableOptions={reachableOptions}
      targetPlaceholder="All Targets"
    />
  );

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  if (isMobile || isTablet) {
    return (
      <Box>
        {favouriteStrip}
        {error && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {error}
          </Alert>
        )}

        {/* The server picker comes from AppHeader (AppBar on tablet, MobileServerBar
            on mobile) — do NOT render a second one here, or users see two stacked
            dropdowns for the same picker. */}

        <Box sx={{ mb: 1 }}>
          <DeviceFilterBar
            targetFilter={targetFilter}
            onTargetFilterChange={setTargetFilter}
            deviceModelFilter={deviceModelFilter}
            onDeviceModelFilterChange={setDeviceModelFilter}
            profileFilter={profileFilter}
            onProfileFilterChange={setProfileFilter}
            uniqueProfiles={uniqueProfiles}
            flagFilter={flagFilter}
            onFlagFilterChange={setFlagFilter}
            targetOptions={targetOptions}
            targetKeys={targetKeys}
            uniqueDeviceModels={uniqueDeviceModels}
            uniqueFlags={uniqueFlags}
            hasActiveFilters={hasActiveFilters}
            onClearFilters={clearFilters}
            reachableOptions={reachableOptions}
            isMobile={isMobile}
            targetPlaceholder="All Targets"
          />
        </Box>

        <Paper sx={{ p: 1.25 }}>
          <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
            <Box display="flex" alignItems="center" gap={1}>
              <Typography variant="subtitle1">{t('Hosts')}</Typography>
              {(errorHostCount > 0 || errorOnly) && (
                <Tooltip
                  title={
                    errorOnly
                      ? t('Showing only hosts with errors — tap to show all')
                      : t('Show only hosts with errors')
                  }
                >
                  <Chip
                    label={`${errorHostCount}`}
                    size="small"
                    color="error"
                    variant={errorOnly ? 'filled' : 'outlined'}
                    onClick={() => {
                      setWarningOnly(false);
                      setErrorOnly((v) => !v);
                    }}
                    sx={{ cursor: 'pointer', height: 22 }}
                  />
                </Tooltip>
              )}
              {warningHostCount > 0 && (
                <Tooltip
                  title={
                    warningOnly
                      ? t('Showing only hosts with warnings — tap to show all')
                      : t('Show only hosts with warnings')
                  }
                >
                  <Chip
                    label={`${warningHostCount}`}
                    size="small"
                    color="warning"
                    variant={warningOnly ? 'filled' : 'outlined'}
                    onClick={() => {
                      setErrorOnly(false);
                      setWarningOnly((v) => !v);
                    }}
                    sx={{ cursor: 'pointer', height: 22 }}
                    data-testid="warning-host-chip-mobile"
                  />
                </Tooltip>
              )}
            </Box>
            <Box display="flex" gap={0.5}>
              {canControlHosts && (
              <>
              <Tooltip title={t('Restart host service')}>
                <span>
                  <IconButton onClick={() => restartAllServices()} disabled={isRestartingService} size="small" sx={neutralButtonSx(P)}>
                    <RestartServiceIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title={t('Restart streams')}>
                <span>
                  <IconButton onClick={() => restartAllStreams()} disabled={isRestarting} size="small" sx={{ color: P.textSecondary }}>
                    <RestartStreamIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              </>
              )}
            </Box>
          </Box>

          {filteredServerHostsData.length === 0 ? (
            <Alert severity="info">{hasActiveFilters ? t('No hosts match the selected filters.') : t('No servers connected')}</Alert>
          ) : (
            <>
              <Box sx={{ mb: 1.5 }}>
                {filteredServerHostsData.map((serverData) => {
                  const serviceHealth = serverData.server_info.service_health;
                  const services = serviceHealth?.services || [];
                  if (!serviceHealth) return null;

                  return (
                    <Accordion
                      key={`mobile-server-services-${serverData.server_info.server_url}`}
                      sx={{
                        mb: 1,
                        boxShadow: 'none',
                        border: `1px solid ${P.borderColor}`, borderRadius: '8px',
                        backgroundColor: P.background,
                        '&:before': { display: 'none' },
                      }}
                    >
                      <AccordionSummary
                        expandIcon={<ExpandMoreIcon />}
                        sx={{
                          minHeight: '36px',
                          backgroundColor: 'transparent',
                          '& .MuiAccordionSummary-content': { margin: '6px 0' }
                        }}
                      >
                        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                          <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                            {t('{server} Services ({count})', { server: serverData.server_info.server_name, count: services.length })}
                          </Typography>
                          <Chip
                            label={statusText(serviceHealth.overall_status || 'unknown')}
                            size="small"
                            color={getOperationalStatusColor(serviceHealth.overall_status || 'unknown')}
                            variant="outlined"
                            sx={{ fontSize: TYPOGRAPHY.microMeta.size, height: '18px' }}
                          />
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 1, backgroundColor: 'transparent' }}>
                        {renderServiceTiles(services, `m-${serverData.server_info.server_url}`)}
                      </AccordionDetails>
                    </Accordion>
                  );
                })}
              </Box>

              <Grid container spacing={isMobile ? 1 : 1.5}>
                {filteredServerHostsData.flatMap((serverData) =>
                  serverData.hosts.map((host) => {
                    return (
                      <Grid item xs={12} md={6} key={host.host_name}>
                        <Card variant="outlined">
                          <CardContent sx={{ py: 1.25 }}>
                            <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}>
                              <Typography variant="subtitle1" noWrap>{host.host_name}</Typography>
                            </Box>
                            <SystemStatsDisplay stats={host.system_stats} compact />
                            <Box sx={{ mt: 0.75, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                              {host.devices.slice(0, 2).map((device) => (
                                <Chip
                                  key={device.device_id}
                                  size="small"
                                  variant="outlined"
                                  label={`${device.device_name} (${device.device_model})`}
                                  icon={<DeviceMaintenanceBadge hostName={host.host_name} deviceId={device.device_id} size={14} />}
                                />
                              ))}
                              {host.devices.length > 2 ? (
                                <Chip size="small" label={t('+{count} more', { count: host.devices.length - 2 })} />
                              ) : null}
                            </Box>
                            <Box sx={{ mt: 0.75 }}>
                              {renderVersionLine(
                                '',
                                host.deployed_version,
                                serverData.server_info.deployed_version,
                              )}
                            </Box>
                          </CardContent>
                        </Card>
                      </Grid>
                    );
                  })
                )}
              </Grid>
            </>
          )}
        </Paper>
      </Box>
    );
  }


  return (
    <Box>
      {/* The filter controls sit in the Dashboard tab row (portalled into its right-hand slot); without that slot
          (full-screen display) they render here. */}
      {filterSlot ? createPortal(filterBar, filterSlot) : <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>{filterBar}</Box>}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
        <WidgetAddButton area="dashboard" />
        <Box sx={{ flex: 1, minWidth: 0 }}>{favouriteStrip}</Box>
      </Box>

      {/* Widgets the user placed (mods, TASK-77); nothing shows when no mod offers one */}
      <WidgetArea area="dashboard" />

      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}

      {/* Connected Devices */}
      <Paper sx={{ p: 2, mt: 2, borderRadius: 3, border: `1px solid ${P.borderColor}`, boxShadow: 'none' }}>
        {/* Errors-only filter; no header strip at all when there is nothing to show. */}
        {(errorHostCount > 0 || warningHostCount > 0 || errorOnly || monitoringProblems.length > 0) && (
          <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <MonitoringProblemChip />
            {(errorHostCount > 0 || errorOnly) && (
          <Tooltip
            title={
              errorOnly
                ? t('Showing only hosts with errors — click to show all')
                : t('Show only hosts with errors')
            }
          >
            <Chip
              label={t('{count} in error', { count: errorHostCount })}
              size="small"
              color="error"
              variant={errorOnly ? 'filled' : 'outlined'}
              onClick={() => {
                setWarningOnly(false);
                setErrorOnly((v) => !v);
              }}
              sx={{ cursor: 'pointer' }}
              data-testid="error-host-chip"
            />
          </Tooltip>
            )}
            {warningHostCount > 0 && (
          <Tooltip title={warningTooltip}>
            <Chip
              label={t('{count} in warning', { count: warningHostCount })}
              size="small"
              color="warning"
              variant={warningOnly ? 'filled' : 'outlined'}
              onClick={() => {
                setErrorOnly(false);
                setWarningOnly((v) => !v);
              }}
              sx={{ cursor: 'pointer' }}
              data-testid="warning-host-chip"
            />
          </Tooltip>
            )}
          </Box>
        )}

        {filteredServerHostsData.length > 0 ? (
          filteredServerHostsData.map((serverData, index) => {
            const hostCount = serverData.hosts.length;
            const deviceCount = serverData.hosts.reduce((total, host) => total + (host.device_count || 0), 0);
            const serverUrl = serverData.server_info.server_url;
            const isCollapsed = collapsedServers.has(serverUrl);

            return (
              <Box 
                key={index} 
                sx={{ 
                  backgroundColor: P.background, 
                  borderRadius: 2, 
                  p: 2, 
                  mb: 2,
                  border: '1px solid',
                  borderColor: P.borderColor
                }}
              >
                <Box display="flex" alignItems="center" justifyContent="space-between" mb={isCollapsed ? 0 : 2}>
                  <Box
                    display="flex"
                    alignItems="center"
                    gap={1}
                    onClick={() => toggleServerCollapsed(serverUrl)}
                    sx={{ cursor: 'pointer', userSelect: 'none' }}
                  >
                    <IconButton
                      size="small"
                      aria-label={isCollapsed ? t('Expand') : t('Collapse')}
                      aria-expanded={!isCollapsed}
                      sx={{ color: P.textSecondary }}
                    >
                      {isCollapsed ? <CollapsedIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                    </IconButton>
                    <Typography variant="h6">
                      {serverData.server_info.server_url_display}
                    </Typography>
                    {/* Server version inline (the source of truth). Turns red
                        with a badge if the frontend bundle is on a different
                        version. */}
                    {renderVersionLine(
                      '',
                      serverData.server_info.deployed_version,
                      frontendVersion,
                      'Frontend',
                    )}
                  </Box>
                  <Box display="flex" alignItems="center" gap={2}>
                    <Chip
                      label={tn(hostCount, '{count} host', '{count} hosts')}
                      size="small"
                      variant="outlined"
                      color="primary"
                    />
                    <Chip
                      label={tn(deviceCount, '{count} device', '{count} devices')}
                      size="small"
                      variant="outlined"
                      color="secondary"
                    />
                    {canControlHosts && (
                      <ActionsMenu
                        testId={`server-actions-menu-${index}`}
                        label={t('More actions')}
                        items={[
                          { key: 'restart-server', group: t('Server'), label: t('Restart vpt-server service'), icon: <RestartServiceIcon fontSize="small" />, onClick: () => handleRestartServerService(serverData.server_info.server_url), disabled: isRestartingServerService },
                          { key: 'reboot-server', group: t('Server'), label: t('Reboot server'), icon: <RebootIcon fontSize="small" />, onClick: () => confirmRebootServer(serverData.server_info.server_url), disabled: isRebootingServer, danger: true },
                          { key: 'restart-service', group: t('All hosts'), label: t('Restart vpt-host service on all hosts'), icon: <RestartServiceIcon fontSize="small" />, onClick: () => restartAllServices(), disabled: isRestartingService },
                          { key: 'reboot', group: t('All hosts'), label: t('Reboot all hosts'), icon: <RebootIcon fontSize="small" />, onClick: () => confirmRebootAllHosts(), disabled: isRebooting, danger: true },
                          { key: 'streams', group: t('All hosts'), label: t('Restart streams on all hosts'), icon: <RestartStreamIcon fontSize="small" />, onClick: () => restartAllStreams(), disabled: isRestarting },
                        ]}
                      />
                    )}
                  </Box>
                </Box>

                <Collapse in={!isCollapsed} timeout={0} unmountOnExit>
                {/* Server Services - Collapsible Accordion */}
                {serverData.server_info.service_health && (
                  <Accordion
                    sx={{
                      mb: 2,
                      boxShadow: 'none',
                      border: `1px solid ${P.borderColor}`, borderRadius: '8px',
                      backgroundColor: P.surface,
                      '&:before': { display: 'none' },
                    }}
                  >
                    <AccordionSummary
                      expandIcon={<ExpandMoreIcon />}
                      sx={{
                        minHeight: '36px',
                        backgroundColor: 'transparent',
                        '& .MuiAccordionSummary-content': { margin: '6px 0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: 2 }
                      }}
                    >
                      <Box display="flex" alignItems="center" gap={1}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                          {t('Server Services ({count})', { count: serverData.server_info.service_health.services?.length || 0 })}
                        </Typography>
                        <Chip
                          label={statusText(serverData.server_info.service_health.overall_status || 'unknown')}
                          size="small"
                          color={getOperationalStatusColor(serverData.server_info.service_health.overall_status || 'unknown')}
                          variant="outlined"
                          sx={{ fontSize: TYPOGRAPHY.microMeta.size, height: '18px' }}
                        />
                      </Box>
                      {/* Compact Server Stats — sit to the right of the "online" chip
                          and to the left of the expand icon. Only shown when the
                          backend actually returned system_stats for this server
                          (see the SERVER_NAME store/read mismatch note in
                          backend_server/src/lib/server/gunicorn_app.py). */}
                      {serverData.server_info.system_stats && (() => {
                        const stats = serverData.server_info.system_stats;
                        const cpuPercent = finiteMetric(stats.cpu_percent);
                        const memoryPercent = finiteMetric(stats.memory_percent);
                        const diskPercent = finiteMetric(stats.disk_percent);
                        const cpuTemperature = finiteMetric(stats.cpu_temperature_celsius);
                        const loadAverage = finiteMetric(stats.load_average_1m);

                        if (
                          cpuPercent === null &&
                          memoryPercent === null &&
                          diskPercent === null &&
                          cpuTemperature === null &&
                          loadAverage === null
                        ) {
                          return null;
                        }

                        return (
                          <Box display="flex" alignItems="center" gap={1} sx={{ mr: 1 }}>
                            {cpuPercent !== null && (
                              <Chip
                                label={`CPU: ${cpuPercent.toFixed(0)}%`}
                                size="small"
                                sx={{
                                  height: 20,
                                  fontSize: TYPOGRAPHY.caption.size,
                                  bgcolor: `${getUsageColor(cpuPercent)}.100`,
                                  color: 'text.primary'
                                }}
                              />
                            )}
                          {memoryPercent !== null && (
                            <Chip
                              label={`RAM: ${memoryPercent.toFixed(0)}%`}
                              size="small"
                              sx={{
                                height: 20,
                                fontSize: TYPOGRAPHY.caption.size,
                                bgcolor: `${getUsageColor(memoryPercent)}.100`,
                                color: 'text.primary'
                              }}
                            />
                          )}
                          {diskPercent !== null && (
                            <Chip
                              label={t('Disk: {value}', { value: `${diskPercent.toFixed(0)}%` })}
                              size="small"
                              sx={{
                                height: 20,
                                fontSize: TYPOGRAPHY.caption.size,
                                bgcolor: `${getDiskColor(diskPercent)}.100`,
                                color: 'text.primary'
                              }}
                            />
                          )}
                          {cpuTemperature !== null && (
                            <Chip
                              label={`${cpuTemperature.toFixed(0)}°C`}
                              size="small"
                              sx={{ height: 20, fontSize: TYPOGRAPHY.caption.size }}
                            />
                          )}
                          {loadAverage !== null && (
                            <Chip
                              label={t('Load: {value}', { value: loadAverage.toFixed(1) })}
                              size="small"
                              sx={{ height: 20, fontSize: TYPOGRAPHY.caption.size }}
                            />
                          )}
                          </Box>
                        );
                      })()}
                    </AccordionSummary>
                    <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 1, backgroundColor: 'transparent' }}>
                      <Box sx={{ backgroundColor: 'transparent' }}>
                        {(serverData.server_info.service_health.services || []).length === 0 ? (
                          <Typography variant="caption" color="textSecondary">
                            {t('Service details not available')}
                          </Typography>
                        ) : (
                          renderServiceTiles(serverData.server_info.service_health.services || [], serverData.server_info.server_url)
                        )}
                      </Box>
                    </AccordionDetails>
                  </Accordion>
                )}
              
              {serverData.hosts.length > 0 ? (
                <Grid container spacing={2}>
                  {serverData.hosts.map((host) => (
                    <Grid item xs={12} sm={6} md={4} lg={4} xl={4} key={host.host_name}>
                      {renderHostCard(host, serverData.server_info.deployed_version)}
                    </Grid>
                  ))}
                </Grid>
              ) : (
                <Typography color="textSecondary">{t('No hosts connected to this server')}</Typography>
              )}
                </Collapse>
            </Box>
          )})
        ) : (
          <Box textAlign="center" py={4}>
            <DevicesIcon sx={{ fontSize: TYPOGRAPHY.displayKpi.size, color: 'text.secondary', mb: 2 }} />
            <Typography color="textSecondary" variant="h6" gutterBottom>
              {hasActiveFilters ? t('No hosts match the selected filters') : t('No servers connected')}
            </Typography>
          </Box>
        )}
      </Paper>

      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />

      <ServiceLogsModal
        open={logsModal.open}
        serviceLabel={logsModal.serviceLabel}
        logService={logsModal.logService}
        logHostName={logsModal.logHostName}
        streamDevices={logsModal.streamDevices}
        defaultLines={500}
        onClose={() => setLogsModal((prev) => ({ ...prev, open: false }))}
      />
    </Box>
  );
};

export default HostsDevicesView;
