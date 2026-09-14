/**
 * Base Infrared Remote Configuration Interface
 * Defines the common structure for all infrared remote types
 */

export interface InfraredRemoteButton {
  key: string;
  label: string;
  position: { x: number; y: number };
  size: { width: number; height: number };
  shape: 'circle' | 'rectangle';
  comment: string;
}

export interface InfraredRemoteInfo {
  name: string;
  type: 'ir_remote';
  image_url: string;
  default_scale: number;
  min_scale: number;
  max_scale: number;
  button_scale_factor: number;
  global_offset: { x: number; y: number };
  text_style: {
    fontSize: string;
    fontWeight: string;
    color: string;
    textShadow: string;
  };
}

export interface InfraredPanelLayout {
  collapsed: {
    width: string;
    height: string;
    position: {
      bottom: string;
      right: string;
    };
  };
  expanded: {
    width: string;
    height: string;
    position: {
      top: string;
      right: string;
    };
  };
  showScreenshotInCollapsed: boolean;
  showScreenshotInExpanded: boolean;
  header: {
    height: string;
    fontSize: string;
    fontWeight: string;
    iconSize: string;
    padding: string;
    backgroundColor: string;
    borderColor: string;
    textColor: string;
  };
}

export interface InfraredRemoteLayout {
  collapsed: {
    width: string;
    height: string;
    scale: number;
    padding: string;
  };
  expanded: {
    width: string;
    height: string;
    scale: number;
    padding: string;
  };
  background_image: {
    url: string;
    width: number;
    height: number;
  };
  global_offset: {
    x: number;
    y: number;
  };
}

export interface InfraredRemoteButtonLayout {
  [buttonId: string]: InfraredRemoteButton;
}

export interface InfraredRemoteConfig {
  remote_info: InfraredRemoteInfo;
  panel_layout: InfraredPanelLayout;
  remote_layout: InfraredRemoteLayout;
  button_layout: InfraredRemoteButtonLayout;
  button_layout_recmodal: InfraredRemoteButtonLayout;
}

// Infrared remote type definitions
export type InfraredRemoteType = 'samsung' | 'stb' | 'fire_tv' | 'apple_tv';

// Common default values for all infrared remotes
export const INFRARED_REMOTE_DEFAULTS = {
  remote_info: {
    type: 'ir_remote' as const,
    default_scale: 1,
    min_scale: 0.3,
    max_scale: 1.0,
    button_scale_factor: 1.5,
    global_offset: { x: 0, y: 0 },
    text_style: {
      fontSize: '12px',
      fontWeight: 'bold',
      color: 'white',
      textShadow: '2px 2px 4px rgba(0,0,0,0.9)',
    },
  },
  panel_layout: {
    collapsed: {
      width: '160px',
      height: '300px',
      position: {
        bottom: '20px',
        right: '20px',
      },
    },
    expanded: {
      width: '240px',
      height: '600px',
      position: {
        top: '100px',
        right: '20px',
      },
    },
    showScreenshotInCollapsed: false,
    showScreenshotInExpanded: true,
    header: {

      fontSize: '0.875rem',
      fontWeight: 'bold',
      iconSize: 'small',
      padding: '8px',
      backgroundColor: '#1E1E1E',
      borderColor: '#333',
      textColor: '#ffffff',
    },
  },
  remote_layout: {
    collapsed: {
      width: '120px',
      height: '250px',
      scale: 0.6,
      padding: '20px',
    },
    expanded: {
      width: '200px',
      height: '500px',
      scale: 1.0,
      padding: '25px',
    },
    global_offset: {
      x: 0,
      y: 0,
    },
  },
} as const;
