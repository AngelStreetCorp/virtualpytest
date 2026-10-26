import { Box, Button, IconButton, Tooltip, Typography } from '@mui/material';
import { keyframes } from '@mui/system';
import FlightTakeoffIcon from '@mui/icons-material/FlightTakeoff';
import FlightLandIcon from '@mui/icons-material/FlightLand';
import PanToolIcon from '@mui/icons-material/PanTool';
import HistoryIcon from '@mui/icons-material/History';
import WifiIcon from '@mui/icons-material/Wifi';
import WifiOffIcon from '@mui/icons-material/WifiOff';
import KeyboardDoubleArrowUpIcon from '@mui/icons-material/KeyboardDoubleArrowUp';
import KeyboardDoubleArrowDownIcon from '@mui/icons-material/KeyboardDoubleArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowLeftIcon from '@mui/icons-material/KeyboardArrowLeft';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import RotateLeftIcon from '@mui/icons-material/RotateLeft';
import RotateRightIcon from '@mui/icons-material/RotateRight';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { DroneBatteryBadge } from '../../rec/DroneBatteryBadge';
import { DroneFlightHistory } from '../../drone/DroneFlightHistory';
import { useControllerApi } from '../../../hooks/controller/useControllerApi';
import { droneHeadline, useDroneWifiStatus, DroneTelemetry } from '../../../hooks/rec/useDroneWifiStatus';
import { Host } from '../../../types/common/Host_Types';
import { TYPOGRAPHY } from '../../../constants/typography';

// TASK-32: Tello remote, layout approved by the owner 2026-10-13.
//   status strip   battery · Wi-Fi · HS m/s · H m
//   main button    Take off (gold) -> red "Tap again to take off" (3 s) -> "Taking off…" (pulses)
//                  -> Land -> "Landing…" (pulses); emergency stop (hand) beside it while in the air
//   flip row       Flip forward / back / left / right (SDK flip f|b|l|r), only while flying
//   controls       centred: Up above, Rotate left | move pad | Rotate right, Down below.
//                  Everything held sends SDK `rc lr fb ud yaw` ~10 Hz, `rc 0 0 0 0` on release.
// Landed: the same layout, greyed. The controls enable as soon as the take-off is sent (optimistic,
// rolled back if it fails), not after the next telemetry poll. Every command still goes through
// the host's SafetyGuard (caps rc, keeps the height band, lands at the battery floor).
// The panel follows the device tile's pairing (useDroneWifiStatus); link down = all greyed + Scan.

interface TelloRemoteProps {
  host: Host;
  deviceId?: string;
  isCollapsed: boolean;
  sx?: any;
}

/** The second tap must come within this window, or Take off disarms again. */
export const TAKEOFF_ARM_MS = 3000;

/** Hold send rate. */
const RC_PERIOD_MS = 100;

/** Up/Down/Rotate buttons send this rc value while held (the guard caps it). */
const RC_BUTTON = 100;

export type FlightPhase = 'landed' | 'armed' | 'taking_off' | 'flying' | 'landing';

const FLIPS = [
  { label: 'Flip forward', cmd: 'flip f', icon: <ArrowUpwardIcon /> },
  { label: 'Flip back', cmd: 'flip b', icon: <ArrowDownwardIcon /> },
  { label: 'Flip left', cmd: 'flip l', icon: <ArrowBackIcon /> },
  { label: 'Flip right', cmd: 'flip r', icon: <ArrowForwardIcon /> },
];

/** State height (cm) at or below which the drone is on the floor (the Tello reads -10..0 landed). */
const GROUND_H_CM = 10;

const pulse = keyframes`
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
`;

/** Horizontal speed in m/s from the state datagram (vgx/vgy are dm/s); 0 when landed. */
export function droneHorizontalSpeedMs(t: DroneTelemetry | null | undefined, airborne: boolean): number {
  if (!airborne || !t) return 0;
  return Math.round(Math.hypot(t.vgx ?? 0, t.vgy ?? 0)) / 10;
}

