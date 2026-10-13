import {
  Alert,
  Box,
  Button,
  CircularProgress,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import React, { useCallback, useState } from 'react';

import { api } from '../../../utils/apiClient';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import { Host } from '../../../types/common/Host_Types';
import { StyledDialog } from '../../common/StyledDialog';

// TASK-32 + phase 2: a dialog that scans the host for Tello-* APs and pairs
// the chosen one. The host does the nmcli join + SDK link verify + pushes
// the new endpoint into the device's TelloRemoteController.
//
// API:
//   POST /server/drone/tello/scan  { host_name }
//     -> { success, tellos: [{ssid, signal, security}], count }
//   POST /server/drone/tello/pair  { host_name, device_id, ssid, tello_ip?, state_port?, video_port?, cmd_port? }
//     -> { success, ssid, tello_ip, ports, link }

interface TelloPairDialogProps {
  open: boolean;
  host: Host;
  deviceId: string;
  onClose: () => void;
  /** Called after a successful pair, so the parent can refresh the controller state. */
  onPaired?: (info: { ssid: string; tello_ip: string; state_port: number; video_port: number }) => void;
}

interface TelloAp {
  ssid: string;
  signal: number | null;
  security: string;
}

interface PairResult {
  success: boolean;
  ssid?: string;
  tello_ip?: string;
  state_port?: number;
  video_port?: number;
  cmd_port?: number;
  link?: { ok: boolean; bytes?: number; reason?: string };
  error?: string;
  stage?: string;
}

export const TelloPairDialog: React.FC<TelloPairDialogProps> = ({
  open, host, deviceId, onClose, onPaired,
}) => {
  const [tellos, setTellos] = useState<TelloAp[]>([]);
  const [selectedSsid, setSelectedSsid] = useState<string>('');
  const [telloIp, setTelloIp] = useState<string>('192.168.10.1');
  const [scanning, setScanning] = useState(false);
  const [pairing, setPairing] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [result, setResult] = useState<PairResult | null>(null);

  const reset = useCallback(() => {
    setTellos([]); setSelectedSsid(''); setTelloIp('192.168.10.1');
    setScanning(false); setPairing(false); setScanError(null); setResult(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const handleScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    setResult(null);
    try {
      const body = await api.post<{ success: boolean; tellos?: TelloAp[]; error?: string; count?: number }>(
        buildServerUrl('/server/drone/tello/scan'),
        { host_name: host.host_name },
      );
      if (!body.success) {
        setScanError(body.error || 'scan failed');
        setTellos([]);
      } else {
        const found: TelloAp[] = body.tellos ?? [];
        setTellos(found);
        if (found.length === 1) {
          setSelectedSsid(found[0].ssid);
        }
      }
    } catch (e: any) {
      setScanError(e?.message || 'scan request failed');
    } finally {
      setScanning(false);
    }
  }, [host.host_name]);

  const handlePair = useCallback(async () => {
    if (!selectedSsid) return;
    setPairing(true);
    setResult(null);
    try {
      const body = await api.post<PairResult>(
        buildServerUrl('/server/drone/tello/pair'),
        {
          host_name: host.host_name,
          device_id: deviceId,
          ssid: selectedSsid,
          tello_ip: telloIp,
          state_port: 8890,
          video_port: 11111,
          cmd_port: 8889,
        },
      );
      setResult(body);
      if (body.success && onPaired && body.ssid && body.tello_ip) {
        onPaired({
          ssid: body.ssid,
          tello_ip: body.tello_ip,
          state_port: body.state_port ?? 8890,
          video_port: body.video_port ?? 11111,
        });
      }
    } catch (e: any) {
      setResult({ success: false, error: e?.message || 'pair request failed' });
    } finally {
      setPairing(false);
    }
  }, [host.host_name, deviceId, selectedSsid, telloIp, onPaired]);

  return (
    <StyledDialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Pair Tello</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <Typography variant="body2" color="textSecondary">
            Scan for Tello-* APs visible to <b>{host.host_name}</b>'s wlan, then join the chosen one.
            The host's TelloRemoteController will be updated with the new IP automatically.
          </Typography>

          <Box>
            <Button
              variant="outlined"
              onClick={handleScan}
              disabled={scanning || pairing}
              startIcon={scanning ? <CircularProgress size={16} /> : null}
            >
              {scanning ? 'Scanning…' : 'Scan for Tello APs'}
            </Button>
          </Box>

          {scanError && <Alert severity="error">{scanError}</Alert>}

          {tellos.length > 0 && (
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Visible Tellos</Typography>
              <List dense sx={{ border: 1, borderColor: 'divider', borderRadius: 1 }}>
                {tellos.map((t) => (
                  <ListItemButton
                    key={t.ssid}
                    selected={selectedSsid === t.ssid}
                    onClick={() => setSelectedSsid(t.ssid)}
                  >
                    <ListItemText
                      primary={t.ssid}
                      secondary={t.signal != null ? `signal ${t.signal}% · ${t.security}` : t.security}
                    />
                  </ListItemButton>
                ))}
              </List>
            </Box>
          )}

          {tellos.length === 0 && !scanning && !scanError && (
            <Typography variant="body2" color="textSecondary" sx={{ fontStyle: 'italic' }}>
              No scan run yet.
            </Typography>
          )}

          {selectedSsid && (
            <TextField
              label="Tello IP"
              size="small"
              value={telloIp}
              onChange={(e) => setTelloIp(e.target.value)}
              helperText="Direct-AP single-drone setup uses 192.168.10.1; netns setups use 10.200.N.2."
            />
          )}

          {result && (
            <Alert severity={result.success ? 'success' : 'error'}>
              {result.success
                ? `Paired ${result.ssid} at ${result.tello_ip}:${result.state_port}/${result.video_port}` +
                  (result.link?.bytes != null ? ` (link reply ${result.link.bytes}B)` : '')
                : `Pair failed at stage "${result.stage || '?'}": ${result.error || 'unknown error'}`}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={pairing}>
          Close
        </Button>
        <Button
          variant="contained"
          onClick={handlePair}
          disabled={!selectedSsid || pairing}
          startIcon={pairing ? <CircularProgress size={16} /> : null}
        >
          {pairing ? 'Pairing…' : 'Pair'}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

export default TelloPairDialog;
