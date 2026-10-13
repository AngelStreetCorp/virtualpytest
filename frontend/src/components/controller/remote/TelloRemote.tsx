import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  IconButton,
  Slider,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import LocationOnIcon from '@mui/icons-material/LocationOn';
import ArticleIcon from '@mui/icons-material/Article';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api } from '../../../utils/apiClient';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import { useControllerApi } from '../../../hooks/controller/useControllerApi';
import { Host } from '../../../types/common/Host_Types';
import { TelloPairDialog } from './TelloPairDialog';

// TASK-32: flight buttons for a Tello (device model `tello`). Every button is one
// remote command; the host's `tello` controller runs it through the safety guard
// (height ceiling, geofence, battery floor, separation) and answers success or the
// refusal reason. `emergency` cuts the motors: the drone drops.
//
// Phase-2 additions:
//   * Pair Tello dialog (scan + join AP, push new endpoint into the controller)
//   * Flip (f, b, l, r) — raw SDK via the controller's `sdk` pass-through
//   * Speed slider (10..100 cm/s) — raw SDK `speed N`
//   * Live battery / temperature / altitude / tof / pose chips, polled every 2 s
//   * "Last flight log" surface after land (clickable to fetch the file)
//   * "Find my Tello" section: last known state + pose + link age; refresh
//     button. The Tello has no GPS, so the position is the controller's
//     last known dead-reckoned (or mission-pad-snapped) pose — best-effort
//     but enough to walk to within Wi-Fi range.

interface TelloRemoteProps {
  host: Host;
  deviceId?: string;
  isCollapsed: boolean;
  sx?: any;
}

interface TelloButton {
  label: string;
  command: string;
  params: Record<string, unknown>;
  color?: 'primary' | 'error' | 'inherit' | 'warning';
}

const MOVE_BUTTONS: TelloButton[] = [
  { label: 'Take off', command: 'takeoff', params: {}, color: 'primary' },
  { label: 'Land', command: 'land', params: {}, color: 'primary' },
  { label: 'Forward', command: 'move', params: { direction: 'forward', cm: 50 } },
  { label: 'Back', command: 'move', params: { direction: 'back', cm: 50 } },
  { label: 'Left', command: 'move', params: { direction: 'left', cm: 50 } },
  { label: 'Right', command: 'move', params: { direction: 'right', cm: 50 } },
  { label: 'Up', command: 'move', params: { direction: 'up', cm: 30 } },
  { label: 'Down', command: 'move', params: { direction: 'down', cm: 30 } },
  { label: 'Turn left', command: 'rotate', params: { direction: 'ccw', deg: 30 } },
  { label: 'Turn right', command: 'rotate', params: { direction: 'cw', deg: 30 } },
];

const FLIP_BUTTONS: TelloButton[] = [
  { label: 'Flip F', command: 'sdk', params: { cmd: 'flip f' } },
  { label: 'Flip B', command: 'sdk', params: { cmd: 'flip b' } },
  { label: 'Flip L', command: 'sdk', params: { cmd: 'flip l' } },
  { label: 'Flip R', command: 'sdk', params: { cmd: 'flip r' } },
];

const EMERGENCY_BUTTON: TelloButton = {
  label: 'Emergency stop', command: 'emergency', params: {}, color: 'error',
};

interface Telemetry {
  bat?: number;
  temph?: number;
  h?: number;
  time?: number;
  tof?: number;
  pose_x?: number;
  pose_y?: number;
  pose_z?: number;
  pose_source?: string;
  pad_id?: number;
}

interface LastKnown {
  ip?: string;
  state_port?: number;
  airborne?: boolean;
  state?: Record<string, any>;
  state_age_s?: number | null;
  pose?: { x: number; y: number; z: number; yaw: number } | null;
  log_path?: string | null;
}

