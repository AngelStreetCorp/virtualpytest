import { useCallback, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

export type SettingKey =
  | 'frontend_deploy_host'
  | 'frontend_deploy_ssh_user'
  | 'frontend_deploy_ssh_key'
  | 'db_dsn'
  | 'database_agent'
  | 'github_token'
  | 'vm_agent_action_token';

/** One setting as GET /server/platform-update/settings returns it. Secrets never carry a value (TASK-128). */
export interface SettingView {
  secret: boolean;
  set: boolean;
  source: 'store' | 'env' | 'none';
  value?: string;
}

export type SettingsView = Record<SettingKey, SettingView>;

/** GET/POST /settings/ssh-key (TASK-128 G4): the server's key for the frontend leg and the lines to paste on the frontend VM. */
export interface ServerKeyView {
  exists: boolean;
  path: string;
  public_key: string;
  authorized_keys_line: string;
  frontend_command: string;
  created?: boolean;
}

const BASE = '/server/platform-update/settings';

const call = async (path: string, init?: { method?: string; body?: string }) => {
  const response = await apiClient(buildServerUrl(path), init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) throw new Error(data.error || data.message || `HTTP ${response.status}`);
  return data;
};

export const usePlatformUpdateSettings = () => {
  const [settings, setSettings] = useState<SettingsView | null>(null);
  /** Where the settings are kept: the database table (per server) or, until its migration is applied, a file. */
  const [storage, setStorage] = useState<'db' | 'file' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const guard = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed');
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const load = useCallback(
    () => guard(async () => { const data = await call(BASE); setSettings(data.settings); setStorage(data.storage ?? null); return true; }),
    [guard]
  );

  /** Send only the changed keys; an empty string clears a key back to the .env fallback. */
  const save = useCallback(
    (changes: Partial<Record<SettingKey, string>>) =>
      guard(async () => { const data = await call(BASE, { method: 'PUT', body: JSON.stringify(changes) }); setSettings(data.settings); setStorage(data.storage ?? null); return true; }),
    [guard]
  );

  /** Makes a new agent token; the returned command holds it, and it is not available again afterwards. */
  const generateToken = useCallback(
    () => guard(async () => {
      const data = await call(`${BASE}/db-backup/token`, { method: 'POST' });
      setSettings(data.settings);
      return { command: String(data.command) };
    }),
    [guard]
  );

  const checkAgent = useCallback(
    () => guard(async () => {
      const data = await call(`${BASE}/db-backup/check`, { method: 'POST' });
      return { ok: Boolean(data.ok), detail: String(data.detail || '') };
    }),
    [guard]
  );

  const [serverKey, setServerKey] = useState<ServerKeyView | null>(null);

  const loadKey = useCallback(
    () => guard(async () => { setServerKey((await call(`${BASE}/ssh-key`)) as ServerKeyView); return true; }),
    [guard]
  );

  /** Creates the key when missing; an existing key is never replaced. */
  const createKey = useCallback(
    () => guard(async () => { setServerKey((await call(`${BASE}/ssh-key`, { method: 'POST' })) as ServerKeyView); return true; }),
    [guard]
  );

  return { settings, storage, busy, error, load, save, generateToken, checkAgent, serverKey, loadKey, createKey };
};
