import { createContext } from 'react';

import { Host, Device } from '../types/common/Host_Types';

/**
 * HostDataContext - Static/readonly host data that rarely changes
 * This context is for data access only and won't trigger re-renders
 * when device control state changes.
 */
export interface HostDataContextType {
  // Server selection state
  selectedServer: string;
  availableServers: string[];
  setSelectedServer: (serverUrl: string) => void;

  // Host data (filtered by interface models)
  availableHosts: Host[];
  getHostByName: (name: string) => Host | null;
  isLoading: boolean;
  error: string | null;

  // Direct data access functions
  getAllHosts: () => Host[];
  getHostsByModel: (models: string[]) => Host[];
  getAllDevices: () => Device[];
  getDevicesFromHost: (hostName: string) => Device[];
  getDevicesByCapability: (capability: string) => { host: Host; device: Device }[];
}

export const HostDataContext = createContext<HostDataContextType | undefined>(undefined);

