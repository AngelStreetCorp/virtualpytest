import { useMemo } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

export interface QueueItem {
  id: string;
  type: string;
  data: any;
  created_at: string;
}

export interface QueueData {
  name: string;
  length: number;
  processed: number;
  discarded: number;
  validated: number;
  items?: QueueItem[];
}

export interface LastAnalyzedResult {
  id: string;
  discard: boolean;
  check_type?: string;
  discard_comment?: string;
  updated_at?: string;
  script_name?: string;
  success?: boolean;
  incident_type?: string;
  status?: string;
  host_name?: string;
  device_id?: string;
}

export interface QueueAnalysisSummary {
  analyzed: number;
  discarded: number;
  kept: number;
  last_analyzed?: LastAnalyzedResult | null;
  items?: LastAnalyzedResult[];
}

export interface AIQueueStatus {
  status: string;
  service: string;
  timestamp: string;
  stats: Record<string, any>;
  analysis_24h?: {
    window_hours: number;
    since: string;
    until: string;
    scripts: QueueAnalysisSummary;
    incidents: QueueAnalysisSummary;
    error?: string;
  };
  queues: {
    incidents: QueueData;
    scripts: QueueData;
  };
}

export const useAIQueue = () => {
  const getQueueStatus = useMemo(
    () => async (includeItems: boolean = false): Promise<AIQueueStatus> => {
      try {
        // Use backend_server proxy to get queue data from Redis
        const url = buildServerUrl(`/server/ai-queue/status${includeItems ? '?include_items=true' : ''}`);
        return await api.get(url);
      } catch (error) {
        console.error('[@hook:useAIQueue] Error fetching queue status:', error);
        throw error;
      }
    },
    [],
  );

  const clearQueues = useMemo(
    () => async (queueType: 'incidents' | 'scripts' | 'all' = 'all'): Promise<void> => {
      try {
        console.log(`[@hook:useAIQueue:clearQueues] Clearing ${queueType} queue(s)`);

        const result = await api.post(buildServerUrl('/server/ai-queue/clear'), {
          queue_type: queueType,
        });
        console.log('[@hook:useAIQueue:clearQueues] Success:', result);
      } catch (error) {
        console.error('[@hook:useAIQueue:clearQueues] Error:', error);
        throw error;
      }
    },
    [],
  );

  return {
    getQueueStatus,
    clearQueues,
  };
};
