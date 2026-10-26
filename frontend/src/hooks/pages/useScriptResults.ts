/**
 * Script Results Hook
 *
 * This hook handles all script results management functionality.
 */

import { useMemo } from 'react';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api, apiClient } from '../../utils/apiClient';
import type { RerunPayload } from '../../types/common/Rerun_Types';
export interface ScriptResult {
  id: string;
  team_id: string;
  /** Run governance (TASK-42): assignment ids and the result's labels, from getAllScriptResults. */
  milestone_id?: string | null;
  run_group_id?: string | null;
  labels?: Array<{ id: string; name: string; color: string | null }>;
  script_name: string;
  script_type: string;
  userinterface_name: string | null;
  host_name: string;
  device_name: string;
  success: boolean;
  /** The run never executed (it was not configured): a skip, not a failure.
   *  The flag comes from the run itself (BUG-0756); a payload that predates it
   *  simply has no flag and keeps the pass / fail reading. */
  skipped?: boolean;
  execution_time_ms: number | null;
  started_at: string;
  completed_at: string;
  html_report_r2_path: string | null;
  html_report_r2_url: string | null;
  logs_r2_path: string | null;
  logs_r2_url: string | null;
  discard: boolean;
  error_msg: string | null;
  metadata: any;
  created_at: string;
  updated_at: string;
  /** Launch config of the deployment that started this run, joined in by
   *  get_script_results. Null for runs with no deployment behind them (campaign
   *  steps, direct API calls) — those derive a payload from `metadata` instead. */
  rerun_payload?: RerunPayload | null;
  
  // AI Discard Analysis fields (from backend_discard service)
  checked?: boolean; // Whether AI has analyzed this script result
  check_type?: string; // Type of check performed ('ai' | 'manual')
  discard_type?: string; // Category: 'false_positive', 'valid', etc.
  discard_comment?: string; // AI explanation for the discard decision

  // TASK-65 G7 — projects this script is tagged with, joined in
  // get_script_results via `executable_tags` → `projects_tags`. Empty list
  // for projectless scripts (the default for legacy runs).
  projects?: Array<{ id: string; name: string; color: string | null }>;
  project_ids?: string[];
}

export interface ScriptResultFilters {
  script_name?: string;
  host_name?: string;
  limit?: number;
  // Active workspace host scope (host names). Applied server-side BEFORE the
  // row limit so a busy workspace can't starve another workspace's rows out of
  // the latest-N window.
  host_filter?: string[];
  // Run-management governance filters (TASK-42), applied server-side before the limit.
  milestone_id?: string;
  run_group_id?: string;
  label_id?: string;
  // Dashboard deep links (TASK-123): verdict and time window, applied server-side before the limit.
  status?: 'passed' | 'failed' | 'aborted';
  range?: '24h' | '7d' | '30d';
}

export const useScriptResults = () => {
  /**
   * Get all script results
   */
  const getAllScriptResults = useMemo(
    () => async (filters?: ScriptResultFilters): Promise<ScriptResult[]> => {
      try {
        console.log(
          '[@hook:useScriptResults:getAllScriptResults] Fetching script results from server',
          filters,
        );

        const params = new URLSearchParams();
        if (filters?.script_name) params.set('script_name', filters.script_name);
        if (filters?.host_name) params.set('host_name', filters.host_name);
        if (filters?.limit) params.set('limit', String(filters.limit));
        if (filters?.host_filter?.length) params.set('host_filter', JSON.stringify(filters.host_filter));
        if (filters?.milestone_id) params.set('milestone_id', filters.milestone_id);
        if (filters?.run_group_id) params.set('run_group_id', filters.run_group_id);
        if (filters?.label_id) params.set('label_id', filters.label_id);
        if (filters?.status) params.set('status', filters.status);
        if (filters?.range) params.set('range', filters.range);
        const qs = params.toString();
        const url = buildServerUrl('/server/script-results/getAllScriptResults') + (qs ? `&${qs}` : '');

        const response = await apiClient(url);

        console.log(
          '[@hook:useScriptResults:getAllScriptResults] Response status:',
          response.status,
        );
        console.log(
          '[@hook:useScriptResults:getAllScriptResults] Response headers:',
          response.headers.get('content-type'),
        );

        if (!response.ok) {
          // Try to get error message from response
          let errorMessage = `Failed to fetch script results: ${response.status} ${response.statusText}`;
          try {
            const errorData = await response.text();
            console.log(
              '[@hook:useScriptResults:getAllScriptResults] Error response body:',
              errorData,
            );

            // Check if it's JSON
            if (response.headers.get('content-type')?.includes('application/json')) {
              const jsonError = JSON.parse(errorData);
              const serverError = String(jsonError.error || '');
              // A database error can wrap a whole proxy HTML page (BUG-0416):
              // show a short message, keep the full text in the console log above.
              errorMessage = /<html|<!doctype/i.test(serverError)
                ? `Failed to fetch script results: the server could not reach the database (${response.status}).`
                : serverError.slice(0, 300) || errorMessage;
            } else {
              // It's HTML or other content, likely a proxy/server issue
              if (errorData.includes('<!doctype') || errorData.includes('<html')) {
                errorMessage =
                  'Server endpoint not available. Make sure the Flask server is running on the correct port and the proxy is configured properly.';
              }
            }
          } catch {
            console.log(
              '[@hook:useScriptResults:getAllScriptResults] Could not parse error response',
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

        const scriptResults = await response.json();
        console.log(
          `[@hook:useScriptResults:getAllScriptResults] Successfully loaded ${scriptResults?.length || 0} script results`,
        );
        return scriptResults || [];
      } catch (error) {
        console.error(
          '[@hook:useScriptResults:getAllScriptResults] Error fetching script results:',
          error,
        );
        throw error;
      }
    },
    [],
  );

  const updateCheckedStatus = useMemo(
    () => async (scriptResultId: string, checked: boolean, checkType: string = 'manual'): Promise<void> => {
      try {
        console.log(
          `[@hook:useScriptResults:updateCheckedStatus] Updating checked status for ${scriptResultId}: ${checked}`,
        );

        await api.put(buildServerUrl(`/server/script-results/updateCheckedStatus/${scriptResultId}`), {
          checked,
          check_type: checkType,
        });

        console.log(`[@hook:useScriptResults:updateCheckedStatus] Successfully updated checked status`);
      } catch (error) {
        console.error('[@hook:useScriptResults:updateCheckedStatus] Error:', error);
        throw error;
      }
    },
    [],
  );

  const updateDiscardStatus = useMemo(
    () => async (
      scriptResultId: string, 
      discard: boolean, 
      discardComment?: string, 
      checkType: string = 'manual'
    ): Promise<void> => {
      try {
        console.log(
          `[@hook:useScriptResults:updateDiscardStatus] Updating discard status for ${scriptResultId}: ${discard}`,
        );

        await api.put(buildServerUrl(`/server/script-results/updateDiscardStatus/${scriptResultId}`), {
          discard,
          discard_comment: discardComment,
          check_type: checkType,
        });

        console.log(`[@hook:useScriptResults:updateDiscardStatus] Successfully updated discard status`);
      } catch (error) {
        console.error('[@hook:useScriptResults:updateDiscardStatus] Error:', error);
        throw error;
      }
    },
    [],
  );

  return {
    getAllScriptResults,
    updateCheckedStatus,
    updateDiscardStatus,
  };
}; 