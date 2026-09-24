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

// The Settings page now surfaces every key each .env file actually contains
// (not a fixed whitelist), so both configs are open-ended string maps. Known
// keys are still accessed by name (config.server.SERVER_NAME etc.) — that
// still typechecks fine against an index signature.
export interface ServerConfig {
  [key: string]: string;
}

export interface FrontendConfig {
  [key: string]: string;
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
  serverSensitiveKeys: string[];
  frontend: FrontendConfig;
  frontendSensitiveKeys: string[];
  // 'ssh' = read from the real frontend VM over the settings bridge; 'local' = this
  // server's own (usually irrelevant) copy. See reference_multi_server_registry.
  frontendSource: 'ssh' | 'local';
  frontendWarning: string | null;
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
  // Resolves with the sections actually written ('server' | 'frontend' | 'host'),
  // so the caller can flag which services now need a restart to apply the change.
  saveConfig: () => Promise<string[]>;
  loadHostConfig: (hostName: string) => Promise<boolean>;
  saveHostConfig: (hostName: string) => Promise<boolean>;
  updateServerConfig: (field: string, value: string) => void;
  updateFrontendConfig: (field: string, value: string) => void;
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
  serverSensitiveKeys: [],
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
  frontendSensitiveKeys: [],
  frontendSource: 'local',
  frontendWarning: null,
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
        serverSensitiveKeys: data.server_sensitive_keys ?? [],
        frontend: { ...defaults.frontend, ...(data.frontend ?? {}) },
        frontendSensitiveKeys: data.frontend_sensitive_keys ?? [],
        frontendSource: data.frontend_source ?? 'local',
        frontendWarning: data.frontend_warning ?? null,
        // Host and device settings are loaded separately from a selected
        // registered host; never display this server's local checkout copy.
        host: defaults.host,
        devices: {},
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

  const loadHostConfig = useCallback(async (hostName: string) => {
    if (!hostName) return false;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get(buildServerUrl(`/server/settings/host-config?host_name=${encodeURIComponent(hostName)}`));
      setConfig((prev) => ({ ...prev, host: { ...getDefaultConfig().host, ...data.host }, devices: data.devices ?? {} }));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to load configuration for ${hostName}`);
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const saveHostConfig = useCallback(async (hostName: string) => {
    if (!hostName) {
      setError('Select a host before saving host and device settings');
      return false;
    }
    try {
      setSaving(true);
      setError(null);
      await api.post(buildServerUrl('/server/settings/host-config'), { host_name: hostName, host: config.host, devices: config.devices });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 5000);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to save configuration for ${hostName}`);
      return false;
    } finally {
      setSaving(false);
    }
  }, [config.devices, config.host]);

  /**
   * Save configuration to backend
   */
  const saveConfig = useCallback(async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(false);

      console.log('[@hook:useSettings] Saving configuration...');
      const localConfig = { server: config.server, frontend: config.frontend };
      const result = await api.post(buildServerUrl('/server/settings/config'), localConfig);
      console.log('[@hook:useSettings] Configuration saved successfully');
      setSuccess(true);

      // Clear success message after 5 seconds
      setTimeout(() => setSuccess(false), 5000);
      return (result?.updated_files ?? []) as string[];
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save configuration';
      console.error('[@hook:useSettings] Error saving configuration:', err);
      setError(errorMessage);
      return [];
    } finally {
      setSaving(false);
    }
  }, [config]);

  /**
   * Update server configuration field
   */
  const updateServerConfig = useCallback((field: string, value: string) => {
    setConfig((prev) => ({
      ...prev,
      server: { ...prev.server, [field]: value },
    }));
  }, []);

  /**
   * Update frontend configuration field
   */
  const updateFrontendConfig = useCallback((field: string, value: string) => {
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
    loadHostConfig,
    saveHostConfig,
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
