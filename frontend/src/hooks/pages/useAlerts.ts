/**
 * Alerts Hook
 *
 * This hook handles all alerts management functionality for monitoring incidents.
 * Optimized to use a single database query with client-side filtering.
 */

import { useMemo } from 'react';

import { Alert } from '../../types/pages/Monitoring_Types';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api, apiClient } from '../../utils/apiClient';
export const useAlerts = () => {
  /**
   * Get all alerts (optimized single query)
   */
  const getAllAlerts = useMemo(
    () => async (): Promise<Alert[]> => {
      try {
        console.log('[@hook:useAlerts:getAllAlerts] Fetching all alerts from server');

        const response = await apiClient(buildServerUrl('/server/alerts/getAllAlerts'));

        console.log('[@hook:useAlerts:getAllAlerts] Response status:', response.status);

        if (!response.ok) {
          let errorMessage = `Failed to fetch alerts: ${response.status} ${response.statusText}`;
          try {
            const errorData = await response.text();
            if (response.headers.get('content-type')?.includes('application/json')) {
              const jsonError = JSON.parse(errorData);
              errorMessage = jsonError.error || errorMessage;
            } else {
              if (errorData.includes('<!doctype') || errorData.includes('<html')) {
                errorMessage =
                  'Server endpoint not available. Make sure the Flask server is running on the correct port and the proxy is configured properly.';
              }
            }
          } catch {
            console.log('[@hook:useAlerts:getAllAlerts] Could not parse error response');
          }

          throw new Error(errorMessage);
        }

        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          throw new Error(
            `Expected JSON response but got ${contentType}. This usually means the Flask server is not running or the proxy is misconfigured.`,
          );
        }

        const result = await response.json();
        console.log(
          `[@hook:useAlerts:getAllAlerts] Successfully loaded ${result.alerts?.length || 0} total alerts`,
        );
        return result.alerts || [];
      } catch (error) {
        console.error('[@hook:useAlerts:getAllAlerts] Error fetching alerts:', error);
        throw error;
      }
    },
    [],
  );

  /**
   * Get all active alerts (client-side filtered)
   */
  const getActiveAlerts = useMemo(
    () => async (): Promise<Alert[]> => {
      try {
        const allAlerts = await getAllAlerts();
        const activeAlerts = allAlerts.filter((alert) => alert.status === 'active');
        console.log(
          `[@hook:useAlerts:getActiveAlerts] Filtered ${activeAlerts.length} active alerts from ${allAlerts.length} total`,
        );
        return activeAlerts;
      } catch (error) {
        console.error('[@hook:useAlerts:getActiveAlerts] Error filtering active alerts:', error);
        throw error;
      }
    },
    [getAllAlerts],
  );

  /**
   * Get all closed/resolved alerts (client-side filtered)
   */
  const getClosedAlerts = useMemo(
    () => async (): Promise<Alert[]> => {
      try {
        const allAlerts = await getAllAlerts();
        const closedAlerts = allAlerts.filter((alert) => alert.status === 'resolved');
        console.log(
          `[@hook:useAlerts:getClosedAlerts] Filtered ${closedAlerts.length} closed alerts from ${allAlerts.length} total`,
        );
        return closedAlerts;
      } catch (error) {
        console.error('[@hook:useAlerts:getClosedAlerts] Error filtering closed alerts:', error);
        throw error;
      }
    },
    [getAllAlerts],
  );

  const updateCheckedStatus = useMemo(
    () => async (alertId: string, checked: boolean, checkType: string = 'manual'): Promise<void> => {
      try {
        console.log(
          `[@hook:useAlerts:updateCheckedStatus] Updating checked status for ${alertId}: ${checked}`,
        );

        await api.put(buildServerUrl(`/server/alerts/updateCheckedStatus/${alertId}`), {
          checked,
          check_type: checkType,
        });

        console.log(`[@hook:useAlerts:updateCheckedStatus] Successfully updated checked status`);
      } catch (error) {
        console.error('[@hook:useAlerts:updateCheckedStatus] Error:', error);
        throw error;
      }
    },
    [],
  );

  const updateDiscardStatus = useMemo(
    () => async (
      alertId: string, 
      discard: boolean, 
      discardComment?: string, 
      checkType: string = 'manual'
    ): Promise<void> => {
      try {
        console.log(
          `[@hook:useAlerts:updateDiscardStatus] Updating discard status for ${alertId}: ${discard}`,
        );

        await api.put(buildServerUrl(`/server/alerts/updateDiscardStatus/${alertId}`), {
          discard,
          discard_comment: discardComment,
          check_type: checkType,
        });

        console.log(`[@hook:useAlerts:updateDiscardStatus] Successfully updated discard status`);
      } catch (error) {
        console.error('[@hook:useAlerts:updateDiscardStatus] Error:', error);
        throw error;
      }
    },
    [],
  );

  const deleteAllAlerts = useMemo(
    () => async (): Promise<{ success: boolean; deleted_count: number; message?: string }> => {
      try {
        console.log('[@hook:useAlerts:deleteAllAlerts] Deleting all alerts');

        const result = await api.delete(buildServerUrl('/server/alerts/deleteAllAlerts'));
        console.log(`[@hook:useAlerts:deleteAllAlerts] Successfully deleted ${result.deleted_count} alerts`);
        
        return result;
      } catch (error) {
        console.error('[@hook:useAlerts:deleteAllAlerts] Error:', error);
        throw error;
      }
    },
    [],
  );

  return {
    getAllAlerts,
    getActiveAlerts,
    getClosedAlerts,
    updateCheckedStatus,
    updateDiscardStatus,
    deleteAllAlerts,
  };
};
