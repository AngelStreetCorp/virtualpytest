/**
 * HLS live stream config — kept in one place so the encoder/player tuning on
 * TASK-79 can flip one knob without re-touching HLSVideoPlayer.tsx.
 *
 * Values are tuned for the vpt-pi3 0.4s-segment live tier (10 fps, GOP=4) and
 * the public path through vpt-pi1 nginx (proxy_buffering off, no gzip on
 * application/vnd.apple.mpegurl) and Cloudflare (cf-cache-status: DYNAMIC).
 *
 * Archive mode (large-DVR seeking, 30s default buffer) stays in
 * HLSVideoPlayer.tsx and is NOT exported here — the archiver has its own
 * serving path and the live path must not bleed knobs into it.
 */
export const LIVE_HLS_CONFIG = {
  enableWorker: true,
  lowLatencyMode: true,
  liveSyncDuration: 1.0,
  liveMaxLatencyDuration: 3,
  maxLiveSyncPlaybackRate: 1.5,
  maxBufferLength: 6,
  maxMaxBufferLength: 150,
  backBufferLength: 150,
  maxBufferSize: 15 * 1000 * 1000,
  maxBufferHole: 0.1,
  fragLoadingTimeOut: 5000,
  manifestLoadingTimeOut: 3000,
  levelLoadingTimeOut: 3000,
  liveBackBufferLength: 150,
  liveDurationInfinity: true,
} as const;
