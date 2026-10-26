import {
  HLS_LIVE_PATH_RE,
  WEBRTC_ICE_SERVERS,
  WHEP_ICE_GATHER_MAX_MS,
  WHEP_LOSS_CHECK_MS,
  WHEP_LOSSY_JITTER_BUFFER_MS,
} from '../../constants/webrtcConstants';
import type { WhepSession } from '../../types/controller/WebRTC_Types';
import { ensureHostSession, isGatedHostPath } from '../../utils/buildUrlUtils';

/**
 * Build the WHEP URL from the live HLS URL of the same device:
 *   …/host/vpt-pi3/stream/capture1/hot/segments/output.m3u8
 *   → …/host/vpt-pi3/whep/capture1/whep
 * Returns null when the URL is not a live HLS playlist (archive, VNC, …).
 */
export const buildWhepUrl = (hlsUrl: string | null | undefined): string | null => {
  if (!hlsUrl) return null;
  const match = hlsUrl.match(HLS_LIVE_PATH_RE);
  if (!match) return null;
  return hlsUrl.replace(HLS_LIVE_PATH_RE, `/whep/${match[1]}/whep`);
};

/**
 * Wait until the offer carries a server-reflexive (public) candidate, gathering completes,
 * or WHEP_ICE_GATHER_MAX_MS passes. Chrome can stay in `gathering` for 20 s+ (a STUN check
 * on an interface that never answers) although host + srflx candidates arrive in ~50 ms.
 * MediaMTX learns any missing browser address as peer-reflexive from its connectivity checks.
 */
const waitForIceCandidates = (pc: RTCPeerConnection): Promise<void> =>
  new Promise((resolve) => {
    if (pc.iceGatheringState === 'complete') return resolve();
    const done = () => {
      window.clearTimeout(timer);
      pc.removeEventListener('icegatheringstatechange', onState);
      pc.removeEventListener('icecandidate', onCandidate);
      resolve();
    };
    const onState = () => {
      if (pc.iceGatheringState === 'complete') done();
    };
    const onCandidate = (ev: RTCPeerConnectionIceEvent) => {
      if (ev.candidate?.type === 'srflx') done();
    };
    const timer = window.setTimeout(done, WHEP_ICE_GATHER_MAX_MS);
    pc.addEventListener('icegatheringstatechange', onState);
    pc.addEventListener('icecandidate', onCandidate);
  });

/**
 * Raise the receive jitter buffer the first time the link loses packets or freezes, so
 * resent packets arrive in time instead of the picture freezing. Checks every
 * WHEP_LOSS_CHECK_MS and stops after it has switched or once `pc` is closed.
 */
const bufferMoreOnLoss = (pc: RTCPeerConnection): void => {
  let last: { loss: number; freeze: number } | null = null;
  const id = window.setInterval(async () => {
    if (pc.signalingState === 'closed') {
      window.clearInterval(id);
      return;
    }
    let loss = 0;
    let freeze = 0;
    (await pc.getStats().catch(() => new Map())).forEach((s) => {
      if (s.type === 'inbound-rtp' && s.kind === 'video') {
        loss = (s.packetsLost ?? 0) + (s.nackCount ?? 0);
        freeze = s.totalFreezesDuration ?? 0;
      }
    });
    if (last && (loss - last.loss >= 3 || freeze > last.freeze)) {
      pc.getReceivers().forEach((r) => {
        // Chrome / Edge / Safari 17.4+; other browsers ignore it.
        (r as RTCRtpReceiver & { jitterBufferTarget?: number }).jitterBufferTarget = WHEP_LOSSY_JITTER_BUFFER_MS;
      });
      window.clearInterval(id);
      return;
    }
    last = { loss, freeze };
  }, WHEP_LOSS_CHECK_MS);
};

/** Open a receive-only WHEP session. `onTrack` gets the remote MediaStream. */
export const openWhepSession = async (
  whepUrl: string,
  onTrack: (stream: MediaStream) => void,
  signal: AbortSignal,
): Promise<WhepSession> => {
  // The proxy gates /host/<id>/whep/ on the host-session cookie: mint it first, or the POST 401s.
  if (!(await ensureHostSession(whepUrl))) throw new Error('host session');
  if (signal.aborted) throw new Error('aborted');
  const pc = new RTCPeerConnection({ iceServers: WEBRTC_ICE_SERVERS });
  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.addTransceiver('audio', { direction: 'recvonly' });
  pc.ontrack = (ev) => {
    if (ev.streams[0]) onTrack(ev.streams[0]);
  };

  try {
    await pc.setLocalDescription(await pc.createOffer());
    await waitForIceCandidates(pc);
    const res = await fetch(whepUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp' },
      body: pc.localDescription?.sdp ?? '',
      // The proxy gates /host/<id>/whep/ on the host-session cookie; the mobile app is
      // cross-origin, so the cookie is only sent when asked for (same as HLS).
      credentials: isGatedHostPath(whepUrl) ? 'include' : 'same-origin',
      signal,
    });
    if (!res.ok) throw new Error(`WHEP POST ${res.status}`);
    const location = res.headers.get('Location');
    await pc.setRemoteDescription({ type: 'answer', sdp: await res.text() });
    bufferMoreOnLoss(pc);
    return { pc, resourceUrl: location ? new URL(location, whepUrl).toString() : null };
  } catch (err) {
    pc.close();
    throw err;
  }
};

/** Close the peer connection and tell the host to drop the session. Never throws. */
export const closeWhepSession = (session: WhepSession | null): void => {
  if (!session) return;
  session.pc.close();
  if (session.resourceUrl) {
    fetch(session.resourceUrl, {
      method: 'DELETE',
      keepalive: true,
      credentials: isGatedHostPath(session.resourceUrl) ? 'include' : 'same-origin',
    }).catch(() => undefined);
  }
};
