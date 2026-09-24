/**
 * Tests for the schema-versioned localStorage cache keys. These are the
 * regression guard for TASK-23's "super admin silently invisible after
 * deploy" bug: when is_platform_admin was added, the cached profile in
 * localStorage kept the OLD shape, and `useProfile().isPlatformAdmin`
 * evaluated to `false`. The fix is a `_vN` suffix in the cache key,
 * bumped when the shape changes.
 *
 * These tests don't need React — they exercise the pure helpers. The
 * localStorage-touching ones stub the global with a tiny Map-backed
 * implementation so they don't require jsdom/happy-dom in CI.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  PROFILE_CACHE_VERSION,
  profileCacheKey,
  pruneOrphanedProfileCacheKeys,
} from './cacheVersion';
import {
  TENANT_BRANDING_CACHE_VERSION,
  tenantBrandingCacheKey,
} from './tenantBrandingCacheVersion';


describe('profileCacheKey', () => {
  it('includes the userId and the current schema version', () => {
    const k = profileCacheKey('user-123');
    expect(k).toContain('user-123');
    expect(k).toContain(`_v${PROFILE_CACHE_VERSION}`);
    expect(k.startsWith('auth_profile_')).toBe(true);
  });

  it('is stable across calls for the same input', () => {
    expect(profileCacheKey('user-123')).toBe(profileCacheKey('user-123'));
  });
});


describe('tenantBrandingCacheKey', () => {
  it('includes the userId and the current schema version', () => {
    const k = tenantBrandingCacheKey('user-123');
    expect(k).toContain('user-123');
    expect(k).toContain(`_v${TENANT_BRANDING_CACHE_VERSION}`);
    expect(k.startsWith('vpt_tenant_branding_')).toBe(true);
  });
});


/**
 * Map-backed localStorage stub. In production, real localStorage is used;
 * the stub only differs in that it ignores StorageEvent and quota errors,
 * neither of which the prune helper cares about.
 */
const installLocalStorageStub = (): Map<string, string> => {
  const map = new Map<string, string>();
  const stub: Storage = {
    get length() { return map.size; },
    clear() { map.clear(); },
    getItem(key: string) { return map.has(key) ? map.get(key)! : null; },
    key(i: number) { return Array.from(map.keys())[i] ?? null; },
    removeItem(key: string) { map.delete(key); },
    setItem(key: string, value: string) { map.set(key, value); },
  };
  vi.stubGlobal('localStorage', stub);
  return map;
};


describe('pruneOrphanedProfileCacheKeys', () => {
  let map: Map<string, string>;

  beforeEach(() => { map = installLocalStorageStub(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('removes keys that match the prefix but not the current version', () => {
    // Old-version keys from before a bump
    map.set('auth_profile_user-1_v1', JSON.stringify({ role: 'admin' }));
    map.set('auth_profile_user-2_v1', JSON.stringify({ role: 'viewer' }));
    // An unrelated key (must not be touched)
    map.set('vpt_tenant_branding_user-1_v1', JSON.stringify({}));
    // The current-version key (must not be touched)
    map.set(profileCacheKey('user-3'), JSON.stringify({ role: 'admin' }));

    const removed = pruneOrphanedProfileCacheKeys();

    expect(removed).toBe(2);
    expect(map.has('auth_profile_user-1_v1')).toBe(false);
    expect(map.has('auth_profile_user-2_v1')).toBe(false);
    expect(map.has('vpt_tenant_branding_user-1_v1')).toBe(true);
    expect(map.has(profileCacheKey('user-3'))).toBe(true);
  });

  it('returns 0 when there is nothing to prune', () => {
    map.set(profileCacheKey('user-1'), JSON.stringify({}));
    expect(pruneOrphanedProfileCacheKeys()).toBe(0);
  });

  it('returns 0 when storage is empty', () => {
    expect(pruneOrphanedProfileCacheKeys()).toBe(0);
  });
});


describe('the regression scenario', () => {
  let map: Map<string, string>;

  beforeEach(() => { map = installLocalStorageStub(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('after a version bump, old keys become orphans and a fresh key is read', () => {
    // A user logged in before TASK-23 had this profile cached (no _vN):
    const oldKey = 'auth_profile_user-pre-task-23';
    map.set(oldKey, JSON.stringify({ role: 'admin' /* no is_platform_admin */ }));
    expect(map.has(oldKey)).toBe(true);

    // Deploy lands. AuthProvider mounts and prunes orphans.
    const removed = pruneOrphanedProfileCacheKeys();
    expect(removed).toBeGreaterThan(0);
    expect(map.has(oldKey)).toBe(false);

    // The profile is re-fetched and cached under the new key. The fresh
    // shape carries the new column.
    map.set(profileCacheKey('user-pre-task-23'),
            JSON.stringify({ role: 'admin', is_platform_admin: true }));
    const cached = JSON.parse(map.get(profileCacheKey('user-pre-task-23'))!);
    expect(cached.is_platform_admin).toBe(true);
  });
});