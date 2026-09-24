import { useState, useCallback, useEffect } from 'react';

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  description: string;
  is_default: boolean;
  created_by?: string;
  team_count: number;
  user_count: number;
  // TASK-23 footer-logo follow-up: per-tenant branding overrides.
  footer_logo_url?: string | null;
  footer_logo_alt?: string | null;
  footer_text_color?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTenantInput {
  name: string;
  slug: string;
  description?: string;
  footer_logo_url?: string;
  footer_logo_alt?: string;
  footer_text_color?: string;
}

export interface UpdateTenantInput {
  name?: string;
  slug?: string;
  description?: string;
  footer_logo_url?: string;
  footer_logo_alt?: string;
  footer_text_color?: string;
}

/**
 * Hook for the Tenants page — full CRUD against /server/tenants (super admin only).
 *
 * Mirrors useTeams so the Tenants page reads the same shape as the Teams page.
 * The 401/403 from the platform-admin decorator is the load-bearing boundary:
 * a non-super-admin user's call returns 403, and `tenants` ends up empty after
 * `loadTenants` clears it.
 */
export const useTenants = () => {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTenants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/server/tenants', {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) {
        // 403 here means the caller is not a platform admin — surface that as
        // a non-empty error so the UI can render an empty-state hint.
        if (res.status === 403) {
          setError('Tenants require platform-admin (super admin) access.');
          setTenants([]);
          return;
        }
        throw new Error(`Failed to load tenants: ${res.status}`);
      }
      const data: Tenant[] = await res.json();
      setTenants(data);
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load tenants');
      setTenants([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const createTenant = useCallback(async (input: CreateTenantInput | UpdateTenantInput): Promise<Tenant | null> => {
    try {
      const res = await fetch('/server/tenants', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => '');
        throw new Error(`Create failed (${res.status}): ${msg || res.statusText}`);
      }
      const created: Tenant = await res.json();
      setTenants((prev) => [...prev, created].sort((a, b) =>
        a.created_at.localeCompare(b.created_at)));
      return created;
    } catch (e: any) {
      setError(e?.message ?? 'Create failed');
      return null;
    }
  }, []);

  const updateTenant = useCallback(async (id: string, input: UpdateTenantInput): Promise<Tenant | null> => {
    try {
      const res = await fetch(`/server/tenants/${id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => '');
        throw new Error(`Update failed (${res.status}): ${msg || res.statusText}`);
      }
      const updated: Tenant = await res.json();
      setTenants((prev) => prev.map((t) => (t.id === id ? updated : t)));
      return updated;
    } catch (e: any) {
      setError(e?.message ?? 'Update failed');
      return null;
    }
  }, []);

  const deleteTenant = useCallback(async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`/server/tenants/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => '');
        if (res.status === 409) {
          throw new Error(`Cannot delete: ${msg || 'tenant has teams'}`);
        }
        throw new Error(`Delete failed (${res.status}): ${msg || res.statusText}`);
      }
      setTenants((prev) => prev.filter((t) => t.id !== id));
      return true;
    } catch (e: any) {
      setError(e?.message ?? 'Delete failed');
      return false;
    }
  }, []);

  useEffect(() => {
    void loadTenants();
  }, [loadTenants]);

  return {
    tenants,
    loading,
    error,
    loadTenants,
    createTenant,
    updateTenant,
    deleteTenant,
  };
};