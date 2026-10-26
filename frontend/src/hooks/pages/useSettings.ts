/**
 * Settings Management Hook
 *
 * Manages non-sensitive system configuration from .env files.
 * Handles loading, saving, and state management for settings.
 */

import { useState, useCallback, useRef, useEffect } from 'react';

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
  // Default monitoring profile of every device on the host ('' = tv_app). Set from Settings -> Host & Devices.
  MONITOR_PROFILE?: string;
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
  // '' = follow the host's MONITOR_PROFILE
  DEVICE_MONITOR_PROFILE?: string;
}

// A capture card reported by the host's `/host/system/grabbers` endpoint.
// `audio` is the ALSA plughw string that the host detected on the same USB
// parent as the video node (e.g. an MS2109 has both UVC and UAC under one
// USB device). `has_audio=false` means the host walked the USB tree and
// found no companion sound card on that port (some capture dongles ship
// video-only).
export interface DetectedGrabber {
  video: string;
  audio: string;
  has_audio: boolean;
  usb_id: string;
  usb_path: string;
  vendor: string;
  product: string;
}

export interface DetectedBluetooth {
  name: string;
  mac: string;
  usb_id: string;
  usb_path: string;
}

export interface DetectedInfrared {
  name: string;
  usb_id: string;
  usb_path: string;
}

export interface DetectedGrabberReport {
  grabbers: DetectedGrabber[];
  bluetooth: DetectedBluetooth[];
  infrared: DetectedInfrared[];
}

