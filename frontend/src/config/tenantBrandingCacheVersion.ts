/**
 * Schema-versioned cache key for the per-tenant branding overrides.
 *
 * Same idea as cacheVersion.ts: bump the version whenever the shape of
 * TenantBranding changes (a new field is added or a field is renamed). Old
 * cached entries become orphans that the next render ignores, so deploys
 * that add or rename tenant-branding fields don't require a manual
 * localStorage clear.
 *
 * Version history:
 *   v1 — initial useTenantBranding cache (userId only)
 */

export const TENANT_BRANDING_CACHE_VERSION = 1;

export const tenantBrandingCacheKey = (userId: string): string =>
  `vpt_tenant_branding_${userId}_v${TENANT_BRANDING_CACHE_VERSION}`;