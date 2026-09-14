/**
 * Device Panel Component - Right Panel
 *
 * Handles device execution, device selection, and video stream display.
 */

import React from 'react';
import {
  Box,
  Typography,
} from '@mui/material';
import {
  Devices as DevicesIcon,
} from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import { HLSVideoPlayer } from '../common/HLSVideoPlayer';
import { calculateVncScaling } from '../../utils/vncUtils';


interface DevicePanelProps {
  showDevice: boolean;
  selectedDevice: string;
  streamUrl: string | null | undefined;
  isLoadingUrl: boolean;
  getSelectedDeviceModel: () => string | undefined;
}

export const DevicePanel: React.FC<DevicePanelProps> = ({
  showDevice,
  selectedDevice,
  streamUrl,
  isLoadingUrl,
  getSelectedDeviceModel,
}) => {
  const theme = useTheme();

  // Determine if device is mobile (for aspect ratio)
  const deviceModel = getSelectedDeviceModel();
  const isMobile = deviceModel?.includes('mobile') || deviceModel === 'android_mobile';

  return (
    <Box
      sx={{
        width: showDevice ? '100%' : 0,
        minWidth: 0,
        height: '100%',
        bgcolor: theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.50',
        borderLeft: showDevice ? '1px solid' : 'none',
        borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.200',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        transition: 'width 0.2s, min-width 0.2s',
      }}
    >
      {showDevice && (
        <Box sx={{ p: 1, height: '100%', display: 'flex', flexDirection: 'column' }}>
          {/* Header with icon and title */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            <DevicesIcon sx={{ fontSize: 18, color: theme.palette.primary.main }} />
            <Typography variant="subtitle2" fontWeight={600}>
              Target
            </Typography>
          </Box>

          {/* Content rectangle - contains video stream or placeholder */}
          <Box
            sx={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 2,
              border: '1px dashed',
              borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.300',
              overflow: 'hidden',
              bgcolor: '#000', // Black background for video
            }}
          >
            {selectedDevice && streamUrl ? (
              deviceModel === 'host_vnc' ? (
                // VNC device - render iframe like RecHostPreview
                // Iframes don't respect % sizing, must use transform scaling
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
                      pointerEvents: 'none', // Disable interaction in panel view
                      ...calculateVncScaling({ width: 380, height: 180 }), // Panel target size
                    }}
                    title="VNC Desktop Stream"
                  />
                </Box>
              ) : (
                // Regular HLS device - use HLSVideoPlayer
                <HLSVideoPlayer
                  streamUrl={streamUrl}
                  isStreamActive={!!streamUrl && !isLoadingUrl}
                  model={deviceModel}
                  layoutConfig={{
                    minHeight: '100%',
                    aspectRatio: isMobile ? '9/16' : '16/9', // Mobile: portrait, TV: landscape
                    objectFit: isMobile ? 'cover' : 'contain', // Mobile: cover to fill, TV: contain to fit
                    isMobileModel: isMobile,
                  }}
                  sx={{
                    width: isMobile ? 'auto' : '100%',
                    height: '100%',
                    maxWidth: '100%',
                  }}
                />
              )
            ) : isLoadingUrl ? (
              <Typography variant="body2" color="text.secondary">
                Loading stream...
              </Typography>
            ) : !selectedDevice ? (
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', px: 2 }}>
                Select a target to view stream
              </Typography>
            ) : (
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', px: 2 }}>
                Stream not available
              </Typography>
            )}
          </Box>
        </Box>
      )}
    </Box>
  );
};
