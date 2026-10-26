/** Session-cached "is this connection really working" checks for the Integrations hub. */
export type CheckState = { state: 'checking' } | { state: 'ok' } | { state: 'failed'; error: string };

const cache = new Map<string, Promise<CheckState>>();

/** Run `probe` once per key per browser session; later callers share the result. */
export const cachedCheck = (key: string, probe: () => Promise<CheckState>): Promise<CheckState> => {
  let hit = cache.get(key);
  if (!hit) {
    hit = probe().catch((e): CheckState => ({ state: 'failed', error: e instanceof Error ? e.message : 'Connection test failed' }));
    cache.set(key, hit);
  }
  return hit;
};

/** Forget cached results (after a save or remove changed the stored credentials). */
export const clearChecks = (): void => cache.clear();

/** Placeholder / CI domains: a stored row that points here is not a real connection. */
export const isTestDomain = (domain: string): boolean => /smoke-test|example|\.test$|localhost/i.test(domain);

const FOLD_PREFIX = 'virtualpytest:integrations:fold:';
export const loadFold = (name: string): boolean | null => {
  try {
    const v = localStorage.getItem(FOLD_PREFIX + name);
    return v === 'open' ? true : v === 'folded' ? false : null;
  } catch { return null; }
};
export const saveFold = (name: string, open: boolean): void => {
  try { localStorage.setItem(FOLD_PREFIX + name, open ? 'open' : 'folded'); } catch { /* storage unavailable */ }
};
