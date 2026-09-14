 import {
  PhotoCamera,
  VideoCall,
  StopCircle,
  Refresh,
  OpenInFull,
  CloseFullscreen,
  KeyboardArrowDown,
  KeyboardArrowUp,
  Monitor,
} from '@mui/icons-material';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import React, { useEffect, useState, useCallback, useMemo } from 'react';

import { getConfigurableAVPanelLayout, loadAVConfig } from '../../../config/av';
import { useVNCState } from '../../../contexts/VNCStateContext';
import { useVncStream, useStream } from '../../../hooks/controller';
import { Host } from '../../../types/common/Host_Types';
import { getZIndex } from '../../../utils/zIndexUtils';
import { calculateVncScaling } from '../../../utils/vncUtils';
import { VerificationEditor } from '../verification';

import { RecordingOverlay, LoadingOverlay, ModeIndicatorDot } from './ScreenEditorOverlay';
import { ScreenshotCapture } from './ScreenshotCapture';
import { VideoCapture } from './VideoCapture';

interface VNCStreamProps {
  host: Host;
  deviceId: string;
  deviceModel?: string;
  isControlActive?: boolean;
  userinterfaceName?: string; // Required for saving references - defines the app/UI context
  onCollapsedChange?: (isCollapsed: boolean) => void;
  onExpandedChange?: (isExpanded: boolean) => void;
  onMinimizedChange?: (isMinimized: boolean) => void;
  onCaptureModeChange?: (mode: 'stream' | 'screenshot' | 'video') => void;
  useAbsolutePositioning?: boolean;
  positionLeft?: string;
  positionBottom?: string;
  sx?: any;
}

// VNC Viewer Component for iframe display with dynamic scaling
const VNCViewer = ({ 
  streamUrl, 
  panelWidth,
  panelHeight,
  sx = {} 
}: { 
  host: Host; 
  streamUrl: string | null; 
  panelWidth: string;
  panelHeight: string;
  sx?: any;
}) => {
  const [isVncLoading, setIsVncLoading] = useState(true);

  const handleVncLoad = () => {
    setIsVncLoading(false);
  };

  if (!streamUrl) {
    return (
      <Box
        sx={{
          ...sx,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'white',
        }}
      >
        <Typography>No VNC stream URL</Typography>
      </Box>
    );
  }

  // Calculate dynamic scaling based on actual container dimensions
  const containerWidth = parseInt(panelWidth);
  const containerHeight = parseInt(panelHeight) - 40; // Subtract header height
  const scaling = calculateVncScaling({ width: containerWidth, height: containerHeight });

  return (
    <Box
      sx={{
        ...sx,
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden', // Important: prevent iframe from extending beyond container
        backgroundColor: 'black',
      }}
    >
      {isVncLoading && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'rgba(0, 0, 0, 0.8)',
            zIndex: 1,
          }}
        >
          <Typography color="white">Loading VNC...</Typography>
        </Box>
      )}

      {/* VNC iframe with dynamic scaling to fit panel */}
      <iframe
        src={streamUrl}
        style={{
          width: scaling.width,
          height: scaling.height,
          border: 'none',
          backgroundColor: '#000',
          transform: scaling.transform,
          transformOrigin: scaling.transformOrigin,
        }}
        onLoad={handleVncLoad}
        title="VNC Desktop Stream"
        allow="fullscreen"
      />
    </Box>
  );
};

