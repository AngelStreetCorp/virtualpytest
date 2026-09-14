import React, { useMemo, useState } from 'react';
import {
  Box,
  TextField,
  InputAdornment,
  Typography,
  Checkbox,
  Tooltip,
  FormControl,
  Select,
  MenuItem,
  ListItemText,
  SelectChangeEvent,
} from '@mui/material';
import { Search as SearchIcon, Lock as LockIcon } from '@mui/icons-material';
import { UserinterfaceSelector } from './UserinterfaceSelector';
import { useDeviceFlags } from '../../hooks/useDeviceFlags';

interface Device {
  device_id: string;
  device_name: string;
  device_model: string;
}

interface Host {
  host_name: string;
}

export interface TargetPanelProps {
  selectedDevices: Map<string, string>;
  onToggle: (key: string) => void;
  onUpdateUserinterface: (key: string, ui: string) => void;
  allHosts: Host[];
  getDevicesFromHost: (hostName: string) => Device[];
  /** Disable toggling for specific target keys (e.g., currently running). */
  isTargetDisabled?: (key: string) => boolean;
  /** Force visual checked state for specific target keys without selecting them for new runs. */
  isTargetForceChecked?: (key: string) => boolean;
  /** Hide host rows that are incompatible with the selected executable. */
  isHostVisible?: (hostName: string) => boolean;
  /** Hide device rows that are incompatible with the selected executable. */
  isDeviceVisible?: (hostName: string, deviceId: string) => boolean;
  /** Show a lock icon for execution-locked targets (informational only). */
  isTargetLocked?: (key: string) => boolean;
  /** Tooltip text for locked targets (e.g., "script_name (2min ago)"). */
  getLockTooltip?: (key: string) => string;
  /** Show UserinterfaceSelector sub-row for each selected device */
  showUserinterfaceSelector?: boolean;
  /**
   * hostOnly=true  → only host rows are checkable (key: "hostname:")
   * hostOnly=false → host row is also checkable + devices listed under it
   */
  hostOnly?: boolean;
  selectionCountLabel?: string;
  disableInternalScroll?: boolean;
}

