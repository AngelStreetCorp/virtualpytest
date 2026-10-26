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
/** Live target latency a player switches to after its first stall (HLSVideoPlayer). A
 *  clean link keeps liveSyncDuration (1 s); a slow or lossy one (vpt-mf1 on WiFi) stops
 *  freezing at 3 s. */
export const LIVE_STALL_TARGET_LATENCY_S = 3;

export const LIVE_HLS_CONFIG = {
  enableWorker: true,
  lowLatencyMode: true,
  liveSyncDuration: 1.0,
  liveMaxLatencyDuration: 8, // above LIVE_STALL_TARGET_LATENCY_S, or the 3 s target would be jumped back
  // Catch up gently: at 1.5x a 60 fps stream asks a 60 Hz screen for 90 frames/s and the
  // browser drops ~30 of them every second it catches up (vpt-mf1 on WiFi: 62 decoded,
  // 31 dropped). 1.1x costs ~6 frames/s and still closes a 1 s lag in ~10 s.
  maxLiveSyncPlaybackRate: 1.1,
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
