import { useCallback, useEffect } from 'react';

import { WHEP_STREAM_PROTOCOL, streamTransportStorageKey } from '../../constants/webrtcConstants';
import type { LiveStreamTransport } from '../../types/controller/WebRTC_Types';
import { webrtcSupportedFor } from '../../utils/streamCapability';
import { usePersistedState } from '../usePersistedState';

/**
 * The operator's HLS/WebRTC choice for one device, remembered per device.
 * First visit defaults to WebRTC when the device reports `stream_protocol: 'whep'`, else HLS.
 *
 * A device whose profile DENIES WebRTC (no MediaMTX on the host, a capture that publishes
 * nothing to it, a cloud farm session — BUG-0833) can never use it, so the stored choice is
 * forced to HLS and forgotten. Without this the WEB button is disabled but a `webrtc` value
 * left in localStorage from an earlier session still switches the player to WebRTC, and the
 * 6 s timeout fires again on every open.
 *
 * Fail-open: a device that reports nothing keeps whatever was stored, so a host whose backend
 * has not been redeployed yet behaves exactly as before.
 */
export const useStreamTransport = (hostName: string, deviceId: string, streamProtocol?: string) => {
  const supported = webrtcSupportedFor(streamProtocol);
  const [stored, setStored] = usePersistedState<LiveStreamTransport>(
    streamTransportStorageKey(hostName, deviceId),
    streamProtocol === WHEP_STREAM_PROTOCOL ? 'webrtc' : 'hls',
  );

  useEffect(() => {
    if (!supported && stored === 'webrtc') setStored('hls');
  }, [supported, stored, setStored]);

  const transport: LiveStreamTransport = supported ? stored : 'hls';
  const setTransport = useCallback<React.Dispatch<React.SetStateAction<LiveStreamTransport>>>(
    (next) => setStored((prev) => (typeof next === 'function' ? next(prev) : next)),
    [setStored],
  );
  const toggleTransport = useCallback(
    () => setTransport((prev) => (prev === 'webrtc' ? 'hls' : 'webrtc')),
    [setTransport],
  );

  return { transport, setTransport, toggleTransport, webrtcSupported: supported };
};