/**
 * Device Stream Grid Component
 * 
 * Extracted from RunTests.tsx to be shared between script runner and campaign interface.
 * This component displays multiple device streams in a responsive grid layout.
 */

import React from 'react';
import { Box, Typography, CircularProgress, Button } from '@mui/material';
import { HLSVideoPlayer } from './HLSVideoPlayer';
import { useStream } from '../../hooks/controller/useStream';
import { calculateVncScaling } from '../../utils/vncUtils';

// Component interfaces
export interface DeviceStreamGridProps {
  devices: {hostName: string, deviceId: string}[];
  allHosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
  maxColumns?: number;
}

interface DeviceStreamItemProps {
  device: {hostName: string, deviceId: string};
  allHosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
}

// Individual device stream component
const DeviceStreamItem: React.FC<DeviceStreamItemProps> = ({ device, allHosts, getDevicesFromHost }) => {
  const hostObject = allHosts.find((host) => host.host_name === device.hostName);
  const [isVisible, setIsVisible] = React.useState(true);
  const effectiveDeviceId = device.deviceId || 'host';
  
  // Use stream hook to get device stream
  const { streamUrl, isLoadingUrl, urlError } = useStream({
    host: hostObject!,
    device_id: effectiveDeviceId,
  });

  // Get device model
  const deviceObject = getDevicesFromHost(device.hostName).find(
    (d) => d.device_id === effectiveDeviceId
  );
  const deviceModel = deviceObject?.device_model || '';
  const displayLabel = device.deviceId ? `${device.hostName}:${device.deviceId}` : device.hostName;
  const modelLabel = deviceModel && deviceModel !== 'unknown' ? ` (${deviceModel})` : '';
  
  // Check if mobile model for sizing
  const isMobileModel = !!(deviceModel && deviceModel.toLowerCase().includes('mobile'));
  
  // Calculate sizes for grid layout - let aspect ratio determine height
  const streamWidth = 320; // Fixed width, let height be determined by aspect ratio
  const streamHeight = isMobileModel ? Math.round(streamWidth * (16/9)) : Math.round(streamWidth * (9/16));

  return (
    <Box
      sx={{
        backgroundColor: 'black',
        borderRadius: 1,
        overflow: 'hidden',
        width: streamWidth,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        maxHeight: { xs: 200, sm: 'none' },
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
        position: 'relative', 
        backgroundColor: 'black',
        overflow: 'hidden', // Ensure content doesn't overflow
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        aspectRatio: isMobileModel ? '9/16' : '16/9', // Let CSS handle aspect ratio
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
                  ...calculateVncScaling({ width: streamWidth, height: streamHeight - 24 }), // Subtract label height
                }}
                title={`VNC Desktop - ${device.hostName}:${device.deviceId}`}
                allow="fullscreen"
              />
            </Box>
          ) : (
            <HLSVideoPlayer
              streamUrl={streamUrl}
              isStreamActive={isVisible}
              isCapturing={false}
              model={deviceModel}
              layoutConfig={{
                minHeight: '180px',
                aspectRatio: isMobileModel ? '9/16' : '16/9',
                objectFit: 'contain', // Prevent cropping like RecHostStreamModal
                isMobileModel,
              }}
              isExpanded={false}
              muted={true}
              sx={{
                width: '100%',
                height: 'auto', // Let video determine its own height based on aspect ratio
              }}
            />
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
              width: '100%',
              aspectRatio: isMobileModel ? '9/16' : '16/9',
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
  maxColumns = 3 
}) => {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: `repeat(${Math.min(devices.length, maxColumns)}, 1fr)`,
        gap: 2,
        maxWidth: '100%',
      }}
    >
      {devices.map((device, index) => (
        <DeviceStreamItem
          key={`${device.hostName}-${device.deviceId}-${index}`}
          device={device}
          allHosts={allHosts}
          getDevicesFromHost={getDevicesFromHost}
        />
      ))}
    </Box>
  );
};
