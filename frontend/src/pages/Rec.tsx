import { Computer as ComputerIcon, FactCheck as DeviceInfoIcon } from '@mui/icons-material';
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
} from '@mui/material';
import React, { useEffect, useState, useMemo, useCallback, memo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { DeviceFilterBar } from '../components/common/DeviceFilterBar';
import { RecHostPreview } from '../components/rec/RecHostPreview';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useRec } from '../hooks/pages/useRec';
import { useDeviceFlags } from '../hooks/useDeviceFlags';
import { useServerManager } from '../hooks/useServerManager';
import { usePersistedState } from '../hooks/usePersistedState';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { STORAGE_KEYS } from '../config/constants';
import { Host, Device } from '../types/common/Host_Types';
import { RecHostStreamModal } from '../components/rec/RecHostStreamModal';

const DEVICE_KEY_SEPARATOR = '::';

const buildDeviceKey = (hostName: string, deviceId: string) => `${hostName}${DEVICE_KEY_SEPARATOR}${deviceId}`;
const getRecTargetLabel = (host: Host, device: Device) => {
  const rawName = device.device_name || device.device_id;
  // Host-only entries (VNC desktop or *_Host) collapse to the host name to
  // match RecHostPreview's display rule.
  if (device.device_model === 'host_vnc' || /_Host$/.test(rawName)) {
    return rawName.replace(/_Host$/, '') || host.host_name;
  }
  // Non-host devices mirror the preview card: "device_name - host_name".
  return `${rawName} - ${host.host_name}`;
};

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
    prevProps.isSelectedForModal === nextProps.isSelectedForModal
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
    prevProps.isSelectedForModal === nextProps.isSelectedForModal // Handler should be stable now
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
  const { isMobile, isTablet } = useResponsiveMode();
  // Server change transition state - blocks UI during stream initialization
  const { isServerChanging } = useServerManager();
  const { isDeviceAllowed } = useWorkspaceContext();
  const navigate = useNavigate();

  // Drop devices hidden by the active workspace before applying the page's
  // own target/model/flag filters.
  const avDevices = useMemo(
    () => rawAvDevices.filter(({ host, device }) => isDeviceAllowed(host.host_name, device.device_id)),
    [rawAvDevices, isDeviceAllowed],
  );
  
  // Device flags hook
  const { deviceFlags, uniqueFlags, batchUpdateDeviceFlags } = useDeviceFlags();

  // Filter states — persisted to localStorage so the selection survives
  // refresh and page navigation (kept separate from the Dashboard page).
  const [targetFilter, setTargetFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.REC_FILTERS}_target`,
    [],
  );
  const [deviceModelFilter, setDeviceModelFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.REC_FILTERS}_model`,
    [],
  );
  const [flagFilter, setFlagFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.REC_FILTERS}_flag`,
    [],
  );
  // 'AND' = device must carry every selected tag; 'OR' = any one. Default AND.
  const [flagMatchMode, setFlagMatchMode] = usePersistedState<'AND' | 'OR'>(
    `${STORAGE_KEYS.REC_FILTERS}_flagMode`,
    'AND',
  );

  // Edit mode state
  const [isEditMode, setIsEditMode] = useState(false);
  const [selectedDevices, setSelectedDevices] = useState<Set<string>>(new Set());
  const [pendingChanges, setPendingChanges] = useState<Map<string, string[]>>(new Map());
  const [isSaving, setIsSaving] = useState(false);
  const [pendingTags, setPendingTags] = useState<string[]>([]);
  const [tagInputValue, setTagInputValue] = useState('');

  // Modal state
  const [modalHost, setModalHost] = useState<Host | null>(null);
  const [modalDevice, setModalDevice] = useState<Device | null>(null);
  const [modalPoster, setModalPoster] = useState<string | null>(null);

  const openModal = useCallback((host: Host, device: Device, poster?: string | null) => {
    setModalHost(host);
    setModalDevice(device);
    setModalPoster(poster ?? null);
  }, []);

  const closeModal = useCallback(() => {
    requestAnimationFrame(() => {
      setModalHost(null);
      setModalDevice(null);
      setModalPoster(null);
    });
  }, []);

  // Get unique target labels and device models for filter controls
  const { targetOptions, uniqueDeviceModels } = useMemo(() => {
    const targets = new Set<string>();
    const deviceModels = new Set<string>();

    avDevices.forEach(({ host, device }) => {
      targets.add(getRecTargetLabel(host, device));
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
        targetFilter.length === 0 || targetFilter.includes(getRecTargetLabel(host, device));
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
        getRecTargetLabel(a.host, a.device).localeCompare(
          getRecTargetLabel(b.host, b.device),
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
  // legitimately restored from localStorage on refresh.
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
    prune(setFlagFilter, uniqueFlags);
  }, [
    isLoading,
    targetOptions,
    uniqueDeviceModels,
    uniqueFlags,
    setTargetFilter,
    setDeviceModelFilter,
    setFlagFilter,
  ]);

  // Clear filters
  const clearFilters = () => {
    setTargetFilter([]);
    setDeviceModelFilter([]);
    setFlagFilter([]);
  };

  // Toggle a single flag in the filter (clicked from preview badge)
  const toggleFlagFilter = useCallback((flag: string) => {
    setFlagFilter(prev => (prev.includes(flag) ? prev.filter(f => f !== flag) : [...prev, flag]));
  }, []);

  // Edit mode toggle handler
  const handleEditModeToggle = useCallback(() => {
    setIsEditMode(prev => {
      const newEditMode = !prev;
      if (prev) {
        // Exiting edit mode - clear selections and pending changes
        setSelectedDevices(new Set());
        setPendingChanges(new Map());
        setPendingTags([]);
        setTagInputValue('');
      }
      return newEditMode;
    });
  }, []);

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
        {/* Left side - Title and compact status */}
        <Box sx={{ flex: 1, minWidth: isMobile || isTablet ? 0 : 250, width: isMobile || isTablet ? '100%' : 'auto' }}>
          {!isMobile && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, minHeight: 40, flexWrap: 'wrap' }}>
              <Typography variant="h4" component="h1" sx={{ mb: 0 }}>
                Device
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
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Tooltip title="Device info">
                  <IconButton size="small" onClick={() => navigate('/device-info')} sx={{ color: 'text.secondary' }}>
                    <DeviceInfoIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Box>
              {isEditMode && (
                <Typography variant="body2" color="text.secondary">
                  {editModeSummary}
                </Typography>
              )}
            </Box>
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
          {/* Edit Mode Toggle — Cancel lives inside the edit block so it
              aligns with the tag field row (see below). */}
          {!isMobile && !isEditMode && (
            <Button
              variant="text"
              size="small"
              onClick={handleEditModeToggle}
              sx={{
                color: '#1976d2',
                textTransform: 'none',
                fontWeight: 500,
                minWidth: 64,
                px: 1,
                flexShrink: 0,
              }}
            >
              Edit
            </Button>
          )}


          {/* Normal Mode - Filters */}
          {!isEditMode && (
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
          )}

          {/* Edit Mode - Bulk Actions. Cancel + tag field + Save share one
              row, top-aligned with matching 40px heights so the two buttons
              sit vertically centered with the tag field. The chips/select-all
              row lives inside the middle column, below the field, so it never
              shifts the buttons. */}
          {isEditMode && (
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <Button
                variant="text"
                size="small"
                onClick={handleEditModeToggle}
                sx={{
                  height: 40,
                  color: '#1976d2',
                  textTransform: 'none',
                  fontWeight: 500,
                  minWidth: 64,
                  px: 1,
                  flexShrink: 0,
                }}
              >
                Cancel
              </Button>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
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
                      borderColor: 'primary.main',
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
                        placeholder={selectedDevices.size === 0 ? "Select devices first..." : "Tags"}
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
                      minWidth: 320,
                      '& .MuiAutocomplete-inputRoot': {
                        alignItems: 'center',
                      },
                      '& .MuiAutocomplete-tag': {
                        my: 0.25,
                      },
                    }}
                  />
                </Box>

                {/* Reserved-height row for selected-flag chips + select/unselect controls */}
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
                  <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                    {selectedFilteredCount} of {filteredDevices.length} selected
                  </Typography>
                  <Typography
                    variant="caption"
                    color={filteredDevices.length > 0 && selectedFilteredCount < filteredDevices.length ? 'primary.main' : 'text.disabled'}
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
                    color={selectedFilteredCount > 0 ? 'primary.main' : 'text.disabled'}
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
                  textTransform: 'none',
                  backgroundColor: hasUnsavedChanges ? '#1976d2' : undefined,
                  '&:disabled': {
                    backgroundColor: hasUnsavedChanges ? 'rgba(25, 118, 210, 0.3)' : undefined
                  }
                }}
              >
                {isSaving ? 'Saving...' : hasUnsavedChanges ? `Save (${pendingChanges.size})` : 'Save'}
              </Button>
            </Box>
          )}
        </Stack>
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
            pb: isMobile ? 2 : 0,
            minHeight: 0,
          }}
        >
          <Grid container spacing={2}>
            {filteredDevices.map(({ host, device }) => {
              const deviceKey = buildDeviceKey(host.host_name, device.device_id);
              return (
                <Grid item xs={12} sm={6} md={4} lg={3} key={deviceKey}>
                  <MemoizedRecHostPreview
                    host={host}
                    device={device}
                    isEditMode={isEditMode}
                    isSelected={selectedDevices.has(deviceKey)}
                    onSelectionChange={getSelectionHandler(deviceKey)}
                    deviceFlags={memoizedDeviceFlags.get(deviceKey)!}
                    activeFlagFilters={flagFilter}
                    onFlagClick={isEditMode ? undefined : toggleFlagFilter}
                    onOpenModal={(poster) => openModal(host, device, poster)}
                    isAnyModalOpen={!!modalHost}
                    isSelectedForModal={modalHost?.host_name === host.host_name && modalDevice?.device_id === device.device_id}
                  />
                </Grid>
              );
            })}
          </Grid>
        </Box>
      )}
      {modalHost && modalDevice && (
        <RecHostStreamModal
          host={modalHost}
          device={modalDevice}
          isOpen={true}
          onClose={closeModal}
          initialPoster={modalPoster}
          minimalControls={isMobile}
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
