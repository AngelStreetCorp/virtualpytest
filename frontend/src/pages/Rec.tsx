import { Computer as ComputerIcon, Dashboard as DashboardIcon, Edit as EditIcon, FactCheck as DeviceInfoIcon } from '@mui/icons-material';
import {
  Box,
  Typography,
  Alert,
  Grid,
  CircularProgress,
  Chip,
  Stack,
  Button,
  TextField,
  Autocomplete,
  Backdrop,
  InputAdornment,
  Divider,
  IconButton,
  Tooltip,
  Pagination,
  keyframes,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import React, { useEffect, useState, useMemo, useCallback, memo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { DeviceFilterBar } from '../components/common/DeviceFilterBar';
import { MobileHeaderActions } from '../components/common/MobileHeaderActions';
import { RecHostPreview } from '../components/rec/RecHostPreview';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useRec } from '../hooks/pages/useRec';
import { useDeviceFlags } from '../hooks/useDeviceFlags';
import { useServerManager } from '../hooks/useServerManager';
import { getDeviceTargetLabel, useDeviceFilters } from '../hooks/useDeviceFilters';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { REC_LIVE_TILE_LIMIT } from '../config/constants';
import { Host, Device } from '../types/common/Host_Types';
import { RecHostStreamModal } from '../components/rec/RecHostStreamModal';
import { GroupControlModal } from '../components/rec/group/GroupControlModal';
import { GroupSelectBar } from '../components/rec/group/GroupSelectBar';
import { useGroupSelection } from '../hooks/rec/useGroupSelection';
import { DeviceLayout } from '../components/rec/layout/DeviceLayout';
import { ViewMenu } from '../components/rec/layout/ViewMenu';
import { useDeviceView } from '../hooks/rec/useDeviceView';
import { useLayoutOrder } from '../hooks/rec/useLayoutOrder';
import { GRID_VIEWS, findView } from '../constants/deviceLayouts';
import { useI18n } from '../i18n/useI18n';
import type { GroupCandidate, GroupSelection } from '../types/pages/groupControl.types';
import type { LiveStreamTransport, WhepStatus } from '../types/controller/WebRTC_Types';

const DEVICE_KEY_SEPARATOR = '::';

const buildDeviceKey = (hostName: string, deviceId: string) => `${hostName}${DEVICE_KEY_SEPARATOR}${deviceId}`;

const parseDeviceKey = (deviceKey: string) => {
  const separatorIndex = deviceKey.indexOf(DEVICE_KEY_SEPARATOR);
  if (separatorIndex === -1) {
    return { hostName: '', deviceId: deviceKey };
  }

  return {
    hostName: deviceKey.slice(0, separatorIndex),
    deviceId: deviceKey.slice(separatorIndex + DEVICE_KEY_SEPARATOR.length),
  };
};

const normalizeFlags = (flags: string[]) => {
  const seen = new Set<string>();

  return flags.reduce<string[]>((acc, flag) => {
    const trimmed = flag.trim();
    if (!trimmed) return acc;

    const normalizedKey = trimmed.toLowerCase();
    if (seen.has(normalizedKey)) return acc;

    seen.add(normalizedKey);
    acc.push(trimmed);
    return acc;
  }, []);
};

// Optimized memoization with deep comparison to prevent re-renders from object reference changes
const MemoizedRecHostPreview = memo(RecHostPreview, (prevProps, nextProps) => {
  // Quick reference check first - if references are same, no need for deep comparison
  if (
    prevProps.host === nextProps.host &&
    prevProps.device === nextProps.device &&
    prevProps.isEditMode === nextProps.isEditMode &&
    prevProps.isSelected === nextProps.isSelected &&
    prevProps.deviceFlags === nextProps.deviceFlags &&
    prevProps.activeFlagFilters === nextProps.activeFlagFilters &&
    prevProps.onFlagClick === nextProps.onFlagClick &&
    prevProps.onSelectionChange === nextProps.onSelectionChange &&
    prevProps.onOpenModal === nextProps.onOpenModal &&
    prevProps.isAnyModalOpen === nextProps.isAnyModalOpen &&
    prevProps.isSelectedForModal === nextProps.isSelectedForModal &&
    prevProps.persistentStreamTarget === nextProps.persistentStreamTarget &&
    prevProps.persistentStreamMuted === nextProps.persistentStreamMuted &&
    prevProps.persistentStreamInteractive === nextProps.persistentStreamInteractive &&
    prevProps.persistentStreamShouldPause === nextProps.persistentStreamShouldPause &&
    prevProps.persistentStreamOnReady === nextProps.persistentStreamOnReady &&
    prevProps.persistentStreamTransport === nextProps.persistentStreamTransport &&
    prevProps.persistentStreamReconnectKey === nextProps.persistentStreamReconnectKey &&
    prevProps.persistentStreamOnWebRTCFailed === nextProps.persistentStreamOnWebRTCFailed &&
    prevProps.persistentStreamOnWebRTCStatusChange === nextProps.persistentStreamOnWebRTCStatusChange &&
    prevProps.groupStreamTarget === nextProps.groupStreamTarget &&
    prevProps.snapshotMode === nextProps.snapshotMode
  ) {
    return true; // Props haven't changed, skip re-render
  }

  // Deep comparison when references differ
  const areEqual = (
    prevProps.host.host_name === nextProps.host.host_name &&
    prevProps.device?.device_id === nextProps.device?.device_id &&
    prevProps.isEditMode === nextProps.isEditMode &&
    prevProps.isSelected === nextProps.isSelected &&
    JSON.stringify(prevProps.deviceFlags) === JSON.stringify(nextProps.deviceFlags) &&
    JSON.stringify(prevProps.activeFlagFilters) === JSON.stringify(nextProps.activeFlagFilters) &&
    JSON.stringify(prevProps.host) === JSON.stringify(nextProps.host) &&
    JSON.stringify(prevProps.device) === JSON.stringify(nextProps.device) &&
    prevProps.onFlagClick === nextProps.onFlagClick &&
    prevProps.onSelectionChange === nextProps.onSelectionChange &&
    prevProps.onOpenModal === nextProps.onOpenModal &&
    prevProps.isAnyModalOpen === nextProps.isAnyModalOpen &&
    prevProps.isSelectedForModal === nextProps.isSelectedForModal && // Handler should be stable now
    prevProps.persistentStreamTarget === nextProps.persistentStreamTarget &&
    prevProps.persistentStreamMuted === nextProps.persistentStreamMuted &&
    prevProps.persistentStreamInteractive === nextProps.persistentStreamInteractive &&
    prevProps.persistentStreamShouldPause === nextProps.persistentStreamShouldPause &&
    prevProps.persistentStreamOnReady === nextProps.persistentStreamOnReady &&
    prevProps.persistentStreamTransport === nextProps.persistentStreamTransport &&
    prevProps.persistentStreamReconnectKey === nextProps.persistentStreamReconnectKey &&
    prevProps.persistentStreamOnWebRTCFailed === nextProps.persistentStreamOnWebRTCFailed &&
    prevProps.persistentStreamOnWebRTCStatusChange === nextProps.persistentStreamOnWebRTCStatusChange &&
    prevProps.groupStreamTarget === nextProps.groupStreamTarget &&
    prevProps.snapshotMode === nextProps.snapshotMode
  );

  return areEqual; // Return true to skip re-render, false to re-render
});

// REC page - directly uses the global HostManagerProvider from App.tsx
// No local HostManagerProvider needed since we only need AV capability filtering
// Memoized to prevent re-renders when HostManagerProvider updates (e.g., take/release control)
const RecContent: React.FC<ReturnType<typeof useRec>> = memo(({
  avDevices: rawAvDevices,
  isLoading,
  error,
}) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const { isMobile, isTablet } = useResponsiveMode();
  // Server change transition state - blocks UI during stream initialization
  const { isServerChanging, selectedServer } = useServerManager();
  const { isDeviceAllowed } = useWorkspaceContext();
  const navigate = useNavigate();

  // Drop devices hidden by the active workspace before applying the page's
  // own target/model/flag filters.
  const avDevices = useMemo(
    () => rawAvDevices.filter(({ host, device }) => isDeviceAllowed(host.host_name, device.device_id)),
    [rawAvDevices, isDeviceAllowed],
  );
  
  // Device flags hook
  const { deviceFlags, uniqueFlags, batchUpdateDeviceFlags, isLoading: isFlagsLoading } = useDeviceFlags();

  // Target/model/tag filters — persisted and shared with the Dashboard page.
  const {
    targetFilter,
    setTargetFilter,
    deviceModelFilter,
    setDeviceModelFilter,
    flagFilter,
    setFlagFilter,
    flagMatchMode,
    setFlagMatchMode,
  } = useDeviceFilters();
  // View (TASK-75): Grid 12/24/48 (scrolls, TASK-48 page sizes) or a layout that fits the
  // screen. Persisted per browser. Phones always use the grid. Current page is plain
  // state — it resets when filters or the view change (see effect below).
  const { view: storedView, setView } = useDeviceView(!isMobile);
  const view = isMobile && storedView.kind === 'layout' ? findView('grid24')! : storedView;
  const pageSize = view.kind === 'grid' ? view.pageSize : view.slots;
  const [page, setPage] = useState(1);

  // Edit mode state
  const [isEditMode, setIsEditMode] = useState(false);
  const [selectedDevices, setSelectedDevices] = useState<Set<string>>(new Set());
  const [pendingChanges, setPendingChanges] = useState<Map<string, string[]>>(new Map());
  const [isSaving, setIsSaving] = useState(false);
  const [pendingTags, setPendingTags] = useState<string[]>([]);
  const [tagInputValue, setTagInputValue] = useState('');

  // Group control (TASK-76): the chosen remote profile defines the group,
  // and any device that owns that profile can join. The selectable pool
  // is the workspace-filtered device list so the per-model badge row can
  // fill the group from every available candidate, not only the ones the
  // operator has already clicked. Built after `filteredDevices` below.
  const [openGroup, setOpenGroup] = useState<GroupSelection | null>(null);
  // Group modal cell slots by device key: a live page tile moves its player into its slot,
  // like the single stream modal does, so Control does not start a second stream per device.
  const [groupStreamTargets, setGroupStreamTargets] = useState<ReadonlyMap<string, HTMLElement>>(new Map());
  const handleGroupStreamSlot = useCallback((key: string, el: HTMLElement | null) => {
    setGroupStreamTargets((prev) => {
      if ((prev.get(key) ?? null) === el) return prev;
      const next = new Map(prev);
      if (el) next.set(key, el);
      else next.delete(key);
      return next;
    });
  }, []);

  // Modal state
  const [modalHost, setModalHost] = useState<Host | null>(null);
  const [modalDevice, setModalDevice] = useState<Device | null>(null);
  const [modalPoster, setModalPoster] = useState<string | null>(null);
  const [modalStreamTarget, setModalStreamTarget] = useState<HTMLElement | null>(null);
  const [modalStreamMuted, setModalStreamMuted] = useState(true);
  const [modalStreamInteractive, setModalStreamInteractive] = useState(false);
  const [modalCanReuseStream, setModalCanReuseStream] = useState(false);
  const [modalStreamShouldPause, setModalStreamShouldPause] = useState(false);
  const [modalStreamOnReady, setModalStreamOnReady] = useState<(() => void) | undefined>();
  const [modalStreamTransport, setModalStreamTransport] = useState<LiveStreamTransport>('hls');
  const [modalStreamReconnectKey, setModalStreamReconnectKey] = useState<string>();
  const [modalWebRTCFailed, setModalWebRTCFailed] = useState<(() => void) | undefined>();
  const [modalWebRTCStatusChange, setModalWebRTCStatusChange] = useState<((status: WhepStatus) => void) | undefined>();

  const openModal = useCallback((host: Host, device: Device, poster?: string | null, canReuseStream = false) => {
    setModalHost(host);
    setModalDevice(device);
    setModalPoster(poster ?? null);
    setModalCanReuseStream(canReuseStream);
  }, []);

  const closeModal = useCallback(() => {
    requestAnimationFrame(() => {
      setModalHost(null);
      setModalDevice(null);
      setModalPoster(null);
      setModalStreamTarget(null);
      setModalStreamMuted(true);
      setModalStreamInteractive(false);
      setModalCanReuseStream(false);
      setModalStreamShouldPause(false);
      setModalStreamOnReady(undefined);
      setModalStreamTransport('hls');
      setModalStreamReconnectKey(undefined);
      setModalWebRTCFailed(undefined);
      setModalWebRTCStatusChange(undefined);
    });
  }, []);

  const handlePersistentStreamState = useCallback(({
    muted,
    interactive,
    shouldPause,
    onPlayerReady,
    transport,
    reconnectKey,
    onWebRTCFailed,
    onWebRTCStatusChange,
  }: {
    muted: boolean;
    interactive: boolean;
    shouldPause: boolean;
    onPlayerReady: () => void;
    transport: LiveStreamTransport;
    reconnectKey: string;
    onWebRTCFailed: () => void;
    onWebRTCStatusChange: (status: WhepStatus) => void;
  }) => {
    setModalStreamMuted(muted);
    setModalStreamInteractive(interactive);
    setModalStreamShouldPause(shouldPause);
    setModalStreamOnReady(() => onPlayerReady);
    setModalStreamTransport(transport);
    setModalStreamReconnectKey(reconnectKey);
    setModalWebRTCFailed(() => onWebRTCFailed);
    setModalWebRTCStatusChange(() => onWebRTCStatusChange);
  }, []);

  // Get unique target labels and device models for filter controls
  const { targetOptions, uniqueDeviceModels } = useMemo(() => {
    const targets = new Set<string>();
    const deviceModels = new Set<string>();

    avDevices.forEach(({ host, device }) => {
      targets.add(getDeviceTargetLabel(host, device));
      if (device.device_model) {
        deviceModels.add(device.device_model);
      }
    });

    return {
      targetOptions: Array.from(targets).sort(),
      uniqueDeviceModels: Array.from(deviceModels).sort(),
    };
  }, [avDevices]);

  // Filter devices based on selected filters
  const filteredDevices = useMemo(() => {
    return avDevices
      .filter(({ host, device }) => {
      // Target filter values come from the dropdown, which is populated with
      // exact target labels. Match exactly so selecting "example-v1" does not
      // also match "example-v1+" — substring matching kept unselected targets
      // visible.
      const matchesTarget =
        targetFilter.length === 0 || targetFilter.includes(getDeviceTargetLabel(host, device));
      const matchesDeviceModel = deviceModelFilter.length === 0 || (device.device_model && deviceModelFilter.includes(device.device_model));

      // Flag filtering — AND requires every selected tag, OR any one.
      let matchesFlag = true;
      if (flagFilter.length > 0) {
        const deviceFlag = deviceFlags.find((df: any) =>
          df.host_name === host.host_name && df.device_id === device.device_id
        );
        const deviceTags: string[] = deviceFlag?.flags || [];
        matchesFlag =
          flagMatchMode === 'AND'
            ? flagFilter.every((f) => deviceTags.includes(f))
            : flagFilter.some((f) => deviceTags.includes(f));
      }

      return matchesTarget && matchesDeviceModel && matchesFlag;
    })
      // Sort by the same label shown on each card so cards appear A→Z
      // (numeric-aware: vfr108 before vfr109).
      .sort((a, b) =>
        getDeviceTargetLabel(a.host, a.device).localeCompare(
          getDeviceTargetLabel(b.host, b.device),
          undefined,
          { numeric: true },
        ),
      );
  }, [avDevices, targetFilter, deviceModelFilter, flagFilter, flagMatchMode, deviceFlags]);

  // Reconcile persisted filter selections against the options that actually
  // exist in the current workspace. Switching workspaces changes avDevices (via
  // isDeviceAllowed) but leaves the localStorage-persisted filters untouched, so
  // a target/model/flag picked in another workspace would otherwise linger in
  // the filter bar and silently hide every device here ("No targets match").
  // Skip while loading so an empty option list mid-fetch doesn't wipe filters
  // legitimately restored from localStorage on refresh. `isLoading` stays true
  // until HostManager has actually copied the hosts in (BUG-0387).
  useEffect(() => {
    if (isLoading) return;
    const prune = (
      setter: React.Dispatch<React.SetStateAction<string[]>>,
      valid: string[],
    ) => {
      const validSet = new Set(valid);
      setter((prev) => {
        const next = prev.filter((v) => validSet.has(v));
        return next.length === prev.length ? prev : next;
      });
    };
    prune(setTargetFilter, targetOptions);
    prune(setDeviceModelFilter, uniqueDeviceModels);
    // Flags load separately from the device list — same rule, own loading flag.
    if (!isFlagsLoading) prune(setFlagFilter, uniqueFlags);
  }, [
    isLoading,
    isFlagsLoading,
    targetOptions,
    uniqueDeviceModels,
    uniqueFlags,
    setTargetFilter,
    setDeviceModelFilter,
    setFlagFilter,
  ]);

  // Total pages for the current filter result. Clamped to ≥1 so a filter that
  // wipes the grid still renders the empty-state Alert below instead of a
  // 0-page Pagination.
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredDevices.length / pageSize)),
    [filteredDevices.length, pageSize],
  );

  // Group control (TASK-76) — declared after `filteredDevices` because the
  // selectable pool is built from it. The chosen remote profile defines the
  // group; any device that owns it can join. The pool memo only consumes
  // data while the user is in group mode (the hook ignores it otherwise),
  // so the per-render cost is just a `.map` over the filtered list.
  const groupSelectablePool = useMemo(
    () => filteredDevices.map(({ host, device }) => ({
      key: buildDeviceKey(host.host_name, device.device_id),
      host,
      device,
    })),
    [filteredDevices],
  );
  const groupSelection = useGroupSelection(groupSelectablePool);

  // Layouts keep the operator's swaps (per layout); the grid keeps the filter order.
  const { ordered: layoutOrdered, swap: swapLayoutTiles, reset: resetLayoutOrder } = useLayoutOrder(
    view.id,
    filteredDevices,
    ({ host, device }) => buildDeviceKey(host.host_name, device.device_id),
  );
  const pageSource = view.kind === 'layout' ? layoutOrdered : filteredDevices;

  // Slice for the current page. Recomputed from the source + page so a
  // filter change (which resets `page` to 1) shows page 1 immediately.
  const paginatedDevices = useMemo(() => {
    const start = (page - 1) * pageSize;
    return pageSource.slice(start, start + pageSize);
  }, [pageSource, page, pageSize]);

  // Snapshot only when the tiles actually rendered exceed the live limit, so
  // ≤ REC_LIVE_TILE_LIMIT devices always play live whatever the page size.
  // Focus layouts: only the big slot plays live, thumbnails are snapshots (TASK-75 G6).
  const snapshotMode = paginatedDevices.length > REC_LIVE_TILE_LIMIT;
  const isFocusLayout = view.kind === 'layout' && !!view.focus;
  // Page tiles that play live (not snapshots) — only those have a player the group modal can reuse.
  const liveTileKeys = useMemo<ReadonlySet<string>>(() => {
    if (snapshotMode) return new Set();
    const live = isFocusLayout ? paginatedDevices.slice(0, 1) : paginatedDevices;
    return new Set(live.map(({ host, device }) => buildDeviceKey(host.host_name, device.device_id)));
  }, [snapshotMode, isFocusLayout, paginatedDevices]);

  // Reset to page 1 whenever the filter inputs change OR the page size
  // changes — filters can otherwise leave the user stranded on an empty page,
  // and switching page size keeps page 1 anchored to the top of the result.
  useEffect(() => {
    setPage(1);
  }, [targetFilter, deviceModelFilter, flagFilter, flagMatchMode, view.id]);

  // Clamp the page when devices disappear (workspace switch, host reload).
  // filteredDevices shrinks so the current page can become empty; without this
  // clamp the user sees a blank grid with a Pagination at "Page 5 of 2".
  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const handlePageChange = useCallback(
    (_event: React.ChangeEvent<unknown>, next: number) => {
      setPage(next);
    },
    [],
  );

  // Clear filters
  const clearFilters = () => {
    setTargetFilter([]);
    setDeviceModelFilter([]);
    setFlagFilter([]);
  };

  // Drop every filter when the user picks a different server in the Server
  // dropdown. The "All Targets / Models / Tags" picks are server-scoped (a
  // target on vpt-pi1 is not a target on vpt-pi3), so carrying the old
  // selection over leaves the new server with an empty result set and no
  // obvious way back. Skipped on the very first mount so the persisted
  // state survives a page reload.
  const previousServerRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (
      previousServerRef.current !== undefined &&
      previousServerRef.current !== selectedServer
    ) {
      clearFilters();
    }
    previousServerRef.current = selectedServer;
  }, [selectedServer]);

  // Toggle a single flag in the filter (clicked from preview badge)
  const toggleFlagFilter = useCallback((flag: string) => {
    setFlagFilter(prev => (prev.includes(flag) ? prev.filter(f => f !== flag) : [...prev, flag]));
  }, []);

  // Edit mode toggle handler — entering Edit mode also exits Group mode so
  // the bottom slot only ever holds one bar (BUG-0444). The two states were
  // orthogonal before, which let the page show both bars; the icon-button
  // refactor unified the bottom slot, so the modes are now mutually exclusive.
  const handleEditModeToggle = useCallback(() => {
    if (isEditMode) {
      // Exiting edit mode - clear selections and pending changes
      setIsEditMode(false);
      setSelectedDevices(new Set());
      setPendingChanges(new Map());
      setPendingTags([]);
      setTagInputValue('');
    } else {
      // Entering edit mode - exit group mode if it was on
      if (groupSelection.isGroupMode) {
        groupSelection.toggleGroupMode();
      }
      setIsEditMode(true);
    }
  }, [isEditMode, groupSelection]);

  // Group mode toggle handler — entering Group mode also exits Edit mode.
  // Symmetric to handleEditModeToggle.
  const handleGroupModeToggle = useCallback(() => {
    if (!groupSelection.isGroupMode && isEditMode) {
      // Entering group mode - exit edit mode
      setIsEditMode(false);
      setSelectedDevices(new Set());
      setPendingChanges(new Map());
      setPendingTags([]);
      setTagInputValue('');
    }
    groupSelection.toggleGroupMode();
  }, [groupSelection, isEditMode]);

  // Create stable selection handlers per device using refs
  const selectionHandlersRef = useRef<Map<string, (selected: boolean) => void>>(new Map());
  
  // Create or get stable handler for a device
  const getSelectionHandler = useCallback((deviceKey: string) => {
    if (!selectionHandlersRef.current.has(deviceKey)) {
      const handler = (selected: boolean) => {
        setSelectedDevices(prev => {
          const newSet = new Set(prev);
          if (selected) {
            newSet.add(deviceKey);
          } else {
            newSet.delete(deviceKey);
          }
          return newSet;
        });
      };
      selectionHandlersRef.current.set(deviceKey, handler);
    }
    return selectionHandlersRef.current.get(deviceKey)!;
  }, []);

  // Group-mode tile handlers, stable per device like the edit-mode ones above.
  const groupCandidateRef = useRef<Map<string, GroupCandidate>>(new Map());
  const groupHandlersRef = useRef<Map<string, (selected: boolean) => void>>(new Map());
  // The cached handlers outlive renders, so they call the latest toggle through a ref.
  const toggleGroupRef = useRef(groupSelection.toggle);
  toggleGroupRef.current = groupSelection.toggle;
  const getGroupSelectionHandler = useCallback((deviceKey: string) => {
    if (!groupHandlersRef.current.has(deviceKey)) {
      groupHandlersRef.current.set(deviceKey, () => {
        const candidate = groupCandidateRef.current.get(deviceKey);
        if (candidate) toggleGroupRef.current(candidate);
      });
    }
    return groupHandlersRef.current.get(deviceKey)!;
  }, []);

  const handleSelectAll = useCallback(() => {
    const allDeviceKeys = filteredDevices.map(({ host, device }) => buildDeviceKey(host.host_name, device.device_id));
    setSelectedDevices(new Set(allDeviceKeys));
  }, [filteredDevices]);

  const handleClearSelection = useCallback(() => {
    setSelectedDevices(new Set());
  }, []);

  // Clear only filtered device selections (keep selections for devices hidden by filters)
  const handleClearFilteredSelection = useCallback(() => {
    const filteredDeviceKeys = new Set(filteredDevices.map(({ host, device }) => buildDeviceKey(host.host_name, device.device_id)));
    setSelectedDevices(prev => {
      const newSet = new Set(prev);
      filteredDeviceKeys.forEach(deviceKey => newSet.delete(deviceKey));
      return newSet;
    });
  }, [filteredDevices]);

  // Memoize device flags lookup to prevent unnecessary re-renders
  const deviceFlagsMap = useMemo(() => {
    const map = new Map<string, string[]>();
    deviceFlags.forEach((df: any) => {
      const key = buildDeviceKey(df.host_name, df.device_id);
      map.set(key, df.flags || []);
    });
    return map;
  }, [deviceFlags]);

  // Get current flags for a device (considering pending changes) - memoized per device
  const getCurrentFlags = useCallback((hostName: string, deviceId: string): string[] => {
    const deviceKey = buildDeviceKey(hostName, deviceId);
    if (pendingChanges.has(deviceKey)) {
      return pendingChanges.get(deviceKey) || [];
    }
    return deviceFlagsMap.get(deviceKey) || [];
  }, [deviceFlagsMap, pendingChanges]);

  // Stable empty array to avoid creating new arrays on every render
  const emptyFlagsArray = useMemo(() => [], []);
  
  // Memoize device flags per device to prevent unnecessary re-renders
  const memoizedDeviceFlags = useMemo(() => {
    const flagsMap = new Map<string, string[]>();
    filteredDevices.forEach(({ host, device }) => {
      const deviceKey = buildDeviceKey(host.host_name, device.device_id);
      const flags = getCurrentFlags(host.host_name, device.device_id);
      // Use stable empty array reference for devices with no flags
      flagsMap.set(deviceKey, flags.length > 0 ? flags : emptyFlagsArray);
    });
    return flagsMap;
  }, [filteredDevices, getCurrentFlags, emptyFlagsArray]);

  // Bulk flag operations (now work with pending changes)
  const handleBulkAddFlag = useCallback((flag: string) => {
    const trimmedFlag = flag.trim();
    if (!trimmedFlag) return;
    
    setPendingChanges(prev => {
      const newChanges = new Map(prev);
      Array.from(selectedDevices).forEach(deviceKey => {
        const { hostName, deviceId } = parseDeviceKey(deviceKey);
        
        // Get current flags from either pending changes or device flags
        let currentFlags: string[];
        if (prev.has(deviceKey)) {
          currentFlags = prev.get(deviceKey) || [];
        } else {
          currentFlags = deviceFlags.find((df: any) => df.host_name === hostName && df.device_id === deviceId)?.flags || [];
        }
        
        if (!currentFlags.includes(trimmedFlag)) {
          const updatedFlags = normalizeFlags([...currentFlags, trimmedFlag]);
          newChanges.set(deviceKey, updatedFlags);
        }
      });
      return newChanges;
    });
  }, [selectedDevices, deviceFlags]);

  const handleBulkRemoveFlag = useCallback((flag: string) => {
    setPendingChanges(prev => {
      const newChanges = new Map(prev);
      Array.from(selectedDevices).forEach(deviceKey => {
        const { hostName, deviceId } = parseDeviceKey(deviceKey);
        
        // Get current flags from either pending changes or device flags
        let currentFlags: string[];
        if (prev.has(deviceKey)) {
          currentFlags = prev.get(deviceKey) || [];
        } else {
          currentFlags = deviceFlags.find((df: any) => df.host_name === hostName && df.device_id === deviceId)?.flags || [];
        }
        
        const updatedFlags = currentFlags.filter(f => f !== flag);
        newChanges.set(deviceKey, updatedFlags);
      });
      return newChanges;
    });
  }, [selectedDevices, deviceFlags]);

  const applyPendingTags = useCallback(() => {
    const trimmedInput = tagInputValue.trim();
    const combined = trimmedInput ? [...pendingTags, trimmedInput] : pendingTags;
    const tagsToApply = normalizeFlags(combined);
    if (tagsToApply.length === 0 || selectedDevices.size === 0) return;

    tagsToApply.forEach(tag => handleBulkAddFlag(tag));
    setPendingTags([]);
    setTagInputValue('');
  }, [handleBulkAddFlag, pendingTags, selectedDevices.size, tagInputValue]);

  // Save all pending changes
  const handleSaveChanges = useCallback(async () => {
    if (pendingChanges.size === 0) return;
    
    setIsSaving(true);
    try {
      const updates = Array.from(pendingChanges.entries()).map(([deviceKey, flags]) => {
        const { hostName, deviceId } = parseDeviceKey(deviceKey);
        return { hostName, deviceId, flags };
      });
      
      const success = await batchUpdateDeviceFlags(updates);
      if (success) {
        setPendingChanges(new Map());
        setSelectedDevices(new Set());
        setPendingTags([]);
        setTagInputValue('');
        setIsEditMode(false);
      }
    } catch (error) {
      console.error('Error saving changes:', error);
    } finally {
      setIsSaving(false);
    }
  }, [pendingChanges, batchUpdateDeviceFlags]);

  // Check if there are unsaved changes
  const hasUnsavedChanges = pendingChanges.size > 0;
  
  // Clean up stale selections when devices change
  useEffect(() => {
    if (isEditMode && selectedDevices.size > 0) {
      const currentDeviceKeys = new Set(avDevices.map(({ host, device }) => buildDeviceKey(host.host_name, device.device_id)));
      const staleSelections = Array.from(selectedDevices).filter(deviceKey => !currentDeviceKeys.has(deviceKey));
      
      if (staleSelections.length > 0) {
        setSelectedDevices(prev => {
          const newSet = new Set(prev);
          staleSelections.forEach(staleKey => newSet.delete(staleKey));
          return newSet;
        });
        
        // Also clean up stale pending changes
        setPendingChanges(prev => {
          const newMap = new Map(prev);
          staleSelections.forEach(staleKey => newMap.delete(staleKey));
          return newMap;
        });
      }
    }
  }, [avDevices, isEditMode, selectedDevices]);

  const hasActiveFilters = targetFilter.length > 0 || deviceModelFilter.length > 0 || flagFilter.length > 0;
  const filteredDeviceKeys = useMemo(
    () => new Set(filteredDevices.map(({ host, device }) => buildDeviceKey(host.host_name, device.device_id))),
    [filteredDevices]
  );
  const selectedFilteredCount = useMemo(
    () => Array.from(selectedDevices).filter(deviceKey => filteredDeviceKeys.has(deviceKey)).length,
    [filteredDeviceKeys, selectedDevices]
  );
  const selectedFlags = useMemo(() => {
    const counts = new Map<string, number>();

    Array.from(selectedDevices).forEach(deviceKey => {
      const { hostName, deviceId } = parseDeviceKey(deviceKey);
      const flags = getCurrentFlags(hostName, deviceId);
      flags.forEach(flag => counts.set(flag, (counts.get(flag) || 0) + 1));
    });

    return Array.from(counts.entries())
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([flag, count]) => ({ flag, count }));
  }, [getCurrentFlags, selectedDevices]);
  const editModeSummary = useMemo(() => {
    if (!isEditMode) return '';

    const parts: string[] = ['Tags Edit '];
    if (selectedDevices.size > selectedFilteredCount) {
      parts.push(`${selectedDevices.size - selectedFilteredCount} hidden by filters`);
    }
    if (hasUnsavedChanges) {
      parts.push(`${pendingChanges.size} unsaved changes`);
    }

    return parts.join(' • ');
  }, [
    hasUnsavedChanges,
    isEditMode,
    pendingChanges.size,
    selectedDevices.size,
    selectedFilteredCount,
  ]);

  // Flash the "X of Y selected" line whenever `selectedFilteredCount`
  // changes (BUG-0443). A useRef holds the last-seen count, the effect
  // bumps a counter on change, and the counter is the Typography's React
  // `key` — remounting replays the `countFlash` keyframe (a 0.7s gold
  // pulse that fades to transparent). The chip/select-all row never
  // reflows because the row keeps its existing 28 px minHeight and the
  // flash only animates the count text's background.
  const [selectedCountFlash, setSelectedCountFlash] = useState(0);
  const prevSelectedFilteredCountRef = useRef(selectedFilteredCount);
  useEffect(() => {
    if (prevSelectedFilteredCountRef.current !== selectedFilteredCount) {
      prevSelectedFilteredCountRef.current = selectedFilteredCount;
      setSelectedCountFlash((c) => c + 1);
    }
  }, [selectedFilteredCount]);
  const countFlash = keyframes`
    0%   { background-color: ${P.accent}40; }
    100% { background-color: transparent; }
  `;

  // One tile for both the grid and the layouts. In a focus layout slot 0 is the big live
  // stream (click opens the stream modal as today); a click on a thumbnail promotes it.
  const renderTile = (entry: { host: Host; device: Device }, { slotIndex }: { slotIndex?: number }) => {
    const { host, device } = entry;
    const deviceKey = buildDeviceKey(host.host_name, device.device_id);
    const candidate: GroupCandidate = { key: deviceKey, host, device };
    groupCandidateRef.current.set(deviceKey, candidate);
    const inGroupMode = groupSelection.isGroupMode;
    const groupDimmed = inGroupMode && !groupSelection.isSelectable(candidate);
    const isThumbnail = isFocusLayout && slotIndex !== undefined && slotIndex > 0;
    const focusKey = paginatedDevices[0]
      ? buildDeviceKey(paginatedDevices[0].host.host_name, paginatedDevices[0].device.device_id)
      : deviceKey;
    const promotes = isThumbnail && !inGroupMode && !isEditMode;
    return (
      <Box
        data-device-tile={deviceKey}
        // A thumbnail click promotes it even when its stream is down; header controls keep their own click.
        onClickCapture={
          promotes
            ? (e: React.MouseEvent) => {
                if ((e.target as HTMLElement).closest('button, a, input, [role="button"]')) return;
                e.stopPropagation();
                swapLayoutTiles(deviceKey, focusKey);
              }
            : undefined
        }
        sx={{
          height: '100%',
          cursor: promotes ? 'pointer' : undefined,
          ...(groupDimmed ? { opacity: 0.35, pointerEvents: 'none' } : {}),
        }}
      >
        <MemoizedRecHostPreview
          host={host}
          device={device}
          isEditMode={isEditMode || inGroupMode}
          isSelected={inGroupMode ? groupSelection.selectedKeys.has(deviceKey) : selectedDevices.has(deviceKey)}
          onSelectionChange={inGroupMode ? getGroupSelectionHandler(deviceKey) : getSelectionHandler(deviceKey)}
          snapshotMode={snapshotMode || isThumbnail}
          deviceFlags={memoizedDeviceFlags.get(deviceKey)!}
          activeFlagFilters={flagFilter}
          onFlagClick={isEditMode || inGroupMode ? undefined : toggleFlagFilter}
          onOpenModal={(poster, canReuseStream) => (inGroupMode ? groupSelection.toggle(candidate) : openModal(host, device, poster, canReuseStream))}
          isAnyModalOpen={!!modalHost || !!openGroup}
          isSelectedForModal={modalHost?.host_name === host.host_name && modalDevice?.device_id === device.device_id}
          persistentStreamTarget={modalStreamTarget}
          persistentStreamMuted={modalStreamMuted}
          persistentStreamInteractive={modalStreamInteractive}
          persistentStreamShouldPause={modalStreamShouldPause}
          persistentStreamOnReady={modalStreamOnReady}
          persistentStreamTransport={modalStreamTransport}
          persistentStreamReconnectKey={modalStreamReconnectKey}
          persistentStreamOnWebRTCFailed={modalWebRTCFailed}
          persistentStreamOnWebRTCStatusChange={modalWebRTCStatusChange}
          groupStreamTarget={openGroup ? groupStreamTargets.get(deviceKey) ?? null : null}
        />
      </Box>
    );
  };

  const layoutPageSummary = (() => {
    const from = (page - 1) * pageSize + 1;
    const to = from + paginatedDevices.length - 1;
    const live = isFocusLayout
      ? tn(Math.max(0, paginatedDevices.length - 1), '1 live + {count} snapshot', '1 live + {count} snapshots')
      : tn(paginatedDevices.length, '{count} live', '{count} live');
    return `${from}–${to} / ${filteredDevices.length} · ${live}`;
  })();

  // View menu (TASK-75): replaces the TASK-48 page-size select. Beside the filters on
  // desktop; on mobile it sits with the pagination under the grid (grid sizes only),
  // because the filter row there is a full-width scroller it would overlap.
  const viewMenu = (
    <ViewMenu view={view} onChange={setView} onResetOrder={resetLayoutOrder} gridOnly={isMobile} />
  );

  return (
    <Box sx={{ position: 'relative' }}>
      {/* Server change loading overlay - blocks interaction during stream initialization */}
      <Backdrop
        open={isServerChanging}
        sx={{
          position: 'absolute',
          zIndex: (theme) => theme.zIndex.drawer + 1,
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          borderRadius: 1,
        }}
      >
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
          <CircularProgress color="inherit" />
          <Typography variant="body1" color="white">
            Switching server...
          </Typography>
        </Box>
      </Backdrop>
      
      {/* Header with integrated filters */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          mb: 1,
          flexWrap: isMobile || isTablet ? 'wrap' : 'nowrap',
          gap: 1.5,
        }}
      >
        {/* Left side - Title and compact status (on mobile the info icon is portaled next to
            the server picker, so this box only shows for the edit-mode summary) */}
        <Box sx={{ flex: 1, minWidth: isMobile || isTablet ? 0 : 250, width: isMobile || isTablet ? '100%' : 'auto', display: isMobile && !isEditMode ? 'none' : undefined }}>
          {!isMobile && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, minHeight: 40, flexWrap: 'wrap' }}>
              <Typography component="h1" sx={{ mb: 0, fontSize: '1.5rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 1 }}>
                Device
                <Box component="span" sx={{ fontSize: '0.75rem', fontWeight: 600, px: 1, py: 0.25, borderRadius: 999, color: P.textSecondary, bgcolor: P.hoverBg }}>
                  {filteredDevices.length}
                </Box>
              </Typography>
              <Tooltip title="Device info">
                <IconButton size="small" onClick={() => navigate('/device-info')} sx={{ color: 'text.secondary' }}>
                  <DeviceInfoIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              {isEditMode && (
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                  {editModeSummary}
                </Typography>
              )}
            </Box>
          )}
          {isMobile && (
            <MobileHeaderActions>
              <Tooltip title="Device info">
                <IconButton size="small" onClick={() => navigate('/device-info')} sx={{ color: 'text.secondary' }}>
                  <DeviceInfoIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </MobileHeaderActions>
          )}
          {isMobile && isEditMode && (
            <Typography variant="body2" color="text.secondary">
              {editModeSummary}
            </Typography>
          )}
        </Box>

        {/* Right side - Restart button and compact filters */}
        <Stack
          direction="row"
          spacing={1}
          sx={{
            alignItems: 'center',
            width: isMobile ? '100%' : 'auto',
            flexWrap: 'nowrap',
            overflowX: isMobile ? 'auto' : 'visible',
            pb: isMobile ? 0.5 : 0,
            '&::-webkit-scrollbar': { display: 'none' },
          }}
        >
          {/* Group control and Edit buttons — always visible (desktop only),
              always at the same x and y, always the same style: two 40×40
              icon buttons (dashboard / pencil) that never change width and
              never change label. The active mode gets a soft gold tint
              (`${P.accent}26` = ~15% alpha), no border, no pulse. Tooltips
              carry the full meaning. BUG-0438: group-control-align-and-stay.
              BUG-0440: short tooltips. BUG-0443: coherence (no border,
              fixed width). BUG-0444: icon toggles + reserved bottom slot. */}
          {!isMobile && (
            <Tooltip title={groupSelection.isGroupMode ? t('Exit group') : t('Take control of several devices together')}>
              <IconButton
                onClick={handleGroupModeToggle}
                sx={{
                  width: 40,
                  height: 40,
                  flexShrink: 0,
                  alignSelf: 'center',
                  color: groupSelection.isGroupMode ? P.accentText : P.textSecondary,
                  backgroundColor: groupSelection.isGroupMode ? `${P.accent}26` : 'transparent',
                  '&:hover': {
                    backgroundColor: groupSelection.isGroupMode ? `${P.accent}40` : P.hoverBg,
                  },
                  transition: 'background-color 120ms, color 120ms',
                }}
              >
                <DashboardIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          {!isMobile && (
            <Tooltip title={isEditMode ? t('Exit Edit mode') : t('Edit tag')}>
              <IconButton
                onClick={handleEditModeToggle}
                sx={{
                  width: 40,
                  height: 40,
                  flexShrink: 0,
                  alignSelf: 'center',
                  color: isEditMode ? P.accentText : P.textSecondary,
                  backgroundColor: isEditMode ? `${P.accent}26` : 'transparent',
                  '&:hover': {
                    backgroundColor: isEditMode ? `${P.accent}40` : P.hoverBg,
                  },
                  transition: 'background-color 120ms, color 120ms',
                }}
              >
                <EditIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}


          {/* Filters + View menu — always visible (BUG-0444). Previously
              hidden when in Edit mode because the tag input took their slot
              in the header; the tag input now lives in the reserved bottom
              slot, so the filters can stay in place and the user can filter
              while editing. */}
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
            hasActiveFilters={!!hasActiveFilters}
            onClearFilters={clearFilters}
            isMobile={isMobile}
            targetPlaceholder="All Targets"
          />
          {!isMobile && viewMenu}

          {/* Edit mode block moved to the reserved bottom slot below the
              device grid (BUG-0444). The header now ends here with just the
              filters + View menu. */}
        </Stack>
      </Box>

      {/* Reserved mode line — BUG-0445. Sits between the page header and
          the device grid. Always at least 56 px tall so the grid never
          shifts when a mode is toggled. Empty in idle; fills with the Edit
          bar in Edit mode or the GroupSelectBar in Group mode. The two
          modes are mutually exclusive (handleEditModeToggle /
          handleGroupModeToggle), so only one bar can be visible. Moved
          here from the bottom of the page in BUG-0444 — the bar above
          the grid reads as part of the header chrome, not as a footer
          that interrupts the device list. */}
      <Box sx={{ mt: 2, minHeight: 56 }}>
        {isEditMode ? (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'stretch',
              gap: 1.5,
              px: 1.5,
              py: 1,
              bgcolor: P.surface,
              border: `1px solid ${P.borderColor}`,
              borderRadius: 1,
            }}
          >
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, flex: 1, minWidth: 0 }}>
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'stretch',
                  minWidth: 320,
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1.5,
                  backgroundColor: 'background.paper',
                  overflow: 'hidden',
                  '&:focus-within': {
                    borderColor: P.accent,
                    boxShadow: (theme) => `0 0 0 1px ${theme.palette.primary.main}`,
                  },
                }}
              >
                <Autocomplete
                  multiple
                  freeSolo
                  size="small"
                  options={uniqueFlags}
                  value={pendingTags}
                  onChange={(_, newValue) => setPendingTags(normalizeFlags(newValue))}
                  inputValue={tagInputValue}
                  onInputChange={(_, newInputValue) => setTagInputValue(newInputValue)}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      placeholder={selectedDevices.size === 0 ? 'Select devices first…' : 'Tags'}
                      disabled={selectedDevices.size === 0}
                      variant="standard"
                      InputProps={{
                        ...params.InputProps,
                        disableUnderline: true,
                        sx: {
                          px: 1.5,
                          py: 0.75,
                          minHeight: 40,
                          alignItems: 'center',
                          flexWrap: 'wrap',
                          gap: 0.5,
                        },
                        endAdornment: (
                          <>
                            {params.InputProps.endAdornment}
                            <InputAdornment position="end" sx={{ ml: 0.5 }}>
                              <Divider orientation="vertical" flexItem sx={{ mr: 1, height: 22 }} />
                              <Button
                                size="small"
                                variant="text"
                                disabled={(pendingTags.length === 0 && tagInputValue.trim().length === 0) || selectedDevices.size === 0}
                                onClick={applyPendingTags}
                                sx={{
                                  minWidth: 'auto',
                                  px: 1,
                                  py: 0.25,
                                  textTransform: 'none',
                                  fontWeight: 600,
                                }}
                              >
                                Add
                              </Button>
                            </InputAdornment>
                          </>
                        ),
                      }}
                    />
                  )}
                  sx={{
                    flex: 1,
                    '& .MuiAutocomplete-inputRoot': {
                      alignItems: 'center',
                    },
                    '& .MuiAutocomplete-tag': {
                      my: 0.25,
                    },
                  }}
                />
              </Box>

              {/* Chips + count + select/unselect (BUG-0443 flash on the count) */}
              <Box
                sx={{
                  minHeight: 28,
                  display: 'flex',
                  alignItems: 'center',
                  flexWrap: 'nowrap',
                  gap: 1,
                  px: 0.5,
                }}
              >
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, flex: 1, minWidth: 0 }}>
                  {selectedDevices.size > 0 && selectedFlags.map(({ flag, count }) => (
                    <Chip
                      key={flag}
                      label={count === selectedDevices.size ? flag : `${flag} (${count})`}
                      size="small"
                      color="default"
                      onDelete={() => handleBulkRemoveFlag(flag)}
                      sx={{
                        borderRadius: 1,
                        height: 20,
                        backgroundColor: count === selectedDevices.size ? 'rgba(255,255,255,0.08)' : 'rgba(255,152,0,0.12)',
                      }}
                    />
                  ))}
                </Box>
                <Typography
                  key={selectedCountFlash}
                  variant="caption"
                  color="text.secondary"
                  sx={{
                    whiteSpace: 'nowrap',
                    borderRadius: 1,
                    px: 0.5,
                    animation: `${countFlash} 0.7s ease-out`,
                  }}
                >
                  {selectedFilteredCount} of {filteredDevices.length} selected
                </Typography>
                <Typography
                  variant="caption"
                  color={filteredDevices.length > 0 && selectedFilteredCount < filteredDevices.length ? P.accentText : P.textMuted}
                  sx={{
                    cursor: filteredDevices.length > 0 && selectedFilteredCount < filteredDevices.length ? 'pointer' : 'default',
                    whiteSpace: 'nowrap',
                  }}
                  onClick={filteredDevices.length > 0 && selectedFilteredCount < filteredDevices.length ? handleSelectAll : undefined}
                >
                  select all
                </Typography>
                <Typography variant="caption" color="text.disabled">-</Typography>
                <Typography
                  variant="caption"
                  color={selectedFilteredCount > 0 ? P.accentText : P.textMuted}
                  sx={{
                    cursor: selectedFilteredCount > 0 ? 'pointer' : 'default',
                    whiteSpace: 'nowrap',
                  }}
                  onClick={selectedFilteredCount > 0 ? (hasActiveFilters ? handleClearFilteredSelection : handleClearSelection) : undefined}
                >
                  unselect all
                </Typography>
              </Box>
            </Box>

            <Button
              variant="contained"
              size="small"
              onClick={handleSaveChanges}
              disabled={!hasUnsavedChanges || isSaving}
              startIcon={isSaving ? <CircularProgress size={16} /> : undefined}
              sx={{
                height: 40,
                flexShrink: 0,
                alignSelf: 'flex-start',
                textTransform: 'none',
                backgroundColor: hasUnsavedChanges ? P.accent : undefined,
                '&:disabled': {
                  backgroundColor: hasUnsavedChanges ? 'rgba(25, 118, 210, 0.3)' : undefined
                }
              }}
            >
              {isSaving ? 'Saving…' : hasUnsavedChanges ? `Save (${pendingChanges.size})` : 'Save'}
            </Button>
          </Box>
        ) : groupSelection.isGroupMode && !isLoading ? (
          <GroupSelectBar
            count={groupSelection.selected.length}
            selectedByModel={groupSelection.selectedByModel}
            poolByModel={groupSelection.poolByModel}
            onToggleByModel={groupSelection.toggleByModel}
            canStart={groupSelection.canStart}
            onClear={groupSelection.clear}
            onStart={() => setOpenGroup(groupSelection.selection)}
          />
        ) : null}
      </Box>


      {/* Error state */}
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {/* Loading state */}
      {isLoading ? (
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            height: '200px',
          }}
        >
          <CircularProgress />
        </Box>
      ) : filteredDevices.length === 0 ? (
        <Alert 
          severity={error?.includes('not responding') ? 'error' : 'info'} 
          icon={<ComputerIcon />}
        >
          {error?.includes('not responding') 
            ? error 
            : (hasActiveFilters 
              ? 'No targets match the selected filters. Try adjusting your filter criteria.' 
              : 'No AV devices found. Make sure your devices are connected and have AV capabilities.')
          }
        </Alert>
      ) : (
        <Box
          sx={{
            overflowY: isMobile ? 'auto' : 'visible',
            maxHeight: isMobile ? 'calc(100vh - 220px)' : 'none',
            WebkitOverflowScrolling: isMobile ? 'touch' : undefined,
            touchAction: isMobile ? 'pan-y' : undefined,
            // Contain overscroll to this box so a flick on the device-grid
            // doesn't fling the whole page (and vice versa). The same prop
            // stops iOS Safari rubber-banding past the grid boundaries.
            overscrollBehavior: isMobile ? 'contain' : undefined,
            pb: isMobile ? 2 : 0,
            minHeight: 0,
          }}
        >
          {view.kind === 'layout' ? (
            <DeviceLayout
              view={view}
              onSwap={swapLayoutTiles}
              items={paginatedDevices.map((entry, i) => ({
                key: buildDeviceKey(entry.host.host_name, entry.device.device_id),
                node: renderTile(entry, { slotIndex: i }),
              }))}
            />
          ) : (
            <Grid container spacing={2}>
              {paginatedDevices.map((entry) => {
                const deviceKey = buildDeviceKey(entry.host.host_name, entry.device.device_id);
                return (
                  // BUG-XXXX: every grid-view tile has the same 16/9 shape,
                  // so a phone (9:16) stream no longer stretches the row
                  // and every TV tile in the same row goes tall + empty.
                  // The inner RecHostPreview letterboxes its own stream.
                  //
                  // BUG-0452: the Card inside (RecHostPreview) still has a
                  // fixed height: 180 of its own. When the aspectRatio above
                  // computes a height < 180 (any container between the
                  // breakpoints where 16:9 of the 25%/33%/100%-width item
                  // drops under 180px), the Card overflows its Grid item and
                  // bleeds past the Grid container into the Pagination row
                  // below — visually the pager overlays the preview tiles.
                  // Mirror the override DeviceLayout already uses on its grid
                  // slots: force the Card to fill the Grid item so the
                  // 16/9 ratio always wins.
                  <Grid
                    item
                    xs={12}
                    sm={6}
                    md={4}
                    lg={3}
                    key={deviceKey}
                    sx={{
                      aspectRatio: '16 / 9',
                      '& > .MuiCard-root, & > * > .MuiCard-root': { height: '100%' },
                    }}
                  >
                    {renderTile(entry, {})}
                  </Grid>
                );
              })}
            </Grid>
          )}
          {/* Pagination — hidden when the whole result fits on one page, so a
              fleet ≤ pageSize keeps its single-screen grid untouched (TASK-48 G2). */}
          {(totalPages > 1 || (isMobile && filteredDevices.length > GRID_VIEWS[0].pageSize)) && (
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                gap: 1,
                mt: 2,
                pb: isMobile ? 1 : 0,
              }}
            >
              {isMobile && viewMenu}
              {totalPages > 1 && (
                <Pagination
                  count={totalPages}
                  page={page}
                  onChange={handlePageChange}
                  color="primary"
                  shape="rounded"
                  showFirstButton={!isMobile}
                  showLastButton={!isMobile}
                  siblingCount={isMobile ? 0 : 1}
                />
              )}
              {view.kind === 'layout' && (
                <Typography variant="caption" sx={{ color: P.textMuted, whiteSpace: 'nowrap' }}>
                  {layoutPageSummary}
                </Typography>
              )}
            </Box>
          )}
        </Box>
      )}
      {/* Old bottom slot removed in BUG-0445 — the mode line moved to the
          header area (between the page header and the device grid). The bar
          reads as part of the header chrome instead of as a footer that
          interrupts the device list. */}

      {openGroup && (
        <GroupControlModal
          selection={openGroup}
          onClose={() => setOpenGroup(null)}
          onExitGroup={groupSelection.toggleGroupMode}
          reusableStreamKeys={liveTileKeys}
          onStreamSlot={handleGroupStreamSlot}
        />
      )}
      {modalHost && modalDevice && (
        <RecHostStreamModal
          host={modalHost}
          device={modalDevice}
          isOpen={true}
          onClose={closeModal}
          initialPoster={modalPoster}
          minimalControls={isMobile}
          reusePreviewStream={modalCanReuseStream}
          onPersistentStreamTargetChange={setModalStreamTarget}
          onPersistentStreamStateChange={handlePersistentStreamState}
        />
      )}
    </Box>
  );
});

// Add display name for debugging
RecContent.displayName = 'RecContent';

const Rec: React.FC = () => {
  const recProps = useRec();
  return <RecContent {...recProps} />;
};

export default Rec;
