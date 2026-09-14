import { Box } from '@mui/material';
import React from 'react';

import { DEFAULT_DEVICE_RESOLUTION } from '../../config/deviceResolutions';
import { Host, Device } from '../../types/common/Host_Types';
import { DesktopPanel } from '../controller/desktop/DesktopPanel';
import { RemotePanel } from '../controller/remote/RemotePanel';
import { WebPanel } from '../controller/web/WebPanel';

interface RecPanelManagerProps {
  host: Host;
  device?: Device;
  
  // Panel states
  showRemote: boolean;
  showWeb: boolean;
  
  // Control state
  isControlActive: boolean;
  
  // Device info
  isDesktopDevice: boolean;
  
  // Layout dimensions
  finalStreamContainerDimensions: {
    width: number;
    height: number;
    x: number;
    y: number;
  };
  
  // Callbacks
  onReleaseControl: () => void;
}

export const RecPanelManager: React.FC<RecPanelManagerProps> = ({
  host,
  device,
  showRemote,
  showWeb,
  isControlActive,
  isDesktopDevice,
  finalStreamContainerDimensions,
  onReleaseControl,
}) => {
  const stableDeviceResolution = DEFAULT_DEVICE_RESOLUTION;

  return (
    <>
      {/* Remote Control Panel or Desktop Terminal */}
      {showRemote && isControlActive && (
        <Box
          sx={{
            width: '20%',
            backgroundColor: 'background.default',
            borderLeft: '1px solid',
            borderColor: 'divider',
            overflow: 'auto',
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
          }}
        >
          {isDesktopDevice ? (
            <DesktopPanel
              host={host}
              deviceId={device?.device_id || 'device1'}
              deviceModel={device?.device_model || 'host_vnc'}
              isConnected={isControlActive}
              onReleaseControl={onReleaseControl}
              initialCollapsed={false}
              streamContainerDimensions={finalStreamContainerDimensions}
            />
          ) : (() => {
            // Handle multiple remote controllers
            const remoteCapability = device?.device_capabilities?.remote;
            const hasMultipleRemotes = Array.isArray(remoteCapability) || device?.device_model === 'fire_tv';
            
            if (hasMultipleRemotes && device?.device_model === 'fire_tv') {
              // For Fire TV devices, render both remotes directly (like host VNC)
              // Account for panel overhead: header (30px) only, no disconnect button in modal
              const panelOverhead = 30; // Header only, disconnect button removed in modal
              const availableHeightForRemotes = finalStreamContainerDimensions.height - (panelOverhead * 2); 
              const stackedDimensions = {
                ...finalStreamContainerDimensions,
                height: Math.round(availableHeightForRemotes / 2) + panelOverhead
              };
              return (
                <>
                  <RemotePanel
                    host={host}
                    deviceId={device?.device_id || 'device1'}
                    deviceModel={device?.device_model || 'fire_tv'}
                    remoteType="android_tv"
                    isConnected={isControlActive}
                    onReleaseControl={onReleaseControl}
                    initialCollapsed={false}
                    deviceResolution={stableDeviceResolution}
                    streamCollapsed={false}
                    streamMinimized={false}
                    streamContainerDimensions={stackedDimensions}
                    disableResize={true}
                  />
                  <RemotePanel
                    host={host}
                    deviceId={device?.device_id || 'device1'}
                    deviceModel={device?.device_model || 'fire_tv'}
                    remoteType="ir_remote"
                    isConnected={isControlActive}
                    onReleaseControl={onReleaseControl}
                    initialCollapsed={false}
                    deviceResolution={stableDeviceResolution}
                    streamCollapsed={false}
                    streamMinimized={false}
                    disableResize={true}
                    streamContainerDimensions={stackedDimensions}
                  />
                </>
              );
            } else if (hasMultipleRemotes) {
              // For other devices with multiple remote controllers
              const remoteTypes = Array.isArray(remoteCapability) ? remoteCapability : [remoteCapability];
              const filteredRemoteTypes = remoteTypes.filter(Boolean);
              // Account for panel overhead: header (30px) only, no disconnect button in modal
              const panelOverhead = 30; // Header only, disconnect button removed in modal
              const availableHeightForRemotes = finalStreamContainerDimensions.height - (panelOverhead * filteredRemoteTypes.length);
              const stackedDimensions = {
                ...finalStreamContainerDimensions,
                height: Math.round(availableHeightForRemotes / filteredRemoteTypes.length) + panelOverhead
              };
              return (
                <>
                  {filteredRemoteTypes.map((remoteType: string) => (
                    <RemotePanel
                      key={`${device?.device_id}-${remoteType}`}
                      host={host}
                      deviceId={device?.device_id || 'device1'}
                      deviceModel={device?.device_model || 'unknown'}
                      remoteType={remoteType}
                      isConnected={isControlActive}
                      onReleaseControl={onReleaseControl}
                      initialCollapsed={false}
                      deviceResolution={stableDeviceResolution}
                      streamCollapsed={false}
                      disableResize={true}
                      streamMinimized={false}
                      streamContainerDimensions={stackedDimensions}
                    />
                  ))}
                </>
              );
            } else {
              // Single remote controller
              return (
                <RemotePanel
                  host={host}
                  deviceId={device?.device_id || 'device1'}
                  deviceModel={device?.device_model || 'unknown'}
                  isConnected={isControlActive}
                  onReleaseControl={onReleaseControl}
                  initialCollapsed={false}
                  deviceResolution={stableDeviceResolution}
                  streamCollapsed={false}
                  streamMinimized={false}
                  streamContainerDimensions={finalStreamContainerDimensions}
                  disableResize={true}
                />
              );
            }
          })()}
        </Box>
      )}

      {/* Web Control Panel */}
      {showWeb && isControlActive && isDesktopDevice && (
        <Box
          sx={{
            width: '20%',
            backgroundColor: 'background.default',
            borderLeft: '1px solid',
            borderColor: 'divider',
            overflow: 'auto',
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
          }}
        >
          <WebPanel
            host={host}
            deviceId={device?.device_id || 'device1'}
            deviceModel={device?.device_model || 'host_vnc'}
            isConnected={isControlActive}
            onReleaseControl={onReleaseControl}
            initialCollapsed={false}
            streamContainerDimensions={finalStreamContainerDimensions}
          />
        </Box>
      )}
    </>
  );
};
