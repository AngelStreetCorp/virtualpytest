import React, { useState, useEffect, useCallback, useMemo } from 'react';

import {
  Refresh as RefreshIcon,
  Terminal as LogsIcon,
  Close as CloseIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Chip,
  IconButton,
  CircularProgress,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  MenuItem,
  Tabs,
  Tab,
} from '@mui/material';

import { StyledDialog } from './StyledDialog';
import { buildServerUrl, buildServerUrlForServer } from '../../utils/buildUrlUtils';
import { useServerManager } from '../../hooks/useServerManager';

interface ServiceLogsModalProps {
  open: boolean;
  /** Human label shown in the title, e.g. "Stream". */
  serviceLabel: string;
  /** systemd unit name passed to /server/logs/view, e.g. "vpt-stream". */
  logService: string;
  /** host_name to proxy the journalctl request to (required for host services). */
  logHostName?: string;
  /**
   * For vpt-stream only: the host's devices. vpt-stream logs to per-device
   * ffmpeg files (not journald), so when present the modal shows one tab
   * per device and fetches each device's ffmpeg log.
   */
  streamDevices?: { device_id: string; device_name?: string }[];
  defaultLines?: number;
  defaultSince?: string;
  onClose: () => void;
}

const LINE_OPTIONS = [50, 100, 200, 500];
const SINCE_OPTIONS = ['15m', '1h', '6h', '24h', '7d'];

/**
 * Self-contained service log viewer. Owns the fetch (/server/logs/view),
 * the Lines/Since filters and loading/error state, so callers only pass the
 * target service + host and an onClose handler. Shared by the Status page
 * and the Dashboard per-service log button.
 */