export const TelloRemote = React.memo(function TelloRemote({
  host,
  deviceId,
  isCollapsed,
  sx = {},
}: TelloRemoteProps) {
  const { executeRemoteCommand } = useControllerApi(host, deviceId);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ severity: 'success' | 'error'; text: string } | null>(null);
  const [pairOpen, setPairOpen] = useState(false);
  const [speed, setSpeed] = useState(100);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [linkOk, setLinkOk] = useState<boolean | null>(null);
  const [lastLogPath, setLastLogPath] = useState<string | null>(null);
  const [lastLogSummary, setLastLogSummary] = useState<{ rows?: number; duration_s?: number; peak_altitude_cm?: number } | null>(null);
  const [lastKnown, setLastKnown] = useState<LastKnown | null>(null);
  const [locateOpen, setLocateOpen] = useState(false);
  const [locateLoading, setLocateLoading] = useState(false);
  const telRef = useRef<number | null>(null);

  const run = useCallback(
    async (button: TelloButton) => {
      setBusy(true);
      try {
        const result = await executeRemoteCommand(button.command, button.params, {}, { includeDeviceId: true });
        const ok = result?.success;
        setMessage(
          ok
            ? { severity: 'success', text: `${button.label}: ok` }
            : { severity: 'error', text: `${button.label}: ${result?.error || 'failed'}` },
        );
        // A land reply carries the per-flight log path; show it on the panel.
        if (button.command === 'land') {
          const lp =
            result?.output_data?.log_path ||
            result?.log_path ||
            null;
          if (lp) setLastLogPath(lp);
          // Pull a quick summary so the panel can show row count + duration
          // without the user having to download the CSV.
          try {
            const summaryResp = await api.post<{ summary: any; log_path?: string }>(
              buildServerUrl('/server/drone/tello/flight_summary'),
              { host_name: host.host_name, device_id: deviceId },
            );
            if (summaryResp?.summary) setLastLogSummary(summaryResp.summary);
          } catch { /* non-fatal */ }
        }
        // Some commands change the airborne state — a fresh telemetry poll
        // will pick that up.
        if (button.command === 'takeoff' || button.command === 'land') {
          pollTelemetry();
        }
      } catch (requestError: any) {
        setMessage({ severity: 'error', text: `${button.label}: ${requestError?.message || 'failed'}` });
      } finally {
        setBusy(false);
      }
    },
    [executeRemoteCommand, host.host_name, deviceId],
  );

  const applySpeed = useCallback(async (_: Event | React.SyntheticEvent, value: number | number[]) => {
    const v = Array.isArray(value) ? value[0] : value;
    setSpeed(v);
    try {
      const result = await executeRemoteCommand('sdk', { cmd: `speed ${v}` }, {}, { includeDeviceId: true });
      if (!result?.success) {
        setMessage({ severity: 'error', text: `Speed ${v}: ${result?.error || 'failed'}` });
      }
    } catch (e: any) {
      setMessage({ severity: 'error', text: `Speed ${v}: ${e?.message || 'failed'}` });
    }
  }, [executeRemoteCommand]);

  const pollTelemetry = useCallback(async () => {
    try {
      const result = await executeRemoteCommand('get_telemetry', {}, {}, { includeDeviceId: true });
      if (result?.success) {
        const t = (result?.output_data?.telemetry || result?.telemetry || {}) as Telemetry;
        setTelemetry(t);
        setLinkOk(true);
      } else {
        setLinkOk(false);
      }
    } catch {
      setLinkOk(false);
    }
  }, [executeRemoteCommand]);

  // 2-second telemetry poll while the panel is mounted.
  useEffect(() => {
    pollTelemetry();
    telRef.current = window.setInterval(pollTelemetry, 2000);
    return () => {
      if (telRef.current != null) window.clearInterval(telRef.current);
    };
  }, [pollTelemetry]);

  // "Find my Tello" — fetch the freshest state + pose from the host. The
  // Tello has no GPS, so the position is whatever the controller's
  // dead-reckoned (or mission-pad-snapped) pose is at that moment, plus
  // how stale the state datagram is.
  const findTello = useCallback(async () => {
    setLocateLoading(true);
    try {
      const r = await api.post<{ success: boolean; state?: any; pose?: any; state_age_s?: number | null; log_path?: string | null; ip?: string; state_port?: number; airborne?: boolean }>(
        buildServerUrl('/server/drone/tello/last_known'),
        { host_name: host.host_name, device_id: deviceId },
      );
      if (r?.success) {
        setLastKnown({
          ip: r.ip,
          state_port: r.state_port,
          airborne: r.airborne,
          state: r.state,
          state_age_s: r.state_age_s,
          pose: r.pose,
          log_path: r.log_path,
        });
        if (r.log_path && !lastLogPath) setLastLogPath(r.log_path);
      } else {
        setMessage({ severity: 'error', text: `Find my Tello: ${(r as any)?.error || 'no data'}` });
      }
    } catch (e: any) {
      setMessage({ severity: 'error', text: `Find my Tello: ${e?.message || 'request failed'}` });
    } finally {
      setLocateLoading(false);
    }
  }, [host.host_name, deviceId, lastLogPath]);

  const batteryColor = useMemo(() => {
    if (telemetry?.bat == null) return 'default' as const;
    if (telemetry.bat < 20) return 'error' as const;
    if (telemetry.bat < 40) return 'warning' as const;
    return 'success' as const;
  }, [telemetry?.bat]);

  const tempColor = useMemo(() => {
    if (telemetry?.temph == null) return 'default' as const;
    if (telemetry.temph >= 85) return 'error' as const;
    if (telemetry.temph >= 70) return 'warning' as const;
    return 'default' as const;
  }, [telemetry?.temph]);

  // "Find my Tello" freshness colour: red if the link has been silent for
  // more than 10 s, amber if more than 3 s, default otherwise.
  const linkAgeColor = useMemo(() => {
    if (lastKnown?.state_age_s == null || lastKnown?.state_age_s == undefined) {
      return 'default' as const;
    }
    if (lastKnown.state_age_s > 10) return 'error' as const;
    if (lastKnown.state_age_s > 3) return 'warning' as const;
    return 'success' as const;
  }, [lastKnown?.state_age_s]);

  return (
    <Box sx={{ ...sx, display: 'flex', flexDirection: 'column', gap: 1.5, p: isCollapsed ? 1 : 1.5, overflow: 'auto' }}>
      {message && <Alert severity={message.severity} onClose={() => setMessage(null)}>{message.text}</Alert>}

      {/* Telemetry strip: live, polled every 2 s */}
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Chip
          size="small"
          color={linkOk === false ? 'error' : linkOk ? 'success' : 'default'}
          label={linkOk === false ? 'link: down' : linkOk ? 'link: ok' : 'link: ?'}
          variant="outlined"
        />
        <Chip size="small" color={batteryColor}
          label={telemetry?.bat != null ? `bat ${telemetry.bat}%` : 'bat ?'} variant="outlined" />
        <Chip size="small" color={tempColor}
          label={telemetry?.temph != null ? `temp ${telemetry.temph}°C` : 'temp ?'} variant="outlined" />
        {telemetry?.h != null && (
          <Chip size="small" color="primary" label={`alt ${telemetry.h} cm`} variant="outlined" />
        )}
        {telemetry?.tof != null && (
          <Chip size="small" label={`tof ${telemetry.tof} cm`} variant="outlined" />
        )}
        {telemetry?.pose_x != null && (
          <Chip size="small" color="info" label={`x ${Math.round(telemetry.pose_x)}`} variant="outlined" />
        )}
        {telemetry?.pose_y != null && (
          <Chip size="small" color="info" label={`y ${Math.round(telemetry.pose_y)}`} variant="outlined" />
        )}
        {telemetry?.pose_source === 'mission_pad' && (
          <Tooltip title="Pose snapped from a Mission Pad (Tello Talent only)">
            <Chip size="small" color="success" label={`pad ${telemetry.pad_id ?? '?'}`} variant="outlined" />
          </Tooltip>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" variant="text" onClick={() => setPairOpen(true)}>
          Pair Tello…
        </Button>
      </Stack>

      <Divider />

      {/* Movement buttons */}
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 1 }}>
        {MOVE_BUTTONS.map((button) => (
          <Button
            key={button.label}
            size="small"
            variant="outlined"
            color={button.color || 'inherit'}
            disabled={busy && button.command !== 'emergency'}
            onClick={() => run(button)}
          >
            {button.label}
          </Button>
        ))}
      </Box>

      {/* Speed slider */}
      <Box>
        <Typography variant="caption" color="textSecondary">
          Speed: <b>{speed} cm/s</b>
        </Typography>
        <Slider
          size="small" min={10} max={100} step={10}
          value={speed}
          onChange={(_, v) => setSpeed(Array.isArray(v) ? v[0] : v)}
          onChangeCommitted={applySpeed}
          marks={[{ value: 10 }, { value: 50 }, { value: 100 }]}
          valueLabelDisplay="auto"
        />
      </Box>

      {/* Flip buttons (5-second cooldown on the firmware) */}
      <Box>
        <Typography variant="caption" color="textSecondary">Flip (5 s cooldown)</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 0.5, mt: 0.5 }}>
          {FLIP_BUTTONS.map((button) => (
            <Tooltip key={button.label} title={button.label} arrow>
              <span>
                <Button size="small" variant="outlined" color="warning"
                  disabled={busy} onClick={() => run(button)}>
                  {button.label}
                </Button>
              </span>
            </Tooltip>
          ))}
        </Box>
      </Box>

      {/* Emergency */}
      <Box>
        <Button fullWidth size="small" variant="outlined" color={EMERGENCY_BUTTON.color}
          disabled={busy} onClick={() => run(EMERGENCY_BUTTON)}>
          {EMERGENCY_BUTTON.label}
        </Button>
      </Box>

      {/* Per-flight log (populated after a Land) */}
      {lastLogPath && (
        <Box sx={{ p: 1, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.default' }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <ArticleIcon fontSize="small" color="action" />
            <Typography variant="caption" sx={{ flexGrow: 1, wordBreak: 'break-all' }}>
              Last flight:&nbsp;
              <Box component="a"
                href={`/host/${encodeURIComponent(host.host_name)}/file?path=${encodeURIComponent(lastLogPath)}`}
                target="_blank" rel="noopener"
                sx={{ color: 'primary.main', textDecoration: 'underline' }}>
                {lastLogPath}
              </Box>
            </Typography>
          </Stack>
          {lastLogSummary && (
            <Stack direction="row" spacing={1} sx={{ mt: 0.5 }} flexWrap="wrap" useFlexGap>
              {lastLogSummary.rows != null && (
                <Chip size="small" label={`${lastLogSummary.rows} rows`} variant="outlined" />
              )}
              {lastLogSummary.duration_s != null && (
                <Chip size="small" label={`${Math.round(lastLogSummary.duration_s)} s`} variant="outlined" />
              )}
              {lastLogSummary.peak_altitude_cm != null && (
                <Chip size="small" label={`peak ${Math.round(lastLogSummary.peak_altitude_cm)} cm`} variant="outlined" />
              )}
            </Stack>
          )}
        </Box>
      )}

      {/* "Find my Tello" — collapsible */}
      <Box>
        <Button
          size="small"
          variant="outlined"
          startIcon={<LocationOnIcon />}
          endIcon={locateOpen ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          onClick={() => { if (!locateOpen) findTello(); setLocateOpen(o => !o); }}
          fullWidth
        >
          Find my Tello
        </Button>
        <Collapse in={locateOpen} unmountOnExit>
          <Box sx={{ mt: 1, p: 1, border: 1, borderColor: 'divider', borderRadius: 1 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="caption" sx={{ flexGrow: 1, color: 'text.secondary' }}>
                Last known position (Tello has no GPS — this is the controller's pose)
              </Typography>
              <Tooltip title="Refresh">
                <span>
                  <IconButton size="small" onClick={findTello} disabled={locateLoading}>
                    <RefreshIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
            </Stack>
            {lastKnown ? (
              <Stack spacing={0.5}>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip size="small" color={linkAgeColor}
                    label={lastKnown.state_age_s != null
                      ? `state age ${lastKnown.state_age_s.toFixed(1)} s`
                      : 'state age ?'}
                    variant="outlined" />
                  <Chip size="small" label={lastKnown.airborne ? 'airborne' : 'grounded'} variant="outlined" />
                  {lastKnown.pose && (
                    <>
                      <Chip size="small" color="info" label={`x ${Math.round(lastKnown.pose.x)} cm`} variant="outlined" />
                      <Chip size="small" color="info" label={`y ${Math.round(lastKnown.pose.y)} cm`} variant="outlined" />
                      <Chip size="small" color="info" label={`z ${Math.round(lastKnown.pose.z)} cm`} variant="outlined" />
                      <Chip size="small" label={`yaw ${Math.round(lastKnown.pose.yaw)}°`} variant="outlined" />
                    </>
                  )}
                </Stack>
                {lastKnown.ip && (
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                    link: {lastKnown.ip}:{lastKnown.state_port}
                  </Typography>
                )}
                {lastKnown.log_path && (
                  <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                    log: {lastKnown.log_path}
                  </Typography>
                )}
                {lastKnown.state && (
                  <Typography variant="caption" color="text.secondary">
                    h {lastKnown.state.h ?? '?'} cm · tof {lastKnown.state.tof ?? '?'} cm · bat {lastKnown.state.bat ?? '?'}%
                  </Typography>
                )}
              </Stack>
            ) : (
              <Typography variant="caption" color="text.secondary">Click Find to query the host.</Typography>
            )}
          </Box>
        </Collapse>
      </Box>

      <Typography variant="caption" color="textSecondary">
        Moves are checked against the room fence, height and battery limits before they are sent.
      </Typography>

      <TelloPairDialog
        open={pairOpen}
        host={host}
        deviceId={deviceId || ''}
        onClose={() => setPairOpen(false)}
        onPaired={() => pollTelemetry()}
      />
    </Box>
  );
});
