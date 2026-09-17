/**
 * Settings Management Hook
 *
 * Manages non-sensitive system configuration from .env files.
 * Handles loading, saving, and state management for settings.
 */

import { useState, useCallback } from 'react';

import { getEnv } from '../../config/constants';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { getCached, setCached } from '../../utils/pageCache';

// =====================================================
// TYPES
// =====================================================

export interface ServerConfig {
  SERVER_NAME: string;
  SERVER_URL: string;
  SERVER_PORT: string;
  ENVIRONMENT: string;
  DEBUG: string;
  PYTHONUNBUFFERED: string;
  AI_PROVIDER: string;
  AI_AGENT_PROVIDER: string;
  AI_AGENT_MODEL: string;
  AI_VISION_PROVIDER: string;
  AI_VISION_MODEL: string;
  AI_TEXT_PROVIDER: string;
  AI_TEXT_MODEL: string;
  ANTHROPIC_API_KEY: string;
  OPENROUTER_API_KEY: string;
  OPENAI_API_KEY: string;
  MINIMAX_API_KEY: string;
  GOOGLE_API_KEY: string;
  LOCAL_AI_BASE_URL: string;
  LOCAL_AI_MODEL: string;
  LOCAL_AI_API_KEY: string;
}

export interface FrontendConfig {
  VITE_SERVER_URL: string;
  VITE_SLAVE_SERVER_URL: string;
  VITE_GRAFANA_URL: string;
  VITE_CLOUDFLARE_R2_PUBLIC_URL: string;
  VITE_DEV_MODE: string;
  VITE_FEATURE_DEPLOYMENTS: string;
  VITE_FEATURE_RUN_VERSION_SELECTOR: string;
  VITE_NAV_HIDDEN: string;
  VITE_NAV_DISABLED: string;
  VITE_NAV_COMING_SOON: string;
}

export interface HostConfig {
  HOST_NAME: string;
  HOST_PORT: string;
  HOST_URL: string;
  HOST_API_URL: string;
}

export interface DeviceConfig {
  DEVICE_NAME: string;
  DEVICE_MODEL: string;
  DEVICE_VIDEO: string;
  DEVICE_VIDEO_STREAM_PATH: string;
  DEVICE_VIDEO_CAPTURE_PATH: string;
  DEVICE_VIDEO_FPS: string;
  DEVICE_VIDEO_AUDIO: string;
  DEVICE_IP: string;
  DEVICE_PORT: string;
  DEVICE_POWER_NAME: string;
  DEVICE_POWER_IP: string;
}

export interface SettingsConfig {
  server: ServerConfig;
  frontend: FrontendConfig;
  host: HostConfig;
  devices: { [key: string]: DeviceConfig };
}

export interface UseSettingsReturn {
  config: SettingsConfig;
  loading: boolean;
  saving: boolean;
  error: string | null;
  success: boolean;
  loadConfig: () => Promise<void>;
  saveConfig: () => Promise<void>;
  updateServerConfig: (field: keyof ServerConfig, value: string) => void;
  updateFrontendConfig: (field: keyof FrontendConfig, value: string) => void;
  updateHostConfig: (field: keyof HostConfig, value: string) => void;
  updateDeviceConfig: (deviceKey: string, field: keyof DeviceConfig, value: string) => void;
  addDevice: () => void;
  deleteDevice: (deviceKey: string) => void;
  setError: (error: string | null) => void;
  setSuccess: (success: boolean) => void;
}

// =====================================================
// DEFAULT CONFIG
// =====================================================

const getDefaultConfig = (): SettingsConfig => ({
  server: {
    SERVER_NAME: '',
    SERVER_URL: '',
    SERVER_PORT: '5109',
    ENVIRONMENT: 'development',
    DEBUG: '1',
    PYTHONUNBUFFERED: '1',
    AI_PROVIDER: '',
    AI_AGENT_PROVIDER: 'anthropic',
    AI_AGENT_MODEL: 'claude-sonnet-4-20250514',
    AI_VISION_PROVIDER: '',
    AI_VISION_MODEL: '',
    AI_TEXT_PROVIDER: '',
    AI_TEXT_MODEL: '',
    ANTHROPIC_API_KEY: '',
    OPENROUTER_API_KEY: '',
    OPENAI_API_KEY: '',
    MINIMAX_API_KEY: '',
    GOOGLE_API_KEY: '',
    LOCAL_AI_BASE_URL: '',
    LOCAL_AI_MODEL: '',
    LOCAL_AI_API_KEY: '',
  },
  frontend: {
    // These show the EFFECTIVE values, so they go through getEnv: a container that
    // overrode them at runtime (public/config.js) must not display the baked-in ones.
    VITE_SERVER_URL: getEnv('VITE_SERVER_URL'),
    VITE_SLAVE_SERVER_URL: getEnv('VITE_SLAVE_SERVER_URL'),
    VITE_GRAFANA_URL: getEnv('VITE_GRAFANA_URL'),
    VITE_CLOUDFLARE_R2_PUBLIC_URL: getEnv('VITE_CLOUDFLARE_R2_PUBLIC_URL'),
    VITE_DEV_MODE: getEnv('VITE_DEV_MODE', 'true'),
    VITE_FEATURE_DEPLOYMENTS: getEnv('VITE_FEATURE_DEPLOYMENTS', 'true'),
    VITE_FEATURE_RUN_VERSION_SELECTOR: getEnv('VITE_FEATURE_RUN_VERSION_SELECTOR', 'false'),
    VITE_NAV_HIDDEN: '',
    VITE_NAV_DISABLED: '',
    VITE_NAV_COMING_SOON: '',
  },
  host: {
    HOST_NAME: '',
    HOST_PORT: '6109',
    HOST_URL: '',
    HOST_API_URL: '',
  },
  devices: {},
});

