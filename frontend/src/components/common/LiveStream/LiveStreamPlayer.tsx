import type { ComponentProps } from 'react';

import { useStreamTransport } from '../../../hooks/controller/useStreamTransport';
import { HLSVideoPlayer } from '../HLSVideoPlayer';
import { LiveStreamSwitch } from './LiveStreamSwitch';

type LiveStreamPlayerProps = ComponentProps<typeof HLSVideoPlayer> & {
  hostName: string;
  deviceId: string;
  /** Device registry `stream_protocol`; 'whep' makes WebRTC the first-visit default. */
  streamProtocol?: string;
};

/** HLS player that switches to WebRTC when the operator picked it for this device. */
export const LiveStreamPlayer = ({ hostName, deviceId, streamProtocol, ...hlsProps }: LiveStreamPlayerProps) => {
  const { transport, setTransport } = useStreamTransport(hostName, deviceId, streamProtocol);

  return (
    <LiveStreamSwitch
      streamUrl={hlsProps.streamUrl}
      webrtcEnabled={transport === 'webrtc'}
      onWebRTCFailed={() => setTransport('hls')}
      layoutConfig={hlsProps.layoutConfig}
      sx={hlsProps.sx}
    >
      <HLSVideoPlayer {...hlsProps} sx={undefined} />
    </LiveStreamSwitch>
  );
};
