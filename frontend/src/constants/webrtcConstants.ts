/** Give WebRTC this long to show a first frame before falling back to HLS. Bumped
 *  from 3 s to 6 s so users on 4G/external networks (where ICE candidate swap can
 *  take longer) get a fair shake before we toast. Last session of #79-RAT. */
export const WHEP_CONNECT_TIMEOUT_MS = 6000;

/** Longest wait for a server-reflexive candidate before the WHEP offer is POSTed with the
 *  candidates so far (normally one arrives in ~50 ms). Counts against WHEP_CONNECT_TIMEOUT_MS. */
export const WHEP_ICE_GATHER_MAX_MS = 1000;

/** How often the latency_debug overlay samples getStats(). */
export const WEBRTC_STATS_INTERVAL_MS = 2000;

/** ICE servers for the browser side. TURN is added here once it exists. */
export const WEBRTC_ICE_SERVERS: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }];

/** Device registry value that opts a device into WebRTC. */
export const WHEP_STREAM_PROTOCOL = 'whep';

/** HLS live playlist suffix, replaced by the WHEP path to build the WHEP URL. */
export const HLS_LIVE_PATH_RE = /\/stream\/([^/]+)\/(?:hot\/)?segments\/output\.m3u8.*$/;

/** After a drop (e.g. ffmpeg restarting on a quality switch), retry this many times before giving up. */
export const WHEP_RECONNECT_ATTEMPTS = 3;
export const WHEP_RECONNECT_DELAY_MS = 1500;

/** localStorage key for the per-device HLS/WebRTC choice. */
export const streamTransportStorageKey = (hostName: string, deviceId: string) =>
  `virtualpytest:stream-transport:${hostName}:${deviceId}`;
