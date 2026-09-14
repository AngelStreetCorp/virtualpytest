/**
 * useIdentityMap
 *
 * Reactive wrapper around the shared identityMapCache module. Both maps load
 * exactly once per page; consuming components re-render once the data is ready.
 *
 * Script key format : "folder/script_name"  (the cache also indexes by basename)
 * Campaign key format: "campaign_name"
 */

import { useEffect, useState } from 'react';

import { apiClientJson } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import {
  IdentityEntry,
  isCampaignMapLoaded,
  isScriptMapLoaded,
  loadCampaignIdentityMap,
  loadScriptIdentityMap,
  lookupCampaignIdentity,
  getExactScriptIdentity,
  lookupScriptIdentity,
  normalizeScriptRef,
  setScriptIdentity,
  subscribeIdentityMapLoaded,
} from '../utils/identityMapCache';

export type { IdentityEntry };

export function useIdentityMap() {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (isScriptMapLoaded() && isCampaignMapLoaded()) return undefined;
    const unsubscribe = subscribeIdentityMapLoaded(() => setTick((t) => t + 1));
    void loadScriptIdentityMap();
    void loadCampaignIdentityMap();
    return unsubscribe;
  }, []);

  function resolveScript(rawName: string): IdentityEntry {
    return lookupScriptIdentity(rawName) || {};
  }

  function resolveCampaign(rawName: string): IdentityEntry {
    return lookupCampaignIdentity(rawName) || {};
  }

  function scriptLabel(rawName: string): string {
    const entry = resolveScript(rawName);
    return entry.display_name ?? rawName;
  }

  function campaignLabel(rawName: string): string {
    const entry = resolveCampaign(rawName);
    return entry.display_name ?? rawName;
  }

  /**
   * Persist prefix / display_name for one script_ref and update the cache in
   * place so the chip changes immediately. Clearing both fields removes the
   * row server-side. Rolls the cache back if the write fails.
   */
  async function saveScriptIdentity(
    rawName: string,
    entry: IdentityEntry,
  ): Promise<{ success: boolean; warning?: string; error?: string }> {
    const scriptRef = normalizeScriptRef(rawName);
    const previous = getExactScriptIdentity(scriptRef);
    const next: IdentityEntry = {
      prefix: entry.prefix?.trim() || undefined,
      display_name: entry.display_name?.trim() || undefined,
    };

    setScriptIdentity(scriptRef, next);
    try {
      const res = await apiClientJson<{ success: boolean; warning?: string; error?: string }>(
        buildServerUrl('/server/script-identity/set'),
        {
          method: 'POST',
          body: JSON.stringify({
            script_ref: scriptRef,
            prefix: next.prefix ?? '',
            display_name: next.display_name ?? '',
          }),
        },
      );
      return { success: true, warning: res?.warning };
    } catch (err: any) {
      setScriptIdentity(scriptRef, previous);
      return { success: false, error: err?.message || 'Failed to save identity' };
    }
  }

  async function clearScriptIdentity(rawName: string): Promise<boolean> {
    return (await saveScriptIdentity(rawName, {})).success;
  }

  const ready = isScriptMapLoaded() && isCampaignMapLoaded();

  return {
    resolveScript,
    resolveCampaign,
    scriptLabel,
    campaignLabel,
    saveScriptIdentity,
    clearScriptIdentity,
    normalizeRef: normalizeScriptRef,
    ready,
  };
}
