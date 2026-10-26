import { Box, Tooltip } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import type { Host, Device } from '../../types/common/Host_Types';
import { api } from '../../utils/apiClient';
import { buildHostServerUrl } from '../../utils/buildUrlUtils';
import { isUnnamedKnownScreen, type ScreenVerdict } from '../../utils/screenVerdict';
import { localizeOff } from '../navigation/Navigation_LocalizeButton';

// Only the tv_app analyzer writes `localize` (the tv_app profile, and profiles that stack it such as
// caption_playback), and only for a device with DEVICE{N}_USERINTERFACE. A device whose frames carry
// none (any other profile) is polled rarely after a few misses.
const IDLE_POLL_MS = 30000;
const IDLE_AFTER_MISSES = 3;

type Verdict = NonNullable<ScreenVerdict['verdict']>;

/** The found node's name (`home`, `Black Screen`, `Live video`), nothing for unknown. The confidence is not shown. */
export function localizeBadgeText(v?: Verdict | null): string | null {
  if (!v || v.kind === 'unknown' || !v.label) return null;
  if (v.kind === 'known_screen' && isUnnamedKnownScreen(v)) return null;
  // Node name only: "Home (tab bar hidden)" reads "Home" (owner 2026-10-19).
  return v.label.replace(/\s*\([^)]*\)\s*/g, ' ').trim() || null;
}

interface LocalizeVideoBadgeProps {
  host: Host;
  device?: Device;
  /** Stream modal (polls 1 s, larger text); tile otherwise (polls 3 s). */
  full?: boolean;
}

/**
 * The monitor's Localize verdict at the top-right corner of the video (TASK-115): the same
 * `analysis.localize.verdict` the Monitoring overlay's "Screen:" line reads. Static (no
 * animation); renders nothing on unknown, for a device whose frames carry no Localize and when
 * monitoring is off. Stays visible in the stream modal when the Monitoring overlay is open
 * (ERROR/WARNING sit below this chip).
 */
export const LocalizeVideoBadge: React.FC<LocalizeVideoBadgeProps> = ({ host, device, full = false }) => {
  const P = useAgentChatPalette();
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const deviceId = device?.device_id;
  const enabled = !!deviceId && !localizeOff(host, deviceId);

  useEffect(() => {
    if (!enabled) {
      setVerdict(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let misses = 0;
    const activeMs = full ? 1000 : 3000;
    const poll = async () => {
      if (document.visibilityState === 'visible') {
        try {
          const res = await api.post<{ success?: boolean; json_data?: { localize?: ScreenVerdict } }>(
            buildHostServerUrl(host, '/server/monitoring/latest-json'),
            { host_name: host.host_name, device_id: deviceId },
          );
          const v = res?.json_data?.localize?.verdict ?? null;
          misses = res?.json_data?.localize ? 0 : misses + 1;
          if (!cancelled) setVerdict(v);
        } catch {
          misses += 1;
        }
      }
      if (!cancelled) timer = setTimeout(poll, misses >= IDLE_AFTER_MISSES ? IDLE_POLL_MS : activeMs);
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, full, host.host_name, host.server_url, deviceId]);

  const text = localizeBadgeText(verdict);
  if (!enabled || !text) return null;
  const chip = (
      <Box
        sx={{
          position: 'absolute',
          top: 6,
          right: 6,
          // Full modal: above the monitoring overlay (z 1300) so the chip is not covered.
          // Tile: above the video, below card chrome.
          zIndex: full ? 1310 : 2,
          maxWidth: '60%',
          px: 0.75,
          py: 0.25,
          borderRadius: 1,
          bgcolor: `${P.background}cc`,
          color: P.textPrimary,
          fontSize: full ? '0.8125rem' : '0.75rem',
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          pointerEvents: 'auto',
        }}
      >
        {text}
      </Box>
  );
  // Tile: the chip is short on space, so the tooltip carries the full node name. Modal: the chip
  // has room for the whole name, so it has no tooltip.
  if (full) return chip;
  return (
    <Tooltip title={text} arrow>
      {chip}
    </Tooltip>
  );
};
