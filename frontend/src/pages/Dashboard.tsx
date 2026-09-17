import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { buildServerUrl, buildServerUrlForServer } from '../utils/buildUrlUtils';
import { formatToLocalTime } from '../utils/dateUtils';

import {
  Computer as ComputerIcon,
  Refresh as RefreshIcon,
  Devices as DevicesIcon,
  Phone as PhoneIcon,
  Tv as TvIcon,
  CheckCircle as SuccessIcon,
  ExpandMore as ExpandMoreIcon,
  RestartAlt as RestartServiceIcon,
  PowerSettingsNew as RebootIcon,
  VideoSettings as RestartStreamIcon,
  AutoFixHigh as AutofixIcon,
  PlayArrow as StartIcon,
  Stop as StopIcon,
  InfoOutlined as InfoIcon,
  Article as LogsIcon,
  ErrorOutline as VersionMismatchIcon,
  Warning as ErrorBadgeIcon,
  Lan as IpIcon,
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
} from '@mui/material';

import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { DeviceFilterBar } from '../components/common/DeviceFilterBar';
import { ServerSelector } from '../components/common/ServerSelector';
import { DeviceInfoTooltipIcon } from '../components/common/DeviceInfoTooltipIcon';
import { featureDeviceLinks } from '../config/features';
import { ServiceLogsModal } from '../components/common/ServiceLogsModal';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { useHostData } from '../hooks/useHostManager';
import { useDeviceFlags } from '../hooks/useDeviceFlags';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useServerManager } from '../hooks/useServerManager';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { useRec } from '../hooks/pages/useRec';
import { useToast } from '../hooks/useToast';
import { usePersistedState } from '../hooks/usePersistedState';
import { STORAGE_KEYS } from '../config/constants';
import { Host } from '../types/common/Host_Types';

