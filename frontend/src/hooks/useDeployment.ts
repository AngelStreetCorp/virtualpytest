import { useCallback } from 'react';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import { useAsyncRequest } from './shared/useAsyncRequest';

export interface Deployment {
  id: string;
  name: string;
  host_name: string;
  device_id: string;
  script_name: string;
  userinterface_name: string;
  parameters?: string;
  campaign_id?: string | null;
  // Per-device manual device info merged into metadata.info of every script
  // this deployment runs (run UI → Selected Items → Device Info).
  device_info?: Record<string, string>;

  // Virtual-script deployments: which dev/test/prod row (virtual_scripts.id)
  // to materialize and run. Absent for disk-script/campaign deployments.
  virtual_script_id?: string;
  // Capacity/KPI tag this run counts as. Defaults server-side to 'prod'.
  environment?: 'dev' | 'test' | 'prod';

  // Cron-based scheduling
  cron_expression: string;
  start_date?: string | null;
  end_date?: string | null;
  max_executions?: number | null;
  
  // Execution tracking
  execution_count: number;
  last_executed_at?: string | null;
  
  status: 'active' | 'paused' | 'stopped' | 'completed' | 'expired';
  created_at: string;
  next_run?: string | null;
}

export interface CampaignScript {
  id: string;
  script_name: string;
  success: boolean;
  execution_order: number;
  started_at?: string;
  completed_at?: string;
  execution_time_ms?: number;
  html_report_r2_url?: string;
  logs_r2_url?: string;
  error_msg?: string;
}

export interface DeploymentExecution {
  id: string;
  deployment_id: string;
  started_at: string;
  completed_at?: string;
  scheduled_at?: string;
  status?: 'queued' | 'running' | 'completed' | 'failed' | 'skipped' | 'aborted';
  success?: boolean;
  error_message?: string;
  report_url?: string;
  logs_url?: string;
  is_campaign?: boolean;
  campaign_name?: string;
  campaign_success?: boolean;
  campaign_scripts?: CampaignScript[];
  deployments?: {
    id?: string;
    name?: string;
    host_name?: string;
    device_id?: string;
    script_name?: string;
    status?: string;
    cron_expression?: string;
    campaign_id?: string | null;
    parameters?: string | null;
    // Launch-time config for one-click rerun in "Last Executions". JSONB on
    // the server side (deployments.rerun_payload). Untyped here to avoid a
    // circular dep with RunTests' RerunPayload union — the consumer narrows
    // it via the type discriminator.
    rerun_payload?: any;
    // Per-device manual device info merged into metadata.info of every script
    // this deployment runs (run UI → Selected Items → Device Info).
    device_info?: Record<string, string>;
  };
}

export interface RecentDeploymentExecutionsResponse {
  success: boolean;
  running_executions: DeploymentExecution[];
  queued_executions: DeploymentExecution[];
  completed_executions: DeploymentExecution[];
  running_count: number;
  queued_count: number;
  completed_count: number;
}

export const useDeployment = () => {
  const { execute, loading } = useAsyncRequest();

  const createDeployment = useCallback(async (data: Partial<Deployment>) => {
    return execute(() => api.post(buildServerUrl('/server/deployment/create'), data));
  }, [execute]);

  const listDeployments = useCallback(async () => {
    return api.get(buildServerUrl('/server/deployment/list'), { cache: 'no-store' });
  }, []);

  const pauseDeployment = useCallback(async (id: string) => {
    return api.post(buildServerUrl(`/server/deployment/pause/${id}`));
  }, []);

  const updateDeployment = useCallback(async (id: string, data: Partial<Deployment>) => {
    return api.put(buildServerUrl(`/server/deployment/update/${id}`), data);
  }, []);

  const resumeDeployment = useCallback(async (id: string) => {
    return api.post(buildServerUrl(`/server/deployment/resume/${id}`));
  }, []);

  const deleteDeployment = useCallback(async (id: string) => {
    return api.delete(buildServerUrl(`/server/deployment/delete/${id}`));
  }, []);

  const runDeploymentNow = useCallback(async (id: string) => {
    return api.post(buildServerUrl(`/server/deployment/run/${id}`));
  }, []);

  const getDeploymentHistory = useCallback(async (id: string) => {
    return api.get(buildServerUrl(`/server/deployment/history/${id}`));
  }, []);

  const getRecentExecutions = useCallback(async (scope?: {
    deviceFilter?: string[];
    scriptFilter?: string[];
  }) => {
    // Workspace scope is applied server-side BEFORE the row limit so each
    // workspace gets its own most-recent rows instead of being starved by
    // another workspace that already filled the global limit.
    const qs = new URLSearchParams();
    if (scope?.deviceFilter?.length) qs.set('device_filter', JSON.stringify(scope.deviceFilter));
    if (scope?.scriptFilter?.length) qs.set('script_filter', JSON.stringify(scope.scriptFilter));
    const query = qs.toString();
    return api.get<RecentDeploymentExecutionsResponse>(
      buildServerUrl(`/server/deployment/executions/recent${query ? `?${query}` : ''}`),
      { cache: 'no-store' },
    );
  }, []);

  return {
    loading,
    createDeployment,
    listDeployments,
    updateDeployment,
    pauseDeployment,
    resumeDeployment,
    deleteDeployment,
    getDeploymentHistory,
    getRecentExecutions,
    runDeploymentNow,
  };
};
