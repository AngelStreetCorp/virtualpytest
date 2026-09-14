import { PlayArrow, Pause } from '@mui/icons-material';
import { Box, Slider, IconButton, Typography } from '@mui/material';
import React, { useState, useEffect, useRef } from 'react';

import { getStreamViewerLayout } from '../../../config/layoutConfig';
import { getZIndex } from '../../../utils/zIndexUtils';

import { DragSelectionOverlay } from './DragSelectionOverlay';

interface DragArea {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface VideoCaptureProps {
  // Core functionality props
  currentFrame?: number;
  totalFrames?: number;
  onFrameChange?: (frame: number) => void;
  onImageLoad?: (
    ref: React.RefObject<HTMLImageElement>,
    dimensions: { width: number; height: number },
    sourcePath: string,
  ) => void;
  selectedArea?: DragArea | null;
  onAreaSelected?: (area: DragArea) => void;
  isCapturing?: boolean;
  videoFramePath?: string; // Current frame image path/URL
  model?: string;
  // When false, Shift+drag fuzzy-area selection is disabled (e.g. text verification)
  allowFuzzy?: boolean;

  sx?: any;
}

export function VideoCapture({
  currentFrame = 0,
  totalFrames = 0,
  onFrameChange,
  onImageLoad,
  selectedArea,
  onAreaSelected,
  isCapturing = false,
  videoFramePath,
  model,
  allowFuzzy = true,
  sx = {},
}: VideoCaptureProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentValue, setCurrentValue] = useState(currentFrame);
  // While the user is dragging an area selection we hide the playback controls
  // (play button + timeline). They legitimately sit on top of the image so they
  // can be clicked, but during a drag they would block selecting across the
  // bottom of the image — so the whole frame becomes draggable.
  const [isAreaDragging, setIsAreaDragging] = useState(false);
  const imageRef = useRef<HTMLImageElement>(null);

  // Latest onFrameChange — kept in a ref so the playback interval (set up once
  // per play) always calls the current handler without re-subscribing.
  const onFrameChangeRef = useRef(onFrameChange);
  useEffect(() => {
    onFrameChangeRef.current = onFrameChange;
  }, [onFrameChange]);

  // Get layout configuration based on device model
  const layoutConfig = getStreamViewerLayout(model);

