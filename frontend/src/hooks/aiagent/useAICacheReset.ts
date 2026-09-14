import { useState, useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { useToast } from '../useToast';

interface UseAICacheResetOptions {
  hostName: string;
}

interface CacheResetResult {
  success: boolean;
  deleted_count?: number;
  error?: string;
}

export const useAICacheReset = ({ hostName }: UseAICacheResetOptions) => {
  const [isResetting, setIsResetting] = useState(false);
  const { showError, showSuccess } = useToast();

  const resetCache = useCallback(async (): Promise<boolean> => {
    if (!hostName) {
      console.error('[@useAICacheReset] Missing host_name');
      showError('Cannot reset cache: missing host information');
      return false;
    }

    setIsResetting(true);
    try {
      // buildServerUrl automatically adds team_id query parameter
      const result: CacheResetResult = await api.post(buildServerUrl('/server/ai/resetCache'), {
        host_name: hostName,
      });

      if (result.success) {
        const deletedCount = result.deleted_count || 0;
        console.log(`[@useAICacheReset] Cache reset successful: ${deletedCount} plans deleted`);
        showSuccess(`Cache cleared: ${deletedCount} AI plan${deletedCount !== 1 ? 's' : ''} deleted`);
        return true;
      } else {
        console.error('[@useAICacheReset] Cache reset failed:', result.error);
        showError(`Failed to reset cache: ${result.error}`);
        return false;
      }
    } catch (error) {
      console.error('[@useAICacheReset] Error resetting cache:', error);
      showError('Error resetting cache');
      return false;
    } finally {
      setIsResetting(false);
    }
  }, [hostName, showError, showSuccess]);

  return {
    resetCache,
    isResetting
  };
};