export const VNCStream = React.memo(
  function VNCStream({
    host,
    deviceId,
    deviceModel,
    isControlActive = false,
    userinterfaceName, // Required for saving references
    onCollapsedChange,
    onMinimizedChange,
    onCaptureModeChange,
    useAbsolutePositioning = false,
    positionLeft,
    positionBottom,
    sx = {},
  }: VNCStreamProps) {
    // VNC state from context
    const { isVNCExpanded, setIsVNCExpanded } = useVNCState();
    
    // Stream state
    const [isMinimized, setIsMinimized] = useState<boolean>(false);
    const [isScreenshotLoading, setIsScreenshotLoading] = useState<boolean>(false);
    // Active verification reference type — text references don't use a fuzzy area,
    // so we disable Shift+drag fuzzy selection on the capture overlay for them.
    const [verificationReferenceType, setVerificationReferenceType] = useState<'image' | 'text'>(
      'image',
    );

    // AV config state
    const [avConfig, setAvConfig] = useState<any>(null);

    // Use stream hook for VNC stream URL (for iframe)
    const { streamUrl, urlError } = useStream({ host, device_id: deviceId });
    const isStreamActive = !!streamUrl && !urlError; // VNC is active if we have a valid stream URL



    // Get device model (always host_vnc for VNC)
    const effectiveDeviceModel = useMemo(() => {
      return deviceModel || 'host_vnc';
    }, [deviceModel]);

    // Load AV config for VNC
    useEffect(() => {
      const loadConfig = async () => {
        const config = await loadAVConfig('vnc_stream', effectiveDeviceModel);
        setAvConfig(config);
      };

      loadConfig();
    }, [effectiveDeviceModel]);

    // Get configurable layout from AV config - memoized to prevent infinite loops
    const panelLayout = useMemo(() => {
      return getConfigurableAVPanelLayout(avConfig);
    }, [avConfig]);

    // Use the VNC hook
    const {
      // State from hook
      captureMode,
      isCaptureActive,
      selectedArea,
      screenshotPath,
      videoFrames,
      totalFrames,
      currentFrame,
      recordingStartTime,

      // Actions from hook
      setCaptureMode,
      setCurrentFrame,
      setIsCaptureActive,
      setCaptureStartTime,
      setRecordingStartTime,
      handleAreaSelected,
      handleImageLoad,
      handleTakeScreenshot: hookTakeScreenshot,
      fetchCapturedFrames,
    } = useVncStream({
      host,
      deviceModel: effectiveDeviceModel,
      streamUrl: streamUrl || '',
      isStreamActive,
    });

    // Fix handleImageLoad signature to match expected type
    const handleImageLoadWrapper = useCallback(
      (
        _ref: React.RefObject<HTMLImageElement>,
        dimensions: { width: number; height: number },
        _sourcePath: string,
      ) => {
        handleImageLoad(dimensions);
      },
      [handleImageLoad],
    );

    // Enhanced screenshot handler
    const handleTakeScreenshot = useCallback(async () => {
      setIsScreenshotLoading(true);
      try {
        await hookTakeScreenshot();
        setCaptureMode('screenshot');
        onCaptureModeChange?.('screenshot');
      } finally {
        setIsScreenshotLoading(false);
      }
    }, [hookTakeScreenshot, setCaptureMode, onCaptureModeChange]);

    // Start video capture
    const handleStartCapture = useCallback(async () => {
      try {
        console.log(`[@component:VNCStream] Starting video capture`);
        const startTime = new Date();
        setIsCaptureActive(true);
        setRecordingStartTime(startTime);
        setCaptureMode('video');
        onCaptureModeChange?.('video');
        console.log(`[@component:VNCStream] Recording started at:`, startTime);
      } catch (error) {
        console.error(`[@component:VNCStream] Error starting capture:`, error);
      }
    }, [setIsCaptureActive, setRecordingStartTime, setCaptureMode, onCaptureModeChange]);

    // Stop video capture
    const handleStopCapture = useCallback(async () => {
      try {
        console.log(`[@component:VNCStream] Stopping video capture`);
        const endTime = new Date();
        setIsCaptureActive(false);

        if (recordingStartTime) {
          const recordingDuration = endTime.getTime() - recordingStartTime.getTime();
          console.log(
            `[@component:VNCStream] Recording duration: ${recordingDuration}ms — loading captured frames`,
          );

          setCaptureStartTime(recordingStartTime);
          setCaptureMode('video');
          await fetchCapturedFrames(recordingStartTime.getTime(), endTime.getTime());
        } else {
          console.warn(`[@component:VNCStream] No recording start time found`);
          setCaptureMode('stream');
        }
      } catch (error) {
        console.error(`[@component:VNCStream] Error stopping capture:`, error);
      }
    }, [
      setIsCaptureActive,
      setCaptureStartTime,
      setCaptureMode,
      recordingStartTime,
      fetchCapturedFrames,
    ]);

    // Cap video recording at 30s so the whole clip always fits in the host's ~60s
    // hot frame buffer (captures aren't archived hot->cold), guaranteeing
    // promoteCapturedFrames can persist every frame. Auto-stops; manual stop clears it.
    useEffect(() => {
      if (!isCaptureActive) return;
      const timer = setTimeout(() => {
        console.log('[@component:VNCStream] Auto-stopping capture at 30s cap');
        handleStopCapture();
      }, 30000);
      return () => clearTimeout(timer);
    }, [isCaptureActive, handleStopCapture]);

    // Return to stream view
    const returnToStream = useCallback(() => {
      console.log(`[@component:VNCStream] Returning to stream view`);
      setCaptureMode('stream');
      onCaptureModeChange?.('stream');
    }, [setCaptureMode, onCaptureModeChange]);

    // Toggle handlers
    const handleMinimizeToggle = () => {
      if (isMinimized) {
        setIsMinimized(false);
        setIsVNCExpanded(true);
        onMinimizedChange?.(false);
        onCollapsedChange?.(false); // Notify parent that panel is now expanded
        console.log(
          `[@component:VNCStream] Restored from minimized to expanded for ${effectiveDeviceModel}`,
        );
      } else {
        setIsMinimized(true);
        onMinimizedChange?.(true);
        console.log(`[@component:VNCStream] Minimized panel for ${effectiveDeviceModel}`);
      }
    };

    const handleExpandCollapseToggle = () => {
      if (isMinimized) {
        setIsMinimized(false);
        setIsVNCExpanded(true);
        onMinimizedChange?.(false);
        onCollapsedChange?.(false); // Notify parent that panel is now expanded
        console.log(
          `[@component:VNCStream] Restored from minimized to expanded for ${effectiveDeviceModel}`,
        );
      } else {
        const newExpanded = !isVNCExpanded;
        setIsVNCExpanded(newExpanded);
        onCollapsedChange?.(!newExpanded);
        
        console.log(`[@component:VNCStream] Panel toggled to ${newExpanded ? 'expanded' : 'collapsed'}`);
      }
    };

    // Handle frame changes in video capture
    const handleFrameChange = useCallback(
      (frame: number) => {
        setCurrentFrame(frame);
      },
      [setCurrentFrame],
    );

    // Panel dimensions
    const collapsedWidth = panelLayout.collapsed.width;
    const collapsedHeight = panelLayout.collapsed.height;
    const expandedWidth = panelLayout.expanded.width;
    const expandedHeight = panelLayout.expanded.height;

    // Position styles
    const positionStyles: any = {
      position: useAbsolutePositioning ? 'absolute' : 'fixed',
      zIndex: getZIndex('VNC_STREAM'),
      // Use provided position props or fall back to config values
      ...(useAbsolutePositioning
        ? {
            bottom: positionBottom || '50px',
            left: positionLeft || '10px',
          }
        : {
            bottom: panelLayout.collapsed.position.bottom || '20px',
            left: panelLayout.collapsed.position.left || '20px',
          }),
      transition: 'left 0.3s ease, bottom 0.3s ease',
      ...sx,
    };

    const headerHeight = panelLayout.header?.height || '40px';

    // Calculate panel dimensions
    const getPanelWidth = () => {
      if (isMinimized) return collapsedWidth;
      return isVNCExpanded ? expandedWidth : collapsedWidth;
    };

    const getPanelHeight = () => {
      if (isMinimized) return headerHeight;
      return isVNCExpanded ? expandedHeight : collapsedHeight;
    };

    const currentVideoFramePath = videoFrames[currentFrame]?.url || '';
    const isVerificationVisible = captureMode === 'screenshot' || captureMode === 'video';

    return (
      <>
        {/* Main VNC Stream Panel */}
        <Box sx={positionStyles}>
          <Box
            sx={{
              width: getPanelWidth(),
              height: getPanelHeight(),
              position: 'absolute',
              bottom: 0,
              left: 0,
              backgroundColor: '#2A2A2A', // Slightly different from HDMI
              // Default discreet white border for all VNC panels (consistent with HDMI)
              border: '1px solid rgba(255, 255, 255, 0.2)',
              borderRadius: isVerificationVisible ? '1px 0 0 1px' : '8px',
              overflow: 'hidden',
              transition: 'width 0.3s ease-in-out, height 0.3s ease-in-out',
            }}
          >
            {/* Header */}
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                p: 1,
                height: headerHeight,
                borderBottom: isMinimized ? 'none' : '1px solid #444',
                bgcolor: '#2A2A2A',
                color: '#ffffff',
              }}
            >
              {/* Left side: Action buttons */}
              {isVNCExpanded && (
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                  <Tooltip title="Take Screenshot">
                    <IconButton
                      size="small"
                      onClick={handleTakeScreenshot}
                      sx={{
                        color:
                          captureMode === 'screenshot' || isScreenshotLoading
                            ? '#ff4444'
                            : '#ffffff',
                        '&:hover': { backgroundColor: 'rgba(255, 255, 255, 0.1)' },
                      }}
                      disabled={!isStreamActive || isCaptureActive || isScreenshotLoading}
                    >
                      <PhotoCamera sx={{ fontSize: 20 }} />
                    </IconButton>
                  </Tooltip>

                  {isCaptureActive ? (
                    <Tooltip title="Stop Capture">
                      <IconButton
                        size="small"
                        onClick={handleStopCapture}
                        sx={{
                          color: '#ff4444',
                          '&:hover': { backgroundColor: 'rgba(255, 255, 255, 0.1)' },
                        }}
                      >
                        <StopCircle sx={{ fontSize: 20 }} />
                      </IconButton>
                    </Tooltip>
                  ) : (
                    <Tooltip title="Start Capture">
                      <IconButton
                        size="small"
                        onClick={handleStartCapture}
                        sx={{
                          color: captureMode === 'video' ? '#ff4444' : '#ffffff',
                          '&:hover': { backgroundColor: 'rgba(255, 255, 255, 0.1)' },
                        }}
                        disabled={!isStreamActive}
                      >
                        <VideoCall sx={{ fontSize: 20 }} />
                      </IconButton>
                    </Tooltip>
                  )}

                  <Tooltip title="Return to Stream">
                    <IconButton
                      size="small"
                      onClick={returnToStream}
                      sx={{
                        color: '#ffffff',
                        '&:hover': { backgroundColor: 'rgba(255, 255, 255, 0.1)' },
                      }}
                      disabled={!isStreamActive || isCaptureActive}
                    >
                      <Refresh sx={{ fontSize: 20 }} />
                    </IconButton>
                  </Tooltip>
                </Box>
              )}

              {/* Center: Title with VNC icon */}
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  flex: 1,
                  justifyContent: 'center',
                }}
              >
                <Monitor sx={{ fontSize: 16 }} />
                <Typography
                  variant="subtitle2"
                  sx={{
                    fontSize: '0.875rem',
                    fontWeight: 'bold',
                  }}
                >
                  VNC
                </Typography>
              </Box>

              {/* Right side: Minimize and Expand/Collapse buttons */}
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Tooltip title={isMinimized ? 'Restore Panel' : 'Minimize Panel'}>
                  <IconButton size="small" onClick={handleMinimizeToggle} sx={{ color: 'inherit' }}>
                    {isMinimized ? (
                      <KeyboardArrowUp fontSize="small" />
                    ) : (
                      <KeyboardArrowDown fontSize="small" />
                    )}
                  </IconButton>
                </Tooltip>

                <Tooltip
                  title={
                    isMinimized ? 'Restore Panel' : isVNCExpanded ? 'Collapse Panel' : 'Expand Panel'
                  }
                >
                  <IconButton
                    size="small"
                    onClick={handleExpandCollapseToggle}
                    sx={{ color: 'inherit' }}
                  >
                    {isVNCExpanded ? (
                      <CloseFullscreen fontSize="small" />
                    ) : (
                      <OpenInFull fontSize="small" />
                    )}
                  </IconButton>
                </Tooltip>
              </Box>
            </Box>

            {/* VNC Content */}
            {!isMinimized && (
              <Box
                sx={{
                  height: `calc(100% - ${headerHeight})`,
                  overflow: 'hidden',
                  position: 'relative',
                }}
              >
                {/* VNC viewer - always rendered in background */}
                <VNCViewer
                  host={host}
                  streamUrl={streamUrl}
                  panelWidth={getPanelWidth()}
                  panelHeight={getPanelHeight()}
                  sx={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    zIndex: 1,
                  }}
                />

                {/* Screenshot capture overlay */}
                {captureMode === 'screenshot' && (
                  <ScreenshotCapture
                    screenshotPath={screenshotPath}
                    isCapturing={false}
                    isSaving={isScreenshotLoading}
                    onImageLoad={handleImageLoadWrapper}
                    selectedArea={selectedArea}
                    onAreaSelected={handleAreaSelected}
                    model={effectiveDeviceModel}
                    selectedHost={host}
                    allowFuzzy={verificationReferenceType !== 'text'}
                    sx={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: '100%',
                      zIndex: getZIndex('SCREENSHOT_MODAL'), // Above AndroidMobileOverlay
                    }}
                  />
                )}

                {/* Video capture overlay */}
                {captureMode === 'video' && (
                  <VideoCapture
                    currentFrame={currentFrame}
                    totalFrames={totalFrames}
                    onFrameChange={handleFrameChange}
                    onImageLoad={handleImageLoadWrapper}
                    selectedArea={selectedArea}
                    onAreaSelected={handleAreaSelected}
                    isCapturing={isCaptureActive}
                    videoFramePath={currentVideoFramePath}
                    model={effectiveDeviceModel}
                    allowFuzzy={verificationReferenceType !== 'text'}
                    sx={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: '100%',
                      zIndex: getZIndex('SCREENSHOT_MODAL'), // Above AndroidMobileOverlay
                    }}
                  />
                )}

                {/* Overlays */}
                <LoadingOverlay isScreenshotLoading={isScreenshotLoading} />
                <RecordingOverlay isCapturing={isCaptureActive} />

                {/* Mode indicator dot for collapsed view */}
                {!isVNCExpanded && <ModeIndicatorDot viewMode={captureMode} />}
              </Box>
            )}
          </Box>
        </Box>

        {/* Verification Editor Side Panel - only shown when the panel is expanded (hidden when collapsed or minimized) */}
        {isVerificationVisible && isVNCExpanded && !isMinimized && (
          <Box
            sx={{
              position: 'fixed',
              zIndex: getZIndex('VERIFICATION_EDITOR'),
              bottom: panelLayout.collapsed.position.bottom || '20px',
              left: `calc(${panelLayout.collapsed.position.left || '370px'} + ${getPanelWidth()})`,
              width: '400px',
              height: getPanelHeight(),
              backgroundColor: '#2A2A2A',
              border: '2px solid #2A2A2A',
              borderLeft: 'none',
              borderRadius: '0 1px 1px 0',
              transition: 'height 0.3s ease-in-out',
            }}
          >
            <VerificationEditor
              isVisible={isVerificationVisible}
              isCaptureActive={isCaptureActive}
              captureSourcePath={
                captureMode === 'screenshot' ? screenshotPath : currentVideoFramePath
              }
              selectedArea={selectedArea}
              onAreaSelected={handleAreaSelected}
              onClearSelection={() => handleAreaSelected({ x: 0, y: 0, width: 0, height: 0 })}
              selectedHost={host}
              selectedDeviceId={deviceId}
              isControlActive={isControlActive}
              userinterfaceName={userinterfaceName} // Pass userinterfaceName for reference saving
              onReferenceTypeChange={setVerificationReferenceType}
              sx={{
                width: '100%',
                height: '100%',
                p: 1,
              }}
            />
          </Box>
        )}
      </>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison to prevent unnecessary re-renders
    const hostChanged = JSON.stringify(prevProps.host) !== JSON.stringify(nextProps.host);
    const sxChanged = JSON.stringify(prevProps.sx) !== JSON.stringify(nextProps.sx);
    const onCollapsedChangeChanged = prevProps.onCollapsedChange !== nextProps.onCollapsedChange;
    const onMinimizedChangeChanged = prevProps.onMinimizedChange !== nextProps.onMinimizedChange;
    const onCaptureModeChangeChanged =
      prevProps.onCaptureModeChange !== nextProps.onCaptureModeChange;
    const useAbsolutePositioningChanged = prevProps.useAbsolutePositioning !== nextProps.useAbsolutePositioning;
    const positionLeftChanged = prevProps.positionLeft !== nextProps.positionLeft;
    const positionBottomChanged = prevProps.positionBottom !== nextProps.positionBottom;

    const shouldRerender =
      hostChanged ||
      sxChanged ||
      onCollapsedChangeChanged ||
      onMinimizedChangeChanged ||
      onCaptureModeChangeChanged ||
      useAbsolutePositioningChanged ||
      positionLeftChanged ||
      positionBottomChanged;

    if (shouldRerender) {
      console.log('[@component:VNCStream] Props changed, re-rendering:', {
        hostChanged,
        sxChanged,
        onCollapsedChangeChanged,
        onMinimizedChangeChanged,
        onCaptureModeChangeChanged,
        useAbsolutePositioningChanged,
        positionLeftChanged,
        positionBottomChanged,
      });
    }

    return !shouldRerender;
  },
);
