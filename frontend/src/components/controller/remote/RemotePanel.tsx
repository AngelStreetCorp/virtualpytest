import {
  OpenInFull,
  CloseFullscreen,
  KeyboardArrowDown,
  KeyboardArrowUp,
} from '@mui/icons-material';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import React, { useState, useEffect, useMemo } from 'react';

import { DEFAULT_DEVICE_RESOLUTION } from '../../../config/deviceResolutions';
import { getConfigurableRemotePanelLayout, loadRemoteConfig } from '../../../config/remote';
import { Host } from '../../../types/common/Host_Types';

import { AndroidMobileRemote } from './AndroidMobileRemote';
import { AndroidTvRemote } from './AndroidTvRemote';
import { AppiumRemote } from './AppiumRemote';
import { BluetoothRemote } from './BluetoothRemote';
import { InfraredRemote } from './InfraredRemote';

const getRemoteRelevantHostState = (host?: Host, deviceId?: string, remoteType?: string) => {
  const device = host?.devices?.find((d) => d.device_id === deviceId);

  return {
    host_name: host?.host_name ?? null,
    host_status: host?.status ?? null,
    device_id: device?.device_id ?? null,
    device_name: device?.device_name ?? null,
    device_model: device?.device_model ?? null,
    ir_type: device?.ir_type ?? null,
    remote_capability: device?.device_capabilities?.remote ?? null,
    remote_type: remoteType ?? null,
  };
};

interface RemotePanelProps {
  host?: Host;
  deviceId?: string; // Device ID to select the correct device and controllers
  deviceModel?: string; // Device model for remote config loading
  isConnected?: boolean; // NEW: Connection status from parent
  onReleaseControl?: () => void;
  initialCollapsed?: boolean;
  // Device resolution for overlay scaling
  deviceResolution?: { width: number; height: number };
  // Stream collapsed state for overlay coordination
  streamCollapsed?: boolean;
  // Stream minimized state for overlay coordination
  streamMinimized?: boolean;
  // Stream hidden state for overlay coordination
  streamHidden?: boolean;
  
  // Alternative props for DeviceManagement usage
  remoteType?: string;
  connectionConfig?: any;
  showScreenshot?: boolean;
  // Current capture mode from HDMIStream
  captureMode?: 'stream' | 'screenshot' | 'video';
  // Verification editor visibility state - hides overlay when verification editor is shown
  isVerificationVisible?: boolean;
  // Navigation editor context - positions overlay at bottom left of viewport
  isNavigationEditorContext?: boolean;
  // NEW: Stream container dimensions for modal context
  streamContainerDimensions?: {
    width: number;
    height: number;
    x: number;
    y: number;
  };
  // NEW: Disable resize controls (for recording modal)
  disableResize?: boolean;
  useAbsolutePositioning?: boolean;
  positionLeft?: string;
  positionBottom?: string;
  positionRight?: string;
  // NEW: Dynamic stream position for overlay alignment
  streamPositionLeft?: string;
  streamPositionBottom?: string;
  // NEW: Orientation change callback for mobile devices
  onOrientationChange?: (isLandscape: boolean) => void;
  // NEW: Control overlay visibility from parent
  showOverlay?: boolean;
}

