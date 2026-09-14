/**
 * identityMapCache
 *
 * Single source of truth for the script/campaign identity maps. Both
 * `useIdentityMap` (reactive hook) and `ensureScriptIdentityMap` (fire-and-
 * forget primer used inside executionUtils) load through this module, so the
 * page issues at most one request per source per session.
 *
 * The SCRIPT map now has two sources, merged on load:
 *   1. `/data/script_identity_map.json` — static JSON in the frontend bundle,
 *      the legacy hand-edited file, kept as a fallback for one release.
 *   2. `GET /server/script-identity/list` — the `executable_identity` table,
 *      the editable source of truth (Test Cases page). Wins per key.
 *
 * Either source failing is non-fatal: an un-migrated deploy keeps rendering the
 * bundled JSON, and a deploy whose bundle ships the empty platform default
 * renders the DB values alone.
 *
 * The CAMPAIGN map is still bundle-only — `kind='campaign'` rows exist in the
 * schema but nothing writes them yet.
 */

import { apiClientJson } from './apiClient';
import { buildServerUrl } from './buildUrlUtils';

export interface IdentityEntry {
  prefix?: string;
  display_name?: string;
}

const SCRIPT_MAP_URL = '/data/script_identity_map.json';
const CAMPAIGN_MAP_URL = '/data/campaign_identity_map.json';

interface ScriptMapShape {
  scripts: Record<string, IdentityEntry>;
  byBasename: Record<string, IdentityEntry>;
}

let _scriptMap: ScriptMapShape | null = null;
let _campaignMap: Record<string, IdentityEntry> | null = null;
let _scriptPromise: Promise<ScriptMapShape> | null = null;
let _campaignPromise: Promise<Record<string, IdentityEntry>> | null = null;
const _listeners: Set<() => void> = new Set();

const notify = () => {
  _listeners.forEach((fn) => {
    try {
      fn();
    } catch (err) {
      console.warn('[@identityMapCache] listener error', err);
    }
  });
};

export const normalizeScriptRef = (scriptName: string): string => {
  let ref = scriptName.replace(/\\/g, '/');
  if (ref.startsWith('./')) ref = ref.substring(2);
  if (ref.startsWith('test_scripts/')) ref = ref.substring('test_scripts/'.length);
  if (ref.startsWith('test_campaign/')) ref = ref.substring('test_campaign/'.length);
  // Strip timestamp suffix (e.g. "gw/gw_info.py_1775050202" → "gw/gw_info.py")
  ref = ref.replace(/_\d{8,}$/, '');
  if (ref.endsWith('.py')) ref = ref.slice(0, -3);
  return ref.replace(/^\/+|\/+$/g, '');
};

const basenameOf = (normKey: string): string => {
  const slashIdx = normKey.lastIndexOf('/');
  return slashIdx >= 0 ? normKey.substring(slashIdx + 1) : normKey;
};

/** Rebuild the basename index from the exact-key map. */
const reindex = (scripts: Record<string, IdentityEntry>): ScriptMapShape => {
  const byBasename: Record<string, IdentityEntry> = {};
  for (const [normKey, value] of Object.entries(scripts)) {
    // Index by basename for every entry (including bare keys with no folder),
    // so a "web/foo" query can resolve a map entry keyed as bare "foo" and
    // vice-versa — the script list and the bundled map don't always agree on
    // whether the folder prefix is present, and converting a disk script to a
    // virtual script drops the folder from its name.
    byBasename[basenameOf(normKey)] = value;
  }
  return { scripts, byBasename };
};

/** Legacy bundled JSON. Resolves to {} on any failure — never rejects. */
const fetchBundledMap = async (): Promise<Record<string, IdentityEntry>> => {
  try {
    const res = await fetch(SCRIPT_MAP_URL);
    if (!res.ok) throw new Error(`identity map fetch ${res.status}`);
    const data = await res.json();
    const scripts = (data?.scripts || {}) as Record<string, IdentityEntry>;
    const normalized: Record<string, IdentityEntry> = {};
    for (const [key, value] of Object.entries(scripts)) {
      normalized[normalizeScriptRef(key)] = value;
    }
    return normalized;
  } catch (err) {
    console.warn('[@identityMapCache] bundled script map unavailable', err);
    return {};
  }
};

