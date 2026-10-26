import { Box, Typography } from '@mui/material';

import type { WebRTCStats } from '../../../types/controller/WebRTC_Types';
import { TYPOGRAPHY } from '../../../constants/typography';

const fmt = (v: number | null, digits: number, unit = '') => (v == null ? 'n/a' : `${v.toFixed(digits)}${unit}`);

/** ?latency_debug=1 overlay for the WebRTC player — same look as the HLS one. */
export const WebRTCStatsOverlay = ({ stats }: { stats: WebRTCStats }) => (
  <Box
    data-testid="latency-debug-overlay"
    sx={{
      position: 'absolute',
      top: 8,
      right: 8,
      zIndex: 10,
      px: 1.25,
      py: 0.75,
      borderRadius: 1,
      backgroundColor: 'rgba(0,0,0,0.72)',
      color: 'primary.main',
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: TYPOGRAPHY.caption.size,
      lineHeight: 1.35,
      pointerEvents: 'none',
      border: '1px solid',
      borderColor: 'primary.main',
    }}
  >
    <Typography component="div" sx={{ font: 'inherit', color: 'inherit' }}>
      webrtc rtt:&nbsp;{fmt(stats.rttSeconds && stats.rttSeconds * 1000, 0, 'ms')}
      &nbsp;jitter buf:&nbsp;{fmt(stats.jitterBufferSeconds && stats.jitterBufferSeconds * 1000, 0, 'ms')}
    </Typography>
    <Typography component="div" sx={{ font: 'inherit', color: 'inherit' }}>
      fps:&nbsp;{fmt(stats.framesPerSecond, 0)}
      &nbsp;dropped:&nbsp;{fmt(stats.framesDropped, 0)}
      &nbsp;kbps:&nbsp;{fmt(stats.bitrateKbps, 0)}
    </Typography>
  </Box>
);
