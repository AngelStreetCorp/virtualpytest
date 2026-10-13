/**
 * Mosaic Player Component
 * 
 * Displays heatmap mosaics with timeline scrubber for 24h circular buffer.
 * Shows mosaic images and provides timeline navigation controls.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box,
  Slider,
  Typography,
  Alert,
  IconButton,
  Tooltip
} from '@mui/material';
import { ChevronLeft, ChevronRight } from '@mui/icons-material';

import { TimelineItem } from '../hooks/useHeatmap';
import { useR2Url } from '../hooks/storage/useR2Url';
import { useAgentChatPalette } from '../constants/agentChatTheme';

// Add type alias for filter
type FilterType = 'ALL' | 'OK' | 'KO';

interface MosaicPlayerProps {
  timeline: TimelineItem[];
  currentIndex: number;
  onIndexChange: (index: number) => void;
  onCellClick?: (deviceData: any) => void;
  hasIncidents?: boolean;
  hasDataError?: boolean;
  displayItem?: TimelineItem | null; // Slot the loaded data came from (may lag currentIndex)
  analysisData?: any; // Device analysis data for overlays
  filter?: FilterType;
  getMosaicUrl?: (item: TimelineItem, filter: FilterType) => string;
  isCompactLayout?: boolean;
}

export const MosaicPlayer: React.FC<MosaicPlayerProps> = ({
  timeline,
  currentIndex,
  onIndexChange,
  onCellClick,
  hasIncidents = false,
  hasDataError = false,
  displayItem,
  analysisData,
  filter = 'ALL',
  getMosaicUrl,
  isCompactLayout = false
}) => {
  const P = useAgentChatPalette();
  const [imageError, setImageError] = useState(false);
  const [imageLoading, setImageLoading] = useState(true);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null); // For drag preview
  const [isDragging, setIsDragging] = useState(false);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const sliderRef = useRef<HTMLDivElement>(null);
  const imageCache = useRef<Map<string, HTMLImageElement>>(new Map());
  const preloadImageRef = useRef<HTMLImageElement | null>(null);
  const imgElementRef = useRef<HTMLImageElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [overlayPositions, setOverlayPositions] = useState<Array<{
    left: number;
    top: number;
    width: number;
    height: number;
  }>>([]);
  
  const currentItem = timeline[currentIndex];
  // Timeline colour = the hour's status: no data muted, incidents red, clean green.
  const sliderColor = (!currentItem || hasDataError) ? P.textMuted : (hasIncidents ? P.error : P.success);
  // Show the mosaic of the frame that was actually loaded. Files are keyed by HHMM
  // in a 24h circular buffer, so the slot's image can be a previous-day leftover the
  // loader rejected - rendering it would contradict the "no data" state.
  const imageItem = hasDataError ? null : displayItem ?? currentItem;
  const mosaicSrcOriginal = imageItem
    ? (getMosaicUrl ? getMosaicUrl(imageItem, filter) : imageItem.mosaicUrl)
    : '';
  
  // Convert R2 URL to signed URL (handles public/private mode automatically)
  const { url: mosaicSrc } = useR2Url(mosaicSrcOriginal || null);
  
  // Reset loading state when filter or index changes
  useEffect(() => {
    setImageLoading(true);
    setImageError(false);
  }, [filter, currentIndex, mosaicSrcOriginal]);

  // Calculate overlay positions based on actual image dimensions
  const calculatePositions = useCallback(() => {
    if (!imgElementRef.current || !containerRef.current || !analysisData?.devices) return;

    const img = imgElementRef.current;
    const container = containerRef.current;

    const containerRect = container.getBoundingClientRect();
    const containerWidth = containerRect.width;
    const containerHeight = containerRect.height;

    const imageNaturalWidth = img.naturalWidth;
    const imageNaturalHeight = img.naturalHeight;
    if (imageNaturalWidth === 0 || imageNaturalHeight === 0) return;

    const containerAspectRatio = containerWidth / containerHeight;
    const imageAspectRatio = imageNaturalWidth / imageNaturalHeight;

    let displayedImageWidth: number;
    let displayedImageHeight: number;
    let offsetX: number;
    let offsetY: number;

    if (imageAspectRatio > containerAspectRatio) {
      displayedImageWidth = containerWidth;
      displayedImageHeight = containerWidth / imageAspectRatio;
      offsetX = 0;
      offsetY = (containerHeight - displayedImageHeight) / 2;
    } else {
      displayedImageWidth = containerHeight * imageAspectRatio;
      displayedImageHeight = containerHeight;
      offsetX = (containerWidth - displayedImageWidth) / 2;
      offsetY = 0;
    }

    const deviceCount = analysisData.devices.length;
    let cols: number, rows: number;
    if (deviceCount <= 1) {
      cols = 1; rows = 1;
    } else if (deviceCount === 2) {
      cols = 2; rows = 1;
    } else if (deviceCount <= 4) {
      cols = 2; rows = 2;
    } else if (deviceCount <= 6) {
      cols = 3; rows = 2;
    } else if (deviceCount <= 9) {
      cols = 3; rows = 3;
    } else {
      cols = Math.min(6, deviceCount);
      rows = Math.ceil(deviceCount / cols);
    }

    const cellWidth = displayedImageWidth / cols;
    const cellHeight = displayedImageHeight / rows;

    const positions = analysisData.devices.map((_: any, index: number) => {
      const col = index % cols;
      const row = Math.floor(index / cols);

      return {
        left: offsetX + (col * cellWidth),
        top: offsetY + (row * cellHeight),
        width: cellWidth,
        height: cellHeight
      };
    });

    setOverlayPositions(positions);
  }, [analysisData]);

  useEffect(() => {
    if (!imgElementRef.current) return;

    const img = imgElementRef.current;
    if (img.complete && !imageLoading) {
      calculatePositions();
    } else {
      img.addEventListener('load', calculatePositions);
    }

    window.addEventListener('resize', calculatePositions);

    return () => {
      if (imgElementRef.current) {
        imgElementRef.current.removeEventListener('load', calculatePositions);
      }
      window.removeEventListener('resize', calculatePositions);
    };
  }, [analysisData, imageLoading, mosaicSrc, calculatePositions]);
  
  // Preload and cache image
  useEffect(() => {
    if (!mosaicSrc || mosaicSrc === '') {
      setImageLoading(false);
      setImageError(true);
      return;
    }
    
    // Check if image is already cached
    if (imageCache.current.has(mosaicSrc)) {
      setImageLoading(false);
      setImageError(false);
      return;
    }
    
    // Preload image.
    // crossOrigin matters here, it is not decoration: storage serves these mosaics with
    // `Cross-Origin-Resource-Policy: same-origin`, which blocks a plain (no-cors) <img> load
    // from any other origin — net::ERR_BLOCKED_BY_RESPONSE.NotSameOrigin. On the web the page
    // and the image share an origin so nothing notices, but the mobile app runs on
    // https://localhost and every mosaic failed there ("No mosaic available"). CORP is only
    // enforced for no-cors requests, and the response already carries a matching
    // Access-Control-Allow-Origin, so asking for CORS mode is what makes it load.
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      imageCache.current.set(mosaicSrc, img);
      setImageLoading(false);
      setImageError(false);
    };
    img.onerror = () => {
      setImageLoading(false);
      setImageError(true);
    };
    img.src = mosaicSrc;
    preloadImageRef.current = img;
    
    return () => {
      if (preloadImageRef.current) {
        preloadImageRef.current.onload = null;
        preloadImageRef.current.onerror = null;
      }
    };
  }, [mosaicSrc]);
  
  
  /**
   * Calculate timeline index from mouse position
   */
  const calculateIndexFromMousePosition = (clientX: number): number => {
    if (!sliderRef.current) return currentIndex;
    
    const rect = sliderRef.current.getBoundingClientRect();
    const relativeX = clientX - rect.left;
    const percentage = Math.max(0, Math.min(1, relativeX / rect.width));
    const maxIndex = Math.max(0, timeline.length - 1);
    return Math.round(percentage * maxIndex);
  };

  /**
   * Handle mouse move during drag
   */
  const handleMouseMove = (event: React.MouseEvent) => {
    if (isDragging) {
      const newIndex = calculateIndexFromMousePosition(event.clientX);
      setPreviewIndex(newIndex);
      setMousePosition({ x: event.clientX, y: event.clientY });
    }
  };

  /**
   * Timeline slider change handler (during drag - for tooltip only)
   */
  const handleSliderChange = (event: Event, newValue: number | number[]) => {
    const index = newValue as number;
    setPreviewIndex(index);
    setIsDragging(true);
    
    // Track mouse position for tooltip
    if (event instanceof MouseEvent) {
      setMousePosition({ x: event.clientX, y: event.clientY });
    }
    // Don't call onIndexChange here - only update tooltip
  };

  /**
   * Timeline slider change committed handler (on mouse release - actual change)
   */
  const handleSliderChangeCommitted = (_event: Event | React.SyntheticEvent, newValue: number | number[]) => {
    const index = newValue as number;
    setIsDragging(false);
    setPreviewIndex(null);
    onIndexChange(index); // Only change heatmap on mouse release
  };

  /**
   * Format time for tooltip during drag
   */
  const formatTimeForTooltip = (index: number): string => {
    const item = timeline[index];
    if (!item) return '';
    
    const time = item.displayTime;
    const timeStr = time.toLocaleTimeString('en-US', { 
      hour12: false, 
      hour: '2-digit', 
      minute: '2-digit'
    });
    
    const dateStr = item.isToday ? 'Today' : 'Yesterday';
    return `${dateStr} ${timeStr}`;
  };
  
  /**
   * Format time for display
   */
  const formatDisplayTime = (item: TimelineItem): string => {
    const time = item.displayTime;
    const timeStr = time.toLocaleTimeString('en-US', { 
      hour12: false, 
      hour: '2-digit', 
      minute: '2-digit' 
    });
    
    if (item.isToday) {
      return `Today ${timeStr}`;
    } else {
      return `Yesterday ${timeStr}`;
    }
  };
  
  
  // One mark per hour (every 4th on compact layouts); the timeline holds one frame per minute.
  const hourStep = isCompactLayout ? 4 : 1;
  const hourMarks = Array.from({ length: Math.ceil(24 / hourStep) }, (_, i) => {
    const index = i * hourStep * 60;
    const item = timeline[index];
    return {
      index,
      item,
      hour: item ? item.displayTime.getHours() : 0,
      isCurrent: currentIndex >= index && currentIndex < index + hourStep * 60,
    };
  });
  const midnightPos = hourMarks.findIndex((m, i) => i > 0 && m.item && m.hour < hourStep);
  const midnightMark = midnightPos > 0 ? { pos: midnightPos } : null;

  if (!currentItem) {
    return (
      <Alert severity="warning">
        No timeline data available
      </Alert>
    );
  }
  
  return (
    <Box>
      {/* Mosaic Display */}
      <Box 
        ref={containerRef}
        sx={{ 
          width: '100%', 
          height: isCompactLayout ? '38vh' : '50vh',
          backgroundColor: 'black',
          borderRadius: 1,
          overflow: 'hidden',
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}
      >
        {imageError || !imageItem ? (
          <Alert 
            severity="warning" 
            sx={{ 
              backgroundColor: 'rgba(255, 193, 7, 0.1)',
              color: 'white'
            }}
          >
            No mosaic available for {currentItem.timeKey}
          </Alert>
        ) : (
          <>
            <img
              ref={imgElementRef}
              crossOrigin="anonymous"
              src={mosaicSrc || undefined}
              alt={`Heatmap ${currentItem.timeKey} - ${filter}`}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain'
              }}
              onLoad={() => {
                setImageLoading(false);
                setImageError(false);
                calculatePositions();
              }}
              onError={() => {
                setImageLoading(false);
                setImageError(true);
              }}
            />
            
            {/* Device Overlays */}
            {!imageLoading && analysisData?.devices && overlayPositions.length > 0 && (
              <Box sx={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: 2 }}>
                {analysisData.devices.map((device: any, index: number) => {
                  const position = overlayPositions[index];
                  if (!position) return null;

                  const analysis = device.analysis_json || {};
                  const deviceName = (device.device_name || device.device_id || 'Unknown').replace(/_Host$/, '');
                  const deviceLabel =
                    deviceName && deviceName !== device.host_name
                      ? `${device.host_name}-${deviceName}`
                      : device.host_name;
                  // audio undefined/null = no audio capability (N/A); false = real loss
                  const audioLabel =
                    analysis.audio === true ? 'Yes' : analysis.audio === false ? 'No' : 'N/A';

                  const tooltipText = `${deviceLabel}
Audio: ${audioLabel}
Video: ${!analysis.blackscreen && !analysis.freeze ? 'Yes' : 'No'}
${analysis.volume_percentage !== undefined ? `Volume: ${analysis.volume_percentage}%` : ''}
${analysis.freeze ? `Freeze: ${(analysis.freeze_diffs || []).length} diffs` : ''}`;

                  return (
                    <Tooltip key={`${device.host_name}-${device.device_id}`} title={tooltipText} arrow>
                      <Box
                        sx={{
                          position: 'absolute',
                          left: `${position.left}px`,
                          top: `${position.top}px`,
                          width: `${position.width}px`,
                          height: `${position.height}px`,
                          cursor: 'pointer',
                          zIndex: 3,
                          '&:hover': {
                            backgroundColor: 'rgba(255, 255, 255, 0.1)',
                            border: '2px solid #fff'
                          }
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          onCellClick?.(device);
                        }}
                      />
                    </Tooltip>
                  );
                })}
              </Box>
            )}
          </>
        )}
        
        {imageLoading && (
          <Box 
            sx={{ 
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              color: 'white'
            }}
          >
            <Typography>Loading mosaic...</Typography>
          </Box>
        )}
      </Box>
      
      {/* Timeline Controls: readout + prev/next, slider, one segment + label per hour */}
      <Box
        sx={{
          mt: 1.5,
          p: 1.5,
          backgroundColor: P.surface,
          border: `1px solid ${P.borderColor}`,
          borderRadius: 3,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <IconButton
              size="small"
              aria-label="Previous frame"
              disabled={currentIndex <= 0}
              onClick={() => onIndexChange(Math.max(0, currentIndex - 1))}
              sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2 }}
            >
              <ChevronLeft fontSize="small" />
            </IconButton>
            <Typography sx={{ width: 150, textAlign: 'center', fontSize: '1.1rem', fontWeight: 600, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
              {formatDisplayTime(timeline[isDragging && previewIndex !== null ? previewIndex : currentIndex] || currentItem)}
            </Typography>
            <IconButton
              size="small"
              aria-label="Next frame"
              disabled={currentIndex >= timeline.length - 1}
              onClick={() => onIndexChange(Math.min(timeline.length - 1, currentIndex + 1))}
              sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2 }}
            >
              <ChevronRight fontSize="small" />
            </IconButton>
          </Box>
          {!isCompactLayout && (
            <Typography sx={{ fontSize: '0.72rem', color: P.textMuted }}>Click an hour or drag the bar</Typography>
          )}
        </Box>

        <Box ref={sliderRef} sx={{ position: 'relative' }} onMouseMove={handleMouseMove}>
          <Tooltip
            title={isDragging && previewIndex !== null ? formatTimeForTooltip(previewIndex) : ''}
            open={isDragging}
            arrow
            placement="top"
            PopperProps={{
              anchorEl: null,
              style: isDragging ? {
                position: 'fixed',
                left: `${mousePosition.x - 50}px`,
                top: `${mousePosition.y - 60}px`,
                zIndex: 9999,
                pointerEvents: 'none'
              } : undefined,
              modifiers: [
                { name: 'offset', enabled: false },
                { name: 'preventOverflow', enabled: false },
              ],
            }}
          >
            <Slider
              value={isDragging && previewIndex !== null ? previewIndex : currentIndex}
              min={0}
              max={Math.max(0, timeline.length - 1)}
              onChange={handleSliderChange}
              onChangeCommitted={handleSliderChangeCommitted}
              sx={{
                color: P.accent,
                py: 1,
                '& .MuiSlider-thumb': { width: 14, height: 14, backgroundColor: P.accent, border: `2px solid ${P.surface}` },
                '& .MuiSlider-track': { backgroundColor: P.accent, border: 'none' },
                '& .MuiSlider-rail': { backgroundColor: P.borderColor, opacity: 1 },
              }}
            />
          </Tooltip>
        </Box>

        {/* One segment per hour: the selected hour carries the frame's status colour. */}
        <Box sx={{ display: 'grid', gridTemplateColumns: `repeat(${hourMarks.length}, 1fr)`, gap: '2px', mt: 0.5 }}>
          {hourMarks.map((m) => (
            <Tooltip key={m.index} title={m.item ? formatDisplayTime(m.item) : ''} arrow>
              <Box
                onClick={() => onIndexChange(m.index)}
                sx={{
                  cursor: 'pointer',
                  textAlign: 'center',
                  borderRadius: '4px',
                  py: 0.25,
                  bgcolor: m.isCurrent ? `${P.accent}26` : 'transparent',
                  '&:hover': { bgcolor: m.isCurrent ? `${P.accent}26` : P.hoverBg },
                }}
              >
                <Box sx={{ height: 6, borderRadius: '2px', mb: 0.5, bgcolor: m.isCurrent ? sliderColor : P.borderColor }} />
                <Typography
                  sx={{
                    fontSize: isCompactLayout ? '0.6rem' : '0.65rem',
                    lineHeight: 1.2,
                    fontVariantNumeric: 'tabular-nums',
                    color: m.isCurrent ? P.accentText : P.textMuted,
                    fontWeight: m.isCurrent ? 600 : 400,
                  }}
                >
                  {String(m.hour).padStart(2, '0')}
                </Typography>
              </Box>
            </Tooltip>
          ))}
        </Box>

        {/* Day divider at midnight, instead of repeating Yesterday/Today on every hour */}
        {midnightMark && (
          <Box sx={{ position: 'relative', height: 18, mt: 0.25 }}>
            <Box sx={{ position: 'absolute', top: 0, bottom: 0, left: `${(midnightMark.pos / hourMarks.length) * 100}%`, borderLeft: `1px dashed ${P.textMuted}` }} />
            <Typography sx={{ position: 'absolute', right: `${100 - (midnightMark.pos / hourMarks.length) * 100 + 0.5}%`, fontSize: '0.65rem', color: P.textMuted }}>Yesterday</Typography>
            <Typography sx={{ position: 'absolute', left: `${(midnightMark.pos / hourMarks.length) * 100 + 0.5}%`, fontSize: '0.65rem', color: P.textMuted }}>Today</Typography>
          </Box>
        )}
      </Box>
    </Box>
  );
};
