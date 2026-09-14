import {
  PhotoCamera,
  VideoCall,
  StopCircle,
  Refresh,
  OpenInFull,
  CloseFullscreen,
  KeyboardArrowDown,
  KeyboardArrowUp,
} from '@mui/icons-material';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';

import { getConfigurableAVPanelLayout, loadAVConfig } from '../../../config/av';
import { useHdmiStream, useStream } from '../../../hooks/controller';
import { Host } from '../../../types/common/Host_Types';
import { VerificationEditor } from '../verification';
import { getZIndex } from '../../../utils/zIndexUtils';
import { DEFAULT_DEVICE_RESOLUTION } from '../../../config/deviceResolutions';

import { RecordingOverlay, LoadingOverlay, ModeIndicatorDot } from './ScreenEditorOverlay';
import { ScreenshotCapture } from './ScreenshotCapture';
import { HLSVideoPlayer } from '../../common/HLSVideoPlayer';
import { VideoCapture } from './VideoCapture';

interface HDMIStreamProps {
  host: Host;
  deviceId: string;
  deviceModel?: string;
  isControlActive?: boolean;
  userinterfaceName?: string; // Required for saving references - defines the app/UI context
  onCollapsedChange?: (isCollapsed: boolean) => void;
  onExpandedChange?: (isExpanded: boolean) => void;
  onMinimizedChange?: (isMinimized: boolean) => void;
  onCaptureModeChange?: (mode: 'stream' | 'screenshot' | 'video') => void;
  deviceResolution?: { width: number; height: number };
  useAbsolutePositioning?: boolean;
  positionLeft?: string;
  positionBottom?: string;
  sx?: any;
  // NEW: Orientation state for mobile devices
  isLandscape?: boolean;
}

