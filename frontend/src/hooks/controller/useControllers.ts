import { useState, useEffect, useCallback } from 'react';

import { ControllerTypesResponse } from '../../types/controller/Remote_Types';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
export function useControllers() {
  const [controllerTypes, setControllerTypes] = useState<ControllerTypesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchControllerTypes = useCallback(async () => {
    try {
      setLoading(true);
      console.log('[@hook:useControllers] Fetching controller types');

      const data = await api.get(buildServerUrl('/server/control/getAllControllers'));

      // Extract controller_types from API response
      setControllerTypes(data.controller_types || data);
      setError(null);
    } catch (err: any) {
      console.error('[@hook:useControllers] Error:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchControllerTypes();
  }, [fetchControllerTypes]);

  return {
    controllerTypes,
    loading,
    error,
    refetch: fetchControllerTypes,
  };
}
