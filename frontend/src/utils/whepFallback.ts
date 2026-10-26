/**
 * What the browser is told when WebRTC gives up and the live view silently
 * drops back to HLS.
 *
 * The fallback is quiet by design — the picture keeps coming, only the
 * transport changed — so the one notification it raises has to carry
 * everything an operator needs: *which* device, *why*, and where to look.
 * The raw reason coming out of `useWhepStream` (`timeout`, `Failed to fetch`,
 * a `connectionState`) is not actionable on its own, and the notification
 * identity has to be per device: keyed by page, every device that falls back
 * while the same screen is open collapses into a single bell row.
 *
 * Pure, so it can be tested without mounting the modal (BUG-0832).
 */

/** Reasons that mean different things to an operator; anything else passes through. */
const REASON_TEXT: Record<string, string> = {
  timeout: 'no frame in time',
  'Failed to fetch': 'the WHEP request never got through (CORS, cookie or proxy)',
  failed: 'connection dropped',
  disconnected: 'connection dropped',
  closed: 'connection dropped',
};

export const whepFailureText = (reason: string): string => REASON_TEXT[reason] ?? reason;

export interface WhepFallbackNotice {
  /** `<host> · <device>: WebRTC unavailable (<why>) — using HLS` */
  message: string;
  /** Per device, so six devices failing give six rows and a repeat replaces its own. */
  id: string;
  category: 'device';
  scope: { host_name: string; device_id: string };
  /** Deep link to that device on the Device Control page — not the page the modal was opened from. */
  action: { label: string; to: string };
}

export const whepFallbackNotice = (args: {
  hostName: string;
  deviceLabel: string;
  deviceId: string;
  reason: string;
}): WhepFallbackNotice => {
  const { hostName, deviceLabel, deviceId, reason } = args;
  return {
    message: `${hostName} · ${deviceLabel}: WebRTC unavailable (${whepFailureText(reason)}) — using HLS`,
    id: `webrtc-fallback:${hostName}:${deviceId}`,
    category: 'device',
    scope: { host_name: hostName, device_id: deviceId },
    action: {
      label: 'Show',
      // The Device Control page reads `?device=<host>/<device_id>` and selects that device.
      to: `/device-control?device=${encodeURIComponent(`${hostName}/${deviceId}`)}`,
    },
  };
};