// =====================================================
// HOOK
// =====================================================

export const useSettings = (): UseSettingsReturn => {
  const [config, setConfig] = useState<SettingsConfig>(() => getCached<SettingsConfig>('settings-config') ?? getDefaultConfig());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  /**
   * Load configuration from backend
   */
  const loadConfig = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      console.log('[@hook:useSettings] Loading configuration...');
      const data = await api.get(buildServerUrl('/server/settings/config'));
      console.log('[@hook:useSettings] Configuration loaded successfully');
      // The settings API reads frontend/.env and frontend/.env.local from the running deployment.
      // Merge those values over runtime defaults so the page shows the deployed frontend config.
      const defaults = getDefaultConfig();
      const merged: SettingsConfig = {
        server: { ...defaults.server, ...data.server },
        frontend: { ...defaults.frontend, ...(data.frontend ?? {}) },
        host: { ...defaults.host, ...data.host },
        devices: data.devices ?? {},
      };
      setConfig(merged);
      setCached('settings-config', merged);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load configuration';
      console.error('[@hook:useSettings] Error loading configuration:', err);
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Save configuration to backend
   */
  const saveConfig = useCallback(async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(false);

      console.log('[@hook:useSettings] Saving configuration...');
      await api.post(buildServerUrl('/server/settings/config'), config);
      console.log('[@hook:useSettings] Configuration saved successfully');
      setSuccess(true);

      // Clear success message after 5 seconds
      setTimeout(() => setSuccess(false), 5000);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save configuration';
      console.error('[@hook:useSettings] Error saving configuration:', err);
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  }, [config]);

  /**
   * Update server configuration field
   */
  const updateServerConfig = useCallback((field: keyof ServerConfig, value: string) => {
    setConfig((prev) => ({
      ...prev,
      server: { ...prev.server, [field]: value },
    }));
  }, []);

  /**
   * Update frontend configuration field
   */
  const updateFrontendConfig = useCallback((field: keyof FrontendConfig, value: string) => {
    setConfig((prev) => ({
      ...prev,
      frontend: { ...prev.frontend, [field]: value },
    }));
  }, []);

  /**
   * Update host configuration field
   */
  const updateHostConfig = useCallback((field: keyof HostConfig, value: string) => {
    setConfig((prev) => ({
      ...prev,
      host: { ...prev.host, [field]: value },
    }));
  }, []);

  /**
   * Update device configuration field
   */
  const updateDeviceConfig = useCallback(
    (deviceKey: string, field: keyof DeviceConfig, value: string) => {
      setConfig((prev) => ({
        ...prev,
        devices: {
          ...prev.devices,
          [deviceKey]: {
            ...prev.devices[deviceKey],
            [field]: value,
          },
        },
      }));
    },
    [],
  );

  /**
   * Add a new device
   */
  const addDevice = useCallback(() => {
    setConfig((prev) => {
      const deviceNumbers = Object.keys(prev.devices)
        .map((key) => parseInt(key.replace('DEVICE', '')))
        .filter((n) => !isNaN(n));
      const nextNumber = deviceNumbers.length > 0 ? Math.max(...deviceNumbers) + 1 : 1;
      const newDeviceKey = `DEVICE${nextNumber}`;

      return {
        ...prev,
        devices: {
          ...prev.devices,
          [newDeviceKey]: {
            DEVICE_NAME: '',
            DEVICE_MODEL: '',
            DEVICE_VIDEO: '',
            DEVICE_VIDEO_STREAM_PATH: '',
            DEVICE_VIDEO_CAPTURE_PATH: '',
            DEVICE_VIDEO_FPS: '10',
            DEVICE_VIDEO_AUDIO: '',
            DEVICE_IP: '',
            DEVICE_PORT: '',
            DEVICE_POWER_NAME: '',
            DEVICE_POWER_IP: '',
          },
        },
      };
    });
  }, []);

  /**
   * Delete a device
   */
  const deleteDevice = useCallback((deviceKey: string) => {
    setConfig((prev) => {
      const newDevices = { ...prev.devices };
      delete newDevices[deviceKey];
      return { ...prev, devices: newDevices };
    });
  }, []);

  return {
    config,
    loading,
    saving,
    error,
    success,
    loadConfig,
    saveConfig,
    updateServerConfig,
    updateFrontendConfig,
    updateHostConfig,
    updateDeviceConfig,
    addDevice,
    deleteDevice,
    setError,
    setSuccess,
  };
};
