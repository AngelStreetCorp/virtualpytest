/**
 * scriptListCache
 *
 * The list of runnable scripts, cached for the session so leaving Run Tests and coming back
 * does not visibly rebuild it.
 *
 * Why it is needed: React Router unmounts a page on navigation, so every return to Run Tests
 * mounted a fresh component whose `useEffect` re-fetched `/server/script/list` from scratch.
 * The page's own guard against duplicate calls is a ref, which dies with the component — it
 * dedupes React's StrictMode double-effect and nothing else. The result was a list that
 * emptied and repopulated on every visit.
 *
 * Stale-while-revalidate rather than load-once: scripts are added from the Virtual Scripts
 * page during a session, so a cache that never refreshed would quietly hide new ones. A
 * caller gets whatever is cached immediately, and a fetch runs in the background when that
 * copy is older than STALE_AFTER_MS, notifying subscribers if anything changed.
 *
 * Same shape as identityMapCache, deliberately — one value, one in-flight promise, a listener
 * set — so there is one way these page-level caches work rather than two.
 */
import { buildServerUrl } from './buildUrlUtils';

export interface ScriptListData {
  scripts: string[];
  aiTestCasesInfo: any[];
}

/** How old a cached list may be before a background refresh is kicked off. */
const STALE_AFTER_MS = 60_000;

let _data: ScriptListData | null = null;
let _loadedAt = 0;
let _promise: Promise<ScriptListData> | null = null;
const _listeners: Set<() => void> = new Set();

const notify = () => {
  _listeners.forEach((fn) => {
    try {
      fn();
    } catch (err) {
      console.warn('[@scriptListCache] listener error', err);
    }
  });
};

export const subscribeScriptList = (fn: () => void): (() => void) => {
  _listeners.add(fn);
  return () => {
    _listeners.delete(fn);
  };
};

/** Whatever is cached right now, without fetching. Null before the first load. */
export const getCachedScriptList = (): ScriptListData | null => _data;

const fetchScriptList = async (): Promise<ScriptListData> => {
  const response = await fetch(buildServerUrl('/server/script/list'));
  if (!response.ok) {
    throw new Error(`API returned ${response.status}`);
  }
  const body = await response.json();
  if (!body.success) {
    throw new Error(body.error || 'API returned success: false');
  }
  return {
    scripts: body.scripts || [],
    aiTestCasesInfo: body.ai_test_cases_info || [],
  };
};

/**
 * Load the script list, reusing the cached copy and any request already in flight.
 *
 * `force` skips the freshness check — for an explicit refresh, not for a remount.
 */
export const loadScriptList = async (force = false): Promise<ScriptListData> => {
  if (_promise) return _promise;
  if (_data && !force && Date.now() - _loadedAt < STALE_AFTER_MS) {
    return _data;
  }

  _promise = fetchScriptList()
    .then((data) => {
      const changed =
        !_data ||
        _data.scripts.length !== data.scripts.length ||
        _data.scripts.some((name, i) => name !== data.scripts[i]);
      _data = data;
      _loadedAt = Date.now();
      if (changed) notify();
      return data;
    })
    .catch((err) => {
      // A failed refresh must not throw away a list that is already on screen: the page keeps
      // showing the previous one and simply tries again next time.
      if (_data) {
        console.warn('[@scriptListCache] refresh failed, keeping the cached list', err);
        return _data;
      }
      throw err;
    })
    .finally(() => {
      _promise = null;
    });

  return _promise;
};

/** Drop the cache — for a deliberate reload, e.g. after a script is created. */
export const invalidateScriptList = (): void => {
  _data = null;
  _loadedAt = 0;
};
