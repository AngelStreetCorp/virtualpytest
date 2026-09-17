import { createContext } from 'react';
import { ServerHostData } from '../types/common/Server_Types';
import { ServerAuthState } from '../lib/serverIdentity';

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

  /**
   * Per-server auth state (TASK-18), keyed by server URL. Servers do not all
   * authenticate against the same Supabase, so "signed in" is a per-server fact:
   * `needs-auth` means reachable but awaiting a login, which is NOT the same as
   * being in `failedServers`.
   */
  serverAuthStates: Record<string, ServerAuthState>;

  // Server change transition state (blocks re-selection while streams initialize)
  isServerChanging: boolean;

  // Actions
  refreshServerData: (includeSystemStats?: boolean) => Promise<void>;
  /** Re-probe every server's identity and recompute its auth state (e.g. after a login). */
  refreshServerAuth: () => Promise<void>;
}

export const ServerManagerContext = createContext<ServerManagerContextType | undefined>(undefined);