export const TargetPanel: React.FC<TargetPanelProps> = ({
  selectedDevices,
  onToggle,
  onUpdateUserinterface,
  allHosts,
  getDevicesFromHost,
  isTargetDisabled,
  isTargetForceChecked,
  isTargetLocked,
  getLockTooltip,
  isHostVisible,
  isDeviceVisible,
  showUserinterfaceSelector = false,
  hostOnly = false,
  selectionCountLabel,
  disableInternalScroll = false,
}) => {
  const [search, setSearch] = useState('');
  const [modelFilter, setModelFilter] = useState<string[]>([]);
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const { deviceFlags, uniqueFlags } = useDeviceFlags();

  const deviceTagsMap = useMemo(() => {
    const map = new Map<string, string[]>();
    deviceFlags.forEach((df) => {
      map.set(`${df.host_name}:${df.device_id}`, df.flags || []);
    });
    return map;
  }, [deviceFlags]);

  const uniqueModels = useMemo(() => {
    const models = new Set<string>();
    allHosts.forEach((host) => {
      getDevicesFromHost(host.host_name).forEach((device) => {
        if (isDeviceVisible && !isDeviceVisible(host.host_name, device.device_id)) return;
        if (device.device_model) models.add(device.device_model);
      });
    });
    return Array.from(models).sort();
  }, [allHosts, getDevicesFromHost, isDeviceVisible]);

  const filteredHosts = useMemo(() => {
    const visibleHosts = allHosts.filter((host) => {
      if (hostOnly) {
        return isHostVisible ? isHostVisible(host.host_name) : true;
      }

      const visibleDevices = getDevicesFromHost(host.host_name).filter((device) =>
        isDeviceVisible ? isDeviceVisible(host.host_name, device.device_id) : true
      );

      return (isHostVisible ? isHostVisible(host.host_name) : true) || visibleDevices.length > 0;
    });

    if (!search.trim()) return visibleHosts;
    const q = search.toLowerCase();
    return visibleHosts.filter(host => {
      if (host.host_name.toLowerCase().includes(q)) return true;
      if (!hostOnly) {
        const devices = getDevicesFromHost(host.host_name).filter((device) =>
          isDeviceVisible ? isDeviceVisible(host.host_name, device.device_id) : true
        );
        return devices.some(
          d =>
            d.device_name?.toLowerCase().includes(q) ||
            d.device_id.toLowerCase().includes(q)
        );
      }
      return false;
    });
  }, [allHosts, search, hostOnly, getDevicesFromHost, isHostVisible, isDeviceVisible]);

  const getFilteredDevices = (hostName: string): Device[] => {
    const devices = getDevicesFromHost(hostName).filter((device) =>
      isDeviceVisible ? isDeviceVisible(hostName, device.device_id) : true
    );
    if (!search.trim()) return devices;
    const q = search.toLowerCase();
    if (hostName.toLowerCase().includes(q)) return devices; // host matches → show all devices
    return devices.filter(
      d =>
        d.device_name?.toLowerCase().includes(q) ||
        d.device_id.toLowerCase().includes(q)
    );
  };

  const visibleTargets = useMemo(() => {
    const q = search.trim().toLowerCase();
    return filteredHosts.flatMap((host) => {
      if (hostOnly) {
        const hostDevices = getDevicesFromHost(host.host_name);
        const firstVisibleDevice =
          hostDevices.find((device) => isDeviceVisible ? isDeviceVisible(host.host_name, device.device_id) : true) ||
          hostDevices[0];
        const inferredModel =
          firstVisibleDevice?.device_model ||
          'host';

        return [{
          key: `${host.host_name}:`,
          hostName: host.host_name,
          targetLabel: host.host_name,
          modelLabel: inferredModel,
          device: firstVisibleDevice,
        }];
      }

      return getFilteredDevices(host.host_name).map((device, index) => ({
        key: `${host.host_name}:${device.device_id}`,
        hostName: host.host_name,
        targetLabel: (device.device_name || `device ${index + 1}`).replace(/_Host$/, ''),
        modelLabel: device.device_model,
        device,
      }));
    }).filter((target) => {
      const matchesSearch = !q || (
        target.hostName.toLowerCase().includes(q) ||
        target.targetLabel.toLowerCase().includes(q) ||
        target.modelLabel.toLowerCase().includes(q) ||
        target.key.toLowerCase().includes(q)
      );
      const matchesModel = modelFilter.length === 0 || modelFilter.includes(target.modelLabel);
      let matchesTag = true;
      if (tagFilter.length > 0) {
        const deviceId = target.device?.device_id;
        const tags = deviceId ? (deviceTagsMap.get(`${target.hostName}:${deviceId}`) || []) : [];
        matchesTag = tags.some((t) => tagFilter.includes(t));
      }
      return matchesSearch && matchesModel && matchesTag;
    }).sort((a, b) => a.hostName.localeCompare(b.hostName, undefined, { numeric: true }));
  }, [filteredHosts, getDevicesFromHost, getFilteredDevices, hostOnly, isDeviceVisible, search, modelFilter, tagFilter, deviceTagsMap]);

  const visibleSelectableKeys = useMemo(() => {
    return visibleTargets
      .map((target) => target.key)
      .filter((targetKey) => !(isTargetDisabled?.(targetKey) ?? false));
  }, [visibleTargets, isTargetDisabled]);

  const visibleSelectedCount = useMemo(
    () => visibleSelectableKeys.filter((key) => selectedDevices.has(key)).length,
    [visibleSelectableKeys, selectedDevices],
  );

  const handleSelectAllVisible = () => {
    visibleSelectableKeys.forEach((key) => {
      if (!selectedDevices.has(key)) {
        onToggle(key);
      }
    });
  };

  const handleUnselectAllVisible = () => {
    visibleSelectableKeys.forEach((key) => {
      if (selectedDevices.has(key)) {
        onToggle(key);
      }
    });
  };

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: disableInternalScroll ? 'auto' : '100%',
        minHeight: 0,
        maxHeight: disableInternalScroll ? 'none' : { xs: 280, md: 360 },
      }}
    >
      {/* Search + inline filters */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
        <TextField
          size="small"
          placeholder="Filter targets..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon sx={{ fontSize: 16 }} />
              </InputAdornment>
            ),
          }}
          sx={{ flex: 1, minWidth: 0 }}
        />
        <FormControl size="small" sx={{ width: 110, flexShrink: 0 }}>
          <Select
            multiple
            displayEmpty
            value={modelFilter}
            onChange={(e: SelectChangeEvent<string[]>) => setModelFilter(e.target.value as string[])}
            renderValue={(selected) => {
              const arr = selected as string[];
              return arr.length === 0 ? 'Models' : `Models (${arr.length})`;
            }}
          >
            {uniqueModels.map((model) => (
              <MenuItem key={model} value={model} dense>
                <Checkbox size="small" checked={modelFilter.includes(model)} />
                <ListItemText primary={model} primaryTypographyProps={{ variant: 'body2' }} />
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ width: 110, flexShrink: 0 }}>
          <Select
            multiple
            displayEmpty
            value={tagFilter}
            onChange={(e: SelectChangeEvent<string[]>) => setTagFilter(e.target.value as string[])}
            renderValue={(selected) => {
              const arr = selected as string[];
              return arr.length === 0 ? 'Tags' : `Tags (${arr.length})`;
            }}
          >
            {uniqueFlags.map((tag) => (
              <MenuItem key={tag} value={tag} dense>
                <Checkbox size="small" checked={tagFilter.includes(tag)} />
                <ListItemText primary={tag} primaryTypographyProps={{ variant: 'body2' }} />
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.75, px: 0.5, flexWrap: 'wrap' }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500 }}>
          {selectionCountLabel || `${selectedDevices.size} target${selectedDevices.size !== 1 ? 's' : ''} selected`}
        </Typography>
        <Typography
          variant="caption"
          color={visibleSelectableKeys.length > 0 ? 'primary.main' : 'text.disabled'}
          sx={{ cursor: visibleSelectableKeys.length > 0 ? 'pointer' : 'default' }}
          onClick={visibleSelectableKeys.length > 0 ? handleSelectAllVisible : undefined}
        >
          select all
        </Typography>
        <Typography variant="caption" color="text.disabled">-</Typography>
        <Typography
          variant="caption"
          color={visibleSelectedCount > 0 ? 'primary.main' : 'text.disabled'}
          sx={{ cursor: visibleSelectedCount > 0 ? 'pointer' : 'default' }}
          onClick={visibleSelectedCount > 0 ? handleUnselectAllVisible : undefined}
        >
          unselect all
        </Typography>
      </Box>

      {/* Target list */}
      <Box
        sx={{
          overflow: disableInternalScroll ? 'visible' : 'auto',
          flex: disableInternalScroll ? '0 0 auto' : 1,
        }}
      >
        {visibleTargets.length === 0 ? (
          <Typography variant="caption" color="text.secondary" sx={{ p: 1, display: 'block' }}>
            No targets found
          </Typography>
        ) : (
          visibleTargets.map((target) => {
            const isSelected = selectedDevices.has(target.key) || (isTargetForceChecked?.(target.key) ?? false);
            const isDisabled = isTargetDisabled?.(target.key) ?? false;
            const isLocked = isTargetLocked?.(target.key) ?? false;
            const userinterface = selectedDevices.get(target.key) || '';

            return (
              <Box key={target.key}>
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.75,
                    minHeight: 28,
                    py: 0.125,
                    px: 0.25,
                    borderRadius: 0.5,
                    '&:hover': { bgcolor: 'action.hover' },
                  }}
                >
                  <Checkbox
                    checked={isSelected}
                    onChange={() => onToggle(target.key)}
                    disabled={isDisabled}
                    size="small"
                    sx={{
                      p: 0.25,
                      '&.Mui-disabled.Mui-checked': {
                        color: 'grey.500',
                      },
                    }}
                  />
                  <Typography
                    variant="body2"
                    sx={{
                      minWidth: 0,
                      flex: '0 1 34%',
                      fontSize: '0.8rem',
                      cursor: isDisabled ? 'default' : 'pointer',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    onClick={() => {
                      if (!isDisabled) {
                        onToggle(target.key);
                      }
                    }}
                  >
                    {target.targetLabel}
                  </Typography>
                  {isLocked && (
                    <Tooltip title={getLockTooltip?.(target.key) || 'Locked'} arrow>
                      <LockIcon sx={{ fontSize: 14, color: 'warning.main', flexShrink: 0 }} />
                    </Tooltip>
                  )}
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      minWidth: 0,
                      flex: '1 1 42%',
                      fontSize: '0.7rem',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {target.hostName}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      minWidth: 0,
                      flex: '0 0 96px',
                      fontSize: '0.7rem',
                      textAlign: 'right',
                      mr: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {target.modelLabel}
                  </Typography>
                </Box>

                {isSelected && showUserinterfaceSelector && (
                  <Box sx={{ pl: 4, pr: 0.25, pb: 0.375 }}>
                    <UserinterfaceSelector
                      deviceModel={target.device?.device_model || ''}
                      value={userinterface}
                      onChange={ui => onUpdateUserinterface(target.key, ui)}
                      label="UI"
                      size="small"
                      fullWidth
                    />
                  </Box>
                )}
              </Box>
            );
          })
        )}
      </Box>
    </Box>
  );
};
