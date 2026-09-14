/**
 * Notifications Hook
 * 
 * Simple hook for managing notification integrations, rules, and history.
 * Follows the same patterns as useDeviceModels.ts for consistency.
 */

import { useState, useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import {
  NotificationIntegration,
  NotificationRule,
  NotificationHistory,
  NotificationIntegrationCreatePayload,
  NotificationRuleCreatePayload,
} from '../../types/pages/Notifications_Types';

interface UseNotificationsReturn {
  // Integrations
  integrations: NotificationIntegration[];
  loadIntegrations: () => Promise<void>;
  createIntegration: (payload: NotificationIntegrationCreatePayload) => Promise<void>;
  updateIntegration: (id: string, payload: NotificationIntegrationCreatePayload) => Promise<void>;
  deleteIntegration: (id: string) => Promise<void>;
  testIntegration: (id: string) => Promise<{ success: boolean; message: string }>;

  // Rules
  rules: NotificationRule[];
  loadRules: () => Promise<void>;
  createRule: (payload: NotificationRuleCreatePayload) => Promise<void>;
  updateRule: (id: string, payload: NotificationRuleCreatePayload) => Promise<void>;
  deleteRule: (id: string) => Promise<void>;

  // History
  history: NotificationHistory[];
  loadHistory: () => Promise<void>;

  // State
  isLoading: boolean;
  error: string | null;
}

const NOTIFICATIONS_API_BASE_URL = buildServerUrl('/server/notifications');

export const useNotifications = (): UseNotificationsReturn => {
  // State
  const [integrations, setIntegrations] = useState<NotificationIntegration[]>([]);
  const [rules, setRules] = useState<NotificationRule[]>([]);
  const [history, setHistory] = useState<NotificationHistory[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Helper function for API calls (uses apiClient for JWT auth)
  const apiCall = useCallback(async <T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> => {
    const url = `${NOTIFICATIONS_API_BASE_URL}${endpoint}`;
    const method = (options.method || 'GET').toUpperCase();
    const body = options.body ? JSON.parse(options.body as string) : undefined;

    if (method === 'GET') return api.get(url);
    if (method === 'POST') return api.post(url, body);
    if (method === 'PUT') return api.put(url, body);
    if (method === 'DELETE') return api.delete(url);
    throw new Error(`Unsupported method: ${method}`);
  }, []);

  // =====================================================
  // INTEGRATIONS
  // =====================================================

  const loadIntegrations = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await apiCall<NotificationIntegration[]>('/integrations');
      setIntegrations(data);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load integrations';
      setError(errorMessage);
      console.error('[@hook:useNotifications:loadIntegrations] Error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  const createIntegration = useCallback(async (payload: NotificationIntegrationCreatePayload) => {
    try {
      setIsLoading(true);
      setError(null);
      const newIntegration = await apiCall<NotificationIntegration>('/integrations', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setIntegrations(prev => [...prev, newIntegration]);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create integration';
      setError(errorMessage);
      console.error('[@hook:useNotifications:createIntegration] Error:', err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  const updateIntegration = useCallback(async (id: string, payload: NotificationIntegrationCreatePayload) => {
    try {
      setIsLoading(true);
      setError(null);
      const updatedIntegration = await apiCall<NotificationIntegration>(`/integrations/${id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setIntegrations(prev => prev.map(integration => 
        integration.id === id ? updatedIntegration : integration
      ));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to update integration';
      setError(errorMessage);
      console.error('[@hook:useNotifications:updateIntegration] Error:', err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  const deleteIntegration = useCallback(async (id: string) => {
    try {
      setIsLoading(true);
      setError(null);
      await apiCall(`/integrations/${id}`, {
        method: 'DELETE',
      });
      setIntegrations(prev => prev.filter(integration => integration.id !== id));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete integration';
      setError(errorMessage);
      console.error('[@hook:useNotifications:deleteIntegration] Error:', err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  const testIntegration = useCallback(async (id: string): Promise<{ success: boolean; message: string }> => {
    try {
      setError(null);
      const result = await apiCall<{ success: boolean; message: string }>(`/integrations/${id}/test`, {
        method: 'POST',
      });
      return result;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to test integration';
      console.error('[@hook:useNotifications:testIntegration] Error:', err);
      return { success: false, message: errorMessage };
    }
  }, [apiCall]);

  // =====================================================
  // RULES
  // =====================================================

  const loadRules = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await apiCall<NotificationRule[]>('/rules');
      setRules(data);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load rules';
      setError(errorMessage);
      console.error('[@hook:useNotifications:loadRules] Error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  const createRule = useCallback(async (payload: NotificationRuleCreatePayload) => {
    try {
      setIsLoading(true);
      setError(null);
      const newRule = await apiCall<NotificationRule>('/rules', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setRules(prev => [...prev, newRule]);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create rule';
      setError(errorMessage);
      console.error('[@hook:useNotifications:createRule] Error:', err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  const updateRule = useCallback(async (id: string, payload: NotificationRuleCreatePayload) => {
    try {
      setIsLoading(true);
      setError(null);
      const updatedRule = await apiCall<NotificationRule>(`/rules/${id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setRules(prev => prev.map(rule => 
        rule.id === id ? updatedRule : rule
      ));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to update rule';
      setError(errorMessage);
      console.error('[@hook:useNotifications:updateRule] Error:', err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  const deleteRule = useCallback(async (id: string) => {
    try {
      setIsLoading(true);
      setError(null);
      await apiCall(`/rules/${id}`, {
        method: 'DELETE',
      });
      setRules(prev => prev.filter(rule => rule.id !== id));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete rule';
      setError(errorMessage);
      console.error('[@hook:useNotifications:deleteRule] Error:', err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  // =====================================================
  // HISTORY
  // =====================================================

  const loadHistory = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await apiCall<NotificationHistory[]>('/history');
      setHistory(data);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load history';
      setError(errorMessage);
      console.error('[@hook:useNotifications:loadHistory] Error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [apiCall]);

  return {
    // Integrations
    integrations,
    loadIntegrations,
    createIntegration,
    updateIntegration,
    deleteIntegration,
    testIntegration,

    // Rules
    rules,
    loadRules,
    createRule,
    updateRule,
    deleteRule,

    // History
    history,
    loadHistory,

    // State
    isLoading,
    error,
  };
};
