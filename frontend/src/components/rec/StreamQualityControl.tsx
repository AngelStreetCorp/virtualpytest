import { Box, ToggleButton, ToggleButtonGroup, Tooltip } from '@mui/material';
import type { MouseEvent } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import type { LiveStreamTransport } from '../../types/controller/WebRTC_Types';
import { webrtcSupportedFor, webrtcUnavailableReason } from '../../utils/streamCapability';
import { segmentedSx } from '../common/PageChrome';

type Quality = 'low' | 'sd' | 'hd' | 'hd_plus';

interface StreamQualityControlProps {
  quality: Quality;
  transport: LiveStreamTransport;
  disabled: boolean;
  compact?: boolean;
  /** Host advertises VAAPI H.264 encode (`system_stats.hardware_encode`): offer HD+. */
  supportsHdPlus?: boolean;
  /** Device's declared stream profile (`stream_protocol`). Absent = not reported = keep WEB. */
  streamProtocol?: string;
  onQualityChange: (event: MouseEvent<HTMLElement>, quality: Quality | null) => void;
  onToggleTransport: () => void;
}

/**
 * Two controls side by side: the HLS resolution (LOW / SD / HD, HD+ on VAAPI hosts) is always
 * highlighted, and WEB is its own on/off toggle. The host runs one encode, so WebRTC carries the
 * highlighted resolution; changing it keeps WEB on (WebRTC reconnects after the ffmpeg restart).
 * No in-button spinners: loading shows in the content area (RecStreamContainer).
 *
 * WEB is hidden entirely when the device's profile denies it (BUG-0833) — a toggle that
 * cannot work is worse than no toggle, since every press costs a 6 s timeout and an error.
 */
export const StreamQualityControl = ({
  quality, transport, disabled, compact, supportsHdPlus = false, streamProtocol,
  onQualityChange, onToggleTransport,
}: StreamQualityControlProps) => {
  const P = useAgentChatPalette();
  const shownQuality = quality === 'hd_plus' && !supportsHdPlus ? 'hd' : quality;
  const webrtcAvailable = webrtcSupportedFor(streamProtocol);
  const segmented = segmentedSx(P, 'sm');
  const groupSx = [
    ...(Array.isArray(segmented) ? segmented : [segmented]),
    {
      flexShrink: 0,
      '& .MuiToggleButton-root': {
        minWidth: compact ? 36 : 48,
        height: compact ? 32 : 40,
        px: compact ? 0.5 : 1,
      },
    },
  ];

  const selectQuality = (event: MouseEvent<HTMLElement>, value: Quality | null) => {
    if (value) onQualityChange(event, value);
  };

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: compact ? 0.5 : 1, flexShrink: 0 }}>
      <ToggleButtonGroup
        data-testid="quality-bar"
        value={shownQuality}
        exclusive
        onChange={selectQuality}
        disabled={disabled}
        aria-label="Stream quality"
        sx={groupSx}
      >
        <ToggleButton value="low">LOW</ToggleButton>
        <ToggleButton value="sd">SD</ToggleButton>
        <ToggleButton value="hd">HD</ToggleButton>
        {supportsHdPlus && (
          <ToggleButton value="hd_plus" title="HD+ (1280x720 @ 30 fps, hardware encode)">
            HD+
          </ToggleButton>
        )}
      </ToggleButtonGroup>
      {webrtcAvailable ? (
        <ToggleButtonGroup
          data-testid="web-toggle"
          value={transport === 'webrtc' ? ['web'] : []}
          onChange={onToggleTransport}
          disabled={disabled}
          aria-label="Low-latency WEB stream"
          sx={groupSx}
        >
          <ToggleButton value="web" title="WEB: low-latency WebRTC at the selected resolution">
            WEB
          </ToggleButton>
        </ToggleButtonGroup>
      ) : (
        // Shown, not hidden: an operator who cannot find WEB needs to be told why, and each
        // denied profile is a different fix (install MediaMTX / never possible / device side).
        <Tooltip title={webrtcUnavailableReason(streamProtocol) ?? ''}>
          <span data-testid="web-unavailable" style={{ display: 'inline-flex' }}>
            <ToggleButton value="web" disabled sx={groupSx[groupSx.length - 1]}>
              WEB
            </ToggleButton>
          </span>
        </Tooltip>
      )}
    </Box>
  );
};
