import { Box, Tooltip } from '@mui/material';
import React from 'react';

import { AGENT_CHAT_PALETTE, useAgentChatPalette } from '../../constants/agentChatTheme';
import type { Host, Device } from '../../types/common/Host_Types';
import { isDroneDevice, useDroneWifiStatus, type DroneTelemetry, type DroneWifiStatus } from '../../hooks/rec/useDroneWifiStatus';
import { TYPOGRAPHY } from '../../constants/typography';

/** Battery colour: red at or below the Tello's take-off floor area, amber below half. */
export function batteryColor(pct: number, P: ReturnType<typeof useAgentChatPalette>): string {
  if (pct <= 20) return P.error;
  if (pct <= 50) return P.warning;
  return P.success;
}

/** Filled bars (0-4) for a percentage: 1-25 = 1 bar ... 76-100 = 4 bars. */
export function batteryBars(pct: number): number {
  return Math.max(0, Math.min(4, Math.ceil(pct / 25)));
}

interface DroneBatteryBadgeProps {
  telemetry: DroneTelemetry;
  /** 'sm' on the device tile, 'md' in the stream modal. */
  size?: 'sm' | 'md';
  /** Fixed palette (the video overlay is dark in both themes); default: the theme's. */
  palette?: typeof AGENT_CHAT_PALETTE;
}

/**
 * Battery icon with 4 bars + percentage, and the drone's temperature when it sends one.
 * Renders nothing until the host has a battery reading.
 */
export const DroneBatteryBadge: React.FC<DroneBatteryBadgeProps> = ({ telemetry, size = 'sm', palette }) => {
  const themeP = useAgentChatPalette();
  const P = palette ?? themeP;
  const bat = telemetry.bat;
  if (bat == null) return null;
  const color = batteryColor(bat, P);
  const bars = batteryBars(bat);
  const temp = telemetry.temph ?? telemetry.templ;
  const md = size === 'md';
  const bodyW = md ? 22 : 18;
  const bodyH = md ? 11 : 9;
  const tooltip =
    temp != null
      ? `Battery ${bat}% · Temperature ${telemetry.templ != null && telemetry.temph != null && telemetry.templ !== telemetry.temph ? `${telemetry.templ}–${telemetry.temph}` : temp} °C`
      : `Battery ${bat}%`;

  return (
    <Tooltip title={tooltip} arrow>
      <Box
        aria-label={tooltip}
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.5,
          flexShrink: 0,
          whiteSpace: 'nowrap',
          fontSize: md ? '0.8125rem' : '0.75rem',
          fontWeight: 600,
          color: P.textSecondary,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <Box sx={{ display: 'inline-flex', alignItems: 'center' }}>
          <Box
            sx={{
              width: bodyW,
              height: bodyH,
              border: `1.5px solid ${P.textSecondary}`,
              borderRadius: '2px',
              p: '1px',
              display: 'flex',
              gap: '1px',
              boxSizing: 'border-box',
            }}
          >
            {[0, 1, 2, 3].map((i) => (
              <Box key={i} sx={{ flex: 1, borderRadius: '1px', bgcolor: i < bars ? color : 'transparent' }} />
            ))}
          </Box>
          <Box sx={{ width: 2, height: bodyH / 2, bgcolor: P.textSecondary, borderRadius: '0 1px 1px 0' }} />
        </Box>
        <Box component="span" sx={{ color }}>{bat}%</Box>
        {temp != null && <Box component="span">{temp}°C</Box>}
      </Box>
    </Tooltip>
  );
};


interface DroneTelemetryOverlayProps {
  host: Host;
  device?: Device;
  /** Stream modal: battery, temperature, HS (m/s) and H (m). Tile: battery and temperature. */
  full?: boolean;
  /** The caller's own pairing status (the tile has one); without it the overlay reads its own. */
  status?: DroneWifiStatus;
}

/**
 * Drone readings at the top-right corner of the video: a small translucent dark plate, the same
 * in both themes so it reads over a bright picture. Read-only (passive): the tile owns the
 * scan and the pairing. Renders nothing for a non-drone device or a drone that is not paired.
 */
export const DroneTelemetryOverlay: React.FC<DroneTelemetryOverlayProps> = ({ host, device, full = false, status }) => {
  const P = AGENT_CHAT_PALETTE;
  const isDrone = isDroneDevice(device);
  const own = useDroneWifiStatus(host, device, isDrone && !status, { passive: true });
  const wifi = status ?? own;
  const t = wifi.telemetry;
  if (!isDrone || wifi.state !== 'connected' || t.bat == null) return null;
  const hs = wifi.airborne ? Math.round(Math.hypot(t.vgx ?? 0, t.vgy ?? 0)) / 10 : 0;
  const h = wifi.airborne && t.h != null ? Math.round(t.h / 10) / 10 : 0;
  return (
    <Box
      sx={{
        position: 'absolute',
        top: 6,
        right: 6,
        // Tile: just above its own video, never above the stream modal opened over the grid.
        // Modal: above the player bars, below the monitoring cards (1300).
        zIndex: full ? 1250 : 2,
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 0.75,
        py: 0.25,
        borderRadius: 1,
        bgcolor: `${P.background}b3`,
        pointerEvents: 'auto',
      }}
    >
      <DroneBatteryBadge telemetry={t} size={full ? 'md' : 'sm'} palette={P} />
      {full &&
        [
          { k: 'HS', v: `${hs.toFixed(1)}m/s` },
          { k: 'H', v: `${h.toFixed(1)}m` },
        ].map((r) => (
          <Box key={r.k} component="span" sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
            <Box component="span" sx={{ fontWeight: 700, color: P.textSecondary, mr: 0.5 }}>{r.k}</Box>
            {r.v}
          </Box>
        ))}
    </Box>
  );
};
