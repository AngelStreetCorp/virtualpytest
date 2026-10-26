import { Box } from '@mui/material';
import React from 'react';

/**
 * The picture the monitor overlay is drawn on (BUG-0836).
 *
 * The overlay's boxes come from one analysed capture while the player shows a live stream, so the two are
 * unrelated in time and the boxes end up beside their objects. Two ways to stop that, and this renders the
 * one that is correct by construction:
 *
 * - **frame** (default): show `url`, the capture the newest analysis was computed FROM, with the boxes on top
 *   of it. Picture and boxes are the same frame: zero lag, no prediction, and it cannot drift whatever the
 *   belt does. The cost is that the picture advances at the capture rate (5 fps here) instead of the stream's.
 * - **live**: the smooth live stream underneath, with the boxes carried forward by each object's velocity.
 *   Smooth to watch, and right only while the motion is constant — good for a scene at rest, not for a belt.
 *
 * This layer only hides the live stream behind a black backdrop. The capture itself is drawn by the overlay, inside
 * the boxes' own SVG (BUG-0913): drawn here as a separate `<img>` it was never scaled like the boxes (it stopped at
 * its pixel size while the boxes filled the player), and every circle landed off its egg.
 *
 * There is no switch any more (owner, 2026-10-26): the corner toggle was not understandable, and the analysed frame
 * is the only picture on which the boxes are right by construction.
 */
interface AnalysedFrameLayerProps {
  /** The capture the newest analysis came from (drawn by the overlay); null = nothing to frame-lock onto. */
  url: string | null;
  /** Whether a profile overlay is drawing (tv_app and an idle monitor draw nothing, so nothing to lock). */
  active: boolean;
  frameLocked: boolean;
}

export const AnalysedFrameLayer: React.FC<AnalysedFrameLayerProps> = ({ url, active, frameLocked }) => {
  if (!active) return null;
  return (
    <>
      {frameLocked && url && (
        <Box
          data-testid="analysed-frame"
          sx={{
            position: 'absolute',
            inset: 0,
            zIndex: 12, // above the video, below the overlay layer (zIndex 1300) and the boxes (15)
            background: '#000',
          }}
        />
      )}
    </>
  );
};

export default AnalysedFrameLayer;