import { hdmiStreamConfig, hdmiStreamMobileConfig } from './hdmiStream';
import { vncStreamConfig } from './vncStream';

/**
 * ConfigurableAVPanelLayout interface defines the structure for AV panel layouts
 */
export interface ConfigurableAVPanelLayout {
  collapsed: {
    width: string;
    height: string;
    position: {
      bottom: string;
      left?: string;
      right?: string;
    };
  };
  expanded: {
    width: string;
    height: string;
    position: {
      bottom: string;
      left?: string;
      right?: string;
    };
  };
  showControlsInCollapsed: boolean;
  showControlsInExpanded: boolean;
  header?: {
    height: string;
    fontSize?: string;
    fontWeight?: string;
    iconSize?: string;
    padding?: string;
    backgroundColor?: string;
    borderColor?: string;
    textColor?: string;
  };
}

/**
 * Get configurable AV panel layout from device config
 * @param deviceModel The device model (e.g., 'android_mobile', 'android_tv')
 * @param avConfig The loaded AV configuration object
 * @returns ConfigurableAVPanelLayout with device-specific or default settings
 */
export const getConfigurableAVPanelLayout = (avConfig: any): ConfigurableAVPanelLayout => {
  // Default fallback layout
  const defaultLayout: ConfigurableAVPanelLayout = {
    collapsed: {
      width: '300px',
      height: '200px',
      position: {
        bottom: '20px',
        left: '20px',
      },
    },
    expanded: {
      width: '700px',
      height: '500px',
      position: {
        bottom: '20px',
        right: '20px',
      },
    },
    showControlsInCollapsed: false,
    showControlsInExpanded: true,
  };

  // Return the panel_layout from avConfig if available, otherwise use default
  return avConfig?.panel_layout || defaultLayout;
};

/**
 * Helper function to detect mobile devices
 */
const isMobileDevice = (deviceModel: string): boolean => {
  return deviceModel.includes('mobile') || deviceModel === 'android_mobile';
};

/**
 * Load AV configuration based on stream type and device model
 * @param streamType The stream type (e.g., 'hdmi_stream')
 * @param deviceModel The device model (optional, for mobile detection)
 * @returns Promise<any> The loaded configuration or null if failed
 */
export const loadAVConfig = async (streamType: string, deviceModel?: string): Promise<any> => {
  try {
    console.log(`[@config:avPanelLayout] Loading config for ${streamType}, device: ${deviceModel}`);

    switch (streamType) {
      case 'hdmi_stream':
        // Use mobile config if device is mobile, otherwise use regular config
        if (deviceModel && isMobileDevice(deviceModel)) {
          console.log(`[@config:avPanelLayout] Using mobile HDMI config for ${deviceModel}`);
          return hdmiStreamMobileConfig;
        } else {
          console.log(`[@config:avPanelLayout] Using standard HDMI config for ${deviceModel}`);
          return hdmiStreamConfig;
        }

      case 'vnc_stream':
        console.log(`[@config:avPanelLayout] Using VNC config for ${deviceModel}`);
        return vncStreamConfig;

      default:
        console.warn(`[@config:avPanelLayout] Unknown stream type: ${streamType}`);
        return null;
    }
  } catch (error) {
    console.error(`[@config:avPanelLayout] Error loading config for ${streamType}:`, error);
    return null;
  }
}; 