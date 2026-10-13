/** Which transport the live view is using right now. */
export type LiveStreamTransport = 'webrtc' | 'hls';

/** WHEP session lifecycle as seen by the player. */
export type WhepStatus = 'idle' | 'connecting' | 'playing' | 'failed';

/** Live WebRTC receive stats, sampled from RTCPeerConnection.getStats(). */
export interface WebRTCStats {
  /** Round-trip time to the host, seconds. */
  rttSeconds: number | null;
  /** Average jitter-buffer delay per emitted frame, seconds. */
  jitterBufferSeconds: number | null;
  framesPerSecond: number | null;
  framesDropped: number | null;
  /** Inbound video bitrate, kbit/s. */
  bitrateKbps: number | null;
}

export interface WhepSession {
  pc: RTCPeerConnection;
  /** WHEP resource URL (from the Location header) — DELETE it to end the session. */
  resourceUrl: string | null;
}
