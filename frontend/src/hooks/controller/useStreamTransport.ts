import { useCallback } from 'react';

import { WHEP_STREAM_PROTOCOL, streamTransportStorageKey } from '../../constants/webrtcConstants';
import type { LiveStreamTransport } from '../../types/controller/WebRTC_Types';
import { usePersistedState } from '../usePersistedState';

/**
 * The operator's HLS/WebRTC choice for one device, remembered per device.
 * First visit defaults to WebRTC when the registry says `stream_protocol: 'whep'`, else HLS.
 */
export const useStreamTransport = (hostName: string, deviceId: string, streamProtocol?: string) => {
  const [transport, setTransport] = usePersistedState<LiveStreamTransport>(
    streamTransportStorageKey(hostName, deviceId),
    streamProtocol === WHEP_STREAM_PROTOCOL ? 'webrtc' : 'hls',
  );

  const toggleTransport = useCallback(
    () => setTransport((prev) => (prev === 'webrtc' ? 'hls' : 'webrtc')),
    [setTransport],
  );

  return { transport, setTransport, toggleTransport };
};
