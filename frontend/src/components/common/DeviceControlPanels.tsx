/**
 * Device Control Panels (Shared Component)
 * 
 * Displays device control panels (Remote/Desktop/VNC/HDMI) based on device type.
 * Used by both TestCaseBuilder and AgentChat for consistent device control UI.
 * 
 * Automatically shows/hides based on:
 * - showRemotePanel: Remote control panels visibility
 * - showAVPanel: AV stream panels visibility
 * - isControlActive: Device control state
 */

import React from 'react';
import { Box } from '@mui/material';
import { RemotePanel } from '../controller/remote/RemotePanel';
import { DesktopPanel } from '../controller/desktop/DesktopPanel';
import { WebPanel } from '../controller/web/WebPanel';
import { VNCStream } from '../controller/av/VNCStream';
import { HDMIStream } from '../controller/av/HDMIStream';
import { DEFAULT_DEVICE_RESOLUTION } from '../../config/deviceResolutions';

interface DeviceControlPanelsProps {
  // Show Panel Conditions
  showRemotePanel: boolean;
  showAVPanel: boolean;
  
  // Host & Device
  selectedHost: any;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  userinterfaceName?: string; // Optional - only needed for AV panels
  
  // AV Panel State (optional - defaults provided)
  isAVPanelCollapsed?: boolean;
  isAVPanelMinimized?: boolean;
  captureMode?: 'stream' | 'screenshot' | 'video';
  isVerificationVisible?: boolean;
  
  // Layout Control (optional - defaults provided)
  isSidebarOpen?: boolean;
  footerHeight?: number;
  
  // 🆕 NEW: Custom Positioning (optional - overrides default positioning)
  customPosition?: {
    left?: string;
    right?: string;
    top?: string;
    bottom?: string;
  };
  
  // 🆕 NEW: Custom Styles (optional - for AV panel styling)
  avPanelSx?: any;
  
  // Handlers
  handleDisconnectComplete: () => void;
  handleAVPanelCollapsedChange?: (collapsed: boolean) => void;
  handleAVPanelMinimizedChange?: (minimized: boolean) => void;
  handleCaptureModeChange?: (mode: 'stream' | 'screenshot' | 'video') => void;
  isMobileOrientationLandscape?: boolean;
  handleMobileOrientationChange?: (isLandscape: boolean) => void;
}

