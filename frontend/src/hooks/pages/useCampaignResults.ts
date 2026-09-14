/**
 * Campaign Results Hook
 *
 * This hook handles all campaign results management functionality.
 */

import { useMemo } from 'react';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { apiClient } from '../../utils/apiClient';
export interface ScriptResult {
  id: string;
  script_name: string;
  script_type: string;
  success: boolean;
  execution_time_ms: number | null;
  started_at: string;
  completed_at: string;
  html_report_r2_url: string | null;
  logs_r2_url: string | null;
  metadata: {
    script_source_url?: string;
    verification_review_r2_url?: string;
    [key: string]: unknown;
  } | null;
  error_msg: string | null;
  folder?: string;
  tags?: Array<{ name: string; color: string }>;
}

export interface CampaignResult {
  id: string;
  team_id: string;
  campaign_name: string;
  campaign_description: string | null;
  campaign_execution_id: string;
  userinterface_name: string | null;
  host_name: string;
  device_name: string;
  status: string;
  success: boolean;
  execution_time_ms: number | null;
  started_at: string;
  completed_at: string | null;
  html_report_r2_path: string | null;
  html_report_r2_url: string | null;
  logs_r2_url: string | null;
  discard: boolean;
  error_message: string | null;
  script_result_ids: string[];
  script_results: ScriptResult[];
  script_configurations: any[];
  execution_config: any;
  executed_by: string | null;
  created_at: string;
  updated_at: string;
}

export const useCampaignResults = () => {
  /**
   * Get all campaign results
   */
  const getAllCampaignResults = useMemo(
    () => async (): Promise<CampaignResult[]> => {
      try {
        console.log(
          '[@hook:useCampaignResults:getAllCampaignResults] Fetching all campaign results from server',
        );

        const response = await apiClient(buildServerUrl('/server/campaign-results/getAllCampaignResults'));

        console.log(
          '[@hook:useCampaignResults:getAllCampaignResults] Response status:',
          response.status,
        );
        console.log(
          '[@hook:useCampaignResults:getAllCampaignResults] Response headers:',
          response.headers.get('content-type'),
        );

        if (!response.ok) {
          // Try to get error message from response
          let errorMessage = `Failed to fetch campaign results: ${response.status} ${response.statusText}`;
          try {
            const errorData = await response.text();
            console.log(
              '[@hook:useCampaignResults:getAllCampaignResults] Error response body:',
              errorData,
            );

            // Check if it's JSON
            if (response.headers.get('content-type')?.includes('application/json')) {
              const jsonError = JSON.parse(errorData);
              errorMessage = jsonError.error || errorMessage;
            } else {
              // It's HTML or other content, likely a proxy/server issue
              if (errorData.includes('<!doctype') || errorData.includes('<html')) {
                errorMessage =
                  'Server endpoint not available. Make sure the Flask server is running on the correct port and the proxy is configured properly.';
              }
            }
          } catch {
            console.log(
              '[@hook:useCampaignResults:getAllCampaignResults] Could not parse error response',
            );
          }

          throw new Error(errorMessage);
        }

        // Check if response is JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          throw new Error(
            `Expected JSON response but got ${contentType}. This usually means the Flask server is not running or the proxy is misconfigured.`,
          );
        }

        const campaignResults = await response.json();
        console.log(
          `[@hook:useCampaignResults:getAllCampaignResults] Successfully loaded ${campaignResults?.length || 0} campaign results`,
        );
        return campaignResults || [];
      } catch (error) {
        console.error(
          '[@hook:useCampaignResults:getAllCampaignResults] Error fetching campaign results:',
          error,
        );
        throw error;
      }
    },
    [],
  );

  return {
    getAllCampaignResults,
  };
};