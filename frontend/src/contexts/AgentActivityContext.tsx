/**
 * Global Agent Activity Context
 * 
 * Tracks all agent activities across the application.
 * Provides data for floating badges and task history.
 */

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { useSocket } from './SocketContext';

// Types
export interface AgentTask {
  id: string;
  agentId: string;
  prompt: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  triggerType: 'manual' | 'auto' | 'alert';
  triggerSource?: string; // chat, dashboard, event, schedule
  steps: TaskStep[];
  response?: string;
  summary?: { title: string; data: Record<string, any> };
  redirectedTo?: string;
  redirectedFrom?: string;
  startedAt: string;
  completedAt?: string;
  feedback?: { rating: number; comment?: string };
  error?: string;
}

export interface TaskStep {
  id: string;
  label: string;
  status: 'pending' | 'active' | 'done' | 'error';
  detail?: string;
  timestamp: string;
}

export interface AgentActivity {
  agentId: string;
  tasks: AgentTask[];
  isExpanded: boolean;
}

interface AgentActivityState {
  activities: Record<string, AgentActivity>;
  
  // Actions
  startTask: (agentId: string, prompt: string, triggerType: 'manual' | 'auto' | 'alert') => string;
  updateTaskStep: (agentId: string, taskId: string, step: TaskStep) => void;
  completeTask: (agentId: string, taskId: string, response: string, summary?: AgentTask['summary']) => void;
  failTask: (agentId: string, taskId: string, error: string) => void;
  submitFeedback: (agentId: string, taskId: string, rating: number, comment?: string) => void;
  dismissTask: (agentId: string, taskId: string) => void;
  toggleExpanded: (agentId: string) => void;
  
  // Computed
  getActiveAgents: () => string[];
  getManualTasks: () => { agentId: string; task: AgentTask }[];
  getAutoTasks: () => { agentId: string; task: AgentTask }[];
  hasActiveManualTask: () => boolean;
}

const AgentActivityContext = createContext<AgentActivityState | undefined>(undefined);

