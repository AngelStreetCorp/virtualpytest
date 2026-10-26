/**
 * Whether the WEB (WebRTC) transport may be offered for a device — the browser half of
 * `shared/src/lib/utils/stream_capability_utils.py`, which is what computes the profile.
 *
 * WebRTC is not a browser preference: it only exists when the host runs MediaMTX AND the
 * capture is a v4l2 grabber that publishes to it. A cloud device farm (Sauce Labs,
 * BrowserStack) has no stream of ours at all — its `video_url` is a recording link the
 * vendor's jobs API returns after the job, not a live feed.
 *
 * BUG-0833: the WEB toggle used to be rendered unconditionally, gated only on "is this
 * live mode". On a host with no MediaMTX every click was a guaranteed 6 s timeout and an
 * error that named nothing.
 *
 * **Fail-open on purpose.** `undefined` and `'hls'` mean "this host has not reported yet",
 * and keep today's behaviour. Only an explicit profile that positively denies WebRTC hides
 * the button — a host whose backend has not been redeployed yet must not silently lose the
 * feature.
 */

/** Profiles reported by the host. Mirrors the backend constants. */
export const STREAM_PROFILE = {
  /** MediaMTX on the host and this capture feeds it. */
  WHEP: 'whep',
  /** Not reported / unknown — permissive, see above. */
  HLS: 'hls',
  /** An Appium session in the vendor's datacentre. Never streamable by us. */
  CLOUD_FARM: 'cloud_farm',
  /** This host runs no MediaMTX. */
  HLS_NO_WEBRTC_HOST: 'hls_no_webrtc_host',
  /** MediaMTX is here, but this capture publishes nothing to it. */
  HLS_NO_PUBLISHER: 'hls_no_publisher',
} as const;

export type StreamProfile = (typeof STREAM_PROFILE)[keyof typeof STREAM_PROFILE];

/** The profiles that positively deny WebRTC. `HLS` is deliberately absent. */
const DENIED: ReadonlySet<string> = new Set<string>([
  STREAM_PROFILE.CLOUD_FARM,
  STREAM_PROFILE.HLS_NO_WEBRTC_HOST,
  STREAM_PROFILE.HLS_NO_PUBLISHER,
]);

/**
 * May the WEB toggle be offered for this device?
 *
 * Fail-open: only an explicit deny removes the button.
 */
export const webrtcSupportedFor = (profile?: string | null): boolean =>
  !profile || !DENIED.has(profile);

/**
 * Why WEB is unavailable, for the operator. Each denied profile gets its own sentence
 * because the fix differs: a missing MediaMTX is a host problem, a cloud farm session is
 * never fixable, and a capture with no publisher is a device problem.
 */
export const webrtcUnavailableReason = (profile?: string | null): string | null => {
  switch (profile) {
    case STREAM_PROFILE.CLOUD_FARM:
      return 'Cloud farm session — this device runs in the vendor\'s datacentre, so there is no stream to carry.';
    case STREAM_PROFILE.HLS_NO_WEBRTC_HOST:
      return 'This host runs no MediaMTX service, so it has no WebRTC endpoint. HLS only.';
    case STREAM_PROFILE.HLS_NO_PUBLISHER:
      return 'This capture is not a grabber, so it publishes nothing to MediaMTX. HLS only.';
    default:
      return null;
  }
};