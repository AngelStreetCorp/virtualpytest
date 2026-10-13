import { Box } from '@mui/material';
import { useEffect, useRef } from 'react';

import type { StreamViewerLayoutConfig } from '../../../config/layoutConfig';
import { useWebRTCStats } from '../../../hooks/controller/useWebRTCStats';
import { WebRTCStatsOverlay } from './WebRTCStatsOverlay';

interface WebRTCVideoPlayerProps {
  stream: MediaStream | null;
  pc: RTCPeerConnection | null;
  layoutConfig?: StreamViewerLayoutConfig;
  showStats: boolean;
  /** Follows the page's mute button. */
  muted?: boolean;
  sx?: any;
}

/**
 * Plays a WHEP MediaStream with the page's mute state. If the browser refuses to autoplay
 * with sound, it plays muted rather than not at all (the mute button can unmute it).
 */
export const WebRTCVideoPlayer = ({ stream, pc, layoutConfig, showStats, muted = true, sx }: WebRTCVideoPlayerProps) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const stats = useWebRTCStats(pc, showStats);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = stream;
    if (!stream) return;
    video.muted = muted;
    video.play().catch(() => {
      video.muted = true;
      video.play().catch(() => undefined);
    });
    // muted is applied by the effect below; a mute toggle must not restart playback.
  }, [stream]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted;
  }, [muted]);

  return (
    <Box
      sx={{
        position: 'relative',
        width: '100%',
        height: '100%',
        backgroundColor: '#000000',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        ...sx,
      }}
    >
      {showStats && <WebRTCStatsOverlay stats={stats} />}
      <video
        ref={videoRef}
        data-testid="webrtc-video"
        autoPlay
        playsInline
        style={{
          width: '100%',
          height: '100%',
          objectFit: layoutConfig?.objectFit ?? 'contain',
          backgroundColor: '#000000',
        }}
      />
    </Box>
  );
};
