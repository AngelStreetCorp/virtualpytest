/** Which transport the live view is using right now. */
export type LiveStreamTransport = 'webrtc' | 'hls';

/** WHEP session lifecycle as seen by the player. */
export type WhepStatus = 'idle' | 'connecting' | 'playing' | 'failed';

/** Live WebRTC receive stats, sampled from RTCPeerConnection.getStats(). */
export interface WebRTCStats {
  /** Round-trip time to the host, seconds. */
  rttSeconds: number | null;
  /** Average jitter-buffer delay per emitted frame over the last sample window, seconds. */
  jitterBufferSeconds: number | null;
  framesPerSecond: number | null;
  framesDropped: number | null;
  /** Inbound video bitrate, kbit/s. */
  bitrateKbps: number | null;
  /** Receiver-side packet jitter, seconds. */
  jitterSeconds: number | null;
  /** Packets never recovered (cumulative). NACK retransmits that arrived do not count here. */
  packetsLost: number | null;
  /** Share of received packets that had to be re-requested (NACK), cumulative, percent. */
  nackPercent: number | null;
  /** Visible freezes since the session started (a gap well beyond the frame interval). */
  freezeCount: number | null;
  /** Share of the last sample window spent frozen, percent. */
  freezePercent: number | null;
}

export interface WhepSession {
  pc: RTCPeerConnection;
  /** WHEP resource URL (from the Location header) — DELETE it to end the session. */
  resourceUrl: string | null;
}
