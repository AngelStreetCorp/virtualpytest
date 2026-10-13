import { useEffect, useRef, useState } from 'react';

import { WEBRTC_STATS_INTERVAL_MS } from '../../constants/webrtcConstants';
import type { WebRTCStats } from '../../types/controller/WebRTC_Types';

const EMPTY_STATS: WebRTCStats = {
  rttSeconds: null,
  jitterBufferSeconds: null,
  framesPerSecond: null,
  framesDropped: null,
  bitrateKbps: null,
};

/** Samples receive stats from `pc` every WEBRTC_STATS_INTERVAL_MS while `enabled`. */
export const useWebRTCStats = (pc: RTCPeerConnection | null, enabled: boolean): WebRTCStats => {
  const [stats, setStats] = useState<WebRTCStats>(EMPTY_STATS);
  const lastBytesRef = useRef<{ bytes: number; ts: number } | null>(null);

  useEffect(() => {
    setStats(EMPTY_STATS);
    lastBytesRef.current = null;
    if (!pc || !enabled) return undefined;

    const sample = async () => {
      const report = await pc.getStats();
      const next: WebRTCStats = { ...EMPTY_STATS };
      report.forEach((s) => {
        if (s.type === 'inbound-rtp' && s.kind === 'video') {
          if (s.jitterBufferEmittedCount > 0) {
            next.jitterBufferSeconds = s.jitterBufferDelay / s.jitterBufferEmittedCount;
          }
          next.framesPerSecond = s.framesPerSecond ?? null;
          next.framesDropped = s.framesDropped ?? null;
          const last = lastBytesRef.current;
          if (last && s.timestamp > last.ts) {
            next.bitrateKbps = ((s.bytesReceived - last.bytes) * 8) / (s.timestamp - last.ts);
          }
          lastBytesRef.current = { bytes: s.bytesReceived, ts: s.timestamp };
        }
        if (s.type === 'candidate-pair' && s.nominated && s.currentRoundTripTime != null) {
          next.rttSeconds = s.currentRoundTripTime;
        }
      });
      setStats(next);
    };

    const id = window.setInterval(() => {
      sample().catch(() => undefined);
    }, WEBRTC_STATS_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [pc, enabled]);

  return stats;
};