export const HDMIStream = React.memo(
  function HDMIStream({
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
    isLandscape = false,
  }: HDMIStreamProps) {
    // Stream state
    const [isExpanded, setIsExpanded] = useState<boolean>(false);
    const [isMinimized, setIsMinimized] = useState<boolean>(false);
    const [isScreenshotLoading, setIsScreenshotLoading] = useState<boolean>(false);
    // Active verification reference type — text references don't use a fuzzy area,
    // so we disable Shift+drag fuzzy selection on the capture overlay for them.
    const [verificationReferenceType, setVerificationReferenceType] = useState<'image' | 'text'>(
      'image',
    );

    // AV config state
    const [avConfig, setAvConfig] = useState<any>(null);
    
    // Ref to store HLS player restart function
    const hlsRestartRef = useRef<any>(null);

    // Use new stream hook - auto-fetches when host/deviceId changes
    const { streamUrl, isLoadingUrl, urlError } = useStream({ host, device_id: deviceId });
    const isStreamActive = !!streamUrl && !isLoadingUrl;

    // Get device model from device or use override
    const effectiveDeviceModel = useMemo(() => {
      if (deviceModel) return deviceModel;
      const device = host.devices?.find((d) => d.device_id === deviceId);
      return device?.device_model || 'unknown';
    }, [deviceModel, host.devices, deviceId]);

    // Load AV config
    useEffect(() => {
      const loadConfig = async () => {
        const config = await loadAVConfig('hdmi_stream', effectiveDeviceModel);
        setAvConfig(config);
      };

      loadConfig();
    }, [effectiveDeviceModel]);

    // Reset expanded state on mount or when host/deviceId changes (e.g., release and take control)
    useEffect(() => {
      console.log('[@component:HDMIStream] Resetting expanded state (mount or host/device change)');
      setIsExpanded(false);
      setIsMinimized(false);
      // Notify parent that panel is now collapsed
      onCollapsedChange?.(true);
      onMinimizedChange?.(false);
    }, [host, deviceId, onCollapsedChange, onMinimizedChange]);

    // Get configurable layout from AV config - memoized to prevent infinite loops
    const panelLayout = useMemo(() => {
      return getConfigurableAVPanelLayout(avConfig);
    }, [avConfig]);

    // Use the existing hook with our fetched stream data
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
      handleClearSelection,
      handleImageLoad,
      handleTakeScreenshot: hookTakeScreenshot,
      fetchCapturedFrames,
    } = useHdmiStream({
      host,
      deviceId,
      deviceModel: effectiveDeviceModel,
      streamUrl: streamUrl || '', // Handle null by providing empty string fallback
      isStreamActive,
    });

    // Show URL error if stream fetch failed
    useEffect(() => {
      if (urlError) {
        console.error(`[@component:HDMIStream] Stream URL error: ${urlError}`);
      }
    }, [urlError]);

    // Enhanced screenshot handler that updates capture mode
    const handleTakeScreenshot = useCallback(async () => {
      setIsScreenshotLoading(true);
      try {
        // Re-screenshot must NOT reset anything: keep the selected reference
        // area, fuzzy search area, and verification editor state intact so the
        // user can refresh the underlying image without losing their selection.
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
        console.log(`[@component:HDMIStream] Starting video capture`);
        const startTime = new Date();
        setIsCaptureActive(true);
        setRecordingStartTime(startTime);
        setCaptureMode('video');
        onCaptureModeChange?.('video');
        console.log(`[@component:HDMIStream] Recording started at:`, startTime);
      } catch (error) {
        console.error(`[@component:HDMIStream] Error starting capture:`, error);
      }
    }, [setIsCaptureActive, setRecordingStartTime, setCaptureMode, onCaptureModeChange]);

    // Stop video capture
    const handleStopCapture = useCallback(async () => {
      try {
        console.log(`[@component:HDMIStream] Stopping video capture`);
        const endTime = new Date();
        setIsCaptureActive(false);

        // Load the real captured frames recorded between start and stop (the host
        // continuously writes capture_*.jpg ~5fps). fetchCapturedFrames sets
        // videoFrames + totalFrames and resets to frame 1.
        if (recordingStartTime) {
          const recordingDuration = endTime.getTime() - recordingStartTime.getTime();
          console.log(
            `[@component:HDMIStream] Recording duration: ${recordingDuration}ms — loading captured frames`,
          );

          setCaptureStartTime(recordingStartTime);
          setCaptureMode('video'); // Keep showing video component with frames
          await fetchCapturedFrames(recordingStartTime.getTime(), endTime.getTime());
        } else {
          console.warn(`[@component:HDMIStream] No recording start time found`);
          setCaptureMode('stream');
        }
      } catch (error) {
        console.error(`[@component:HDMIStream] Error stopping capture:`, error);
      }
    }, [
      setIsCaptureActive,
      setCaptureStartTime,
      setCaptureMode,
      recordingStartTime,
      fetchCapturedFrames,
    ]);

    // Cap video recording at 30s. The host's hot RAM buffer only holds ~60s of
    // frames (300 @ 5fps) and captures are never archived hot->cold, so a longer
    // recording would lose its early frames before promoteCapturedFrames runs.
    // 30s guarantees the whole clip is still in hot at stop time. Auto-stops; a
    // manual stop flips isCaptureActive false and the cleanup clears the timer.
    useEffect(() => {
      if (!isCaptureActive) return;
      const timer = setTimeout(() => {
        console.log('[@component:HDMIStream] Auto-stopping capture at 30s cap');
        handleStopCapture();
      }, 30000);
      return () => clearTimeout(timer);
    }, [isCaptureActive, handleStopCapture]);

    // Return to stream view and restart stream if needed
    const returnToStream = useCallback(() => {
      console.log(`[@component:HDMIStream] Returning to stream view - restarting stream`);
      // Clear any drawn reference/fuzzy rectangles before leaving capture mode
      handleClearSelection();
      // Reset capture mode to stream (removes screenshot/video capture components)
      setCaptureMode('stream');
      onCaptureModeChange?.('stream');

      // Force restart the stream to ensure it's working
      if (hlsRestartRef.current) {
        console.log(`[@component:HDMIStream] Triggering HLS player restart`);
        hlsRestartRef.current();
      }
    }, [handleClearSelection, setCaptureMode, onCaptureModeChange]);

    // Smart toggle handlers with minimized state logic
    const handleMinimizeToggle = () => {
      if (isMinimized) {
        // Restore from minimized directly to expanded state
        setIsMinimized(false);
        setIsExpanded(true);
        onMinimizedChange?.(false);
        onCollapsedChange?.(false); // Notify parent that panel is now expanded
        console.log(
          `[@component:HDMIStream] Restored from minimized to expanded for ${effectiveDeviceModel}`,
        );
      } else {
        // Minimize the panel
        setIsMinimized(true);
        onMinimizedChange?.(true);
        console.log(`[@component:HDMIStream] Minimized panel for ${effectiveDeviceModel}`);
      }
    };

    const handleExpandCollapseToggle = () => {
      if (isMinimized) {
        // Restore from minimized directly to expanded state
        setIsMinimized(false);
        setIsExpanded(true);
        onMinimizedChange?.(false);
        onCollapsedChange?.(false); // Notify parent that panel is now expanded
        console.log(
          `[@component:HDMIStream] Restored from minimized to expanded for ${effectiveDeviceModel}`,
        );
      } else {
        // Normal expand/collapse logic
        const newExpanded = !isExpanded;
        setIsExpanded(newExpanded);
        onCollapsedChange?.(!newExpanded);
        console.log(
          `[@component:HDMIStream] Toggling panel state to ${newExpanded ? 'expanded' : 'collapsed'} for ${effectiveDeviceModel}`,
        );
      }
    };

    // Handle frame changes in video capture
    const handleFrameChange = useCallback(
      (frame: number) => {
        setCurrentFrame(frame);
      },
      [setCurrentFrame],
    );

    // Use dimensions directly from the loaded config (no device_specific needed)
    const collapsedWidth = panelLayout.collapsed.width;
    const collapsedHeight = panelLayout.collapsed.height;
    const expandedWidth = panelLayout.expanded.width;
    const expandedHeight = panelLayout.expanded.height;

    // Build position styles - simple container without scaling
    const positionStyles: any = {
      position: useAbsolutePositioning ? 'absolute' : 'fixed',
      zIndex: getZIndex('HDMI_STREAM'),
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
      // Don't apply sx here - it will be applied to inner content box
    };
    
    // Extract border/visual styles from sx for inner box
    const contentStyles = sx || {};

    const headerHeight = panelLayout.header?.height || '40px';

    // Calculate panel dimensions based on state and orientation
    const getPanelWidth = () => {
      if (isMinimized) return collapsedWidth;
      
      // For mobile landscape: swap width and height
      if (isMobile && isLandscape) {
        return isExpanded ? expandedHeight : collapsedHeight;
      }
      
      return isExpanded ? expandedWidth : collapsedWidth;
    };

    const getPanelHeight = () => {
      if (isMinimized) return headerHeight;
      
      // For mobile landscape: swap width and height
      if (isMobile && isLandscape) {
        return isExpanded ? expandedWidth : collapsedWidth;
      }
      
      return isExpanded ? expandedHeight : collapsedHeight;
    };

    // Current frame URL = the captured frame at the playback index. videoFrames
    // is populated from the host's capture list when recording stops.
    const currentVideoFramePath = videoFrames[currentFrame]?.url || '';

    // Check if verification editor should be visible
    const isVerificationVisible = captureMode === 'screenshot' || captureMode === 'video';

    // Once recording has stopped and we have captured frames to play back, pause
    // (background) the live HLS stream so it stops loading/playing behind the
    // captured-frames overlay. Without this the live stream keeps running under
    // VideoCapture, competing with the frame playback. returnToStream() flips
    // captureMode back to 'stream' and restarts the player, resuming it.
    const showingCapturedFrames =
      captureMode === 'video' && !isCaptureActive && totalFrames > 0;
    const isStreamPlaying = isStreamActive && !showingCapturedFrames;

    // Compute isMobile from effectiveDeviceModel
    const isMobile = effectiveDeviceModel?.includes('mobile') || effectiveDeviceModel === 'android_mobile';

    return (
      <>
        {/* Main HDMIStream Panel */}
        <Box sx={positionStyles}>
          {/* Inner content container - uses appropriate size for state */}
          <Box
            sx={{
              width: getPanelWidth(),
              height: getPanelHeight(),
              position: 'absolute',
              // Simple positioning - bottom and left anchored
              bottom: 0,
              left: 0,
              backgroundColor: '#1E1E1E',
              // Default discreet white border for all HDMI panels
              border: '1px solid rgba(255, 255, 255, 0.2)',
              borderRadius: isVerificationVisible ? '1px 0 0 1px' : '8px', // Connect to side panel when visible
              overflow: 'hidden',
              transition: 'width 0.3s ease-in-out, height 0.3s ease-in-out',
              ...contentStyles, // Apply custom styles (can override defaults)
            }}
          >
            {/* Header with minimize and expand/collapse buttons */}
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                p: 1,
                height: headerHeight,
                borderBottom: isMinimized ? 'none' : '1px solid #333',
                bgcolor: '#1E1E1E',
                color: '#ffffff',
              }}
            >
              {/* Left side: Action buttons (only visible when expanded and not minimized) */}
              {isExpanded && !isMinimized && (
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

              {/* Center: Title */}
              <Typography
                variant="subtitle2"
                sx={{
                  fontSize: '0.875rem',
                  fontWeight: 'bold',
                  flex: 1,
                  textAlign: 'center',
                }}
              >
                HDMI
              </Typography>

              {/* Right side: Minimize and Expand/Collapse buttons */}
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                {/* Minimize/Restore button */}
                <Tooltip title={isMinimized ? 'Restore Panel' : 'Minimize Panel'}>
                  <IconButton size="small" onClick={handleMinimizeToggle} sx={{ color: 'inherit' }}>
                    {isMinimized ? (
                      <KeyboardArrowUp fontSize="small" />
                    ) : (
                      <KeyboardArrowDown fontSize="small" />
                    )}
                  </IconButton>
                </Tooltip>

                {/* Expand/Collapse button */}
                <Tooltip
                  title={
                    isMinimized ? 'Restore Panel' : isExpanded ? 'Collapse Panel' : 'Expand Panel'
                  }
                >
                  <IconButton
                    size="small"
                    onClick={handleExpandCollapseToggle}
                    sx={{ color: 'inherit' }}
                  >
                    {isExpanded ? (
                      <CloseFullscreen fontSize="small" />
                    ) : (
                      <OpenInFull fontSize="small" />
                    )}
                  </IconButton>
                </Tooltip>
              </Box>
            </Box>

            {/* Stream Content - hidden when minimized */}
            {!isMinimized && (
              <Box
                sx={{
                  height: `calc(100% - ${headerHeight})`, // Subtract header height from total height
                  overflow: 'hidden',
                  position: 'relative',
                }}
              >
                {/* Unified HLS player - consistent with RecHostPreview */}
                <HLSVideoPlayer
                  streamUrl={streamUrl || undefined}
                  isStreamActive={isStreamPlaying}
                  isCapturing={isCaptureActive}
                  model={effectiveDeviceModel}
                  isExpanded={isExpanded}
                  onRestartRequest={hlsRestartRef as any}
                  layoutConfig={{
                    minHeight: isExpanded ? '400px' : '120px',
                    aspectRatio: isMobile
                      ? `${DEFAULT_DEVICE_RESOLUTION.height}/${DEFAULT_DEVICE_RESOLUTION.width}` // Mobile: 9:16
                      : `${DEFAULT_DEVICE_RESOLUTION.width}/${DEFAULT_DEVICE_RESOLUTION.height}`, // TV: 16:9
                    objectFit: isMobile ? 'cover' : 'contain',
                    isMobileModel: isMobile,
                  }}
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
                    onImageLoad={handleImageLoad}
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
                    onImageLoad={handleImageLoad}
                    selectedArea={selectedArea}
                    onAreaSelected={handleAreaSelected}
                    isCapturing={isCaptureActive}
                    videoFramePath={currentVideoFramePath} // Pass current frame URL
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
                {!isExpanded && <ModeIndicatorDot viewMode={captureMode} />}
              </Box>
            )}
          </Box>
        </Box>

        {/* Verification Editor Side Panel - only shown when the panel is expanded (hidden when collapsed or minimized) */}
        {isVerificationVisible && isExpanded && !isMinimized && (
          <Box
            sx={{
              position: useAbsolutePositioning ? 'absolute' : 'fixed',
              zIndex: getZIndex('VERIFICATION_EDITOR'),
              // Position right next to the main panel - must match main panel's positioning logic
              bottom: useAbsolutePositioning
                ? positionBottom || '50px'
                : panelLayout.collapsed.position.bottom || '20px',
              left: useAbsolutePositioning
                ? `calc(${positionLeft || '10px'} + ${getPanelWidth()})`
                : `calc(${panelLayout.collapsed.position.left || '20px'} + ${getPanelWidth()})`,
              width: '400px', // Fixed width for verification editor
              height: getPanelHeight(),
              backgroundColor: '#1E1E1E',
              border: '2px solid #1E1E1E',
              borderLeft: 'none', // No border between panels to make them appear connected
              borderRadius: '0 1px 1px 0', // Round only right side
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
              onClearSelection={handleClearSelection}
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
    // Custom comparison function to prevent unnecessary re-renders
    const hostChanged = JSON.stringify(prevProps.host) !== JSON.stringify(nextProps.host);
    const sxChanged = JSON.stringify(prevProps.sx) !== JSON.stringify(nextProps.sx);
    const onCollapsedChangeChanged = prevProps.onCollapsedChange !== nextProps.onCollapsedChange;
    const onMinimizedChangeChanged = prevProps.onMinimizedChange !== nextProps.onMinimizedChange;
    const onCaptureModeChangeChanged =
      prevProps.onCaptureModeChange !== nextProps.onCaptureModeChange;
    const useAbsolutePositioningChanged = prevProps.useAbsolutePositioning !== nextProps.useAbsolutePositioning;
    const positionLeftChanged = prevProps.positionLeft !== nextProps.positionLeft;
    const positionBottomChanged = prevProps.positionBottom !== nextProps.positionBottom;
    const isLandscapeChanged = prevProps.isLandscape !== nextProps.isLandscape;

    // Only re-render if meaningful props have changed
    const shouldRerender =
      hostChanged ||
      sxChanged ||
      onCollapsedChangeChanged ||
      onMinimizedChangeChanged ||
      onCaptureModeChangeChanged ||
      useAbsolutePositioningChanged ||
      positionLeftChanged ||
      positionBottomChanged ||
      isLandscapeChanged;

    if (shouldRerender) {
      console.log('[@component:HDMIStream] Props changed, re-rendering:', {
        hostChanged,
        sxChanged,
        onCollapsedChangeChanged,
        onMinimizedChangeChanged,
        onCaptureModeChangeChanged,
        useAbsolutePositioningChanged,
        positionLeftChanged,
        positionBottomChanged,
        isLandscapeChanged,
      });
    }

    return !shouldRerender; // Return true to skip re-render, false to re-render
  },
);