export const DeviceControlPanels: React.FC<DeviceControlPanelsProps> = ({
  showRemotePanel,
  showAVPanel,
  selectedHost,
  selectedDeviceId,
  isControlActive,
  userinterfaceName = '',
  isAVPanelCollapsed = true,
  isAVPanelMinimized = false,
  captureMode = 'stream',
  isVerificationVisible = false,
  isSidebarOpen = true,
  footerHeight = 40,
  customPosition, // 🆕 NEW: Custom positioning
  avPanelSx, // 🆕 NEW: Custom AV panel styles
  handleDisconnectComplete,
  handleAVPanelCollapsedChange = () => {},
  handleAVPanelMinimizedChange = () => {},
  handleCaptureModeChange = () => {},
  isMobileOrientationLandscape = false,
  handleMobileOrientationChange = () => {},
}) => {
  const selectedDevice = selectedHost?.devices?.find((d: any) => d.device_id === selectedDeviceId);
  const deviceModel = selectedDevice?.device_model;
  const remoteCapability = selectedDevice?.device_capabilities?.remote;
  const hasMultipleRemotes = Array.isArray(remoteCapability) || deviceModel === 'fire_tv';
  const isDesktopDevice = deviceModel === 'host_vnc';

  // Calculate stream position based on sidebar state OR use custom position
  const sidebarWidth = 280; // Width of the sidebar when open
  const defaultStreamLeft = isSidebarOpen ? `${sidebarWidth + 10}px` : '10px';
  const streamLeftPosition = customPosition?.left || defaultStreamLeft;
  const streamBottomPosition = customPosition?.bottom || `${footerHeight + 10}px`;

  return (
    <>
      {/* Remote/Desktop Panel */}
      {showRemotePanel && selectedHost && selectedDeviceId && isControlActive && (
        <>
          {isDesktopDevice ? (
            // Desktop device: DesktopPanel + WebPanel
            <>
              <DesktopPanel
                host={selectedHost}
                deviceId={selectedDeviceId}
                deviceModel={deviceModel || 'host_vnc'}
                isConnected={isControlActive}
                onReleaseControl={handleDisconnectComplete}
                initialCollapsed={true}
                useAbsolutePositioning={true}
                positionRight="440px"
                positionBottom={`${footerHeight + 10}px`}
              />
              <WebPanel
                host={selectedHost}
                deviceId={selectedDeviceId}
                deviceModel={deviceModel || 'host_vnc'}
                isConnected={isControlActive}
                onReleaseControl={handleDisconnectComplete}
                initialCollapsed={true}
                useAbsolutePositioning={true}
                positionRight="10px"
                positionBottom={`${footerHeight + 10}px`}
              />
            </>
          ) : hasMultipleRemotes && deviceModel === 'fire_tv' ? (
            // Fire TV: AndroidTvRemote + InfraredRemote
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'row',
                gap: 2,
                position: 'absolute',
                right: 10,
                bottom: 20,
                zIndex: 1000,
                height: 'auto',
              }}
            >
              <RemotePanel
                host={selectedHost}
                deviceId={selectedDeviceId}
                deviceModel={deviceModel || 'fire_tv'}
                remoteType="android_tv"
                isConnected={isControlActive}
                onReleaseControl={handleDisconnectComplete}
                deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                streamCollapsed={isAVPanelCollapsed}
                streamMinimized={isAVPanelMinimized}
                streamHidden={showAVPanel}
                captureMode={captureMode}
                initialCollapsed={true}
                useAbsolutePositioning={true}
              />
              <RemotePanel
                host={selectedHost}
                deviceId={selectedDeviceId}
                deviceModel={deviceModel || 'fire_tv'}
                remoteType="ir_remote"
                isConnected={isControlActive}
                onReleaseControl={handleDisconnectComplete}
                deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                streamCollapsed={isAVPanelCollapsed}
                streamMinimized={isAVPanelMinimized}
                streamHidden={showAVPanel}
                captureMode={captureMode}
                initialCollapsed={true}
                useAbsolutePositioning={true}
              />
            </Box>
          ) : hasMultipleRemotes ? (
            // Other devices with multiple remotes
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'row',
                gap: 2,
                position: 'absolute',
                right: 10,
                bottom: 20,
                zIndex: 1000,
                height: 'auto',
              }}
            >
              {((Array.isArray(remoteCapability) ? remoteCapability : [remoteCapability]) as string[])
                .filter(Boolean)
                .map((remoteType: string, index: number) => (
                  <RemotePanel
                    key={`${selectedDeviceId}-${remoteType}`}
                    host={selectedHost}
                    deviceId={selectedDeviceId}
                    deviceModel={deviceModel || 'unknown'}
                    remoteType={remoteType}
                    isConnected={isControlActive}
                    onReleaseControl={handleDisconnectComplete}
                    deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                    streamCollapsed={isAVPanelCollapsed}
                    streamMinimized={isAVPanelMinimized}
                    captureMode={captureMode}
                    initialCollapsed={index > 0}
                    useAbsolutePositioning={true}
                  />
                ))}
            </Box>
          ) : (
            // Single remote device
            <RemotePanel
              host={selectedHost}
              deviceId={selectedDeviceId}
              deviceModel={deviceModel || 'unknown'}
              isConnected={isControlActive}
              onReleaseControl={handleDisconnectComplete}
              deviceResolution={DEFAULT_DEVICE_RESOLUTION}
              streamCollapsed={isAVPanelCollapsed}
              streamMinimized={isAVPanelMinimized}
              captureMode={captureMode}
              isVerificationVisible={isVerificationVisible}
              isNavigationEditorContext={false}
              useAbsolutePositioning={true}
              positionRight="10px"
              positionBottom={`${footerHeight + 10}px`}
              streamPositionLeft={streamLeftPosition}
              streamPositionBottom={`${footerHeight + 10}px`}
              onOrientationChange={handleMobileOrientationChange}
            />
          )}
        </>
      )}

      {/* AV Panel */}
      {showAVPanel && selectedHost && selectedDeviceId && (
        <>
          {deviceModel === 'host_vnc' ? (
            <VNCStream
              host={selectedHost}
              deviceId={selectedDeviceId}
              deviceModel={deviceModel}
              isControlActive={isControlActive}
              userinterfaceName={userinterfaceName}
              onCollapsedChange={handleAVPanelCollapsedChange}
              onMinimizedChange={handleAVPanelMinimizedChange}
              onCaptureModeChange={handleCaptureModeChange}
              useAbsolutePositioning={true}
              positionLeft={streamLeftPosition}
              positionBottom={streamBottomPosition}
              sx={avPanelSx}
            />
          ) : (
            <HDMIStream
              host={selectedHost}
              deviceId={selectedDeviceId}
              deviceModel={deviceModel}
              isControlActive={isControlActive}
              userinterfaceName={userinterfaceName}
              onCollapsedChange={handleAVPanelCollapsedChange}
              onMinimizedChange={handleAVPanelMinimizedChange}
              onCaptureModeChange={handleCaptureModeChange}
              deviceResolution={DEFAULT_DEVICE_RESOLUTION}
              useAbsolutePositioning={true}
              positionLeft={streamLeftPosition}
              positionBottom={streamBottomPosition}
              isLandscape={isMobileOrientationLandscape}
              sx={avPanelSx}
            />
          )}
        </>
      )}
    </>
  );
};

