import { DeviceFavoriteGroupHeader } from '../components/common/DeviceFavoriteGroupHeader';
import { DeviceFavoriteStar } from '../components/common/DeviceFavoriteStar';
import { DeviceMaintenanceBadge } from '../components/common/DeviceMaintenanceBadge';
import {
  OpenInNew as OpenInNewIcon,
} from '@mui/icons-material';
import {
  Box,
  Paper,
  Typography,
  Button,
  TextField,
  FormControl,
  InputLabel,
  OutlinedInput,
  Select,
  MenuItem,
  Chip,
  Link,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  SelectChangeEvent,
} from '@mui/material';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { useDeviceFavorites } from '../hooks/useDeviceFavorites';
import { useHostData } from '../hooks/useHostManager';
import { useToast } from '../hooks/useToast';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { TYPOGRAPHY } from '../constants/typography';

// 'device' = OCR device info (metadata->'info'); 'gateway' = gw_info network
// environment (flat metadata). Same override table/routes, distinguished by source.
type InfoSource = 'device' | 'gateway';

interface KeyStatus {
  device_name: string;
  host_name: string;
  userinterface_name: string | null;
  info_key: string;
  raw_value: string | null;
  override_value: string | null;
  is_overridden: boolean;
  effective_value: string | null;
  override_stale: boolean;
}

interface DeviceReport {
  report_url?: string | null;
  scanned_at?: string | null;
  initial_screenshot_url?: string | null;
  final_screenshot_url?: string | null;
  video_url?: string | null;
}

interface DeviceOption {
  device_id?: string;
  device_name: string;
  host_name: string;
  device_info: Record<string, string>;
  gateway_info: Record<string, string>;
  device_info_report?: DeviceReport;
  gateway_info_report?: DeviceReport;
}

const keyOf = (deviceName: string, hostName: string) => `${deviceName}::${hostName}`;
const hasKeys = (o?: Record<string, string> | null) => !!o && Object.keys(o).length > 0;