export const AgentActivityProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activities, setActivities] = useState<Record<string, AgentActivity>>({});
  const completionTimeouts = useRef<Record<string, NodeJS.Timeout>>({});

  // Use centralized socket
  const { socket, connect } = useSocket();

  // Connect to agent socket for real-time updates
  useEffect(() => {
    if (!socket) return;

    // Connect the centralized socket if not already connected
    connect();

    // Listen for agent events from any agent
    socket.on('agent_activity', (event: any) => {
      console.log('🎯 Agent Activity Event:', event);

      const { agent_id, type, task_id, ...data } = event;

      if (type === 'task_started') {
        startTask(agent_id, data.prompt || 'Processing...', data.trigger_type || 'auto');
      }

      if (type === 'step_update' && task_id) {
        updateTaskStep(agent_id, task_id, {
          id: `step-${Date.now()}`,
          label: data.label || 'Processing',
          status: data.status || 'active',
          detail: data.detail,
          timestamp: new Date().toISOString(),
        });
      }

      if (type === 'task_completed' && task_id) {
        completeTask(agent_id, task_id, data.response || '', data.summary);
      }

      if (type === 'task_failed' && task_id) {
        failTask(agent_id, task_id, data.error || 'Unknown error');
      }
    });

    socket.on('connect', () => {
      console.log('🎯 AgentActivity socket connected to /agent namespace');
    });

    // No cleanup needed - socket is managed by SocketContext
  }, [socket, connect]);

  const generateId = () => `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

  const startTask = useCallback((agentId: string, prompt: string, triggerType: 'manual' | 'auto' | 'alert'): string => {
    const taskId = generateId();
    const task: AgentTask = {
      id: taskId,
      agentId,
      prompt,
      status: 'running',
      triggerType,
      triggerSource: triggerType === 'manual' ? 'chat' : 'event',
      steps: [
        { id: 'start', label: 'Starting', status: 'done', timestamp: new Date().toISOString() },
        { id: 'process', label: 'Processing', status: 'active', timestamp: new Date().toISOString() },
      ],
      startedAt: new Date().toISOString(),
      redirectedFrom: window.location.pathname !== '/ai-agent' ? window.location.pathname : undefined,
    };

    console.log('🎯 AgentActivity: Starting task', { agentId, taskId, triggerType, redirectedFrom: task.redirectedFrom });

    setActivities(prev => ({
      ...prev,
      [agentId]: {
        agentId,
        tasks: [...(prev[agentId]?.tasks || []), task],
        isExpanded: false, // Keep running tasks collapsed; expand on completion instead
      },
    }));

    return taskId;
  }, []);

  const updateTaskStep = useCallback((agentId: string, taskId: string, step: TaskStep) => {
    setActivities(prev => {
      const activity = prev[agentId];
      if (!activity) return prev;

      return {
        ...prev,
        [agentId]: {
          ...activity,
          tasks: activity.tasks.map(t => {
            if (t.id !== taskId) return t;
            return {
              ...t,
              steps: [...t.steps.filter(s => s.status !== 'active').map(s => ({ ...s, status: 'done' as const })), step],
            };
          }),
        },
      };
    });
  }, []);

  const completeTask = useCallback((agentId: string, taskId: string, response: string, summary?: AgentTask['summary']) => {
    console.log('🎯 AgentActivity: Completing task', { agentId, taskId });
    
    setActivities(prev => {
      const activity = prev[agentId];
      if (!activity) {
        console.warn('🎯 AgentActivity: No activity found for', agentId);
        return prev;
      }

      return {
        ...prev,
        [agentId]: {
          ...activity,
          tasks: activity.tasks.map(t => {
            if (t.id !== taskId) return t;
            return {
              ...t,
              status: 'completed',
              response,
              summary,
              completedAt: new Date().toISOString(),
              steps: t.steps.map(s => ({ ...s, status: 'done' as const })),
            };
          }),
          isExpanded: true, // Expand on completion for manual tasks
        },
      };
    });

    // Auto-dismiss auto tasks after 30 seconds (increased from 10)
    // Manual tasks should stay visible until user dismisses
    setActivities(prev => {
      const task = prev[agentId]?.tasks.find(t => t.id === taskId);
      if (task?.triggerType !== 'manual') {
        completionTimeouts.current[taskId] = setTimeout(() => {
          dismissTask(agentId, taskId);
        }, 30000); // 30 seconds for auto tasks
      }
      return prev;
    });
  }, []);

  const failTask = useCallback((agentId: string, taskId: string, error: string) => {
    setActivities(prev => {
      const activity = prev[agentId];
      if (!activity) return prev;

      return {
        ...prev,
        [agentId]: {
          ...activity,
          tasks: activity.tasks.map(t => {
            if (t.id !== taskId) return t;
            return {
              ...t,
              status: 'failed',
              error,
              completedAt: new Date().toISOString(),
              steps: [...t.steps.filter(s => s.status !== 'active'), { id: 'error', label: 'Error', status: 'error' as const, detail: error, timestamp: new Date().toISOString() }],
            };
          }),
          isExpanded: true,
        },
      };
    });
  }, []);

  const submitFeedback = useCallback(async (agentId: string, taskId: string, rating: number, comment?: string) => {
    // Update local state first for immediate UI feedback
    setActivities(prev => {
      const activity = prev[agentId];
      if (!activity) return prev;

      return {
        ...prev,
        [agentId]: {
          ...activity,
          tasks: activity.tasks.map(t => {
            if (t.id !== taskId) return t;
            return { ...t, feedback: { rating, comment } };
          }),
        },
      };
    });

    // Send feedback to backend API
    try {
      const activity = activities[agentId];
      const task = activity?.tasks.find(t => t.id === taskId);
      
      const response = await fetch(buildServerUrl('/server/benchmarks/feedback'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: agentId,
          rating: rating,
          comment: comment,
          task_description: task?.prompt,
          // execution_id: taskId,  // Skipping - taskId is not UUID format
        }),
      });
      
      if (!response.ok) {
        console.error('Failed to submit feedback to backend:', await response.text());
      } else {
        console.log('✅ Feedback submitted successfully to database');
      }
    } catch (error) {
      console.error('Error submitting feedback:', error);
    }

    // Dismiss after feedback (removed auto-dismiss as per user request)
    // setTimeout(() => dismissTask(agentId, taskId), 1000);
  }, [activities]);

  const dismissTask = useCallback((agentId: string, taskId: string) => {
    // Clear any pending timeout
    if (completionTimeouts.current[taskId]) {
      clearTimeout(completionTimeouts.current[taskId]);
      delete completionTimeouts.current[taskId];
    }

    setActivities(prev => {
      const activity = prev[agentId];
      if (!activity) return prev;

      const remainingTasks = activity.tasks.filter(t => t.id !== taskId);
      
      if (remainingTasks.length === 0) {
        const { [agentId]: _, ...rest } = prev;
        return rest;
      }

      return {
        ...prev,
        [agentId]: {
          ...activity,
          tasks: remainingTasks,
        },
      };
    });
  }, []);

  const toggleExpanded = useCallback((agentId: string) => {
    setActivities(prev => {
      const activity = prev[agentId];
      if (!activity) return prev;

      return {
        ...prev,
        [agentId]: {
          ...activity,
          isExpanded: !activity.isExpanded,
        },
      };
    });
  }, []);

  const getActiveAgents = useCallback((): string[] => {
    return Object.keys(activities).filter(agentId => 
      activities[agentId].tasks.some(t => t.status === 'running' || t.status === 'completed')
    );
  }, [activities]);

  const getManualTasks = useCallback((): { agentId: string; task: AgentTask }[] => {
    const result: { agentId: string; task: AgentTask }[] = [];
    Object.entries(activities).forEach(([agentId, activity]) => {
      activity.tasks
        .filter(t => t.triggerType === 'manual')
        .forEach(task => result.push({ agentId, task }));
    });
    return result.sort((a, b) => new Date(b.task.startedAt).getTime() - new Date(a.task.startedAt).getTime());
  }, [activities]);

  const getAutoTasks = useCallback((): { agentId: string; task: AgentTask }[] => {
    const result: { agentId: string; task: AgentTask }[] = [];
    Object.entries(activities).forEach(([agentId, activity]) => {
      activity.tasks
        .filter(t => t.triggerType !== 'manual')
        .forEach(task => result.push({ agentId, task }));
    });
    return result.sort((a, b) => new Date(b.task.startedAt).getTime() - new Date(a.task.startedAt).getTime());
  }, [activities]);

  const hasActiveManualTask = useCallback((): boolean => {
    return getManualTasks().some(({ task }) => task.status === 'running' || task.status === 'completed');
  }, [getManualTasks]);

  return (
    <AgentActivityContext.Provider value={{
      activities,
      startTask,
      updateTaskStep,
      completeTask,
      failTask,
      submitFeedback,
      dismissTask,
      toggleExpanded,
      getActiveAgents,
      getManualTasks,
      getAutoTasks,
      hasActiveManualTask,
    }}>
      {children}
    </AgentActivityContext.Provider>
  );
};

export const useAgentActivity = () => {
  const context = useContext(AgentActivityContext);
  if (!context) throw new Error('useAgentActivity must be used within AgentActivityProvider');
  return context;
};
