/**
 * Host Types - Canonical host type definitions for host machines that control devices
 *
 * A Host represents a machine running Flask that can control a device.
 *
 * Used consistently across all layers:
 * 1. Host Registration (what host sends to server)
 * 2. Server Storage (what server stores in memory registry)
 * 3. Frontend Interface (what frontend receives from API)
 *
 * NO DATA TRANSFORMATION should occur between these layers.
 */
import type { Actions } from '../controller/Action_Types';
import { SystemStats } from '../pages/Dashboard_Types';
import type { Verifications } from '../verification/Verification_Types';

/**
 * Controller object interfaces
 */
export interface ControllerObject {
  type: string;
  implementation: string;
  status?: any;
}

/**
 * Canonical Host Type - Used consistently across all layers
 *
 * This represents a host machine (Flask server) that manages a device.
 * Matches exactly what the host sends during registration and
 * what the server should store and return to the frontend.
 */
export interface DeviceCapabilities {
  av?: string; // 'hdmi_stream' | null
  remote?: string; // 'android_mobile' | 'android_tv' | 'appium' | null
  power?: string; // 'tapo' | null
  verification?: string[]; // ['image', 'text', 'adb', 'appium']
}

export interface Device {
  id?: string; // Database ID (for EditDialog compatibility)
  created_at?: string; // Creation timestamp (for EditDialog compatibility)
  updated_at?: string; // Update timestamp (for EditDialog compatibility)
  device_id: string; // Device identifier (device1, device2, etc.)
  device_name: string; // Device display name (matches server format)
  device_model: string; // Device model for controller configuration (matches server format)
  device_description?: string; // Device description
  device_ip?: string; // Device IP address (for ADB/device control)
  device_port?: string; // Device port (for ADB/device control)
  ir_type?: string; // IR remote type (samsung, stb, etc.)

  // === VIDEO CAPTURE CONFIGURATION ===
  video_stream_path?: string; // Video stream path for URL building (e.g., '/host/stream/capture1')
  video_capture_path?: string; // Video capture path for URL building (e.g., '/var/www/html/stream/capture1')
  video?: string; // Video device path (e.g., '/dev/video0', '/dev/video2')
  video_fps?: number; // Video capture FPS (frames per second) - used to align segments with captures (e.g., 5 for HDMI, 2 for VNC)

  device_capabilities: DeviceCapabilities; // New detailed capability format (matches server format)
  device_controller_types?: string[]; // Device-specific controller types (prefixed for consistency)
  controller_configs?: {
    [controllerType: string]: {
      implementation: string;
      parameters: { [key: string]: any };
      capabilities?: any[];
      connectionConfig?: any;
    };
  }; // Controller configurations (for EditDialog compatibility)

  // === DEVICE-LEVEL VERIFICATION AND ACTIONS ===
  device_verification_types?: Verifications; // Device verification types (simplified naming)
  device_action_types?: Actions; // Device action types (simplified naming)

  // === PER-DEVICE SCRIPT DEFAULTS (from host .env DEVICE{i}_USERINTERFACE/_VARIANT) ===
  preferred_userinterface?: string; // Default userinterface for navigation scripts on this device
  preferred_variant?: string; // Default named variant (only meaningful with preferred_userinterface)

  // === DEPLOYMENT STATUS ===
  has_running_deployment?: boolean; // True if a deployment script is currently running on this device

  // === DEVICE INFO (from latest get_info scan, corrected) ===
  device_info?: Record<string, string>; // key -> corrected value; attached by getAllHosts
  device_info_report?: {
    report_url?: string | null; // HTML report URL of the get_info scan the info came from
    scanned_at?: string | null; // started_at of that scan
    initial_screenshot_url?: string | null; // presigned R2 URL — initial state
    final_screenshot_url?: string | null; // presigned R2 URL — final state (the "Über"/info screen)
    video_url?: string | null; // presigned R2 URL — scan test video
  }; // attached by getAllHosts alongside device_info

  // === GATEWAY INFO (network environment, from latest gw_info scan, corrected) ===
  // Keyed per device — different devices on a host can be behind different gateways.
  gateway_info?: Record<string, string>; // key -> corrected value; attached by getAllHosts
  gateway_info_report?: {
    report_url?: string | null; // HTML report URL of the gw_info scan
    scanned_at?: string | null; // started_at of that scan
    initial_screenshot_url?: string | null;
    final_screenshot_url?: string | null;
    video_url?: string | null;
  }; // attached by getAllHosts alongside gateway_info

  // === RUNTIME PROPERTIES (added by HostManagerProvider) ===
  hostName?: string; // Host name this device belongs to (added dynamically by getAllDevices)
}

export interface Host {
  // === PRIMARY IDENTIFICATION ===
  host_name: string; // Host machine name (primary identifier)
  description?: string; // Optional description
  device_model?: string; // Device model for backward compatibility
  host_type?: string; // Host type: 'host_vnc' | 'runner_host' | 'runner_android_mobile' | 'runner_android_tablet' | 'runner_android_tv'
  device_type?: string; // Device role: 'host_device' | 'host_device_runner'
  controller_configs?: {
    [controllerType: string]: {
      implementation: string;
      type: string;
      parameters: any;
      capabilities?: any[];
      connectionConfig?: any;
    };
  }; // Controller configurations

  // === NETWORK CONFIGURATION ===
  host_url: string; // Host base URL (e.g., https://virtualpytest.com or http://localhost:6109)
  host_api_url?: string; // Direct server-to-server URL (e.g., http://192.168.0.108:6109)
  host_port: number; // Host port number

  // === MULTI-DEVICE CONFIGURATION ===
  devices: Device[]; // Array of devices controlled by this host
  device_count: number; // Number of devices

  // === STATUS AND METADATA ===
  status: 'online' | 'offline' | 'unreachable' | 'maintenance';
  deployed_version?: string;
  last_seen: number; // Unix timestamp
  registered_at: string; // ISO timestamp
  system_stats: SystemStats; // System resource usage

  // === DEVICE LOCK MANAGEMENT ===
  isLocked: boolean; // Device lock status
  lockedBy?: string; // Session/user who locked it
  lockedAt?: number; // Timestamp when locked
}

/**
 * Host registration payload (what host sends to server)
 * This should match exactly what's in host_utils.py
 */
export interface HostRegistrationPayload {
  host_name: string;
  host_url: string;
  host_port: number;
  device_name: string;
  device_model: string;
  device_ip: string;
  device_port: string;
  system_stats: SystemStats;
}

export const HostStatus = {
  ONLINE: 'online',
  OFFLINE: 'offline',
  UNREACHABLE: 'unreachable',
  MAINTENANCE: 'maintenance',
} as const;

export type HostStatusType = (typeof HostStatus)[keyof typeof HostStatus];
