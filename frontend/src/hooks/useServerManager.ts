import { useContext } from 'react';
import { ServerManagerContext } from '../contexts/ServerManagerContext';

/**
 * Hook to access Server Manager context
 * 
 * Provides access to backend server selection and server data.
 * Must be used within a ServerManagerProvider.
 * 
 * @returns ServerManagerContextType
 * @throws Error if used outside ServerManagerProvider
 */
export const useServerManager = () => {
  const context = useContext(ServerManagerContext);
  
  if (context === undefined) {
    throw new Error('useServerManager must be used within a ServerManagerProvider');
  }
  
  return context;
};
