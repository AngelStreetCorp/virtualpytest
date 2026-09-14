/**
 * @deprecated This component is deprecated. Use DeviceControlPanels from 'components/common/DeviceControlPanels' instead.
 * 
 * This file is kept for backward compatibility but should not be used in new code.
 * All functionality has been moved to the shared DeviceControlPanels component.
 */

import React from 'react';
import { Box } from '@mui/material';
import { RemotePanel } from '../../controller/remote/RemotePanel';
import { DesktopPanel } from '../../controller/desktop/DesktopPanel';
import { WebPanel } from '../../controller/web/WebPanel';
import { VNCStream } from '../../controller/av/VNCStream';
import { HDMIStream } from '../../controller/av/HDMIStream';
import { DEFAULT_DEVICE_RESOLUTION } from '../../../config/deviceResolutions';

/**
 * @deprecated Use DeviceControlPanels instead
 */
interface TestCaseBuilderPanelsProps {
  // Show Panel Conditions
  showRemotePanel: boolean;
  showAVPanel: boolean;
  
  // Host & Device
  selectedHost: any;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  userinterfaceName: string;
  
  // AV Panel State
  isAVPanelCollapsed: boolean;
  isAVPanelMinimized: boolean;
  captureMode: 'stream' | 'screenshot' | 'video';
  isVerificationVisible: boolean;
  
  // Layout Control
  isSidebarOpen: boolean;
  footerHeight?: number;
  
  // Handlers
  handleDisconnectComplete: () => void;
  handleAVPanelCollapsedChange: (collapsed: boolean) => void;
  handleAVPanelMinimizedChange: (minimized: boolean) => void;
  handleCaptureModeChange: (mode: 'stream' | 'screenshot' | 'video') => void;
  isMobileOrientationLandscape: boolean;
  handleMobileOrientationChange: (isLandscape: boolean) => void;
}

export const TestCaseBuilderPanels: React.FC<TestCaseBuilderPanelsProps> = ({
  showRemotePanel,
  showAVPanel,
  selectedHost,
  selectedDeviceId,
  isControlActive,
  userinterfaceName,
  isAVPanelCollapsed,
  isAVPanelMinimized,
  captureMode,
  isVerificationVisible,
  isSidebarOpen,
  footerHeight = 40,
  handleDisconnectComplete,
  handleAVPanelCollapsedChange,
  handleAVPanelMinimizedChange,
  handleCaptureModeChange,
  isMobileOrientationLandscape,
  handleMobileOrientationChange,
}) => {
  const selectedDevice = selectedHost?.devices?.find((d: any) => d.device_id === selectedDeviceId);
  const deviceModel = selectedDevice?.device_model;
  const remoteCapability = selectedDevice?.device_capabilities?.remote;
  const hasMultipleRemotes = Array.isArray(remoteCapability) || deviceModel === 'fire_tv';
  const isDesktopDevice = deviceModel === 'host_vnc';

  // Calculate stream position based on sidebar state
  const sidebarWidth = 280; // Width of the sidebar when open (from TestCaseBuilderSidebar.tsx)
  const streamLeftPosition = isSidebarOpen ? `${sidebarWidth + 10}px` : '10px'; // sidebar width + margin

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
              positionBottom={`${footerHeight + 10}px`}
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
              positionBottom={`${footerHeight + 10}px`}
              isLandscape={isMobileOrientationLandscape}
            />
          )}
        </>
      )}
    </>
  );
};