export const ServiceLogsModal: React.FC<ServiceLogsModalProps> = ({
  open,
  serviceLabel,
  logService,
  logHostName,
  streamDevices,
  defaultLines = 100,
  defaultSince = '1h',
  onClose,
}) => {
  const perDevice = logService === 'vpt-stream' && !!streamDevices && streamDevices.length > 0;
  const [lines, setLines] = useState(defaultLines);
  const [since, setSince] = useState(defaultSince);
  const [activeDevice, setActiveDevice] = useState<string>('');
  const [logs, setLogs] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | undefined>(undefined);

  // Route the logs request to the server that actually owns this host.
  // serverHostsData already maps every host -> its server, so clicking
  // "Logs" works regardless of which server is selected (no manual
  // re-selection on Dashboard/Status). Falls back to the selected server
  // for server-level logs (no host_name).
  const { serverHostsData } = useServerManager();
  const logsEndpointUrl = useMemo(() => {
    if (logHostName) {
      const owner = serverHostsData.find((sd) =>
        sd.hosts.some((h) => h.host_name === logHostName),
      );
      if (owner?.server_info?.server_url) {
        return buildServerUrlForServer(owner.server_info.server_url, '/server/logs/view');
      }
    }
    return buildServerUrl('/server/logs/view');
  }, [serverHostsData, logHostName]);

  const fetchLogs = useCallback(
    async (lineCount: number, sinceValue: string, deviceId?: string) => {
      if (!logService) return;
      if (perDevice && !deviceId) return; // wait until a device tab is selected
      setLoading(true);
      setError(undefined);
      setLogs('');
      try {
        const payload: Record<string, unknown> = {
          service: logService,
          lines: lineCount,
          since: sinceValue,
        };
        if (logHostName) payload.host_name = logHostName;
        if (perDevice && deviceId) payload.device_id = deviceId;
        const res = await fetch(logsEndpointUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.success) {
          setLogs(data.logs || '');
        } else {
          setError(data.error || 'Failed to fetch logs');
        }
      } catch (err: any) {
        setError(err?.message || 'Network error');
      } finally {
        setLoading(false);
      }
    },
    [logService, logHostName, perDevice, logsEndpointUrl],
  );

  // Reset filters on open / service change. For per-device (vpt-stream)
  // select the first device tab — the fetch is driven by the effect below.
  // For journal services, fetch immediately.
  useEffect(() => {
    if (!open) return;
    setLines(defaultLines);
    setSince(defaultSince);
    if (perDevice) {
      setActiveDevice(streamDevices![0].device_id);
    } else {
      setActiveDevice('');
      fetchLogs(defaultLines, defaultSince);
    }
  }, [open, logService, logHostName, defaultLines, defaultSince, perDevice, streamDevices, fetchLogs]);

  // Per-device fetch: runs on initial device selection and on tab change.
  useEffect(() => {
    if (!open || !perDevice || !activeDevice) return;
    fetchLogs(defaultLines, defaultSince, activeDevice);
  }, [open, perDevice, activeDevice, defaultLines, defaultSince, fetchLogs]);

  return (
    <StyledDialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      fullWidth
      // Fixed-height modal: the body fills it and scrolls internally, so
      // switching device tabs or refreshing logs never resizes the dialog
      // (no flash / layout shift on reload).
      PaperProps={{
        sx: { height: '85vh', display: 'flex', flexDirection: 'column' },
      }}
    >
      {/* Single compact header: title + chip + filters + count + close */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: 1.5,
          py: 0.75,
          borderBottom: '1px solid',
          borderColor: 'divider',
          flexShrink: 0,
        }}
      >
        <LogsIcon fontSize="small" />
        <Typography variant="subtitle2" noWrap sx={{ fontWeight: 600 }}>
          Logs — {serviceLabel}
        </Typography>
        <Chip
          label={logService}
          size="small"
          variant="outlined"
          sx={{ fontFamily: 'monospace', fontSize: '0.7rem', height: 20 }}
        />
        <TextField
          select
          value={lines}
          onChange={(e) => setLines(Number(e.target.value))}
          size="small"
          sx={{ width: 80, ml: 1 }}
        >
          {LINE_OPTIONS.map((n) => (
            <MenuItem key={n} value={n}>
              {n}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          value={since}
          onChange={(e) => setSince(e.target.value)}
          size="small"
          sx={{ width: 80 }}
        >
          {SINCE_OPTIONS.map((v) => (
            <MenuItem key={v} value={v}>
              {v}
            </MenuItem>
          ))}
        </TextField>
        <Button
          variant="outlined"
          size="small"
          startIcon={<RefreshIcon />}
          onClick={() => fetchLogs(lines, since, activeDevice)}
          disabled={loading}
        >
          Refresh
        </Button>
        <Typography variant="caption" color="textSecondary" sx={{ ml: 'auto' }}>
          {logs ? `${logs.split('\n').filter(Boolean).length} lines` : ''}
        </Typography>
        <IconButton onClick={onClose} size="small">
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Per-device tabs for vpt-stream (ffmpeg logs are one file per device). */}
      {perDevice && (
        <Tabs
          value={activeDevice}
          onChange={(_e, v) => setActiveDevice(v)}
          variant="scrollable"
          scrollButtons={false}
          sx={{ borderBottom: '1px solid', borderColor: 'divider', minHeight: 36, flex: 'none' }}
        >
          {streamDevices!.map((d) => (
            <Tab
              key={d.device_id}
              value={d.device_id}
              label={d.device_name || d.device_id}
              sx={{ minHeight: 36, py: 0, textTransform: 'none' }}
            />
          ))}
        </Tabs>
      )}

      <DialogContent sx={{ p: 0, flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* Log output — fills the fixed-height dialog and scrolls internally
            so its content length never changes the modal size. */}
        <Box
          sx={{
            fontFamily: 'monospace',
            fontSize: '0.75rem',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            backgroundColor: 'grey.900',
            color: 'grey.100',
            p: 2,
            height: '100%',
            overflowY: 'auto',
          }}
        >
          {loading && (
            <Box display="flex" justifyContent="center" pt={4}>
              <CircularProgress size={24} />
            </Box>
          )}
          {error && <Typography color="error.light">{error}</Typography>}
          {!loading && !error && (logs || <Typography color="grey.500">No logs available</Typography>)}
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        <Button
          variant="outlined"
          size="small"
          onClick={() => {
            const blob = new Blob([logs || ''], { type: 'text/plain' });
            window.open(URL.createObjectURL(blob), '_blank');
          }}
          disabled={!logs}
        >
          Open in New Tab
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};