const DeviceInfoOverrides: React.FC = () => {
  const { showSuccess, showError } = useToast();
  const { getAllDevices, selectedServer } = useHostData();
  const { isDeviceAllowed } = useWorkspaceContext();
  const [searchParams] = useSearchParams();

  // Devices in scope: getAllDevices() is already narrowed to the selected server
  // (HostManagerProvider derives availableHosts from that server's payload), so
  // only the workspace scope has to be applied here — same rule as Dashboard/Rec.
  // Both sources re-run this memo on change: a server switch swaps the host list,
  // a workspace switch swaps the `isDeviceAllowed` identity.
  const allDevices = useMemo(() => getAllDevices(), [getAllDevices]);
  const favorites = useDeviceFavorites();
  const scopedDevices = useMemo(
    () => allDevices.filter((d) => isDeviceAllowed(d.hostName || '', d.device_id)),
    [allDevices, isDeviceAllowed],
  );

  // Devices + their info come from the host manager — getAllHosts already embeds
  // device_info and gateway_info — so there's no separate fetch / loading /
  // refresh here. A device is offered if it has either info family.
  const devices = useMemo<DeviceOption[]>(
    () =>
      scopedDevices
        .filter((d) => hasKeys(d.device_info) || hasKeys(d.gateway_info))
        .map((d) => ({
          device_id: d.device_id,
          device_name: d.device_name,
          host_name: d.hostName || '',
          device_info: (d.device_info as Record<string, string>) || {},
          gateway_info: (d.gateway_info as Record<string, string>) || {},
          device_info_report: d.device_info_report,
          gateway_info_report: d.gateway_info_report,
        }))
        .sort((a, b) =>
          `${a.device_name}${a.host_name}`.localeCompare(`${b.device_name}${b.host_name}`),
        ),
    [scopedDevices],
  );

  // Preselect from ?device_name=&host_name=&tab= (deep link from the info icon).
  const [selected, setSelected] = useState<string>(() => {
    const dn = searchParams.get('device_name');
    const hn = searchParams.get('host_name');
    return dn && hn ? keyOf(dn, hn) : '';
  });
  // Remember the cold-load deep link so the auto-select effect below does not
  // re-fill the empty state after the drop-scope effect clears a now-stale link.
  const hasInitialDeepLink = useMemo(() => {
    const dn = searchParams.get('device_name');
    const hn = searchParams.get('host_name');
    return !!(dn && hn);
  }, [searchParams]);
  const [source, setSource] = useState<InfoSource>(
    () => (searchParams.get('tab') === 'gateway' ? 'gateway' : 'device'),
  );
  const [rows, setRows] = useState<KeyStatus[]>([]);
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const selectedDevice = useMemo(
    () => devices.find((d) => keyOf(d.device_name, d.host_name) === selected),
    [devices, selected],
  );
  const hasDevice = hasKeys(selectedDevice?.device_info);
  const hasGateway = hasKeys(selectedDevice?.gateway_info);

  // If the active tab has no data for the newly-selected device, fall to the one
  // that does (the other tab stays greyed out).
  useEffect(() => {
    if (!selectedDevice) return;
    if (source === 'device' && !hasDevice && hasGateway) setSource('gateway');
    else if (source === 'gateway' && !hasGateway && hasDevice) setSource('device');
  }, [selectedDevice, source, hasDevice, hasGateway]);

  // Drop a selection that has left scope — the device belongs to the server we
  // just switched away from, or the workspace we just switched to does not allow
  // it. Matched against `scopedDevices` rather than `devices`, so a device still
  // in scope but with no info keys yet keeps its selection instead of flickering
  // away.
  //
  // Gated on a non-empty raw host list rather than on `isLoading`: HostManager
  // copies the server payload into `availableHosts` from an effect, and this
  // component's effects run *before* its provider's, so on the commit where
  // loading flips false the list here is still empty for one render — an
  // isLoading gate would clear the ?device_name= deep link every cold load.
  // An empty list means "nothing to compare against" (loading, or the selected
  // server is not responding), never "your device is gone".
  useEffect(() => {
    if (!selected || allDevices.length === 0) return;
    if (scopedDevices.some((d) => keyOf(d.device_name, d.hostName || '') === selected)) return;
    setSelected('');
  }, [allDevices, scopedDevices, selected]);

  // Auto-select the first device once the host list has loaded and no deep link
  // pre-selected one. The drop-scope effect above clears `selected` for stale
  // deep links — this one fills the empty state on a cold load so the page
  // never lands on an empty dropdown. Uses the same alphabetical/favorites order
  // the Select renders, so the highlighted row matches what's visible.
  useEffect(() => {
    if (selected || hasInitialDeepLink || allDevices.length === 0 || devices.length === 0) return;
    const first =
      devices.find((d) => !!d.device_id && favorites.isFavorite(d.host_name, d.device_id)) ||
      devices[0];
    setSelected(keyOf(first.device_name, first.host_name));
  }, [selected, hasInitialDeepLink, allDevices, devices, favorites]);

  // Dropdown options: provider devices, plus a synthetic entry for a deep-linked
  // device not yet in the host list (keeps the Select value valid while /keys loads).
  const options = useMemo<DeviceOption[]>(() => {
    if (selected && !devices.some((d) => keyOf(d.device_name, d.host_name) === selected)) {
      const [device_name, host_name] = selected.split('::');
      return [{ device_name, host_name, device_info: {}, gateway_info: {} }, ...devices];
    }
    return devices;
  }, [devices, selected]);

  // Keep the latest device list reachable from effects keyed only on `selected` /
  // `source` (so a background host-data refresh doesn't wipe an in-progress edit —
  // see feedback_reset_effect_async_deps).
  const devicesRef = useRef<DeviceOption[]>(devices);
  devicesRef.current = devices;

  // Per-key edit detail (raw value, override, stale) that getAllHosts doesn't
  // carry. Fetched silently on selection; the table renders instantly from the
  // host-provided info, then enriches when this returns.
  const loadKeys = useCallback(
    async (deviceName: string, hostName: string, src: InfoSource) => {
      try {
        const params = new URLSearchParams({ device_name: deviceName, host_name: hostName, source: src });
        const data = await api.get<KeyStatus[]>(
          buildServerUrl(`/server/device-info-overrides/keys?${params.toString()}`),
        );
        if (data && data.length) setRows(data);
      } catch (e: any) {
        showError(`Failed to load info detail: ${e?.message || e}`);
      }
    },
    [showError],
  );

  useEffect(() => {
    setEdited({});
    // `selectedServer` is not read here — buildServerUrl picks the selection up
    // from localStorage — but it is a real dependency: a server switch must
    // re-fetch the detail rows from the newly selected backend.
    if (!selected || !selectedServer) {
      setRows([]);
      return;
    }
    const [deviceName, hostName] = selected.split('::');
    const device = devicesRef.current.find((d) => keyOf(d.device_name, d.host_name) === selected);
    const info = device ? (source === 'gateway' ? device.gateway_info : device.device_info) : {};
    // Instant render from host-provided info (effective values)…
    setRows(
      Object.entries(info || {}).map(([info_key, value]) => ({
        device_name: deviceName,
        host_name: hostName,
        userinterface_name: null,
        info_key,
        raw_value: null,
        override_value: null,
        is_overridden: false,
        effective_value: value,
        override_stale: false,
      })),
    );
    // …then enrich with raw/override/stale detail.
    loadKeys(deviceName, hostName, source);
  }, [selected, source, selectedServer, loadKeys]);

  // Report link + scan time for the selected device/source, so the operator can
  // see which scan these values came from.
  const selectedReport = useMemo<DeviceReport | undefined>(
    () => (source === 'gateway' ? selectedDevice?.gateway_info_report : selectedDevice?.device_info_report),
    [selectedDevice, source],
  );

  const handleSelect = (e: SelectChangeEvent) => setSelected(e.target.value);

  const draftValue = (row: KeyStatus): string =>
    row.info_key in edited ? edited[row.info_key] : row.effective_value ?? '';

  const setDraft = (key: string, value: string) =>
    setEdited((prev) => ({ ...prev, [key]: value }));

  const reload = useCallback(() => {
    if (!selected) return;
    const [deviceName, hostName] = selected.split('::');
    loadKeys(deviceName, hostName, source);
  }, [selected, source, loadKeys]);

  const save = useCallback(
    async (row: KeyStatus) => {
      const value = draftValue(row);
      setSavingKey(row.info_key);
      try {
        await api.put(buildServerUrl('/server/device-info-overrides'), {
          device_name: row.device_name,
          host_name: row.host_name,
          userinterface_name: row.userinterface_name,
          info_key: row.info_key,
          corrected_value: value,
          raw_value_at_edit: row.raw_value,
          source,
        });
        showSuccess(`Saved correction for "${row.info_key}"`);
        reload();
      } catch (e: any) {
        showError(`Failed to save: ${e?.message || e}`);
      } finally {
        setSavingKey(null);
      }
    },
    [edited, reload, source, showSuccess, showError],
  );

  const clear = useCallback(
    async (row: KeyStatus) => {
      setSavingKey(row.info_key);
      try {
        await api.delete(buildServerUrl('/server/device-info-overrides'), {
          body: JSON.stringify({
            device_name: row.device_name,
            host_name: row.host_name,
            userinterface_name: row.userinterface_name,
            info_key: row.info_key,
            source,
          }),
        });
        showSuccess(`Cleared override for "${row.info_key}" — reverted to raw value`);
        reload();
      } catch (e: any) {
        showError(`Failed to clear: ${e?.message || e}`);
      } finally {
        setSavingKey(null);
      }
    },
    [reload, source, showSuccess, showError],
  );

  const rawHeader = source === 'gateway' ? 'Raw' : 'Raw (OCR)';

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Device Info
      </Typography>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
        {source === 'gateway' ? (
          <>
            Correct values from the latest <code>gw_info</code> gateway (network environment) scan.
          </>
        ) : (
          <>
            Correct OCR-misread values from the latest <code>get_info</code> device scan.
          </>
        )}
      </Typography>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <FormControl sx={{ minWidth: 360 }} size="small">
            <InputLabel id="device-label" shrink>Device</InputLabel>
            <Select
              labelId="device-label"
              value={selected}
              onChange={handleSelect}
              displayEmpty
              input={<OutlinedInput notched label="Device" />}
              sx={{ '& .MuiSelect-select .MuiIconButton-root': { display: 'none' } }}
            >
              {options.length === 0 && (
                <MenuItem value="" disabled>
                  No devices with info
                </MenuItem>
              )}
              {(() => {
                const isFav = (d: DeviceOption) => !!d.device_id && favorites.isFavorite(d.host_name, d.device_id);
                const renderOption = (d: DeviceOption) => {
                  // Host names of the form `<device>_Host` (auto-derived from the
                  // device) just duplicate the device name — show device alone.
                  const redundantHost = d.host_name === `${d.device_name}_Host`;
                  return (
                    <MenuItem
                      key={keyOf(d.device_name, d.host_name)}
                      value={keyOf(d.device_name, d.host_name)}
                    >
                      {redundantHost ? d.device_name : `${d.device_name} — ${d.host_name}`}
                      <DeviceMaintenanceBadge hostName={d.host_name} deviceName={d.device_name} size={14} />
                      {d.device_id && (
                        <span style={{ marginLeft: 'auto', paddingLeft: 8, display: 'flex' }}>
                          <DeviceFavoriteStar hostName={d.host_name} deviceId={d.device_id} />
                        </span>
                      )}
                    </MenuItem>
                  );
                };
                const favoriteOptions = options.filter(isFav);
                const otherOptions = options.filter((d) => !isFav(d));
                return [
                  ...(favoriteOptions.length > 0
                    ? [
                        <DeviceFavoriteGroupHeader key="__favorites" kind="favorites" />,
                        ...favoriteOptions.map(renderOption),
                        ...(otherOptions.length > 0 ? [<DeviceFavoriteGroupHeader key="__all" kind="all" />] : []),
                      ]
                    : []),
                  ...otherOptions.map(renderOption),
                ];
              })()}
            </Select>
          </FormControl>

          {/* Link back to the scan these values came from. */}
          {selected && selectedReport?.report_url && (
            <Link
              href={selectedReport.report_url}
              target="_blank"
              rel="noopener noreferrer"
              sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, fontSize: TYPOGRAPHY.body.size }}
            >
              <OpenInNewIcon fontSize="small" />
              View source report
              {selectedReport.scanned_at && (
                <Typography component="span" variant="caption" color="textSecondary" sx={{ ml: 0.5 }}>
                  ({new Date(selectedReport.scanned_at).toLocaleString()})
                </Typography>
              )}
            </Link>
          )}
        </Stack>
      </Paper>

      {selected && (
        <>
          {/* Device / Gateway tabs — a tab is greyed out when that info family is
              not available for the selected device. */}
          <Tabs
            value={source}
            onChange={(_, v: InfoSource) => setSource(v)}
            sx={{ mb: 1, minHeight: 40 }}
          >
            <Tab value="device" label="Device" disabled={!hasDevice} sx={{ minHeight: 40 }} />
            <Tab value="gateway" label="Gateway" disabled={!hasGateway} sx={{ minHeight: 40 }} />
          </Tabs>

          <TableContainer component={Paper}>
            <Table
              size="small"
              sx={{
                // Fixed layout so column widths/header never reflow when the row
                // values swap (provider seed → /keys enrich) — only cell contents
                // change, no flashing/resizing.
                tableLayout: 'fixed',
                // Override the global .MuiTableRow-root:hover gray (index.css) —
                // keep rows transparent on hover, consistent with other tables.
                '& .MuiTableRow-root': { backgroundColor: 'transparent !important' },
                '& .MuiTableRow-root:hover': { backgroundColor: 'transparent !important' },
                '& .MuiTableCell-root': { backgroundColor: 'transparent !important' },
              }}
            >
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 'bold', width: '20%', fontSize: TYPOGRAPHY.caption.size }}>Field</TableCell>
                  <TableCell sx={{ fontWeight: 'bold', width: '28%', fontSize: TYPOGRAPHY.caption.size }}>{rawHeader}</TableCell>
                  <TableCell sx={{ fontWeight: 'bold', width: '26%', fontSize: TYPOGRAPHY.caption.size }}>Corrected value</TableCell>
                  <TableCell sx={{ fontWeight: 'bold', width: '12%', fontSize: TYPOGRAPHY.caption.size }}>Flags</TableCell>
                  <TableCell sx={{ fontWeight: 'bold', width: '14%', fontSize: TYPOGRAPHY.caption.size }} align="right">
                    Actions
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => {
                  const busy = savingKey === row.info_key;
                  const draft = draftValue(row);
                  const dirty = draft !== (row.effective_value ?? '');
                  return (
                    <TableRow key={row.info_key}>
                      <TableCell sx={{ fontFamily: 'monospace', wordBreak: 'break-all', fontSize: TYPOGRAPHY.caption.size, py: 0.75 }}>{row.info_key}</TableCell>
                      <TableCell
                        sx={{ fontFamily: 'monospace', color: 'text.secondary', wordBreak: 'break-all', fontSize: TYPOGRAPHY.caption.size, py: 0.75 }}
                      >
                        {row.raw_value}
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <TextField
                          size="small"
                          fullWidth
                          value={draft}
                          onChange={(e) => setDraft(row.info_key, e.target.value)}
                          InputProps={{ sx: { fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size } }}
                        />
                      </TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                          {row.is_overridden && (
                            <Chip
                              size="small"
                              color="primary"
                              label="overridden"
                              sx={{ height: 18, fontSize: TYPOGRAPHY.microMeta.size, '& .MuiChip-label': { px: 0.75 } }}
                            />
                          )}
                          {row.override_stale && (
                            <Tooltip title="Raw value changed since this override was set — the underlying value may have really changed (e.g. firmware update). Review.">
                              <Chip
                                size="small"
                                color="error"
                                label="stale"
                                sx={{ height: 18, fontSize: TYPOGRAPHY.microMeta.size, '& .MuiChip-label': { px: 0.75 } }}
                              />
                            </Tooltip>
                          )}
                        </Stack>
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                          <Button
                            size="small"
                            variant="contained"
                            disabled={busy || !dirty}
                            onClick={() => save(row)}
                            sx={{ minWidth: 0, px: 1, fontSize: TYPOGRAPHY.caption.size }}
                          >
                            Save
                          </Button>
                          <Button
                            size="small"
                            color="inherit"
                            disabled={busy || !row.is_overridden}
                            onClick={() => clear(row)}
                            sx={{ minWidth: 0, px: 1, fontSize: TYPOGRAPHY.caption.size }}
                          >
                            Clear
                          </Button>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">
                      <Typography variant="body2" color="textSecondary" sx={{ py: 2 }}>
                        No {source} info fields for this device.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>

          {/* Final-state screenshot from the source scan, so the operator can see
              the screen these values came from. Prefer `final_screenshot_url` and
              fall back to `initial_screenshot_url`; if neither is set, or the
              image fails to load (broken/missing asset on the host), hide the
              panel entirely instead of leaving a broken-image icon on the page. */}
          {(() => {
            const url =
              selectedReport?.final_screenshot_url || selectedReport?.initial_screenshot_url;
            if (!url) return null;
            return (
              <Paper sx={{ p: 2, mt: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Final state (source screenshot)
                </Typography>
                <Link href={url} target="_blank" rel="noopener noreferrer">
                  <Box
                    component="img"
                    src={url}
                    alt="Final state screenshot from the scan"
                    onError={(e) => {
                      // Asset missing on the host — drop the whole panel so we
                      // don't leave a broken-image icon next to a working link.
                      (e.currentTarget as HTMLImageElement).closest('a')?.remove();
                    }}
                    sx={{
                      maxWidth: '100%',
                      maxHeight: 480,
                      borderRadius: 1,
                      border: '1px solid',
                      borderColor: 'divider',
                      display: 'block',
                    }}
                  />
                </Link>
              </Paper>
            );
          })()}
        </>
      )}
    </Box>
  );
};

export default DeviceInfoOverrides;