const Dashboard: React.FC = () => {
  const { isMobile, isTablet } = useResponsiveMode();
  const navigate = useNavigate();
  const { getAllHosts } = useHostData();
  const { serverHostsData, selectedServer, isLoading: loading, error, refreshServerData } = useServerManager();
  const { isDeviceAllowed } = useWorkspaceContext();
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
  const { deviceFlags, uniqueFlags } = useDeviceFlags();
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();
  const { showSuccess, showError } = useToast();

  // A host "has errors" when its overall operational status is error/degraded,
  // or it has a non-optional service down (vpt-host excluded — it has its own
  // recovery path). Drives the header error badge + "errors only" filter.
  const hostHasError = useCallback((host: Host): boolean => {
    const opStatus =
      host.system_stats?.operational_status ??
      (host.status === 'online' ? 'online' : 'error');
    if (opStatus === 'error' || opStatus === 'degraded') return true;
    const services = host.system_stats?.service_health?.services || [];
    return services.some(
      (s) =>
        s.name !== 'vpt-host' &&
        !s.optional &&
        (s.status === 'stopped' || s.status === 'error' || s.status === 'stuck'),
    );
  }, []);

  // Show only the selected server's data, with workspace device filter applied.
  const selectedServerData = useMemo(() => {
    const base = selectedServer
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

  // Filter states — persisted to localStorage so the selection survives
  // refresh and page navigation (kept separate from the Device page).
  const [targetFilter, setTargetFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.DASHBOARD_FILTERS}_target`,
    [],
  );
  const [deviceModelFilter, setDeviceModelFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.DASHBOARD_FILTERS}_model`,
    [],
  );
  const [flagFilter, setFlagFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.DASHBOARD_FILTERS}_flag`,
    [],
  );
  // 'AND' = device must carry every selected tag; 'OR' = any one. Default AND.
  const [flagMatchMode, setFlagMatchMode] = usePersistedState<'AND' | 'OR'>(
    `${STORAGE_KEYS.DASHBOARD_FILTERS}_flagMode`,
    'AND',
  );
  // "Errors only" toggle — driven by the error badge in the header. When on,
  // the dashboard shows only hosts currently in an error/degraded state.
  const [errorOnly, setErrorOnly] = usePersistedState<boolean>(
    `${STORAGE_KEYS.DASHBOARD_FILTERS}_errorOnly`,
    false,
  );

  const hasAttributeFilters =
    targetFilter.length > 0 || deviceModelFilter.length > 0 || flagFilter.length > 0;
  const hasActiveFilters = hasAttributeFilters || errorOnly;

  const clearFilters = useCallback(() => {
    setTargetFilter([]);
    setDeviceModelFilter([]);
    setFlagFilter([]);
    setErrorOnly(false);
  }, []);

  // Compute unique values for filter controls
  const { targetOptions, uniqueDeviceModels } = useMemo(() => {
    const hosts = new Set<string>();
    const deviceModels = new Set<string>();

    selectedServerData.forEach((serverData) => {
      serverData.hosts.forEach((host) => {
        hosts.add(host.host_name);
        host.devices.forEach((device) => {
          if (device.device_model) deviceModels.add(device.device_model);
        });
      });
    });

    return {
      targetOptions: Array.from(hosts).sort(),
      uniqueDeviceModels: Array.from(deviceModels).sort(),
    };
  }, [selectedServerData]);

  // Apply the target/model/flag filters (everything except the error toggle).
  const attributeFilteredServerHostsData = useMemo(() => {
    if (!hasAttributeFilters) return selectedServerData;

    return selectedServerData.map((serverData) => ({
      ...serverData,
      hosts: serverData.hosts.filter((host) => {
        if (targetFilter.length > 0 && !targetFilter.some(t => host.host_name.toLowerCase().includes(t.toLowerCase()))) {
          return false;
        }

        const hasMatchingDevice = host.devices.some((device) => {
          if (deviceModelFilter.length > 0 && (!device.device_model || !deviceModelFilter.includes(device.device_model))) return false;
          if (flagFilter.length > 0) {
            const df = deviceFlags.find(
              (f: any) => f.host_name === host.host_name && f.device_id === device.device_id
            );
            const deviceTags: string[] = df?.flags || [];
            const matches =
              flagMatchMode === 'AND'
                ? flagFilter.every((f) => deviceTags.includes(f))
                : flagFilter.some((f) => deviceTags.includes(f));
            if (!matches) return false;
          }
          return true;
        });

        return hasMatchingDevice;
      }),
    })).filter((serverData) => serverData.hosts.length > 0);
  }, [selectedServerData, targetFilter, deviceModelFilter, flagFilter, flagMatchMode, deviceFlags, hasAttributeFilters]);

  // Count of hosts currently in error within the attribute-filtered scope.
  // Computed before the error toggle so the badge number stays stable whether
  // or not the toggle is on.
  const errorHostCount = useMemo(() => {
    let count = 0;
    attributeFilteredServerHostsData.forEach((serverData) =>
      serverData.hosts.forEach((host) => {
        if (hostHasError(host)) count++;
      }),
    );
    return count;
  }, [attributeFilteredServerHostsData, hostHasError]);

  // Final dashboard data: optionally narrowed to only the hosts in error.
  const filteredServerHostsData = useMemo(() => {
    if (!errorOnly) return attributeFilteredServerHostsData;
    return attributeFilteredServerHostsData
      .map((serverData) => ({
        ...serverData,
        hosts: serverData.hosts.filter((host) => hostHasError(host)),
      }))
      .filter((serverData) => serverData.hosts.length > 0);
  }, [attributeFilteredServerHostsData, errorOnly, hostHasError]);
  
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

  // Services that matter for this host and are currently down. Optional
  // services (e.g. Subtitle on a non-android host) and vpt-host itself are
  // excluded — vpt-host is recovered via the dedicated restart/reboot buttons.
  const getDownHostServices = useCallback((host: Host) => {
    const services = host.system_stats?.service_health?.services || [];
    return services.filter(
      (s) =>
        s.name !== 'vpt-host' &&
        !s.optional &&
        (s.status === 'stopped' || s.status === 'error' || s.status === 'stuck'),
    );
  }, []);

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
  const controlService = useCallback(
    async (
      hostName: string,
      service: { name: string; resolved_name?: string; label: string },
      action: 'start' | 'stop' | 'restart',
    ) => {
      if (pendingService || isHostBusy(hostName)) return;
      const key = `${hostName}::${service.name}`;
      const past = { start: 'started', stop: 'stopped', restart: 'restarted' }[action];
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
            `${hostName}: could not ${action} ${service.label}${result.error ? ` — ${result.error}` : ''}`,
          );
          return;
        }
        showSuccess(`${hostName}: ${past} ${service.label}`);
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
        showError(`${hostName}: could not ${action} ${service.label}`);
      } finally {
        setPendingService(null);
        refreshServerData(true);
      }
    },
    [pendingService, isHostBusy, showSuccess, showError, refreshServerData, waitForServiceStatus],
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
          if (fixed) showSuccess(`${host.host_name}: fixed ${svc.label}`);
          else showError(`${host.host_name}: could not fix ${svc.label}`);
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
      const response = await fetch(buildServerUrlForServer(serverUrl, '/server/system/restartServerService'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      
      const result = await response.json();
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
      title: 'Reboot',
      message: `Reboot "${hostName}"?\n\nIt will be unreachable for ~1-2 minutes while it restarts.`,
      confirmText: 'Reboot',
      confirmColor: 'error',
      onConfirm: () => {
        void rebootHost(hostName);
      },
    });
  }, [confirm, rebootHost]);

  const confirmRebootAllHosts = useCallback(() => {
    confirm({
      title: 'Reboot All Hosts',
      message: `Reboot ALL hosts?\n\nEvery host will be unreachable for ~1-2 minutes while it restarts.`,
      confirmText: 'Reboot',
      confirmColor: 'error',
      onConfirm: () => {
        void rebootAllHosts();
      },
    });
  }, [confirm, rebootAllHosts]);

  const confirmRebootServer = useCallback((serverUrl: string) => {
    confirm({
      title: 'Reboot Server',
      message: `Reboot server "${serverUrl}"?\n\nThe server will be unreachable for ~1-2 minutes while it restarts.`,
      confirmText: 'Reboot',
      confirmColor: 'error',
      onConfirm: () => {
        void handleRebootServer(serverUrl);
      },
    });
  }, [confirm, handleRebootServer]);

  const getDeviceIcon = (deviceModel: string) => {
    switch (deviceModel) {
      case 'android_mobile':
        return <PhoneIcon color="primary" />;
      case 'android_tv':
        return <TvIcon color="secondary" />;
      default:
        return <ComputerIcon color="info" />;
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
      return 'Unknown';
    }

    const now = Date.now() / 1000;
    const diff = Math.max(0, now - parsedTimestamp);

    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  };

  // Normalize a deployed_version string to its comparable build id (the
  // last "-" segment, e.g. "debug-2026.05.21-8731" -> "8731"), stripping an
  // optional "current:" prefix that VERSION.txt carries. Mirrors
  // CodeDeployment's extractHash so the two pages agree on equality.
  const normalizeVersion = (value?: string | null): string => {
    if (!value) return '';
    const cleaned = value.trim().replace(/^current\s*:/i, '');
    const parts = cleaned.split('-');
    return parts.length >= 2 ? parts[parts.length - 1] : cleaned;
  };

  // The server is the source of truth. A version is "mismatched" when both it
  // and the reference (server) version are known and their build ids differ.
  const isVersionMismatch = (
    version?: string | null,
    reference?: string | null,
  ): boolean =>
    !!version &&
    !!reference &&
    normalizeVersion(version) !== normalizeVersion(reference);

  // Strip the "current:" prefix VERSION.txt carries so only the build string
  // (e.g. "debug-2026.05.21-8731") is shown.
  const displayVersion = (value?: string | null): string => {
    if (!value) return 'unknown';
    return value.trim().replace(/^current\s*:/i, '') || 'unknown';
  };

  // Render a "<label>: <version>" caption (label optional). When the version
  // differs from `reference`, it turns red with an error badge whose tooltip
  // names the differing side (`referenceLabel`).
  const renderVersionLine = (
    label: string,
    version?: string | null,
    reference?: string | null,
    referenceLabel = 'Server',
  ) => {
    const mismatch = isVersionMismatch(version, reference);
    return (
      <Box display="flex" alignItems="center" gap={0.5}>
        {label && (
          <Typography color="textSecondary" variant="caption">
            {label}:
          </Typography>
        )}
        <Typography
          variant="caption"
          sx={{
            fontFamily: 'monospace',
            color: mismatch ? 'error.main' : 'text.secondary',
            fontWeight: mismatch ? 700 : 400,
          }}
        >
          {displayVersion(version)}
        </Typography>
        {mismatch && (
          <Tooltip title={`${referenceLabel} version differs (${displayVersion(reference)})`}>
            <VersionMismatchIcon color="error" sx={{ fontSize: 14 }} />
          </Tooltip>
        )}
      </Box>
    );
  };

  const formatRegisteredAt = (dateString: unknown) => {
    if (typeof dateString !== 'string' || dateString.trim() === '') {
      return 'Unknown';
    }

    const formatted = formatToLocalTime(dateString);
    if (!formatted || formatted === '-' || formatted.toLowerCase() === 'invalid date') {
      return 'Unknown';
    }

    return formatted;
  };

  const getUsageColor = (percentage: number) => {
    if (percentage >= 90) return 'error';
    if (percentage >= 75) return 'warning';
    if (percentage >= 50) return 'info';
    return 'success';
  };

  const getHostOperationalStatus = (host: Host): 'online' | 'degraded' | 'error' | 'unknown' => {
    const operationalStatus = host.system_stats?.operational_status;
    if (operationalStatus) return operationalStatus;

    return host.status === 'online' ? 'online' : 'error';
  };

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
    if (status === 'stopped' || status === 'error') return optional ? 'default' : 'error';
    return 'default';
  };

  const SystemStatsDisplay: React.FC<{ stats: Host['system_stats']; compact?: boolean }> = ({
    stats: systemStats,
    compact = false,
  }) => {
    if (!systemStats) {
      return (
        <Typography variant="caption" color="error">
          No system stats available
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

    return (
      <Box display="grid" gridTemplateColumns="1fr 1fr" gap={0.5}>
        {/* CPU */}
        <Box display="flex" alignItems="center" gap={0.5}>
          <Typography variant="caption" color="textSecondary">
            CPU:
          </Typography>
          <Typography variant="caption" fontWeight="bold" sx={{ minWidth: 32, textAlign: 'right' }}>
            {systemStats.cpu_percent}%
          </Typography>
          <Box sx={{ width: 30, height: 3, backgroundColor: 'grey.300', borderRadius: 1 }}>
            <Box
              sx={{
                width: `${Math.min(systemStats.cpu_percent, 100)}%`,
                height: '100%',
                backgroundColor: `${getUsageColor(systemStats.cpu_percent)}.main`,
                borderRadius: 1,
              }}
            />
          </Box>
        </Box>

        {/* Memory */}
        <Box display="flex" alignItems="center" gap={0.5}>
          <Typography variant="caption" color="textSecondary">
            RAM:
          </Typography>
          <Typography variant="caption" fontWeight="bold" sx={{ minWidth: 32, textAlign: 'right' }}>
            {systemStats.memory_percent}%
          </Typography>
          <Box sx={{ width: 30, height: 3, backgroundColor: 'grey.300', borderRadius: 1 }}>
            <Box
              sx={{
                width: `${Math.min(systemStats.memory_percent, 100)}%`,
                height: '100%',
                backgroundColor: `${getUsageColor(systemStats.memory_percent)}.main`,
                borderRadius: 1,
              }}
            />
          </Box>
        </Box>

        {!compact && (
          <>
            {/* Disk */}
            <Box display="flex" alignItems="center" gap={0.5}>
              <Typography variant="caption" color="textSecondary">
                Disk:
              </Typography>
              <Typography variant="caption" fontWeight="bold" sx={{ minWidth: 32, textAlign: 'right' }}>
                {systemStats.disk_percent}%
              </Typography>
              <Box sx={{ width: 30, height: 3, backgroundColor: 'grey.300', borderRadius: 1 }}>
                <Box
                  sx={{
                    width: `${Math.min(systemStats.disk_percent, 100)}%`,
                    height: '100%',
                    backgroundColor: `${getUsageColor(systemStats.disk_percent)}.main`,
                    borderRadius: 1,
                  }}
                />
              </Box>
            </Box>

            {/* Load Average */}
            {systemStats.load_average_1m !== undefined && (
              <Box display="flex" alignItems="center" gap={0.5}>
                <Typography variant="caption" color="textSecondary">
                  Load:
                </Typography>
                <Typography variant="caption" fontWeight="bold" sx={{ minWidth: 32, textAlign: 'right' }}>
                  {systemStats.load_average_1m.toFixed(1)}
                </Typography>
              </Box>
            )}
          </>
        )}
      </Box>
    );
  };

  const renderHostCard = (host: Host, serverVersion?: string | null) => (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        {(() => {
          const operationalStatus = getHostOperationalStatus(host);
          const services = host.system_stats?.service_health?.services || [];
          const downServices = getDownHostServices(host);
          return (
            <>
        {/* Host Header */}
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={1.5}>
          <Box display="flex" alignItems="center" gap={1}>
            <ComputerIcon color="primary" />
            <Typography variant="h6" component="div" noWrap>
              {host.host_name}
            </Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={1}>
            <Chip
              label={`${host.device_count} device${host.device_count > 1 ? 's' : ''}`}
              size="small"
              variant="outlined"
              sx={{ fontSize: '0.7rem' }}
            />
            <Chip
              label={operationalStatus}
              size="small"
              color={getOperationalStatusColor(operationalStatus)}
              variant="outlined"
            />
          </Box>
        </Box>

        <Typography color="textSecondary" variant="body2" gutterBottom>
          {host.host_api_url || host.host_url}
        </Typography>

        {/* System Stats - Compact */}
        <Box sx={{ mb: 1.5 }}>
          <Box
            display="flex"
            alignItems="center"
            justifyContent="space-between"
            sx={{ mb: 0.5 }}
          >
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
              System Stats
            </Typography>
            <Typography variant="caption" color="textSecondary">
              {host.system_stats?.platform} ({host.system_stats?.architecture})
            </Typography>
          </Box>
          <SystemStatsDisplay stats={host.system_stats} />
        </Box>

        {/* Devices - Collapsible Accordion */}
        <Accordion
          sx={{
            mb: 1.5,
            boxShadow: 'none',
            border: '1px solid #e0e0e0',
            backgroundColor: 'transparent',
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
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
              Devices ({host.device_count})
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 1, backgroundColor: 'transparent' }}>
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
                  <Typography
                    variant="body2"
                    sx={{ minWidth: '70px', fontWeight: 500, fontSize: '0.8rem' }}
                  >
                    {device.device_name}
                  </Typography>
                  <Chip
                    label={device.device_model}
                    size="small"
                    variant="outlined"
                    sx={{ fontSize: '0.6rem', height: '18px' }}
                  />
                  <DeviceInfoTooltipIcon
                    info={device.device_info}
                    gatewayInfo={device.gateway_info}
                    deviceName={device.device_name}
                    hostName={host.host_name}
                    fontSize={15}
                  />
                  {/* Optional-feature per-device shortcuts (docs/technical/FEATURES.md) */}
                  {featureDeviceLinks().map((link) => (
                    <Tooltip key={link.label} title={link.label}>
                      <IconButton
                        size="small"
                        sx={{ p: 0.25, color: 'text.secondary' }}
                        onClick={() => navigate(link.path(host.host_name, device.device_id))}
                      >
                        {link.icon}
                      </IconButton>
                    </Tooltip>
                  ))}
                  {device.device_ip && (
                    <Tooltip title={device.device_ip}>
                      <IpIcon
                        sx={{ ml: 'auto', fontSize: 15, color: 'text.secondary' }}
                      />
                    </Tooltip>
                  )}
                </Box>
              ))}
            </Box>
          </AccordionDetails>
        </Accordion>

        {/* Services - Collapsible Accordion */}
        <Accordion
          sx={{
            mb: 1.5,
            boxShadow: 'none',
            border: '1px solid #e0e0e0',
            backgroundColor: 'transparent',
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
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                Services ({services.length})
              </Typography>
              {/* Single, fixed-position activity spinner: shown while any
                  service/host action on this host is in flight, until the
                  success/failure toast. Icons never move or hide. */}
              {(pendingService?.startsWith(`${host.host_name}::`) ||
                autofixHost === host.host_name ||
                isHostBusy(host.host_name)) && (
                <CircularProgress size={14} thickness={5} />
              )}
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 1, backgroundColor: 'transparent' }}>
            <Box sx={{ backgroundColor: 'transparent' }}>
              {services.length === 0 ? (
                <Typography variant="caption" color="textSecondary">
                  Service details not available
                </Typography>
              ) : (
                services.map((service) => {
                  const dispStatus =
                    optimisticStatus[`${host.host_name}::${service.name}`] ?? service.status;
                  return (
                  <Box
                    key={service.name}
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
                    <Typography
                      variant="body2"
                      sx={{ minWidth: '90px', fontWeight: 500, fontSize: '0.8rem' }}
                    >
                      {service.label}
                    </Typography>
                    {service.description && (
                      <Tooltip title={service.description}>
                        <InfoIcon
                          sx={{ fontSize: 14, color: 'text.disabled', cursor: 'help' }}
                        />
                      </Tooltip>
                    )}
                    <Chip
                      label={dispStatus}
                      size="small"
                      color={getServiceStatusColor(dispStatus, service.optional)}
                      variant="outlined"
                      sx={{ fontSize: '0.6rem', height: '18px' }}
                    />
                    <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center' }}>
                      <Tooltip
                        title={
                          ['stopped', 'inactive', 'not_installed'].includes(dispStatus)
                            ? 'No logs — service is not running'
                            : 'View logs'
                        }
                      >
                        <span>
                          <IconButton
                            size="small"
                            sx={{ p: 0.25 }}
                            disabled={['stopped', 'inactive', 'not_installed'].includes(
                              dispStatus,
                            )}
                            onClick={() =>
                              setLogsModal({
                                open: true,
                                serviceLabel: service.label,
                                logService: service.name,
                                logHostName: host.host_name,
                                streamDevices:
                                  service.name === 'vpt-stream'
                                    ? (host.devices || []).map((d) => ({
                                        device_id: d.device_id,
                                        device_name: d.device_name,
                                      }))
                                    : undefined,
                              })
                            }
                          >
                            <LogsIcon sx={{ fontSize: 16 }} />
                          </IconButton>
                        </span>
                      </Tooltip>
                      {(() => {
                        // vpt-host is the API serving this request: it can't be
                        // start/stop'd from here (no remote recovery), and its
                        // restart must use the dedicated detached path. Show all
                        // 3 icons for visual consistency but only enable restart.
                        const isVptHost = service.name === 'vpt-host';
                        if (
                          service.status === 'not_installed' ||
                          (!service.controllable && !isVptHost)
                        ) {
                          return null;
                        }
                        // While an action is pending, keep all 3 icons in
                        // place (just disabled) — never swap them for a
                        // spinner: that hides/shifts the icons and flashes.
                        const busy = isHostBusy(host.host_name) || pendingService !== null;
                        return (
                          <>
                            <IconButton
                              size="small"
                              color="success"
                              sx={{ p: 0.25 }}
                              disabled={isVptHost || busy || dispStatus === 'active'}
                              onClick={() => controlService(host.host_name, service, 'start')}
                            >
                              <StartIcon sx={{ fontSize: 16 }} />
                            </IconButton>
                            <IconButton
                              size="small"
                              color="error"
                              sx={{ p: 0.25 }}
                              disabled={isVptHost || busy || dispStatus === 'stopped'}
                              onClick={() => controlService(host.host_name, service, 'stop')}
                            >
                              <StopIcon sx={{ fontSize: 16 }} />
                            </IconButton>
                            <IconButton
                              size="small"
                              color="info"
                              sx={{ p: 0.25 }}
                              disabled={busy}
                              onClick={() =>
                                isVptHost
                                  ? restartHostService(host.host_name)
                                  : controlService(host.host_name, service, 'restart')
                              }
                            >
                              <RestartServiceIcon sx={{ fontSize: 16 }} />
                            </IconButton>
                          </>
                        );
                      })()}
                    </Box>
                  </Box>
                  );
                })
              )}
            </Box>
          </AccordionDetails>
        </Accordion>

        {/* Per-Host System Controls */}
        <Box display="flex" alignItems="center" justifyContent="center" gap={0.5} sx={{ mb: 1 }}>
          <Tooltip title="Restart vpt-host service">
            <span>
              <IconButton
                onClick={() => restartHostService(host.host_name)}
                disabled={isHostBusy(host.host_name)}
                size="small"
                color="warning"
              >
                {getHostActionType(host.host_name) === 'service' ? <CircularProgress size={18} color="warning" /> : <RestartServiceIcon fontSize="small" />}
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Reboot">
            <span>
              <IconButton
                onClick={() => confirmRebootHost(host.host_name)}
                disabled={isHostBusy(host.host_name)}
                size="small"
                color="error"
              >
                {getHostActionType(host.host_name) === 'reboot' ? <CircularProgress size={18} color="error" /> : <RebootIcon fontSize="small" />}
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Restart streams">
            <span>
              <IconButton
                onClick={() => handleRestartStreams(host.host_name)}
                disabled={isHostBusy(host.host_name)}
                size="small"
                color="info"
              >
                {getHostActionType(host.host_name) === 'stream' ? <CircularProgress size={18} color="info" /> : <RestartStreamIcon fontSize="small" />}
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip
            title={
              downServices.length > 0
                ? `Auto-fix ${downServices.length} down service${downServices.length > 1 ? 's' : ''}: ${downServices.map((s) => s.label).join(', ')}`
                : 'All services healthy'
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
                size="small"
                color="success"
              >
                {autofixHost === host.host_name ? <CircularProgress size={18} color="success" /> : <AutofixIcon fontSize="small" />}
              </IconButton>
            </span>
          </Tooltip>
        </Box>

        {renderVersionLine('', host.deployed_version, serverVersion)}

        <Typography color="textSecondary" variant="caption" display="block">
          Last seen: {formatLastSeen(host.last_seen)}
        </Typography>

        <Typography color="textSecondary" variant="caption" display="block">
          Registered: {formatRegisteredAt(host.registered_at)}
        </Typography>
            </>
          );
        })()}
      </CardContent>
    </Card>
  );

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  const totalDevices = filteredServerHostsData.reduce(
    (total, serverData) => total + serverData.hosts.reduce((hostTotal, host) => hostTotal + (host.device_count || 0), 0),
    0
  );
  const totalHosts = filteredServerHostsData.reduce((total, serverData) => total + serverData.hosts.length, 0);

  if (isMobile || isTablet) {
    return (
      <Box>
        {!isMobile && (
          <Typography variant="h4" component="h1" mb={1}>
            Dashboard
          </Typography>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {error}
          </Alert>
        )}

        {/* The desktop navbar carries the server picker, and mobile does not render that
            navbar at all — so on a phone there was no way to switch server. It sits above the
            device filters because it scopes them: the targets and models below are whichever
            this server knows about. */}
        <Box sx={{ mb: 1 }}>
          <ServerSelector size="small" minWidth={160} />
        </Box>

        <Box sx={{ mb: 1 }}>
          <DeviceFilterBar
            targetFilter={targetFilter}
            onTargetFilterChange={setTargetFilter}
            deviceModelFilter={deviceModelFilter}
            onDeviceModelFilterChange={setDeviceModelFilter}
            flagFilter={flagFilter}
            onFlagFilterChange={setFlagFilter}
            targetOptions={targetOptions}
            uniqueDeviceModels={uniqueDeviceModels}
            uniqueFlags={uniqueFlags}
            hasActiveFilters={hasActiveFilters}
            onClearFilters={clearFilters}
            isMobile={isMobile}
            targetPlaceholder="All Targets"
          />
        </Box>

        <Paper sx={{ p: 1.25 }}>
          <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
            <Box display="flex" alignItems="center" gap={1}>
              <Typography variant="subtitle1">Hosts</Typography>
              {(errorHostCount > 0 || errorOnly) && (
                <Tooltip
                  title={
                    errorOnly
                      ? 'Showing only hosts with errors — tap to show all'
                      : 'Show only hosts with errors'
                  }
                >
                  <Chip
                    icon={<ErrorBadgeIcon />}
                    label={`${errorHostCount}`}
                    size="small"
                    color="error"
                    variant={errorOnly ? 'filled' : 'outlined'}
                    onClick={() => setErrorOnly((v) => !v)}
                    sx={{ cursor: 'pointer', height: 22 }}
                  />
                </Tooltip>
              )}
            </Box>
            <Box display="flex" gap={0.5}>
              <Tooltip title="Restart host service">
                <span>
                  <IconButton onClick={() => restartAllServices()} disabled={isRestartingService} size="small" color="warning">
                    <RestartServiceIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="Restart streams">
                <span>
                  <IconButton onClick={() => restartAllStreams()} disabled={isRestarting} size="small" color="info">
                    <RestartStreamIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
            </Box>
          </Box>

          {filteredServerHostsData.length === 0 ? (
            <Alert severity="info">{hasActiveFilters ? 'No hosts match the selected filters.' : 'No servers connected'}</Alert>
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
                        border: '1px solid #e0e0e0',
                        backgroundColor: 'transparent',
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
                            {serverData.server_info.server_name} Services ({services.length})
                          </Typography>
                          <Chip
                            label={serviceHealth.overall_status || 'unknown'}
                            size="small"
                            color={getOperationalStatusColor(serviceHealth.overall_status || 'unknown')}
                            variant="outlined"
                            sx={{ fontSize: '0.65rem', height: '18px' }}
                          />
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 1, backgroundColor: 'transparent' }}>
                        {services.map((service) => (
                          <Box
                            key={`${serverData.server_info.server_url}-${service.name}`}
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
                            <Typography
                              variant="body2"
                              sx={{ minWidth: '110px', fontWeight: 500, fontSize: '0.8rem' }}
                            >
                              {service.label}
                            </Typography>
                            <Chip
                              label={service.status}
                              size="small"
                              color={getServiceStatusColor(service.status, service.optional)}
                              variant="outlined"
                              sx={{ fontSize: '0.6rem', height: '18px' }}
                            />
                          </Box>
                        ))}
                      </AccordionDetails>
                    </Accordion>
                  );
                })}
              </Box>

              <Grid container spacing={isMobile ? 1 : 1.5}>
                {filteredServerHostsData.flatMap((serverData) =>
                  serverData.hosts.map((host) => {
                    const operationalStatus = getHostOperationalStatus(host);
                    return (
                      <Grid item xs={12} md={6} key={host.host_name}>
                        <Card variant="outlined">
                          <CardContent sx={{ py: 1.25 }}>
                            <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}>
                              <Typography variant="subtitle1" noWrap>{host.host_name}</Typography>
                              <Chip
                                label={operationalStatus}
                                size="small"
                                color={getOperationalStatusColor(operationalStatus)}
                                variant="outlined"
                              />
                            </Box>
                            <SystemStatsDisplay stats={host.system_stats} compact />
                            <Box sx={{ mt: 0.75, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                              {host.devices.slice(0, 2).map((device) => (
                                <Chip
                                  key={device.device_id}
                                  size="small"
                                  variant="outlined"
                                  label={`${device.device_name} (${device.device_model})`}
                                />
                              ))}
                              {host.devices.length > 2 ? (
                                <Chip size="small" label={`+${host.devices.length - 2} more`} />
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
      {/* Dashboard Header + Filters */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="h4" component="h1">
          Dashboard
        </Typography>
        <DeviceFilterBar
          targetFilter={targetFilter}
          onTargetFilterChange={setTargetFilter}
          deviceModelFilter={deviceModelFilter}
          onDeviceModelFilterChange={setDeviceModelFilter}
          flagFilter={flagFilter}
          onFlagFilterChange={setFlagFilter}
          flagMatchMode={flagMatchMode}
          onFlagMatchModeChange={setFlagMatchMode}
          targetOptions={targetOptions}
          uniqueDeviceModels={uniqueDeviceModels}
          uniqueFlags={uniqueFlags}
          hasActiveFilters={hasActiveFilters}
          onClearFilters={clearFilters}
          targetPlaceholder="All Targets"
        />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}

      {/* Connected Devices */}
      <Paper sx={{ p: 2, mt: 3 }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
          <Box display="flex" alignItems="center" gap={1.5}>
            <Typography variant="h6">
              Registered Servers ({filteredServerHostsData.length}) -{' '}
              {totalHosts} Hosts -{' '}
              {totalDevices} Devices
            </Typography>
            {(errorHostCount > 0 || errorOnly) && (
              <Tooltip
                title={
                  errorOnly
                    ? 'Showing only hosts with errors — click to show all'
                    : 'Show only hosts with errors'
                }
              >
                <Chip
                  icon={<ErrorBadgeIcon />}
                  label={`${errorHostCount} in error`}
                  size="small"
                  color="error"
                  variant={errorOnly ? 'filled' : 'outlined'}
                  onClick={() => setErrorOnly((v) => !v)}
                  sx={{ cursor: 'pointer' }}
                />
              </Tooltip>
            )}
          </Box>
          <Box display="flex" alignItems="center" gap={1}>
            {/* Global System Controls */}
            <Tooltip title="Restart vpt-host service on all hosts">
              <span>
                <IconButton
                  onClick={() => restartAllServices()}
                  disabled={isRestartingService}
                  size="small"
                  color="warning"
                >
                  <RestartServiceIcon />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="Reboot all hosts">
              <span>
                <IconButton
                  onClick={() => confirmRebootAllHosts()}
                  disabled={isRebooting}
                  size="small"
                  color="error"
                >
                  <RebootIcon />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="Restart streams on all hosts">
              <span>
                <IconButton
                  onClick={() => restartAllStreams()}
                  disabled={isRestarting}
                  size="small"
                  color="info"
                >
                  <RestartStreamIcon />
                </IconButton>
              </span>
            </Tooltip>
            
            <Tooltip title="Hosts automatically refresh">
              <span>
                <IconButton disabled size="small">
                  <RefreshIcon />
                </IconButton>
              </span>
            </Tooltip>
          </Box>
        </Box>

        {filteredServerHostsData.length > 0 ? (
          filteredServerHostsData.map((serverData, index) => {
            const hostCount = serverData.hosts.length;
            const deviceCount = serverData.hosts.reduce((total, host) => total + (host.device_count || 0), 0);
            
            return (
              <Box 
                key={index} 
                sx={{ 
                  backgroundColor: 'transparent', 
                  borderRadius: 2, 
                  p: 2, 
                  mb: 2,
                  border: '1px solid',
                  borderColor: 'grey.200'
                }}
              >
                <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
                  <Box display="flex" alignItems="center" gap={2}>
                    <Typography variant="h6">
                      Server: {serverData.server_info.server_name} - {serverData.server_info.server_url_display}
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
                    {/* Compact Server Stats */}
                    {serverData.server_info.system_stats && (
                      <Box display="flex" alignItems="center" gap={1}>
                        <Chip 
                          label={`CPU: ${serverData.server_info.system_stats.cpu_percent.toFixed(0)}%`}
                          size="small"
                          sx={{ 
                            height: 20, 
                            fontSize: '0.7rem',
                            bgcolor: `${getUsageColor(serverData.server_info.system_stats.cpu_percent)}.100`,
                            color: 'text.primary'
                          }}
                        />
                        <Chip 
                          label={`RAM: ${serverData.server_info.system_stats.memory_percent.toFixed(0)}%`}
                          size="small"
                          sx={{ 
                            height: 20, 
                            fontSize: '0.7rem',
                            bgcolor: `${getUsageColor(serverData.server_info.system_stats.memory_percent)}.100`,
                            color: 'text.primary'
                          }}
                        />
                        <Chip 
                          label={`Disk: ${serverData.server_info.system_stats.disk_percent.toFixed(0)}%`}
                          size="small"
                          sx={{ 
                            height: 20, 
                            fontSize: '0.7rem',
                            bgcolor: `${getUsageColor(serverData.server_info.system_stats.disk_percent)}.100`,
                            color: 'text.primary'
                          }}
                        />
                        {serverData.server_info.system_stats.cpu_temperature_celsius && (
                          <Chip 
                            label={`${serverData.server_info.system_stats.cpu_temperature_celsius.toFixed(0)}°C`}
                            size="small"
                            sx={{ height: 20, fontSize: '0.7rem' }}
                          />
                        )}
                        {serverData.server_info.system_stats.load_average_1m !== undefined && (
                          <Chip 
                            label={`Load: ${serverData.server_info.system_stats.load_average_1m.toFixed(1)}`}
                            size="small"
                            sx={{ height: 20, fontSize: '0.7rem' }}
                          />
                        )}
                      </Box>
                    )}
                  </Box>
                  <Box display="flex" alignItems="center" gap={2}>
                    <Chip 
                      label={`${hostCount} host${hostCount !== 1 ? 's' : ''}`}
                      size="small"
                      variant="outlined"
                      color="primary"
                    />
                    <Chip 
                      label={`${deviceCount} device${deviceCount !== 1 ? 's' : ''}`}
                      size="small"
                      variant="outlined"
                      color="secondary"
                    />
                    <Tooltip title="Restart vpt-server service">
                      <span>
                        <IconButton 
                          onClick={() => handleRestartServerService(serverData.server_info.server_url)} 
                          disabled={isRestartingServerService}
                          size="small"
                          color="warning"
                        >
                          <RestartServiceIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title="Reboot server">
                      <span>
                        <IconButton 
                          onClick={() => confirmRebootServer(serverData.server_info.server_url)}
                          disabled={isRebootingServer}
                          size="small"
                          color="error"
                        >
                          <RebootIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </Box>
                </Box>

                {/* Server Services - Collapsible Accordion */}
                {serverData.server_info.service_health && (
                  <Accordion
                    sx={{
                      mb: 2,
                      boxShadow: 'none',
                      border: '1px solid #e0e0e0',
                      backgroundColor: 'transparent',
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
                      <Box display="flex" alignItems="center" gap={1}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                          Server Services ({serverData.server_info.service_health.services?.length || 0})
                        </Typography>
                        <Chip
                          label={serverData.server_info.service_health.overall_status || 'unknown'}
                          size="small"
                          color={getOperationalStatusColor(serverData.server_info.service_health.overall_status || 'unknown')}
                          variant="outlined"
                          sx={{ fontSize: '0.65rem', height: '18px' }}
                        />
                      </Box>
                    </AccordionSummary>
                    <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 1, backgroundColor: 'transparent' }}>
                      <Box sx={{ backgroundColor: 'transparent' }}>
                        {(serverData.server_info.service_health.services || []).length === 0 ? (
                          <Typography variant="caption" color="textSecondary">
                            Service details not available
                          </Typography>
                        ) : (
                          (serverData.server_info.service_health.services || []).map((service) => (
                            <Box
                              key={service.name}
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
                              <Typography
                                variant="body2"
                                sx={{ minWidth: '110px', fontWeight: 500, fontSize: '0.8rem' }}
                              >
                                {service.label}
                              </Typography>
                              <Tooltip title={service.detail || ''}>
                                <Chip
                                  label={service.status}
                                  size="small"
                                  color={getServiceStatusColor(service.status, service.optional)}
                                  variant="outlined"
                                  sx={{ fontSize: '0.6rem', height: '18px' }}
                                />
                              </Tooltip>
                            </Box>
                          ))
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
                <Typography color="textSecondary">No hosts connected to this server</Typography>
              )}
            </Box>
          )})
        ) : (
          <Box textAlign="center" py={4}>
            <DevicesIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
            <Typography color="textSecondary" variant="h6" gutterBottom>
              {hasActiveFilters ? 'No hosts match the selected filters' : 'No servers connected'}
            </Typography>
          </Box>
        )}
      </Paper>

      {/* System Status */}
      <Paper sx={{ p: 1, mt: 3 }}>
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6} md={3} key="api-server">
            <Box display="flex" alignItems="center" gap={1}>
              <SuccessIcon color="success" />
              <Typography>API Server: Online</Typography>
            </Box>
          </Grid>
          <Grid item xs={12} sm={6} md={3} key="database">
            <Box display="flex" alignItems="center" gap={1}>
              <SuccessIcon color="success" />
              <Typography>Database: Connected</Typography>
            </Box>
          </Grid>
        </Grid>
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

export default Dashboard;
