/**
 * Device Stream Grid Component
 * 
 * Extracted from RunTests.tsx to be shared between script runner and campaign interface.
 * This component displays multiple device streams in a responsive grid layout.
 */

import React, { useState, useEffect } from 'react';
import { Box, Typography, CircularProgress, Button } from '@mui/material';
import { HLSVideoPlayer } from '../HLSVideoPlayer';
import { useStream } from '../../../hooks/controller/useStream';
import { calculateVncScaling } from '../../../utils/vncUtils';

// Component interfaces
export interface DeviceStreamGridProps {
  devices: {hostName: string, deviceId: string}[];
  allHosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
  maxColumns?: number;
  isActive?: boolean; // Add prop to control stream lifecycle
}

interface DeviceStreamItemProps {
  device: {hostName: string, deviceId: string};
  allHosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
  isActive?: boolean; // Add prop to control stream lifecycle
}

// Move previewHeight to top level
const PREVIEW_HEIGHT = 120; // Consistent preview box height
const PREVIEW_HEIGHT_MOBILE = 200; // Max height on mobile

// Individual device stream component
const DeviceStreamItem: React.FC<DeviceStreamItemProps> = ({ device, allHosts, getDevicesFromHost, isActive = true }) => {
  const hostObject = allHosts.find((host) => host.host_name === device.hostName);
  
  // Stream lifecycle management
  const [isStreamActive, setIsStreamActive] = useState(isActive);
  const [isVisible, setIsVisible] = useState(true);
  const effectiveDeviceId = device.deviceId || 'host';
  
  // Use stream hook to get device stream
  const { streamUrl, isLoadingUrl, urlError } = useStream({
    host: hostObject!,
    device_id: effectiveDeviceId,
  });

  // Update stream active state when parent isActive prop changes
  useEffect(() => {
    setIsStreamActive(isActive && isVisible);
  }, [isActive, isVisible]);

  // Cleanup stream when component unmounts
  useEffect(() => {
    return () => {
      console.log(`[@component:DeviceStreamItem] Component unmounting, stopping stream for ${device.hostName}:${device.deviceId}`);
      setIsStreamActive(false);
    };
  }, [device.hostName, device.deviceId]);

  // Get device model
  const deviceObject = getDevicesFromHost(device.hostName).find(
    (d) => d.device_id === effectiveDeviceId
  );
  const deviceModel = deviceObject?.device_model || '';
  const displayLabel = device.deviceId ? `${device.hostName}:${device.deviceId}` : device.hostName;
  const modelLabel = deviceModel && deviceModel !== 'unknown' ? ` (${deviceModel})` : '';
  
  // Check if mobile model for content adaptation
  const isMobileModel = !!(deviceModel && deviceModel.toLowerCase().includes('mobile'));
  
  // Use consistent preview box size like RecHostPreview - fixed height container
  // const previewHeight = 120; // Consistent preview box height

  return (
    <Box
      sx={{
        backgroundColor: 'black',
        borderRadius: 1,
        overflow: 'hidden',
        width: '100%', // Let grid control width, content adapts inside
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {/* Device label */}
      <Box sx={{ px: 1, py: 0.5, backgroundColor: 'rgba(0,0,0,0.8)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 0.5 }}>
        <Typography variant="caption" noWrap>
          {displayLabel}{modelLabel}
        </Typography>
        <Button
          size="small"
          variant="text"
          color="inherit"
          onClick={() => setIsVisible((prev) => !prev)}
          sx={{ minWidth: 56, px: 0.5, py: 0, fontSize: '0.65rem' }}
        >
          {isVisible ? 'Hide' : 'Show'}
        </Button>
      </Box>
      
      {/* Stream content */}
      <Box sx={{ 
        height: { xs: PREVIEW_HEIGHT_MOBILE, sm: PREVIEW_HEIGHT },
        position: 'relative', 
        backgroundColor: 'black',
        overflow: 'hidden', // Ensure content doesn't overflow
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 0,
      }}>
        {!isVisible ? (
          <Typography variant="caption" color="text.secondary">
            Stream hidden
          </Typography>
        ) : streamUrl && hostObject ? (
          // VNC devices: Show iframe, Others: Use HLSVideoPlayer
          deviceModel === 'host_vnc' ? (
            <Box
              sx={{
                position: 'relative',
                width: '100%',
                height: '100%',
                backgroundColor: 'black',
                overflow: 'hidden',
              }}
            >
              <iframe
                src={streamUrl}
                style={{
                  border: 'none',
                  backgroundColor: '#000',
                  pointerEvents: 'none',
                  display: 'block',
                  margin: '0 auto',
                  ...calculateVncScaling({ width: 300, height: PREVIEW_HEIGHT - 24 }), // Subtract label height, use standard preview size
                }}
                title={`VNC Desktop - ${device.hostName}:${device.deviceId}`}
                allow="fullscreen"
              />
            </Box>
          ) : (
            // Absolute fill inside fixed-height container to strictly clamp size
            <Box sx={{ position: 'absolute', inset: 0 }}>
              <HLSVideoPlayer
                streamUrl={streamUrl}
                isStreamActive={isStreamActive}
                isCapturing={false}
                model={deviceModel}
                layoutConfig={{
                  minHeight: '0px',
                  aspectRatio: isMobileModel ? '9/16' : '16/9',
                  objectFit: 'contain',
                  isMobileModel,
                }}
                isExpanded={false}
                muted={true}
                sx={{
                  width: '100%',
                  height: '100%',
                  '& video': {
                    width: '100% !important',
                    height: '100% !important',
                    objectFit: 'contain !important',
                  },
                }}
              />
            </Box>
          )
        ) : (
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'white',
              textAlign: 'center',
              height: '100%',
            }}
          >
            {isLoadingUrl ? (
              <>
                <CircularProgress sx={{ color: 'white', mb: 1 }} size={20} />
                <Typography variant="caption">Loading...</Typography>
              </>
            ) : urlError ? (
              <>
                <Typography color="error" variant="caption" sx={{ mb: 1 }}>
                  Stream Error
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6rem' }}>
                  {urlError}
                </Typography>
              </>
            ) : (
              <Typography variant="caption">No stream available</Typography>
            )}
          </Box>
        )}
      </Box>
    </Box>
  );
};

// Main grid component
export const DeviceStreamGrid: React.FC<DeviceStreamGridProps> = ({ 
  devices, 
  allHosts, 
  getDevicesFromHost,
  maxColumns = 3,
  isActive = true
}) => {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: `repeat(${Math.min(devices.length, maxColumns)}, 1fr)`,
        gap: 2,
        maxWidth: '100%',
        gridAutoRows: { xs: `${PREVIEW_HEIGHT_MOBILE}px`, sm: `${PREVIEW_HEIGHT}px` },
      }}
    >
      {devices.map((device, index) => (
        <DeviceStreamItem
          key={`${device.hostName}-${device.deviceId}-${index}`}
          device={device}
          allHosts={allHosts}
          getDevicesFromHost={getDevicesFromHost}
          isActive={isActive}
        />
      ))}
    </Box>
  );
};