/** executable_identity rows. Resolves to {} on any failure — never rejects. */
const fetchDbMap = async (): Promise<Record<string, IdentityEntry>> => {
  try {
    const data = await apiClientJson<{ items?: Array<IdentityEntry & { script_ref?: string }> }>(
      buildServerUrl('/server/script-identity/list'),
    );
    const normalized: Record<string, IdentityEntry> = {};
    for (const item of data?.items || []) {
      if (!item?.script_ref) continue;
      normalized[normalizeScriptRef(item.script_ref)] = {
        prefix: item.prefix ?? undefined,
        display_name: item.display_name ?? undefined,
      };
    }
    return normalized;
  } catch (err) {
    console.warn('[@identityMapCache] DB script identity unavailable', err);
    return {};
  }
};

export const loadScriptIdentityMap = (): Promise<ScriptMapShape> => {
  if (_scriptMap) return Promise.resolve(_scriptMap);
  if (_scriptPromise) return _scriptPromise;
  _scriptPromise = Promise.all([fetchBundledMap(), fetchDbMap()]).then(([bundled, db]) => {
    // DB wins per key; bundled entries with no DB row survive.
    _scriptMap = reindex({ ...bundled, ...db });
    notify();
    return _scriptMap;
  });
  return _scriptPromise;
};

/**
 * Apply one identity locally after a successful save, so the chip updates with
 * no refetch. Pass null to remove it (Clear). Falls back to the bundled entry
 * only on a full reload — a cleared key is simply gone from the cache.
 */
export const setScriptIdentity = (scriptRef: string, entry: IdentityEntry | null): void => {
  if (!_scriptMap) return;
  const key = normalizeScriptRef(scriptRef);
  const scripts = { ..._scriptMap.scripts };
  if (entry && (entry.prefix || entry.display_name)) {
    scripts[key] = entry;
  } else {
    delete scripts[key];
  }
  _scriptMap = reindex(scripts);
  notify();
};

/**
 * The entry stored under the EXACT key, with no basename fallback. Used to
 * snapshot before an optimistic edit: lookupScriptIdentity may answer from a
 * different key's entry, and restoring that under this key would invent a value.
 */
export const getExactScriptIdentity = (scriptRef: string): IdentityEntry | null =>
  _scriptMap?.scripts[normalizeScriptRef(scriptRef)] ?? null;

/** Force the next loadScriptIdentityMap() to refetch both sources. */
export const invalidateScriptIdentityMap = (): void => {
  _scriptMap = null;
  _scriptPromise = null;
};

export const loadCampaignIdentityMap = (): Promise<Record<string, IdentityEntry>> => {
  if (_campaignMap) return Promise.resolve(_campaignMap);
  if (_campaignPromise) return _campaignPromise;
  _campaignPromise = fetch(CAMPAIGN_MAP_URL)
    .then(async (res) => {
      if (!res.ok) throw new Error(`campaign map fetch ${res.status}`);
      const data = await res.json();
      _campaignMap = (data?.campaigns || {}) as Record<string, IdentityEntry>;
      notify();
      return _campaignMap;
    })
    .catch((err) => {
      console.warn('[@identityMapCache] campaign map load failed', err);
      _campaignMap = {};
      notify();
      return _campaignMap;
    });
  return _campaignPromise;
};

export const lookupScriptIdentity = (scriptName: string): IdentityEntry | null => {
  if (!_scriptMap) return null;
  const key = normalizeScriptRef(scriptName);
  // Try exact normalized key, then the basename of the query (so "web/foo"
  // resolves a map entry keyed "foo", and "foo" resolves one keyed "web/foo").
  const slashIdx = key.lastIndexOf('/');
  const base = slashIdx >= 0 ? key.substring(slashIdx + 1) : key;
  return _scriptMap.scripts[key] || _scriptMap.byBasename[base] || _scriptMap.byBasename[key] || null;
};

export const lookupCampaignIdentity = (rawName: string): IdentityEntry | null => {
  if (!_campaignMap) return null;
  return _campaignMap[rawName] || null;
};

export const isScriptMapLoaded = (): boolean => _scriptMap !== null;
export const isCampaignMapLoaded = (): boolean => _campaignMap !== null;

export const subscribeIdentityMapLoaded = (listener: () => void): (() => void) => {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
};