export const RemotePanel = React.memo(
  function RemotePanel({
    host,
    deviceId,
    deviceModel,
    remoteType, // Specific remote type to use
    isConnected,
    onReleaseControl,
    initialCollapsed = true,
    deviceResolution,
    streamCollapsed = true,
    streamMinimized = false,
    streamHidden = false,
    captureMode = 'stream',
    isVerificationVisible = false,
    streamContainerDimensions,
    disableResize = false,
    useAbsolutePositioning = false,
    positionLeft,
    positionBottom,
    positionRight,
    streamPositionLeft,
    streamPositionBottom,
    onOrientationChange,
    showOverlay = true,
  }: RemotePanelProps) {
    // Panel state - three states: expanded, collapsed, minimized
    // Force expanded state when disableResize is true
    const [isCollapsed, setIsCollapsed] = useState(disableResize ? false : initialCollapsed);
    const [isMinimized, setIsMinimized] = useState(disableResize ? false : false);
    const [remoteConfig, setRemoteConfig] = useState<any>(null);
    const selectedDevice = useMemo(
      () => host?.devices?.find((d) => d.device_id === deviceId),
      [host?.devices, deviceId],
    );

    // Load remote config for the device type
    useEffect(() => {
      const loadConfig = async () => {
        if (host && deviceId) {
          const remoteCapability = selectedDevice?.device_capabilities?.remote;
          
          // Handle both single remote type (string) and multiple remote types (array)
          let configType = remoteType || remoteCapability || deviceModel;
          
          // If remoteType is explicitly provided, use it (for multi-remote devices)
          if (remoteType) {
            configType = remoteType;
            console.log(`[@component:RemotePanel] Using explicit remoteType: ${remoteType}`);
          } else if (Array.isArray(remoteCapability)) {
            // If remoteCapability is an array, use the first one for this panel
            // (Multiple RemotePanel components will be rendered for each type)
            configType = remoteCapability[0];
            console.log(`[@component:RemotePanel] Multiple remote types detected: ${remoteCapability.join(', ')}, using: ${configType}`);
          }
          
          if (configType) {
            // For IR remotes, we need to get the IR type from device
            let irType = undefined;
            if (configType === 'ir_remote' && selectedDevice?.ir_type) {
              irType = selectedDevice.ir_type;
            }
            
            const config = await loadRemoteConfig(configType, irType);
            setRemoteConfig(config);
          }
        }
      };

      loadConfig();
    }, [host, deviceId, deviceModel, remoteType, selectedDevice]);

    // Get configurable layout from device config - memoized to prevent infinite loops
    const panelLayout = useMemo(() => {
      if (host && deviceId) {
        const remoteCapability = selectedDevice?.device_capabilities?.remote;
        
        // Use remote capability if available, otherwise fall back to device model
        const configType = remoteCapability || deviceModel;

        return getConfigurableRemotePanelLayout(configType, remoteConfig);
      }
      return getConfigurableRemotePanelLayout(deviceModel, remoteConfig);
    }, [host, deviceId, deviceModel, remoteConfig, selectedDevice]);

    // BLE status indicator rendered in the panel header next to the title.
    // BluetoothRemote publishes its dot color via the onBluetoothStatusChange
    // callback when the bluetooth_remote branch renders below. null means
    // "no BLE remote active" — we render nothing. This is slightly coupled
    // to one specific child but it avoids duplicating useBluetoothRemote's
    // D-Bus polling in two places.
    const [bleDotColor, setBleDotColor] = useState<string | null>(null);
    const [bleDotTooltip, setBleDotTooltip] = useState<string>('');

    // Calculate dimensions inline - no state, no useEffects
    const collapsedWidth = panelLayout.collapsed.width;
    const collapsedHeight = panelLayout.collapsed.height;
    const expandedWidth = panelLayout.expanded.width;
    const expandedHeight = panelLayout.expanded.height;
    const headerHeight = remoteConfig?.panel_layout?.header?.height || '30px';

    // Current panel dimensions based on state
    const currentWidth = isCollapsed ? collapsedWidth : expandedWidth;
    const currentHeight = isMinimized
      ? headerHeight
      : isCollapsed
        ? collapsedHeight
        : expandedHeight;

    // Smart toggle handlers with minimized state logic
    const handleMinimizeToggle = () => {
      // Prevent resizing when disableResize is true
      if (disableResize) {
        console.log(`[@component:RemotePanel] Resize disabled for ${deviceModel} (recording mode)`);
        return;
      }
      
      if (isMinimized) {
        // Restore from minimized to collapsed state
        setIsMinimized(false);
        setIsCollapsed(true);
        console.log(
          `[@component:RemotePanel] Restored from minimized to collapsed for ${deviceModel}`,
        );
      } else {
        // Minimize the panel
        setIsMinimized(true);
        console.log(`[@component:RemotePanel] Minimized panel for ${deviceModel}`);
      }
    };

    const handleExpandCollapseToggle = () => {
      // Prevent resizing when disableResize is true
      if (disableResize) {
        console.log(`[@component:RemotePanel] Resize disabled for ${deviceModel} (recording mode)`);
        return;
      }
      
      if (isMinimized) {
        // First restore from minimized to collapsed, then user can click again to expand
        setIsMinimized(false);
        setIsCollapsed(true);
        console.log(
          `[@component:RemotePanel] Restored from minimized to collapsed for ${deviceModel}`,
        );
      } else {
        // Normal expand/collapse logic
        setIsCollapsed(!isCollapsed);
        console.log(
          `[@component:RemotePanel] Toggling panel state to ${!isCollapsed ? 'collapsed' : 'expanded'} for ${deviceModel}`,
        );
      }
    };

    // Build position styles - detect modal context
    const positionStyles: any = streamContainerDimensions
      ? {
          // Modal context: use relative positioning within the modal container
          position: 'relative',
          width: '100%',
          height: '100%',
        }
      : {
          // Floating panel context: use fixed or absolute based on prop
          position: useAbsolutePositioning ? 'absolute' : 'fixed',
          zIndex: panelLayout.zIndex,
          // Use provided position props or fall back to config values
          ...(useAbsolutePositioning
            ? {
                bottom: positionBottom || '50px',
                right: positionRight || '10px',
                ...(positionLeft && { left: positionLeft, right: 'auto' }),
              }
            : {
                bottom: panelLayout.collapsed.position.bottom || '20px',
                right: panelLayout.collapsed.position.right || '20px',
              }),
          transition: 'left 0.3s ease, right 0.3s ease, bottom 0.3s ease',
        };

    // Simple device model detection - no loading, no fallback, no validation
    const effectiveDeviceResolution = useMemo(() => {
      return deviceResolution || DEFAULT_DEVICE_RESOLUTION;
    }, [deviceResolution]);

    // Create stable reference for streamContainerDimensions to prevent unnecessary re-renders
    const stableStreamContainerDimensions = useMemo(() => {
      return streamContainerDimensions;
    }, [streamContainerDimensions]);

    const renderRemoteComponent = useMemo(() => {
      if (!host || !deviceId) {
        return (
          <Box sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="textSecondary">
              Remote controller requires host and device configuration
            </Typography>
          </Box>
        );
      }

      // Find the device and get its remote capability
      const remoteCapability = selectedDevice?.device_capabilities?.remote;
      
      // Use remote capability if available, otherwise fall back to device model
      const finalRemoteType = remoteType || remoteCapability || deviceModel;
      switch (finalRemoteType) {
        case 'android_mobile':
        case 'phone_agent': // paired phone (features/mobile-app): same tap/dump/apps surface
          return (
            <AndroidMobileRemote
              host={host}
              deviceId={deviceId}
              onDisconnectComplete={onReleaseControl}
              isCollapsed={isCollapsed}
              panelWidth={currentWidth}
              panelHeight={currentHeight}
              deviceResolution={effectiveDeviceResolution}
              streamCollapsed={streamCollapsed}
              streamMinimized={streamMinimized}
              streamHidden={streamHidden}
              captureMode={captureMode}
              isVerificationVisible={isVerificationVisible}
              streamContainerDimensions={stableStreamContainerDimensions}
              streamPositionLeft={streamPositionLeft}
              streamPositionBottom={streamPositionBottom}
              onOrientationChange={onOrientationChange}
              showOverlay={showOverlay}
              sx={{
                height: '100%',
                '& .MuiButton-root': {
                  fontSize: isCollapsed ? '0.7rem' : '0.875rem',
                },
              }}
            />
          );
        case 'android_tv':
          return (
            <AndroidTvRemote
              host={host}
              deviceId={deviceId}
              isConnected={isConnected}
              isCollapsed={isCollapsed}
              streamContainerDimensions={stableStreamContainerDimensions}
              sx={{
                height: '100%',
                '& .MuiButton-root': {
                  fontSize: isCollapsed ? '0.6rem' : '0.7rem',
                },
              }}
            />
          );
        case 'ir_remote':
          return (
            <InfraredRemote
              host={host}
              deviceId={deviceId}
              isConnected={isConnected}
              isCollapsed={isCollapsed}
              streamContainerDimensions={stableStreamContainerDimensions}
              onStatusChange={(color, tooltip) => {
                setBleDotColor(color);
                setBleDotTooltip(tooltip);
              }}
              sx={{
                height: '100%',
                '& .MuiButton-root': {
                  fontSize: isCollapsed ? '0.6rem' : '0.7rem',
                },
              }}
            />
          );
        case 'bluetooth_remote':
          return (
            <BluetoothRemote
              host={host}
              deviceId={deviceId}
              isConnected={isConnected}
              isCollapsed={isCollapsed}
              streamContainerDimensions={stableStreamContainerDimensions}
              onStatusChange={(color, tooltip) => {
                setBleDotColor(color);
                setBleDotTooltip(tooltip);
              }}
              sx={{
                height: '100%',
                '& .MuiButton-root': {
                  fontSize: isCollapsed ? '0.6rem' : '0.7rem',
                },
              }}
            />
          );
        case 'ios_mobile':
        case 'appium': // what a device reports when its remote is an Appium one
        case 'cloud_ios_mobile': // features/device-farm: same panel, session in the farm
        case 'cloud_android_mobile':
          return (
            <AppiumRemote
              host={host}
              deviceId={deviceId}
              onDisconnectComplete={onReleaseControl}
              isCollapsed={isCollapsed}
              panelWidth={currentWidth}
              panelHeight={currentHeight}
              deviceResolution={effectiveDeviceResolution}
              streamCollapsed={streamCollapsed}
              streamMinimized={streamMinimized}
              streamHidden={streamHidden}
              captureMode={captureMode}
              sx={{
                height: '100%',
                '& .MuiButton-root': {
                  fontSize: isCollapsed ? '0.7rem' : '0.875rem',
                },
              }}
            />
          );

        default:
          return (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                p: 2,
              }}
            >
              <Typography variant="body2" color="textSecondary" textAlign="center">
                Unsupported device: {deviceModel}
              </Typography>
            </Box>
          );
      }
    }, [
      host,
      deviceId,
      deviceModel,
      remoteType,
      isConnected,
      onReleaseControl,
      isCollapsed,
      currentWidth,
      currentHeight,
      effectiveDeviceResolution,
      streamCollapsed,
      streamMinimized,
      streamHidden,
      captureMode,
      isVerificationVisible,
      stableStreamContainerDimensions,
      selectedDevice,
      // Ensure overlay re-renders when sidebar-driven positions change
      streamPositionLeft,
      streamPositionBottom,
      // Orientation callback for mobile devices
      onOrientationChange,
    ]);

    return (
      <Box sx={positionStyles}>
        {/* Inner content container - uses appropriate size for state */}
        <Box
          sx={{
            width: streamContainerDimensions ? '100%' : currentWidth,
            height: streamContainerDimensions ? '100%' : currentHeight,
            position: streamContainerDimensions ? 'relative' : 'absolute',
            // Simple positioning - bottom and right anchored (only for floating panels)
            ...(streamContainerDimensions
              ? {}
              : {
                  bottom: 0,
                  right: 0,
                }),
            backgroundColor: 'background.paper',
            border: streamContainerDimensions ? 'none' : '1px solid',
            borderColor: 'divider',
            borderRadius: streamContainerDimensions ? 0 : 1,
            boxShadow: streamContainerDimensions ? 'none' : 3,
            overflow: 'hidden',
            transition: streamContainerDimensions
              ? 'none'
              : 'width 0.3s ease-in-out, height 0.3s ease-in-out',
          }}
        >
          {/* Header with minimize and expand/collapse buttons */}
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              px: 0.5,
              py: parseInt(remoteConfig?.panel_layout?.header?.padding || '8px') / 8,
              height: headerHeight,
              borderBottom: isMinimized
                ? 'none'
                : `1px solid ${remoteConfig?.panel_layout?.header?.borderColor || '#333'}`,
              bgcolor: remoteConfig?.panel_layout?.header?.backgroundColor || '#1E1E1E',
              color: remoteConfig?.panel_layout?.header?.textColor || '#ffffff',
            }}
          >
            {/* Center: Title + optional BLE status dot */}
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 0.75,
                flex: 1,
              }}
            >
              <Typography
                variant="subtitle2"
                sx={{
                  fontSize: remoteConfig?.panel_layout?.header?.fontSize || '0.875rem',
                  fontWeight: remoteConfig?.panel_layout?.header?.fontWeight || 'bold',
                  textAlign: 'center',
                }}
              >
                {remoteConfig?.remote_info?.name || `${deviceModel} Remote`}
              </Typography>
              {bleDotColor && (
                <Tooltip title={bleDotTooltip} placement="bottom">
                  <Box
                    sx={{
                      width: 10,
                      height: 10,
                      borderRadius: '50%',
                      bgcolor: bleDotColor,
                      boxShadow: `0 0 4px ${bleDotColor}`,
                      border: '1px solid rgba(0,0,0,0.4)',
                      flexShrink: 0,
                    }}
                  />
                </Tooltip>
              )}
            </Box>

            {/* Right side: Minimize and Expand/Collapse buttons - hidden when disableResize is true */}
            {!disableResize && (
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                {/* Minimize/Restore button */}
                <Tooltip title={isMinimized ? 'Restore Panel' : 'Minimize Panel'}>
                  <IconButton
                    size={remoteConfig?.panel_layout?.header?.iconSize || 'small'}
                    onClick={handleMinimizeToggle}
                    sx={{ color: 'inherit', p: 0.25 }}
                  >
                    {isMinimized ? (
                      <KeyboardArrowUp
                        fontSize={remoteConfig?.panel_layout?.header?.iconSize || 'small'}
                      />
                    ) : (
                      <KeyboardArrowDown
                        fontSize={remoteConfig?.panel_layout?.header?.iconSize || 'small'}
                      />
                    )}
                  </IconButton>
                </Tooltip>

                {/* Expand/Collapse button */}
                <Tooltip
                  title={
                    isMinimized ? 'Restore Panel' : isCollapsed ? 'Expand Panel' : 'Collapse Panel'
                  }
                >
                  <IconButton
                    size={remoteConfig?.panel_layout?.header?.iconSize || 'small'}
                    onClick={handleExpandCollapseToggle}
                    sx={{ color: 'inherit', p: 0.25 }}
                  >
                    {isCollapsed ? (
                      <OpenInFull sx={{ fontSize: 14 }} />
                    ) : (
                      <CloseFullscreen sx={{ fontSize: 14 }} />
                    )}
                  </IconButton>
                </Tooltip>
              </Box>
            )}
          </Box>

          {/* Remote Content - hidden when minimized */}
          {!isMinimized && (
            <Box
              sx={{
                height: `calc(100% - ${headerHeight})`,
                overflow: 'hidden',
              }}
            >
              {renderRemoteComponent}
            </Box>
          )}
        </Box>
      </Box>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison function to prevent unnecessary re-renders
    // Only re-render if meaningful props have changed
    const hostChanged =
      JSON.stringify(
        getRemoteRelevantHostState(prevProps.host, prevProps.deviceId, prevProps.remoteType),
      ) !==
      JSON.stringify(
        getRemoteRelevantHostState(nextProps.host, nextProps.deviceId, nextProps.remoteType),
      );
    const deviceIdChanged = prevProps.deviceId !== nextProps.deviceId;
    const deviceModelChanged = prevProps.deviceModel !== nextProps.deviceModel;
    const remoteTypeChanged = prevProps.remoteType !== nextProps.remoteType;
    const deviceResolutionChanged =
      JSON.stringify(prevProps.deviceResolution) !== JSON.stringify(nextProps.deviceResolution);
    const initialCollapsedChanged = prevProps.initialCollapsed !== nextProps.initialCollapsed;
    const streamCollapsedChanged = prevProps.streamCollapsed !== nextProps.streamCollapsed;
    const streamMinimizedChanged = prevProps.streamMinimized !== nextProps.streamMinimized;
    const captureModeChanged = prevProps.captureMode !== nextProps.captureMode;
    const onReleaseControlChanged = prevProps.onReleaseControl !== nextProps.onReleaseControl;
    const streamContainerDimensionsChanged =
      JSON.stringify(prevProps.streamContainerDimensions) !==
      JSON.stringify(nextProps.streamContainerDimensions);
    const disableResizeChanged = prevProps.disableResize !== nextProps.disableResize;
    const useAbsolutePositioningChanged = prevProps.useAbsolutePositioning !== nextProps.useAbsolutePositioning;
    // Track dynamic stream alignment props so overlay moves when sidebar toggles
    const streamPositionLeftChanged = prevProps.streamPositionLeft !== nextProps.streamPositionLeft;
    const streamPositionBottomChanged = prevProps.streamPositionBottom !== nextProps.streamPositionBottom;
    const showOverlayChanged = prevProps.showOverlay !== nextProps.showOverlay;

    // Return true if props are equal (don't re-render), false if they changed (re-render)
    const shouldSkipRender =
      !hostChanged &&
      !deviceIdChanged &&
      !deviceModelChanged &&
      !remoteTypeChanged &&
      !deviceResolutionChanged &&
      !initialCollapsedChanged &&
      !streamCollapsedChanged &&
      !streamMinimizedChanged &&
      !captureModeChanged &&
      !onReleaseControlChanged &&
      !streamContainerDimensionsChanged &&
      !disableResizeChanged &&
      !useAbsolutePositioningChanged &&
      !streamPositionLeftChanged &&
      !streamPositionBottomChanged &&
      !showOverlayChanged;

    return shouldSkipRender;
  },
);
