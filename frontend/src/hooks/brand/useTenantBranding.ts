import { useEffect, useState } from 'react';
import { useAuthContext } from '../../contexts/auth/AuthContext';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { tenantBrandingCacheKey } from '../../config/tenantBrandingCacheVersion';

export type TenantBranding = {
  footerLogoUrl?: string | null;
  footerLogoAlt?: string | null;
  footerTextColor?: string | null;
};

const EMPTY: TenantBranding = {};

/**
 * Reads the caller's per-tenant branding overrides from
 * `/server/branding/tenant`. The endpoint resolves the tenant from the JWT
 * (no client-side tenantId needed), so it always matches the tenant the
 * server considers the caller's "home" tenant.
 *
 * Returns `{}` when the caller has no tenant (e.g. a stale token pre-TASK-23
 * where the DB fallback also missed) — the BrandingContext falls through to
 * the deployment-level and build-time defaults in that case.
 *
 * Result is cached in localStorage keyed by user_id + a schema-version
 * suffix so a deploy that changes the TenantBranding shape doesn't lock
 * users out behind stale cached data. See
 * ../../config/tenantBrandingCacheVersion.ts.
 */
export const useTenantBranding = (): TenantBranding => {
  const { user } = useAuthContext();
  const [branding, setBranding] = useState<TenantBranding>(EMPTY);

  useEffect(() => {
    let cancelled = false;

    const cacheKey = user?.id ? tenantBrandingCacheKey(user.id) : null;

    const apply = (next: TenantBranding) => {
      if (!cancelled) setBranding(next);
    };

    // Synchronous cache hit — render immediately with whatever was cached.
    if (cacheKey) {
      try {
        const cached = localStorage.getItem(cacheKey);
        if (cached) {
          const parsed = JSON.parse(cached) as TenantBranding;
          if (parsed && typeof parsed === 'object') apply(parsed);
        }
      } catch {
        // ignore — fall through to the fetch
      }
    }

    const load = async () => {
      try {
        const res = await fetch(buildServerUrl('/server/branding/tenant'), {
          credentials: 'include',
        });
        if (!res.ok) {
          return;
        }
        const data = (await res.json()) as TenantBranding;
        // Empty {} is a valid response when the tenant has no overrides.
        apply(data || EMPTY);
        if (cacheKey) {
          try {
            localStorage.setItem(cacheKey, JSON.stringify(data || EMPTY));
          } catch {
            // localStorage may be unavailable (private mode, etc.) — fall through.
          }
        }
      } catch {
        // Backend unreachable — keep whatever was cached.
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  return branding;
};