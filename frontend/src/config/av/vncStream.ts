import { HDMI_STREAM_HEADER_HEIGHT } from './hdmiStream';
import { DEFAULT_DEVICE_RESOLUTION } from '../deviceResolutions';

export const vncStreamConfig = {
  stream_info: {
    name: 'VNC',
    type: 'vnc_stream' as const,
    default_quality: 'high' as const,
    supported_resolutions: [`${DEFAULT_DEVICE_RESOLUTION.width}x${DEFAULT_DEVICE_RESOLUTION.height}`, '1280x720', '1280x720', '800x600'] as const,
    default_resolution: `${DEFAULT_DEVICE_RESOLUTION.width}x${DEFAULT_DEVICE_RESOLUTION.height}` as const,
  },
  panel_layout: {
    collapsed: {
      width: '370px',
      height: '240px', // Always landscape - VNC is desktop/host screen
      position: {
        bottom: '20px',
        left: '20px', // Left-aligned at 20px
      },
    },
    expanded: {
      width: '520px',
      height: '360px', // Always landscape - VNC is desktop/host screen
      position: {
        bottom: '20px',
        right: '20px',
      },
    },
    showControlsInCollapsed: false,
    showControlsInExpanded: true,
    header: {
      height: HDMI_STREAM_HEADER_HEIGHT,
      fontSize: '0.875rem',
      fontWeight: 'bold',
      iconSize: 'small',
      padding: '8px',
      backgroundColor: '#2A2A2A', // Slightly different from HDMI
      borderColor: '#444',
      textColor: '#ffffff',
    },
  },
  content_layout: {
    collapsed: {
      objectFit: 'contain' as const,
      width: '100%',
      height: '100%',
      // VNC-specific iframe scaling for small containers
      iframe: {
        transform: 'scale(0.35)', // Scale down to fit small collapsed panel
        transformOrigin: 'top left',
        width: '285%', // Inverse of scale to maintain aspect ratio
        height: '285%', // Inverse of scale to maintain aspect ratio
      },
    },
    expanded: {
      objectFit: 'contain' as const,
      width: '100%',
      height: '100%', 
      // VNC-specific iframe scaling for expanded containers
      iframe: {
        transform: 'scale(0.5)', // Scale down to fit expanded panel
        transformOrigin: 'top left',
        width: '200%', // Inverse of scale to maintain aspect ratio
        height: '200%', // Inverse of scale to maintain aspect ratio
      },
    },
  },
} as const;

// VNC streams are always landscape (desktop/host screens) regardless of device type
// No mobile config needed - use the same config for all scenarios
export const vncStreamMobileConfig = vncStreamConfig; 