  // Handle frame playback for captured images. The displayed image is owned by
  // the parent (videoFramePath), so each tick must notify the parent via
  // onFrameChange — otherwise the slider/counter advance but the picture stays
  // frozen. One frame per second; stop on the last frame.
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (isPlaying && totalFrames > 0) {
      interval = setInterval(() => {
        setCurrentValue((prev) => {
          const next = prev + 1;
          if (next >= totalFrames) {
            // Stop playing when reaching the last frame
            console.log('[@component:VideoCapture] Reached last frame, stopping playback');
            setIsPlaying(false);
            return prev; // Stay on last frame
          }
          onFrameChangeRef.current?.(next); // Tell the parent to swap the image
          return next;
        });
      }, 1000); // 1 second per frame
    }
    return () => clearInterval(interval);
  }, [isPlaying, totalFrames]);

  // Sync with external frame changes
  useEffect(() => {
    setCurrentValue(currentFrame);
  }, [currentFrame]);

  const handleSliderChange = (_event: Event, newValue: number | number[]) => {
    const frame = newValue as number;
    setCurrentValue(frame);
    onFrameChange?.(frame);
  };

  const handlePlayPause = () => {
    setIsPlaying(!isPlaying);
  };

  // Handle image load to pass ref and dimensions to parent
  const handleImageLoad = () => {
    if (imageRef.current && onImageLoad && videoFramePath) {
      const img = imageRef.current;
      const dimensions = {
        width: img.naturalWidth,
        height: img.naturalHeight,
      };
      console.log(
        '[@component:VideoCapture] Image loaded successfully:',
        videoFramePath,
        dimensions,
      );
      onImageLoad(imageRef, dimensions, videoFramePath);
    }
  };

  // Use processed URL directly from backend
  const imageUrl = videoFramePath || '';

  console.log(
    `[@component:VideoCapture] Rendering with imageUrl: ${imageUrl}, totalFrames: ${totalFrames}, isCapturing: ${isCapturing}`,
  );

  // Determine if drag selection should be enabled
  const allowDragSelection = totalFrames > 0 && onAreaSelected && imageRef.current;

  return (
    <Box
      sx={{
        // Match ScreenshotCapture exactly: one full-size centered box so the image
        // and the drag overlay share the same geometry as a normal screenshot
        // (the old flex-column + header row shrank/offset the image and broke
        // full-image area selection). The frame label/controls are absolute overlays.
        position: 'relative',
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        backgroundColor: 'transparent',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        MozUserSelect: 'none',
        msUserSelect: 'none',
        ...sx,
      }}
    >
      {/* Drag Selection Overlay - covers the full image, same as ScreenshotCapture */}
      {allowDragSelection && (
        <DragSelectionOverlay
          imageRef={imageRef}
          onAreaSelected={onAreaSelected}
          selectedArea={selectedArea || null}
          allowFuzzy={allowFuzzy}
          onDraggingChange={setIsAreaDragging}
          sx={{ zIndex: getZIndex('VIDEO_CAPTURE_OVERLAY') }}
        />
      )}

      {/* Captured frame - identical sizing to ScreenshotCapture's <img> */}
      {totalFrames > 0 && imageUrl && !isCapturing && (
        <img
          ref={imageRef}
          src={imageUrl}
          alt={`Captured Frame ${currentValue + 1}`}
          style={{
            maxWidth: layoutConfig.isMobileModel ? 'auto' : '100%',
            maxHeight: '100%',
            width: layoutConfig.isMobileModel ? 'auto' : '100%',
            height: layoutConfig.isMobileModel ? '100%' : 'auto', // Match StreamViewer/ScreenshotCapture
            objectFit: layoutConfig.objectFit,
            backgroundColor: 'transparent',
          }}
          draggable={false}
          onLoad={handleImageLoad}
          onError={(e) => {
            const imgSrc = (e.target as HTMLImageElement).src;
            console.error(`[@component:VideoCapture] Failed to load image: ${imgSrc}`);

            // Set a transparent fallback image
            (e.target as HTMLImageElement).src =
              'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

            // Add placeholder styling
            const img = e.target as HTMLImageElement;
            img.style.backgroundColor = 'transparent';
            img.style.border = '1px solid #E0E0E0';
            img.style.maxWidth = '100%';
            img.style.maxHeight = '100%';
            img.style.width = 'auto';
            img.style.height = 'auto';
            img.style.objectFit = 'contain';
            img.style.padding = '4px';
          }}
        />
      )}

      {/* CAPTURED FRAMES label - absolute overlay (takes no layout height, so it
          can't shrink the image). pointerEvents:none keeps the top of the image
          fully drag-selectable. */}
      {totalFrames > 0 && !isCapturing && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '4px 8px',
            pointerEvents: 'none',
            background: 'linear-gradient(rgba(0,0,0,0.55), transparent)',
            zIndex: getZIndex('VIDEO_CAPTURE_OVERLAY', 1),
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <Box
              sx={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: '#4caf50',
                marginRight: 1,
              }}
            />
            <Typography variant="caption" sx={{ color: '#ffffff', fontSize: '10px' }}>
              CAPTURED FRAMES
            </Typography>
          </Box>
          <Typography variant="caption" sx={{ color: '#cccccc', fontSize: '10px' }}>
            {totalFrames} frames
          </Typography>
        </Box>
      )}

      {/* Recording state overlay */}
      {isCapturing && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'rgba(0,0,0,0.3)',
            zIndex: getZIndex('VIDEO_CAPTURE_OVERLAY'),
          }}
        >
          <Typography variant="body1" sx={{ color: '#ffffff', textAlign: 'center', opacity: 0.8 }}>
            Recording in progress...
          </Typography>
        </Box>
      )}

      {/* Placeholder when no frames available and not recording */}
      {totalFrames === 0 && !isCapturing && (
        <Box
          sx={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'transparent',
            border: '1px solid #333333',
          }}
        >
          <Typography variant="caption" sx={{ color: '#666666' }}>
            No Captured Frames Available
          </Typography>
        </Box>
      )}

      {/* Playback controls - only show when we have captured frames, and hidden
          while an area is being dragged so the whole image stays selectable. */}
      {totalFrames > 0 && !isAreaDragging && (
        <Box
          sx={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            background: 'linear-gradient(transparent, rgba(0,0,0,0.8))',
            p: 1,
            backgroundColor: 'transparent',
            // Sit ABOVE the drag-selection overlay so the play button and timeline
            // are clickable. The wrapper itself is click-through (pointerEvents:none)
            // so area-dragging still works on the rest of the image; only the actual
            // widgets below re-enable pointer events.
            zIndex: getZIndex('VIDEO_CAPTURE_OVERLAY', 1),
            pointerEvents: 'none',
          }}
        >
          {/* Play/Pause button - bottom left (raised to vertically align with the timeline) */}
          <Box
            sx={{
              position: 'absolute',
              bottom: 14,
              left: 8,
              pointerEvents: 'auto',
            }}
          >
            <IconButton
              size="medium"
              onClick={handlePlayPause}
              sx={{
                color: '#ffffff',
                // Black border + dark fill so the control stays visible on a white screen
                backgroundColor: 'rgba(0,0,0,0.55)',
                border: '1px solid #000',
                '&:hover': {
                  backgroundColor: 'rgba(0,0,0,0.75)',
                },
                zIndex: getZIndex('VIDEO_CAPTURE_CONTROLS', 1),
              }}
            >
              {isPlaying ? <Pause /> : <PlayArrow />}
            </IconButton>
          </Box>

          {/* Frame counter - bottom right */}
          <Box
            sx={{
              position: 'absolute',
              bottom: 16,
              right: 16,
              zIndex: getZIndex('VIDEO_CAPTURE_CONTROLS', 1),
            }}
          >
            <Typography
              variant="caption"
              sx={{
                color: '#ffffff',
                fontSize: '0.8rem',
                textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
              }}
            >
              {currentValue + 1} / {totalFrames}
            </Typography>
          </Box>

          {/* Scrubber - centered horizontally, at bottom */}
          <Box
            sx={{
              position: 'absolute',
              bottom: 12,
              left: '80px',
              right: '80px',
              pointerEvents: 'auto',
            }}
          >
            <Slider
              value={currentValue}
              min={0}
              max={Math.max(0, totalFrames - 1)}
              onChange={handleSliderChange}
              sx={{
                color: '#ffffff',
                // Black borders on thumb/track/rail keep the timeline visible on a white screen
                '& .MuiSlider-thumb': {
                  width: 16,
                  height: 16,
                  backgroundColor: '#fff',
                  border: '2px solid #000',
                  '&:hover': {
                    boxShadow: '0px 0px 0px 8px rgba(255, 255, 255, 0.16)',
                  },
                },
                '& .MuiSlider-track': {
                  backgroundColor: '#fff',
                  border: '1px solid #000',
                },
                '& .MuiSlider-rail': {
                  backgroundColor: 'rgba(255,255,255,0.5)',
                  border: '1px solid #000',
                  opacity: 1,
                },
              }}
            />
          </Box>
        </Box>
      )}
    </Box>
  );
}

export default VideoCapture;
