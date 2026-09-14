/**
 * Agent Selector Component
 * 
 * Displays dropdown to select active agent and shows real-time status
 */

import React, { useState, useEffect } from 'react';
import { io, Socket } from 'socket.io-client';
import { 
  ErrorOutline as AlertCircle, 
  AutoMode as Activity, 
  Pause, 
  Cancel as XCircle, 
  PlayArrow as Play 
} from '@mui/icons-material';

interface AgentInstance {
  instance_id: string;
  agent_id: string;
  version: string;
  state: 'idle' | 'running' | 'paused' | 'error' | 'stopped';
  current_task: string | null;
  started_at: string;
  last_activity: string;
  team_id: string;
}

interface AgentSelectorProps {
  onAgentSelect?: (instanceId: string | null) => void;
  selectedInstanceId?: string | null;
}

export const AgentSelector: React.FC<AgentSelectorProps> = ({ 
  onAgentSelect, 
  selectedInstanceId 
}) => {
  const [instances, setInstances] = useState<AgentInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchInstances = async () => {
    try {
      const response = await fetch('/server/runtime/instances');
      if (!response.ok) throw new Error('Failed to fetch instances');

      const data = await response.json();
      setInstances(data.instances || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  // Push-based refresh via /system socket events (agent runtime domain)
  useEffect(() => {
    fetchInstances();

    const socket: Socket = io(`${window.location.origin}/system`, {
      transports: ['websocket'],
      reconnection: true,
    });

    let refreshDebounce: ReturnType<typeof setTimeout> | null = null;
    const scheduleRefresh = () => {
      if (refreshDebounce) {
        clearTimeout(refreshDebounce);
      }
      refreshDebounce = setTimeout(() => {
        fetchInstances();
      }, 250);
    };

    socket.on('system_update', (event: any) => {
      if (event?.domain === 'agent_runtime' || String(event?.type || '').startsWith('agent_runtime_')) {
        scheduleRefresh();
      }
    });

    socket.on('connect', scheduleRefresh);

    return () => {
      if (refreshDebounce) {
        clearTimeout(refreshDebounce);
      }
      socket.disconnect();
    };
  }, []);

  const getStateIcon = (state: string) => {
    switch (state) {
      case 'running':
        return <Activity sx={{ fontSize: 16, color: '#22c55e' }} className="animate-pulse" />;
      case 'idle':
        return <Pause sx={{ fontSize: 16, color: '#9ca3af' }} />;
      case 'error':
        return <AlertCircle sx={{ fontSize: 16, color: '#ef4444' }} />;
      case 'paused':
        return <Pause sx={{ fontSize: 16, color: '#eab308' }} />;
      default:
        return <XCircle sx={{ fontSize: 16, color: '#9ca3af' }} />;
    }
  };

  const getStateColor = (state: string) => {
    switch (state) {
      case 'running':
        return 'border-green-500 bg-green-50';
      case 'idle':
        return 'border-gray-300 bg-gray-50';
      case 'error':
        return 'border-red-500 bg-red-50';
      case 'paused':
        return 'border-yellow-500 bg-yellow-50';
      default:
        return 'border-gray-300 bg-gray-50';
    }
  };

  const getStateBadge = (state: string) => {
    const colors: Record<string, string> = {
      running: 'bg-green-100 text-green-800',
      idle: 'bg-gray-100 text-gray-800',
      error: 'bg-red-100 text-red-800',
      paused: 'bg-yellow-100 text-yellow-800',
      stopped: 'bg-gray-100 text-gray-600'
    };

    return (
      <span className={`px-2 py-1 text-xs font-medium rounded-full ${colors[state] || colors.idle}`}>
        {state.toUpperCase()}
      </span>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-4">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-900">Active Agents</h3>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">{instances.length} instance(s)</span>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
          <AlertCircle sx={{ fontSize: 20, color: '#ef4444' }} />
          <span className="text-sm text-red-700">{error}</span>
        </div>
      )}

      {/* Instance List */}
      {instances.length === 0 ? (
        <div className="text-center p-8 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <Play sx={{ fontSize: 48, color: '#9ca3af', mb: 1.5, mx: 'auto', display: 'block' }} />
          <p className="text-gray-600 font-medium">No agents running</p>
          <p className="text-sm text-gray-500 mt-1">Start an agent to begin</p>
        </div>
      ) : (
        <div className="space-y-2">
          {instances.map((instance) => (
            <div
              key={instance.instance_id}
              className={`
                p-4 border-2 rounded-lg cursor-pointer transition-all
                ${selectedInstanceId === instance.instance_id 
                  ? 'border-blue-500 bg-blue-50 shadow-md' 
                  : getStateColor(instance.state)
                }
                hover:shadow-lg
              `}
              onClick={() => onAgentSelect?.(instance.instance_id)}
            >
              {/* Instance Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {getStateIcon(instance.state)}
                  <span className="font-semibold text-gray-900">
                    {instance.agent_id}
                  </span>
                  <span className="text-sm text-gray-500">v{instance.version}</span>
                </div>
                {getStateBadge(instance.state)}
              </div>

              {/* Current Task */}
              {instance.current_task && (
                <div className="mt-2 text-sm text-gray-700">
                  <span className="font-medium">Task:</span> {instance.current_task}
                </div>
              )}

              {/* Instance Info */}
              <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                <span>ID: {instance.instance_id.split('_')[1]}</span>
                <span>Started: {new Date(instance.started_at).toLocaleTimeString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Quick Actions */}
      {selectedInstanceId && (
        <div className="flex gap-2 pt-2 border-t border-gray-200">
          <button 
            className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              // TODO: Pause functionality
            }}
          >
            Pause
          </button>
          <button 
            className="flex-1 px-4 py-2 text-sm font-medium text-red-700 bg-red-100 rounded-lg hover:bg-red-200 transition-colors"
            onClick={async (e) => {
              e.stopPropagation();
              try {
                await fetch(`/server/runtime/instances/${selectedInstanceId}/stop`, {
                  method: 'POST'
                });
              } catch (err) {
                console.error('Failed to stop agent:', err);
              }
            }}
          >
            Stop
          </button>
        </div>
      )}
    </div>
  );
};
