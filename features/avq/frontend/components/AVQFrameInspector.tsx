import { Box, CircularProgress, Typography } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAVQFrames } from '../hooks/useAVQFrames';

interface AVQFrameInspectorProps {
  host: any;
  deviceId: string;
  /** Wall-clock epoch ms of the frame to show; null = follow live (newest). */
  selectedTime: number | null;
  /** Reports the displayed frame's exact epoch (both live & selected) — ONE-WAY.
   *  The page uses it for the right panel + timeline playhead + tab-row label. We
   *  deliberately do NOT write back into selectedTime (that caused a render loop). */
  onFrameTime?: (epochMs: number | null) => void;
}

/**
 * Frame-by-frame inspector — just the full-res still, over the 24h archive
 * (1 fps) or live. Navigation (LIVE/time + step arrows) lives on the page's tab
 * row; all per-frame / per-minute info is shown in the page's right-hand panel
 * (same as the Player tab).
 */
export const AVQFrameInspector: React.FC<AVQFrameInspectorProps> = ({
  host,
  deviceId,
  selectedTime,
  onFrameTime,
}) => {
  const live = selectedTime == null;

  // No auto-playback: when "live" (nothing selected), anchor ONCE on the newest
  // archived frame (~35s ago, past the 1fps archiver's 30s safety window) and hold
  // it static. Re-anchors only when the user jumps back to latest (selectedTime→null).
  const [liveAnchor, setLiveAnchor] = useState(() => Date.now() - 35_000);
  useEffect(() => {
    if (live) setLiveAnchor(Date.now() - 35_000);
  }, [live]);
  const cursor = live ? liveAnchor : (selectedTime as number);

  const { loading, frameAt } = useAVQFrames(host, deviceId, cursor);
  const frame = frameAt(cursor);

  const [imgError, setImgError] = useState(false);
  useEffect(() => setImgError(false), [frame?.imageUrl]);

  // Report the displayed frame time to the page (one-way; for the panel + playhead
  // + tab-row label). cursor depends only on selectedTime, never on the reported
  // value, so this can't feed back into a loop.
  useEffect(() => {
    onFrameTime?.(frame?.epochMs ?? null);
  }, [frame?.epochMs, onFrameTime]);

  return (
    <Box sx={{ position: 'relative', flex: 1, minHeight: 230, bgcolor: 'black', overflow: 'hidden', borderRadius: 1 }}>
      {loading && !frame && (
        <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <CircularProgress size={20} />
        </Box>
      )}
      {frame && !imgError && (
        <img
          src={frame.imageUrl}
          alt={`frame ${frame.seq}`}
          draggable={false}
          onError={() => setImgError(true)}
          style={{ width: '100%', height: '100%', objectFit: 'contain' }}
        />
      )}
      {(!frame || imgError) && !loading && (
        <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', px: 2 }}>
          <Typography variant="caption" color="text.secondary">
            {imgError
              ? 'Full-res still not retained for this time. Enable capture archiving (--keep-captures true) on the host to keep 24h of stills.'
              : 'No frame for this time.'}
          </Typography>
        </Box>
      )}
    </Box>
  );
};
