import { useEffect, useRef, useState } from 'react';

import { closeWhepSession, openWhepSession } from '../../actions/webrtc/whepActions';
import {
  WHEP_CONNECT_TIMEOUT_MS,
  WHEP_RECONNECT_ATTEMPTS,
  WHEP_RECONNECT_DELAY_MS,
} from '../../constants/webrtcConstants';
import type { WhepSession, WhepStatus } from '../../types/controller/WebRTC_Types';

interface UseWhepStreamReturn {
  status: WhepStatus;
  stream: MediaStream | null;
  /** Live peer connection, for getStats(). Null until connected. */
  pc: RTCPeerConnection | null;
}

/**
 * Receive-only WHEP session for `whepUrl`.
 * - No first frame within WHEP_CONNECT_TIMEOUT_MS → `failed`.
 * - A session that was playing and drops (the host restarts ffmpeg on a quality
 *   switch) is retried WHEP_RECONNECT_ATTEMPTS times before going `failed`.
 * A new `whepUrl` or `reconnectKey` starts over with a fresh retry budget.
 */
export const useWhepStream = (whepUrl: string | null, reconnectKey?: string): UseWhepStreamReturn => {
  const [status, setStatus] = useState<WhepStatus>('idle');
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [pc, setPc] = useState<RTCPeerConnection | null>(null);
  const [attempt, setAttempt] = useState(0);
  const sessionRef = useRef<WhepSession | null>(null);
  const hasPlayedRef = useRef(false);

  // Fresh retry budget whenever the target changes.
  useEffect(() => {
    setAttempt(0);
    hasPlayedRef.current = false;
  }, [whepUrl, reconnectKey]);

  useEffect(() => {
    setPc(null);
    if (!whepUrl || typeof RTCPeerConnection === 'undefined') {
      setStream(null);
      setStatus(whepUrl ? 'failed' : 'idle');
      return undefined;
    }

    const abort = new AbortController();
    let gotTrack = false;
    let retryTimer = 0;
    const fail = (reason: string) => {
      if (abort.signal.aborted) return;
      abort.abort();
      closeWhepSession(sessionRef.current);
      sessionRef.current = null;
      setPc(null);
      if (hasPlayedRef.current && attempt < WHEP_RECONNECT_ATTEMPTS) {
        console.warn(`[@hook:useWhepStream] WebRTC dropped (${reason}) — reconnect ${attempt + 1}`);
        setStatus('connecting');
        retryTimer = window.setTimeout(() => setAttempt((a) => a + 1), WHEP_RECONNECT_DELAY_MS);
        return;
      }
      console.warn(`[@hook:useWhepStream] WebRTC failed (${reason}) — falling back to HLS`);
      setStream(null);
      setStatus('failed');
    };

    if (!hasPlayedRef.current) setStatus('connecting');
    const timeout = window.setTimeout(() => {
      if (!gotTrack) fail('timeout');
    }, WHEP_CONNECT_TIMEOUT_MS);

    openWhepSession(
      whepUrl,
      (remote) => {
        gotTrack = true;
        hasPlayedRef.current = true;
        setStream(remote);
        setStatus('playing');
      },
      abort.signal,
    )
      .then((session) => {
        if (abort.signal.aborted) {
          closeWhepSession(session);
          return;
        }
        sessionRef.current = session;
        setPc(session.pc);
        session.pc.addEventListener('connectionstatechange', () => {
          const state = session.pc.connectionState;
          if (state === 'failed' || state === 'disconnected' || state === 'closed') fail(state);
        });
      })
      .catch((err: Error) => fail(err.message));

    return () => {
      window.clearTimeout(timeout);
      window.clearTimeout(retryTimer);
      abort.abort();
      closeWhepSession(sessionRef.current);
      sessionRef.current = null;
    };
  }, [whepUrl, reconnectKey, attempt]);

  return { status, stream, pc };
};
