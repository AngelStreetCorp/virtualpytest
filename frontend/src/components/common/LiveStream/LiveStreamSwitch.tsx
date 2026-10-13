import { Box } from '@mui/material';
import { useEffect, useRef, type ReactNode } from 'react';

import type { StreamViewerLayoutConfig } from '../../../config/layoutConfig';
import { useLiveTransport } from '../../../hooks/controller/useLiveTransport';
import type { WhepStatus } from '../../../types/controller/WebRTC_Types';
import { WebRTCVideoPlayer } from './WebRTCVideoPlayer';

interface LiveStreamSwitchProps {
  /** Live HLS URL of the device; the WHEP URL is derived from it. */
  streamUrl?: string;
  /** Operator chose WebRTC. False = always the HLS `children`. */
  webrtcEnabled: boolean;
  /** Changing it reconnects WebRTC (e.g. the quality level, which restarts ffmpeg). */
  reconnectKey?: string;
  /** Called once when WebRTC gives up, so the caller can flip the toggle back to HLS. */
  onWebRTCFailed?: () => void;
  onStatusChange?: (status: WhepStatus) => void;
  layoutConfig?: StreamViewerLayoutConfig;
  /** Audio follows the page's mute button, like the HLS player. */
  muted?: boolean;
  /** Drawn over the WebRTC player (the HLS `children` carry their own overlays). */
  webrtcOverlay?: ReactNode;
  /** The HLS player, rendered whenever WebRTC is not the one playing. */
  children: ReactNode;
  sx?: any;
}

/** Swaps the HLS player for WebRTC once WebRTC shows a frame; back to HLS on failure. */
export const LiveStreamSwitch = ({
  streamUrl,
  webrtcEnabled,
  reconnectKey,
  onWebRTCFailed,
  onStatusChange,
  layoutConfig,
  muted = true,
  webrtcOverlay,
  children,
  sx,
}: LiveStreamSwitchProps) => {
  const { transport, status, stream, pc, showStats } = useLiveTransport(streamUrl, webrtcEnabled, reconnectKey);

  // Callbacks in a ref so inline arrows from the caller don't re-fire on every render.
  const callbacksRef = useRef({ onStatusChange, onWebRTCFailed });
  callbacksRef.current = { onStatusChange, onWebRTCFailed };
  useEffect(() => {
    callbacksRef.current.onStatusChange?.(status);
    if (status === 'failed') callbacksRef.current.onWebRTCFailed?.();
  }, [status]);

  return (
    <Box sx={{ position: 'relative', width: '100%', height: '100%', ...sx }}>
      {transport === 'webrtc' ? (
        <>
          <WebRTCVideoPlayer stream={stream} pc={pc} layoutConfig={layoutConfig} showStats={showStats} muted={muted} />
          {webrtcOverlay}
        </>
      ) : (
        children
      )}
    </Box>
  );
};