// Where the current DEVICE_VIDEO_AUDIO value is coming from, surfaced in the
// form as a small caption under the audio field so the operator understands
// whether the value was auto-derived or typed by hand.
//
//   detected : the host reports a UAC card on the same USB parent as the
//              video node, and we have already auto-filled DEVICE_VIDEO_AUDIO
//              from it. Editing the field would be a manual override that
//              reverts on the next page load (loadGrabbers reapplies).
//   env      : the .env had a value the operator typed previously; the host
//              either reported no audio for this video, or the report hasn't
//              loaded yet. Editing the field is the normal path.
//   missing  : the .env had no value and the host reported no audio either —
//              the field is empty by design. The operator can type a manual
//              value (e.g. for a cross-port HDMI audio source) but that
//              value will not survive a page reload if detection still says
//              no audio. (If detection later finds audio, the field is
//              auto-filled and `env` becomes `detected`.)
export type AudioSource = 'detected' | 'env' | 'missing';

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
  // Detected grabbers: the host reports UVC + paired UAC + bluetooth + IR
  // through /server/settings/host-grabbers. The Settings page surfaces the
  // capture cards in a "Detected Grabbers" panel with a one-click "Use"
  // button that fills the next free device's DEVICE_VIDEO + DEVICE_VIDEO_AUDIO
  // together. The list is per-host; loadGrabbers is called alongside
  // loadHostConfig when the operator selects a host.
  grabbers: DetectedGrabberReport;
  grabbersLoading: boolean;
  grabbersError: string | null;
  loadGrabbers: (hostName: string) => Promise<boolean>;
  // Returns the set of grabber `video` paths that are already referenced
  // by some device on the current page (used to mark "in use" rows).
  usedGrabberVideoPaths: () => Set<string>;
  // Fills DEVICE_VIDEO + DEVICE_VIDEO_AUDIO on `deviceKey` from a grabber.
  // If `deviceKey` is empty, the next device with no DEVICE_VIDEO set is
  // picked (so a single "Use" on a fresh page just works).
  applyGrabberToDevice: (grabber: DetectedGrabber, deviceKey?: string) => string | null;
  // Tells the form which source is currently in effect for a device's
  // DEVICE_VIDEO_AUDIO field. The form renders a small caption under the
  // audio TextField so the operator can tell auto-detected values apart
  // from operator-typed .env values at a glance.
  getAudioSource: (deviceKey: string) => AudioSource;
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
  const [grabbers, setGrabbers] = useState<DetectedGrabberReport>({ grabbers: [], bluetooth: [], infrared: [] });
  const [grabbersLoading, setGrabbersLoading] = useState(false);
  const [grabbersError, setGrabbersError] = useState<string | null>(null);
  // Ref-mirror of `grabbers` so the setConfig functional updaters in
  // loadGrabbers and updateDeviceConfig can read the freshest detection
  // without rebuilding the callback every time grabbers change. Without
  // this, loadGrabbers's auto-fill pass would use the empty initial list
  // (or the previous host's list) and miss the new host's devices.
  const grabbersRef = useRef<DetectedGrabberReport>(grabbers);
  useEffect(() => { grabbersRef.current = grabbers; }, [grabbers]);

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
        server: { ...defaults.server, ...(data.server ?? {}) },
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
    // No page-level `loading` here: the page swaps to a full spinner on it, so
    // toggling it right after loadConfig made Settings visibly load twice.
    // Callers track readiness themselves (Settings' hostConfigReady).
    setError(null);
    try {
      const data = await api.get(buildServerUrl(`/server/settings/host-config?host_name=${encodeURIComponent(hostName)}`));
      setConfig((prev) => ({ ...prev, host: { ...getDefaultConfig().host, ...data.host }, devices: data.devices ?? {} }));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to load configuration for ${hostName}`);
      return false;
    }
  }, []);

  const loadGrabbers = useCallback(async (hostName: string) => {
    if (!hostName) return false;
    setGrabbersLoading(true);
    setGrabbersError(null);
    try {
      const data = await api.get(buildServerUrl(`/server/settings/host-grabbers?host_name=${encodeURIComponent(hostName)}`));
      const fresh: DetectedGrabberReport = {
        grabbers: data.grabbers ?? [],
        bluetooth: data.bluetooth ?? [],
        infrared: data.infrared ?? [],
      };
      setGrabbers(fresh);
      grabbersRef.current = fresh;
      // Auto-fill DEVICE_VIDEO_AUDIO for every device whose DEVICE_VIDEO
      // matches a detected grabber, regardless of what the .env says.
      // This is the "audio follows the dynamic mapping" rule: detection
      // wins over the operator-typed .env value, and the .env only
      // remains in effect when no detection exists for that video.
      setConfig((prev) => {
        const next = { ...prev.devices };
        let changed = false;
        for (const [k, dev] of Object.entries(next)) {
          if (!dev.DEVICE_VIDEO) continue;
          const detected = fresh.grabbers.find((g) => g.video === dev.DEVICE_VIDEO);
          if (detected && detected.has_audio) {
            if (dev.DEVICE_VIDEO_AUDIO !== detected.audio) {
              next[k] = { ...dev, DEVICE_VIDEO_AUDIO: detected.audio };
              changed = true;
            }
          }
        }
        return changed ? { ...prev, devices: next } : prev;
      });
      return true;
    } catch (err) {
      // Don't surface a hard error: a host running vpt-host as a user
      // without the video group simply reports zero grabbers, which is
      // the same shape the bash script produced before this fix.
      // We still log it for the operator console.
      const message = err instanceof Error ? err.message : `Failed to detect grabbers on ${hostName}`;
      console.warn('[@hook:useSettings] grabber detection failed:', message);
      setGrabbersError(message);
      setGrabbers({ grabbers: [], bluetooth: [], infrared: [] });
      grabbersRef.current = { grabbers: [], bluetooth: [], infrared: [] };
      return false;
    } finally {
      setGrabbersLoading(false);
    }
  }, []);

  const usedGrabberVideoPaths = useCallback((): Set<string> => {
    const used = new Set<string>();
    for (const device of Object.values(config.devices)) {
      if (device.DEVICE_VIDEO) {
        used.add(device.DEVICE_VIDEO);
      }
    }
    return used;
  }, [config.devices]);

  const applyGrabberToDevice = useCallback((grabber: DetectedGrabber, deviceKey?: string): string | null => {
    let targetKey = deviceKey;
    if (!targetKey) {
      // Pick the first device with no DEVICE_VIDEO yet; if all are filled,
      // fall back to the lexicographically first device key so the operator
      // can still see the result of clicking "Use" (and clear the field
      // manually if they want a different one).
      const keys = Object.keys(config.devices).sort();
      targetKey = keys.find((k) => !config.devices[k].DEVICE_VIDEO) ?? keys[0];
    }
    if (!targetKey) {
      return null;
    }
    setConfig((prev) => {
      const existing = prev.devices[targetKey!] ?? {
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
      };
      return {
        ...prev,
        devices: {
          ...prev.devices,
          [targetKey!]: {
            ...existing,
            DEVICE_VIDEO: grabber.video,
            DEVICE_VIDEO_AUDIO: grabber.has_audio ? grabber.audio : '',
          },
        },
      };
    });
    return targetKey;
  }, [config.devices]);

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
      setConfig((prev) => {
        const updated = { ...prev.devices[deviceKey], [field]: value };
        // When the operator changes DEVICE_VIDEO, mirror the audio from the
        // detection so the field stays consistent. No detection → clear the
        // audio so the operator sees they need to type one. We read
        // grabbersRef rather than the closure `grabbers` to dodge stale
        // callbacks when grabbers reload after a host switch.
        if (field === 'DEVICE_VIDEO') {
          const detected = grabbersRef.current.grabbers.find((g) => g.video === value);
          updated.DEVICE_VIDEO_AUDIO = detected && detected.has_audio ? detected.audio : '';
        }
        return {
          ...prev,
          devices: {
            ...prev.devices,
            [deviceKey]: updated,
          },
        };
      });
    },
    [],
  );

  // Tell the form where the current DEVICE_VIDEO_AUDIO value came from, so
  // it can render a "auto-detected from USB 3-1" / "from .env" / "no
  // audio detected" caption. The rule: detection wins over .env, and the
  // .env value is only in effect when no detection exists for this video.
  const getAudioSource = useCallback((deviceKey: string): AudioSource => {
    const dev = config.devices[deviceKey];
    if (!dev || !dev.DEVICE_VIDEO) return 'missing';
    const detected = grabbersRef.current.grabbers.find((g) => g.video === dev.DEVICE_VIDEO);
    if (detected && detected.has_audio) {
      // Detection exists. The form value is the detected one (either auto-
      // filled on load or on the last DEVICE_VIDEO change). Anything else
      // is a one-shot operator override that will revert on the next load.
      if (dev.DEVICE_VIDEO_AUDIO === detected.audio) return 'detected';
      return 'env';
    }
    // No detection for this video. Whatever the field says is from the
    // .env (typed by the operator previously, or left empty).
    return dev.DEVICE_VIDEO_AUDIO ? 'env' : 'missing';
  }, [config.devices]);

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
    grabbers,
    grabbersLoading,
    grabbersError,
    loadGrabbers,
    usedGrabberVideoPaths,
    applyGrabberToDevice,
    getAudioSource,
  };
};
