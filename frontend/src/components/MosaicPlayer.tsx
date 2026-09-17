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
  Tooltip
} from '@mui/material';

import { TimelineItem } from '../hooks/useHeatmap';
import { useR2Url } from '../hooks/storage/useR2Url';

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
      
      {/* Timeline Controls */}
      <Box 
        sx={{ 
          mt: 0,
          mb: 0,
          ml: isCompactLayout ? 0 : 2,
          pl: 1,
          pr: 1,
          backgroundColor: 'rgba(0,0,0,0.05)',
          borderRadius: 1
        }}
      >
        {isCompactLayout && (
          <Box sx={{ pt: 0.5, display: 'flex', justifyContent: 'space-between', gap: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {formatDisplayTime(currentItem)}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Frame {currentIndex + 1} / {timeline.length}
            </Typography>
          </Box>
        )}
        
        {/* Timeline Scrubber */}
        <Box 
          ref={sliderRef}
          sx={{ position: 'relative', pb: 0 }}
          onMouseMove={handleMouseMove}
        >
          <Tooltip
            title={isDragging && previewIndex !== null ? formatTimeForTooltip(previewIndex) : ''}
            open={isDragging}
            arrow
            placement="top"
            PopperProps={{
              anchorEl: null,
              style: isDragging ? {
                position: 'fixed',
                left: `${mousePosition.x - 50}px`, // Center tooltip on mouse
                top: `${mousePosition.y - 60}px`,  // Position above mouse
                zIndex: 9999,
                pointerEvents: 'none'
              } : undefined,
              modifiers: [
                {
                  name: 'offset',
                  enabled: false,
                },
                {
                  name: 'preventOverflow',
                  enabled: false,
                },
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
                color: (!currentItem || hasDataError) ? '#888888' : (hasIncidents ? '#FF0000' : '#00AA00'),
                '& .MuiSlider-thumb': {
                  width: 16,
                  height: 16,
                  backgroundColor: (!currentItem || hasDataError) ? '#888888' : (hasIncidents ? '#FF0000' : '#00AA00'),
                },
                '& .MuiSlider-track': {
                  backgroundColor: (!currentItem || hasDataError) ? '#888888' : (hasIncidents ? '#FF0000' : '#00AA00'),
                },
                '& .MuiSlider-rail': {
                  backgroundColor: '#CCCCCC',
                }
              }}
            />
          </Tooltip>
          
          
          {/* Hour Marks with Date/Time Display */}
          <Box sx={{ position: 'absolute', top: 25, left: 0, right: 0, height: 40 }}>
            {Array.from({ length: isCompactLayout ? 6 : 24 }, (_, i) => {
              const hourStep = isCompactLayout ? 4 : 1;
              const hourIndex = i * hourStep * 60;
              const position = (hourIndex / Math.max(1, timeline.length - 1)) * 100;
              const timelineItem = timeline[hourIndex];
              
              // Get the actual hour from the timeline item at this position
              const displayHour = timelineItem ? timelineItem.displayTime.getHours() : 0;
              
              // Check if this hour mark corresponds to the current timeline position
              // We need to check if the current timeline index falls within this hour range
              const isCurrentHour = currentIndex >= hourIndex && currentIndex < hourIndex + 60;
              
              return (
                <Tooltip 
                  key={i}
                  title={timelineItem ? formatDisplayTime(timelineItem) : ''}
                  arrow
                >
                  <Box
                    sx={{
                      position: 'absolute',
                      left: `${position}%`,
                      transform: 'translateX(-50%)',
                      fontSize: '10px',
                      cursor: 'pointer',
                      textAlign: 'center',
                      padding: '2px 4px',
                      borderRadius: '4px',
                      border: isCurrentHour ? '2px solid #4a90e2' : '2px solid transparent',
                      backgroundColor: isCurrentHour ? 'rgba(74, 144, 226, 0.1)' : 'transparent',
                      fontWeight: isCurrentHour ? 'bold' : 'normal',
                      color: isCurrentHour ? '#4a90e2' : 'inherit',
                      '&:hover': { fontWeight: 'bold' }
                    }}
                    onClick={() => onIndexChange(hourIndex)}
                  >
                    <Typography variant="caption" sx={{ fontSize: isCompactLayout ? '9px' : '10px', display: 'block' }}>
                      {String(displayHour).padStart(2, '0')}{isCompactLayout ? '' : 'h'}
                    </Typography>
                    {!isCompactLayout && timelineItem && (
                      <Typography variant="caption" sx={{ fontSize: '8px', color: 'text.secondary', display: 'block' }}>
                        {timelineItem.isToday ? 'Today' : 'Yesterday'}
                      </Typography>
                    )}
                  </Box>
                </Tooltip>
              );
            })}
          </Box>
        </Box>
      </Box>
    </Box>
  );
};
