import { createContext } from 'react';
import { ServerHostData } from '../types/common/Server_Types';

/**
 * Server Manager Context
 * 
 * Manages backend server selection and server data fetching.
 * Separate from HostManager to maintain single responsibility.
 */
export interface ServerManagerContextType {
  // Server selection state
  selectedServer: string;
  availableServers: string[];
  setSelectedServer: (serverUrl: string) => void;

  // Server data (fetched from all configured servers)
  serverHostsData: ServerHostData[];
  isLoading: boolean;
  error: string | null;
  pendingServers: Set<string>;
  failedServers: Set<string>;

  // Server change transition state (blocks re-selection while streams initialize)
  isServerChanging: boolean;

  // Actions
  refreshServerData: (includeSystemStats?: boolean) => Promise<void>;
}

export const ServerManagerContext = createContext<ServerManagerContextType | undefined>(undefined);
