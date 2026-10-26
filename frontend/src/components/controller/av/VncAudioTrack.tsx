import { VolumeOff as VolumeOffIcon, VolumeUp as VolumeUpIcon } from '@mui/icons-material';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import Hls from 'hls.js';
import React, { useEffect, useRef, useState } from 'react';

import { TYPOGRAPHY } from '../../../constants/typography';

/**
 * Audio track bound to a host_vnc desktop's separate audio HLS playlist
 * (BUG-0597 / BUG-0605). Muted by default because browsers block unmuted
 * autoplay; the chip unmutes it in one click.
 *
 * Shared by the REC / Take Control player (`VNCStream`) and the Device Control
 * grid tile (`DeviceStreamGrid`), so a Windows desktop's sound is reachable
 * wherever its screen is.
 */
const VncAudioTrack: React.FC<{ audioStreamUrl: string }> = ({ audioStreamUrl }) => {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [muted, setMuted] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!audioRef.current) return;
    const audio = audioRef.current;
    if (Hls.isSupported()) {
      // The playlist lives on the device server's origin (e.g. vpt-pi4), while
      // the dashboard is on another origin. nginx gates /host/<name>/... behind
      // the host-session cookie, so the XHR must send credentials; hls.js
      // defaults withCredentials to false (same fix as HLSVideoPlayer).
      const hls = new Hls({
        liveDurationInfinity: true,
        enableWorker: true,
        xhrSetup: (xhr: XMLHttpRequest) => {
          xhr.withCredentials = true;
        },
      });
      hls.loadSource(audioStreamUrl);
      hls.attachMedia(audio);
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        console.warn('[VncAudioTrack] HLS error', data);
        if (data.fatal) setError(true);
      });
      return () => hls.destroy();
    }
    // Safari (with native HLS): point the audio element directly at the m3u8.
    if (audio.canPlayType('application/vnd.apple.mpegurl')) {
      audio.src = audioStreamUrl;
      return;
    }
    setError(true);
    return undefined;
  }, [audioStreamUrl]);

  if (error) return null;
  return (
    <Box
      data-testid="vnc-audio-track"
      sx={{
        position: 'absolute',
        right: 8,
        bottom: 8,
        display: 'flex',
        alignItems: 'center',
        gap: 0.5,
        backgroundColor: 'rgba(0, 0, 0, 0.55)',
        borderRadius: 1,
        px: 0.75,
        py: 0.25,
        zIndex: 2,
      }}
    >
      <Tooltip title={muted ? 'Unmute desktop audio' : 'Mute desktop audio'}>
        <IconButton
          size="small"
          aria-label={muted ? 'unmute audio' : 'mute audio'}
          onClick={() => {
            setMuted(!muted);
            if (audioRef.current) audioRef.current.muted = !muted;
          }}
          sx={{ color: '#fff', p: 0.25 }}
        >
          {muted ? <VolumeOffIcon fontSize="small" /> : <VolumeUpIcon fontSize="small" />}
        </IconButton>
      </Tooltip>
      <Typography variant="caption" sx={{ color: '#fff', fontSize: TYPOGRAPHY.caption.size, opacity: 0.75 }}>
        {muted ? 'muted' : 'on'}
      </Typography>
      <audio ref={audioRef} muted autoPlay playsInline style={{ display: 'none' }} />
    </Box>
  );
};

export default VncAudioTrack;
