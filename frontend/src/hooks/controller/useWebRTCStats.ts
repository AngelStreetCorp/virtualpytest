import { useEffect, useRef, useState } from 'react';

import { WEBRTC_STATS_INTERVAL_MS } from '../../constants/webrtcConstants';
import type { WebRTCStats } from '../../types/controller/WebRTC_Types';

const EMPTY_STATS: WebRTCStats = {
  rttSeconds: null,
  jitterBufferSeconds: null,
  framesPerSecond: null,
  framesDropped: null,
  bitrateKbps: null,
  jitterSeconds: null,
  packetsLost: null,
  nackPercent: null,
  freezeCount: null,
  freezePercent: null,
};

/** Samples receive stats from `pc` every WEBRTC_STATS_INTERVAL_MS while `enabled`. */
export const useWebRTCStats = (pc: RTCPeerConnection | null, enabled: boolean): WebRTCStats => {
  const [stats, setStats] = useState<WebRTCStats>(EMPTY_STATS);
  const lastBytesRef = useRef<{ bytes: number; ts: number } | null>(null);
  const lastFreezeRef = useRef<{ seconds: number; ts: number } | null>(null);
  const lastJitterBufferRef = useRef<{ delay: number; count: number } | null>(null);

  useEffect(() => {
    setStats(EMPTY_STATS);
    lastBytesRef.current = null;
    lastFreezeRef.current = null;
    lastJitterBufferRef.current = null;
    if (!pc || !enabled) return undefined;

    const sample = async () => {
      const report = await pc.getStats();
      const next: WebRTCStats = { ...EMPTY_STATS };
      report.forEach((s) => {
        if (s.type === 'inbound-rtp' && s.kind === 'video') {
          // Over the last window, not the session: the buffer grows when the link turns lossy
          // (whepActions bufferMoreOnLoss) and a session average would hide that for minutes.
          const lastJb = lastJitterBufferRef.current;
          if (lastJb && s.jitterBufferEmittedCount > lastJb.count) {
            next.jitterBufferSeconds =
              (s.jitterBufferDelay - lastJb.delay) / (s.jitterBufferEmittedCount - lastJb.count);
          } else if (s.jitterBufferEmittedCount > 0) {
            next.jitterBufferSeconds = s.jitterBufferDelay / s.jitterBufferEmittedCount;
          }
          lastJitterBufferRef.current = { delay: s.jitterBufferDelay, count: s.jitterBufferEmittedCount };
          next.framesPerSecond = s.framesPerSecond ?? null;
          next.framesDropped = s.framesDropped ?? null;
          const last = lastBytesRef.current;
          if (last && s.timestamp > last.ts) {
            next.bitrateKbps = ((s.bytesReceived - last.bytes) * 8) / (s.timestamp - last.ts);
          }
          lastBytesRef.current = { bytes: s.bytesReceived, ts: s.timestamp };

          next.jitterSeconds = s.jitter ?? null;
          next.packetsLost = s.packetsLost ?? null;
          if (s.packetsReceived > 0 && s.nackCount != null) {
            next.nackPercent = (s.nackCount / s.packetsReceived) * 100;
          }
          next.freezeCount = s.freezeCount ?? null;
          // totalFreezesDuration is cumulative seconds; the share of THIS window is what says "now".
          const lastFreeze = lastFreezeRef.current;
          if (s.totalFreezesDuration != null) {
            if (lastFreeze && s.timestamp > lastFreeze.ts) {
              const windowSeconds = (s.timestamp - lastFreeze.ts) / 1000;
              next.freezePercent = Math.min(
                100,
                (Math.max(0, s.totalFreezesDuration - lastFreeze.seconds) / windowSeconds) * 100,
              );
            }
            lastFreezeRef.current = { seconds: s.totalFreezesDuration, ts: s.timestamp };
          }
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
