/**
 * Schema-versioned localStorage cache keys.
 *
 * Why this exists: AuthContext caches the fetched profile in localStorage keyed
 * only by `userId`. When a deploy adds a new column to `public.profiles`
 * (e.g. `is_platform_admin` in TASK-23, or any future field), the cached
 * profile keeps the OLD shape — the new column is `undefined` — and the user
 * has to manually clear localStorage to see features gated on the new column.
 *
 * The fix is to put a `PROFILE_CACHE_VERSION` integer into the cache key.
 * When the schema changes, bump the version. The old keys become orphans
 * (still in localStorage but never read), and the next render reads from
 * the fresh key, fetching the up-to-date shape from the database.
 *
 * Version history:
 *   v1 — initial AuthContext cache (userId only)
 *   v2 — added `is_platform_admin` (TASK-23) — bump required, otherwise
 *        super-admin users keep seeing themselves as plain admin after deploy
 *
 * Rule of thumb: bump this whenever a field on `UserProfile` is added or
 * renamed. Renames especially — the old cached field would otherwise mask
 * the new one. The cost of a bump is one extra `SELECT *` per user session,
 * which is negligible.
 *
 * Garbage collection of orphaned keys happens on mount via
 * `pruneOrphanedCacheKeys()` — see AuthContext.
 */

export const PROFILE_CACHE_VERSION = 2;

/**
 * The localStorage key prefix. The full key is
 * `auth_profile_<userId>_v<PROFILE_CACHE_VERSION>`.
 */
export const PROFILE_CACHE_KEY_PREFIX = 'auth_profile_';

/**
 * Build the versioned cache key for a given user id.
 */
export const profileCacheKey = (userId: string): string =>
  `${PROFILE_CACHE_KEY_PREFIX}${userId}_v${PROFILE_CACHE_VERSION}`;

/**
 * Walk every key in localStorage matching `PROFILE_CACHE_KEY_PREFIX` and
 * drop the ones that aren't on the current version. Called once on mount
 * by AuthContext so the orphaned entries don't accumulate forever.
 *
 * Returns the number of keys removed — useful for tests and logging.
 */
export const pruneOrphanedProfileCacheKeys = (): number => {
  if (typeof localStorage === 'undefined') return 0;
  let removed = 0;
  try {
    const suffix = `_v${PROFILE_CACHE_VERSION}`;
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (!k || !k.startsWith(PROFILE_CACHE_KEY_PREFIX)) continue;
      if (k.endsWith(suffix)) continue;
      localStorage.removeItem(k);
      removed++;
    }
  } catch {
    // localStorage may throw in private mode or restricted iframes. Best
    // effort only; we don't want a storage failure to block app boot.
  }
  return removed;
};