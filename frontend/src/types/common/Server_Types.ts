/**
 * Server-related type definitions
 * 
 * Centralizes all server data structures used across the application
 */

import { Host } from './Host_Types';
import { SystemStats } from '../pages/Dashboard_Types';

/**
 * Server information returned from backend
 */
export interface ServerInfo {
  server_name: string;           // Server name from SERVER_NAME env (e.g., "RPI1-server")
  server_url: string;             // Full server URL for API calls (e.g., "https://dev.virtualpytest.com:443")
  server_url_display: string;     // Cleaned URL for display (e.g., "dev.virtualpytest.com")
  server_port: string;            // Server port (e.g., "443")
  deployed_version?: string | null;
  last_deploy_at?: string | null;
  deploy_state?: string | null;
  system_stats?: SystemStats;     // Server's own system stats (CPU, RAM, Disk, etc.)
  service_health?: SystemStats['service_health']; // Server service states (vpt-server, vpt-discard-scripts, vpt-discard-incidents, vpt-heatmap)
}

export interface FrontendInfo {
  deployed_version?: string | null;
}

/**
 * Server data with hosts
 * Returned from /server/system/getAllHosts endpoint for each server
 */
export interface ServerHostData {
  server_info: ServerInfo;
  frontend_info?: FrontendInfo | null;
  hosts: Host[];
}

/**
 * Server manager state
 */
export interface ServerManagerState {
  selectedServer: string;         // Currently selected server URL (full URL)
  availableServers: string[];     // List of all configured server URLs
  serverHostsData: ServerHostData[]; // Data from all servers
  isLoading: boolean;
  error: string | null;
}
