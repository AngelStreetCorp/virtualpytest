import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { buildWhepUrl } from '../../actions/webrtc/whepActions';
import type { LiveStreamTransport, WhepStatus } from '../../types/controller/WebRTC_Types';
import { useWhepStream } from './useWhepStream';

interface UseLiveTransportReturn {
  /** What is actually on screen: WebRTC only once a frame arrived, HLS otherwise. */
  transport: LiveStreamTransport;
  status: WhepStatus;
  stream: MediaStream | null;
  pc: RTCPeerConnection | null;
  showStats: boolean;
}

/**
 * Runs the WebRTC session when `enabled`. HLS stays on screen until the first
 * WebRTC frame, and takes over again whenever WebRTC is not playing.
 */
export const useLiveTransport = (
  streamUrl: string | undefined,
  enabled: boolean,
  reconnectKey?: string,
): UseLiveTransportReturn => {
  const [searchParams] = useSearchParams();
  const candidateUrl = useMemo(() => (enabled ? buildWhepUrl(streamUrl) : null), [enabled, streamUrl]);
  // openWhepSession mints the host-session cookie itself, so the session (and its
  // 'connecting' status, which drives the loading overlay) starts on the click.
  const { status, stream, pc } = useWhepStream(candidateUrl, reconnectKey);

  return {
    transport: status === 'playing' ? 'webrtc' : 'hls',
    status,
    stream,
    pc,
    showStats: searchParams.get('latency_debug') === '1',
  };
};