/** Height in m from `h` (cm); 0 when landed. */
export function droneHeightM(t: DroneTelemetry | null | undefined, airborne: boolean): number {
  if (!airborne || !t || t.h == null) return 0;
  return Math.round(t.h / 10) / 10;
}

/** Stick offset (-1..1 per axis, y up = +) from a pointer position inside the pad. */
export function stickVector(rect: { left: number; top: number; width: number; height: number }, x: number, y: number) {
  const r = rect.width / 2;
  let dx = (x - (rect.left + r)) / r;
  let dy = -(y - (rect.top + rect.height / 2)) / r;
  const len = Math.hypot(dx, dy);
  if (len > 1) {
    dx /= len;
    dy /= len;
  }
  return { x: dx, y: dy };
}

type Vec = { x: number; y: number };
const ZERO: Vec = { x: 0, y: 0 };

/** The round move pad: forward/back = pitch, left/right = roll. Knob follows the pointer while held. */
const MovePad: React.FC<{ disabled: boolean; onChange: (v: Vec) => void }> = ({ disabled, onChange }) => {
  const P = useAgentChatPalette();
  const padRef = useRef<HTMLDivElement | null>(null);
  const [vec, setVec] = useState<Vec>(ZERO);
  const [held, setHeld] = useState(false);

  const update = (e: React.PointerEvent) => {
    const el = padRef.current;
    if (!el) return;
    const v = stickVector(el.getBoundingClientRect(), e.clientX, e.clientY);
    setVec(v);
    onChange(v);
  };
  const release = () => {
    if (!held) return;
    setHeld(false);
    setVec(ZERO);
    onChange(ZERO);
  };
  // Greyed mid-hold (link lost, landed): stop at once.
  useEffect(() => {
    if (disabled) release();
  }, [disabled]);

  const iconSx = { position: 'absolute', color: disabled ? P.textMuted : P.textSecondary, fontSize: TYPOGRAPHY.kpiValue.size, pointerEvents: 'none' } as const;
  // No tooltip here on purpose: the stick is press-and-hold, so the pointer stays on the pad for
  // the whole flight and a hover tooltip parks itself over the controls, hiding the pad you steer
  // with. The direction arrows are the label, and the aria-label keeps it for screen readers.
  return (
    <Box
      ref={padRef}
      role="slider"
      aria-label="Move pad"
      aria-disabled={disabled}
      onPointerDown={(e) => {
        if (disabled) return;
        setHeld(true);
        e.currentTarget.setPointerCapture?.(e.pointerId);
        update(e);
      }}
      onPointerMove={(e) => held && update(e)}
      onPointerUp={release}
      onPointerCancel={release}
      onLostPointerCapture={release}
      sx={{
        position: 'relative',
        width: 150,
        height: 150,
        flexShrink: 1,
        minWidth: 112,
        aspectRatio: '1 / 1',
        borderRadius: '50%',
        border: `2px solid ${disabled ? P.borderColor : P.textMuted}`,
        bgcolor: P.hoverBg,
        touchAction: 'none',
        userSelect: 'none',
        cursor: disabled ? 'default' : 'grab',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <Box sx={{ ...iconSx, top: 4, left: '50%', transform: 'translateX(-50%)' }}><KeyboardArrowUpIcon fontSize="inherit" /></Box>
      <Box sx={{ ...iconSx, bottom: 4, left: '50%', transform: 'translateX(-50%)' }}><KeyboardArrowDownIcon fontSize="inherit" /></Box>
      <Box sx={{ ...iconSx, left: 4, top: '50%', transform: 'translateY(-50%)' }}><KeyboardArrowLeftIcon fontSize="inherit" /></Box>
      <Box sx={{ ...iconSx, right: 4, top: '50%', transform: 'translateY(-50%)' }}><KeyboardArrowRightIcon fontSize="inherit" /></Box>
      <Box
        sx={{
          position: 'absolute',
          width: '30%',
          height: '30%',
          borderRadius: '50%',
          left: `${35 + vec.x * 35}%`,
          top: `${35 - vec.y * 35}%`,
          bgcolor: held ? P.accent : P.surface,
          border: `2px solid ${disabled ? P.borderColor : P.textSecondary}`,
          pointerEvents: 'none',
        }}
      />
    </Box>
  );
};

/** A round press-and-hold button (Up, Down, Rotate): `onHold(true)` on press, `false` on release. */
const HoldButton: React.FC<{ label: string; disabled: boolean; onHold: (down: boolean) => void; children: React.ReactNode }> = ({
  label, disabled, onHold, children,
}) => {
  const P = useAgentChatPalette();
  const [down, setDown] = useState(false);
  const release = () => {
    if (!down) return;
    setDown(false);
    onHold(false);
  };
  useEffect(() => {
    if (disabled) release();
  }, [disabled]);
  // No tooltip here for the same reason as the move pad: this is press-and-hold, so the pointer
  // stays on the button for the whole flight and the tooltip parks itself over the controls next to
  // it. The icon is the label, and aria-label keeps it for screen readers.
  return (
    <IconButton
      aria-label={label}
      disabled={disabled}
      onPointerDown={(e) => {
        setDown(true);
        e.currentTarget.setPointerCapture?.(e.pointerId);
        onHold(true);
      }}
      onPointerUp={release}
      onPointerCancel={release}
      onLostPointerCapture={release}
      sx={{
        width: 52,
        height: 52,
        touchAction: 'none',
        // The wrapper used to be a span with min-width auto, which is what stopped these round
        // buttons from being squashed in the row; without it, say so explicitly.
        flexShrink: 0,
        border: `2px solid ${down ? P.accentText : P.textMuted}`,
        color: down ? P.accentText : P.textSecondary,
        bgcolor: down ? `${P.accent}26` : P.hoverBg,
        '&.Mui-disabled': { borderColor: P.borderColor, color: P.textMuted, opacity: 0.5 },
        '& .MuiSvgIcon-root': { fontSize: TYPOGRAPHY.pageTitle.size },
      }}
    >
      {children}
    </IconButton>
  );
};

export const TelloRemote = React.memo(function TelloRemote({
  host,
  deviceId,
  isCollapsed,
  sx = {},
}: TelloRemoteProps) {
  const P = useAgentChatPalette();
  const { executeRemoteCommand } = useControllerApi(host, deviceId);
  const device = useMemo(() => host.devices?.find((d) => d.device_id === deviceId), [host.devices, deviceId]);
  const wifi = useDroneWifiStatus(host, device, Boolean(device));
  const paired = wifi.state === 'connected';

  const [phase, setPhase] = useState<FlightPhase>('landed');
  const [historyOpen, setHistoryOpen] = useState(false);
  const phaseRef = useRef<FlightPhase>('landed');
  phaseRef.current = phase;
  const [message, setMessage] = useState<string | null>(null);
  const [telemetry, setTelemetry] = useState<DroneTelemetry | null>(null);
  const telemetryRef = useRef<DroneTelemetry | null>(null);
  telemetryRef.current = telemetry;
  const [flipBusy, setFlipBusy] = useState(false);
  const armTimer = useRef<number | null>(null);

  const pollTelemetry = useCallback(async () => {
    try {
      const result = await executeRemoteCommand('get_telemetry', {}, {}, { includeDeviceId: true });
      if (!result?.success) return;
      setTelemetry((result?.output_data?.telemetry || result?.telemetry || {}) as DroneTelemetry);
      const up = Boolean(result?.output_data?.airborne ?? result?.airborne);
      // A command in progress owns the phase; otherwise the host's word wins (auto-land, a script).
      const p = phaseRef.current;
      if (p === 'taking_off' || p === 'landing' || p === 'armed') return;
      setPhase(up ? 'flying' : 'landed');
    } catch {
      // The pairing hook reports a lost drone; this poll only refreshes the readings.
    }
  }, [executeRemoteCommand]);

  // 2-second telemetry poll while the drone is paired.
  useEffect(() => {
    if (!paired) return undefined;
    void pollTelemetry();
    const timer = window.setInterval(pollTelemetry, 2000);
    return () => window.clearInterval(timer);
  }, [paired, pollTelemetry]);

  const run = useCallback(async (label: string, command: string, params: Record<string, unknown> = {}) => {
    try {
      const result = await executeRemoteCommand(command, params, {}, { includeDeviceId: true });
      if (result?.success) {
        setMessage(result?.already_grounded || result?.output_data?.already_grounded ? 'Already on the ground' : null);
        return true;
      }
      setMessage(`${label}: ${result?.error || 'failed'}`);
    } catch (e: any) {
      setMessage(`${label}: ${e?.message || 'failed'}`);
    }
    return false;
  }, [executeRemoteCommand]);

  // --- one rc stream for the pad and the hold buttons ----------------------------------------
  const pad = useRef<Vec>(ZERO);
  const ud = useRef(0);
  const yaw = useRef(0);
  const rcTimer = useRef<number | null>(null);
  const rcInFlight = useRef(false);

  const rcParams = () => ({
    lr: Math.round(pad.current.x * 100),
    fb: Math.round(pad.current.y * 100),
    ud: ud.current,
    yaw: yaw.current,
  });
  const sendRc = useCallback(() => {
    // Drop a frame rather than queue: the next tick carries the newest position.
    if (rcInFlight.current) return;
    rcInFlight.current = true;
    executeRemoteCommand('rc', rcParams(), {}, { includeDeviceId: true })
      .catch(() => undefined)
      .finally(() => {
        rcInFlight.current = false;
      });
  }, [executeRemoteCommand]);

  const rcChanged = useCallback(() => {
    const active = pad.current !== ZERO || ud.current !== 0 || yaw.current !== 0;
    if (active && rcTimer.current == null) {
      sendRc();
      rcTimer.current = window.setInterval(sendRc, RC_PERIOD_MS);
    } else if (!active && rcTimer.current != null) {
      window.clearInterval(rcTimer.current);
      rcTimer.current = null;
      // The stop always goes out, even with a frame still in flight.
      void executeRemoteCommand('rc', { lr: 0, fb: 0, ud: 0, yaw: 0 }, {}, { includeDeviceId: true }).catch(() => undefined);
    }
  }, [executeRemoteCommand, sendRc]);

  useEffect(() => () => {
    if (rcTimer.current != null) window.clearInterval(rcTimer.current);
    if (armTimer.current != null) window.clearTimeout(armTimer.current);
  }, []);

  // --- main button ----------------------------------------------------------------------------
  const onMain = useCallback(async () => {
    if (!paired) {
      wifi.rescan();
      return;
    }
    if (phase === 'flying') {
      setPhase('landing');
      const ok = await run('Land', 'land');
      // A refused land never strands the button: when the height reads ~0 the drone is down, so
      // Take off comes back whatever the answer was; the poll then corrects any other case.
      const h = telemetryRef.current?.h;
      const down = h != null && h <= GROUND_H_CM;
      if (!ok && down) setMessage('Already on the ground');
      setPhase(ok || down ? 'landed' : 'flying');
      void pollTelemetry();
      return;
    }
    if (phase === 'landed') {
      setPhase('armed');
      armTimer.current = window.setTimeout(() => {
        if (phaseRef.current === 'armed') setPhase('landed');
      }, TAKEOFF_ARM_MS);
      return;
    }
    if (phase === 'armed') {
      if (armTimer.current != null) window.clearTimeout(armTimer.current);
      armTimer.current = null;
      // Optimistic: the controls enable now; a failed take-off rolls back.
      setPhase('taking_off');
      const ok = await run('Take off', 'takeoff');
      setPhase(ok ? 'flying' : 'landed');
      void pollTelemetry();
    }
  }, [paired, phase, run, pollTelemetry, wifi]);

  const onEmergency = useCallback(async () => {
    const ok = await run('Emergency stop', 'emergency');
    if (ok) setPhase('landed');
    void pollTelemetry();
  }, [run, pollTelemetry]);

  const onFlip = useCallback(async (label: string, cmd: string) => {
    setFlipBusy(true);
    await run(label, 'sdk', { cmd });
    setFlipBusy(false);
  }, [run]);

  const inAir = phase === 'taking_off' || phase === 'flying' || phase === 'landing';
  const controlsOn = paired && inAir;
  const t = telemetry ?? wifi.telemetry;
  const hs = droneHorizontalSpeedMs(t, inAir);
  const hm = droneHeightM(t, inAir);

  const main = !paired
    ? { label: wifi.busy ? 'Scanning…' : 'Scan', icon: null, color: 'primary' as const, pulsing: false, disabled: wifi.busy }
    : phase === 'armed'
      ? { label: 'Tap again to take off', icon: <FlightTakeoffIcon />, color: 'error' as const, pulsing: false, disabled: false }
      : phase === 'taking_off'
        ? { label: 'Taking off…', icon: <FlightTakeoffIcon />, color: 'primary' as const, pulsing: true, disabled: true }
        : phase === 'flying'
          ? { label: 'Land', icon: <FlightLandIcon />, color: 'primary' as const, pulsing: false, disabled: false }
          : phase === 'landing'
            ? { label: 'Landing…', icon: <FlightLandIcon />, color: 'primary' as const, pulsing: true, disabled: true }
            : { label: 'Take off', icon: <FlightTakeoffIcon />, color: 'primary' as const, pulsing: false, disabled: false };

  const lineText = !paired
    ? wifi.state === 'connecting' ? droneHeadline(wifi.state, wifi.droneName, device?.device_name) : 'Not paired'
    : message;

  return (
    <Box sx={{ ...sx, display: 'flex', flexDirection: 'column', gap: 1.25, p: isCollapsed ? 1 : 1.5, overflow: 'auto' }}>
      {/* Status strip: battery, link, HS, H */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minHeight: 24, whiteSpace: 'nowrap' }}>
        {paired && t.bat != null ? (
          <DroneBatteryBadge telemetry={{ bat: t.bat }} />
        ) : (
          <Tooltip title="Battery unknown">
            <Box aria-label="Battery unknown" sx={{ width: 18, height: 9, border: `1.5px solid ${P.error}`, borderRadius: '2px', flexShrink: 0 }} />
          </Tooltip>
        )}
        <Tooltip title={paired ? 'Linked' : 'Not linked'}>
          {paired ? (
            <WifiIcon aria-label="Linked" sx={{ fontSize: TYPOGRAPHY.pageSubtitle.size, color: P.textSecondary }} />
          ) : (
            <WifiOffIcon aria-label="Not linked" sx={{ fontSize: TYPOGRAPHY.pageSubtitle.size, color: P.textMuted }} />
          )}
        </Tooltip>
        <Box sx={{ width: '1px', alignSelf: 'stretch', bgcolor: P.borderColor }} />
        {[
          { k: 'HS', v: `${hs.toFixed(1)} m/s` },
          { k: 'H', v: `${hm.toFixed(1)} m` },
        ].map((r) => (
          <Typography key={r.k} component="span" sx={{ fontSize: TYPOGRAPHY.body.size, color: paired ? P.textPrimary : P.textMuted, fontVariantNumeric: 'tabular-nums' }}>
            <Box component="span" sx={{ fontWeight: 700, color: P.textSecondary, mr: 0.5 }}>{r.k}</Box>
            {r.v}
          </Typography>
        ))}
        <Tooltip title="Flight history: every command sent, flights, path and battery">
          <IconButton size="small" aria-label="Flight history" data-testid="open-flight-history" onClick={() => setHistoryOpen(true)} sx={{ ml: 'auto', color: P.textSecondary }}>
            <HistoryIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      {/* Main button + emergency slot (reserved, so the button never changes width) */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Button
          fullWidth
          variant="contained"
          color={main.color}
          disabled={main.disabled && !main.pulsing}
          onClick={main.disabled ? undefined : onMain}
          startIcon={main.icon}
          aria-busy={main.pulsing}
          sx={{
            height: 52,
            fontSize: TYPOGRAPHY.navbarItem.size,
            fontWeight: 600,
            whiteSpace: 'nowrap',
            '& .MuiButton-startIcon .MuiSvgIcon-root': { fontSize: TYPOGRAPHY.kpiValue.size },
            ...(main.pulsing ? { animation: `${pulse} 0.9s ease-in-out infinite`, pointerEvents: 'none' } : {}),
          }}
        >
          {main.label}
        </Button>
        <Box sx={{ width: 52, height: 52, flexShrink: 0 }}>
          {paired && inAir && (
            <Tooltip title="Emergency stop">
              <IconButton
                aria-label="Emergency stop"
                onClick={onEmergency}
                sx={{ width: 52, height: 52, border: `2px solid ${P.dangerText}`, color: P.dangerText, '& .MuiSvgIcon-root': { fontSize: TYPOGRAPHY.pageTitle.size } }}
              >
                <PanToolIcon />
              </IconButton>
            </Tooltip>
          )}
        </Box>
      </Box>

      {/* One fixed-height line: link state or the last error */}
      <Typography
        variant="caption"
        onClick={() => setMessage(null)}
        sx={{ minHeight: 18, color: paired ? P.error : P.textSecondary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {lineText}
      </Typography>

      {/* Flips */}
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 0.75 }}>
        {FLIPS.map((f) => (
          <Tooltip key={f.cmd} title={f.label}>
            <span>
              <Button
                fullWidth
                size="small"
                variant="outlined"
                aria-label={f.label}
                disabled={!paired || phase !== 'flying' || flipBusy}
                onClick={() => void onFlip(f.label, f.cmd)}
                startIcon={f.icon}
                sx={{ minWidth: 0, px: 0.5, whiteSpace: 'nowrap', '& .MuiButton-startIcon': { mr: 0.5 } }}
              >
                Flip
              </Button>
            </span>
          </Tooltip>
        ))}
      </Box>

      {/* Controls, centred across and right under the flips (owner: no gap above them):
          Up / Rotate left · pad · Rotate right / Down */}
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1, mt: 1 }}>
        <HoldButton label="Up" disabled={!controlsOn} onHold={(d) => { ud.current = d ? RC_BUTTON : 0; rcChanged(); }}>
          <KeyboardDoubleArrowUpIcon />
        </HoldButton>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <HoldButton label="Rotate left" disabled={!controlsOn} onHold={(d) => { yaw.current = d ? -RC_BUTTON : 0; rcChanged(); }}>
            <RotateLeftIcon />
          </HoldButton>
          <MovePad disabled={!controlsOn} onChange={(v) => { pad.current = v.x === 0 && v.y === 0 ? ZERO : v; rcChanged(); }} />
          <HoldButton label="Rotate right" disabled={!controlsOn} onHold={(d) => { yaw.current = d ? RC_BUTTON : 0; rcChanged(); }}>
            <RotateRightIcon />
          </HoldButton>
        </Box>
        <HoldButton label="Down" disabled={!controlsOn} onHold={(d) => { ud.current = d ? -RC_BUTTON : 0; rcChanged(); }}>
          <KeyboardDoubleArrowDownIcon />
        </HoldButton>
      </Box>
      <DroneFlightHistory open={historyOpen} onClose={() => setHistoryOpen(false)} hostName={host.host_name} deviceId={deviceId} deviceName={device?.device_name} />
    </Box>
  );
});
