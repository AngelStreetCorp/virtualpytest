import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { getEnv } from '../config/constants';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { useTenantBranding } from '../hooks/brand/useTenantBranding';
import { useAuthContext } from './auth/AuthContext';
import { isAuthEnabled } from '../lib/supabase';

export type Branding = {
  name: string;
  logoUrl: string;
  faviconUrl: string;
  tagline: string;
  showFooter: boolean;
  showProjectName: boolean;
  // Footer links; default on, hide with VITE_SHOW_GITHUB_LINK=false / VITE_SHOW_MOBILE_APP_LINK=false
  // or from Settings > Branding (no rebuild needed).
  showGithubLink: boolean;
  showMobileAppLink: boolean;
  title: string;
  // TASK-23 footer-logo follow-up: per-tenant override applied on top of
  // the deployment-level branding. The footer reads these directly.
  tenantFooterLogoUrl?: string;
  tenantFooterLogoAlt?: string;
  tenantFooterTextColor?: string;
};

type BrandingContextValue = {
  branding: Branding;
  isLoaded: boolean;
  setBranding: (overrides: Partial<Branding>) => Promise<void>;
  resetBranding: () => Promise<void>;
  hasBackup: boolean;
};

// Build-time defaults from Vite env vars
const buildDefaults = (): Branding => {
  // Whitespace-only (e.g. VITE_PROJECT_NAME=" ", seen live on the demo server) is not an
  // empty string, so getEnv's own "empty means unset" rule doesn't catch it — trim first.
  const name = getEnv('VITE_PROJECT_NAME', 'VirtualPyTest').trim() || 'VirtualPyTest';
  const logoUrl = getEnv('VITE_PROJECT_LOGO_URL', '/logo.png');
  const faviconUrl = getEnv('VITE_PROJECT_FAVICON_URL', '/favicon.ico');
  const tagline = getEnv('VITE_PROJECT_TAGLINE', 'Automated Testing Platform');
  const showFooter = getEnv('VITE_SHOW_FOOTER') !== 'false';
  // A wordmark logo already spells the name out; set VITE_SHOW_PROJECT_NAME=false so the
  // header/footer/mobile bar show the logo alone instead of printing the name twice.
  const showProjectName = getEnv('VITE_SHOW_PROJECT_NAME') !== 'false';
  const showGithubLink = getEnv('VITE_SHOW_GITHUB_LINK') !== 'false';
  const showMobileAppLink = getEnv('VITE_SHOW_MOBILE_APP_LINK') !== 'false';
  const title = getEnv('VITE_PROJECT_TITLE') || `${name} Web Interface`;
  return { name, logoUrl, faviconUrl, tagline, showFooter, showProjectName, showGithubLink, showMobileAppLink, title };
};

const DEFAULTS = buildDefaults();

const applyFavicon = (url: string) => {
  if (!url) return;
  let link = document.querySelector<HTMLLinkElement>("link[rel~='icon']");
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  link.href = url;
};

const BrandingContext = createContext<BrandingContextValue>({
  branding: DEFAULTS,
  isLoaded: false,
  setBranding: async () => {},
  resetBranding: async () => {},
  hasBackup: false,
});

export const BrandingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [overrides, setOverrides] = useState<Partial<Branding>>({});
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasBackup, setHasBackup] = useState(false);
  // TASK-23: per-tenant branding overrides sit on top of the deployment-level
  // branding. The hook fetches from /server/branding/tenant and caches in
  // localStorage. Empty object when the caller has no tenant (e.g. a stale
  // token pre-TASK-23).
  const tenantBranding = useTenantBranding();

  // `/server/branding*` is behind the global /server/* auth guard like everything else
  // that is not in UNAUTHENTICATED_SERVER_PREFIXES, and BrandingProvider mounts ABOVE the
  // login gate — so on a Supabase deployment these two calls were a guaranteed 401 on
  // every logged-out page load, silently falling back to the build-time defaults they
  // already start from. Deployments with no Supabase (isAuthEnabled false) still load
  // their branding before any login, as they always did.
  const { isAuthenticated } = useAuthContext();
  const canLoadBranding = !isAuthEnabled || isAuthenticated;

  const branding: Branding = {
    ...DEFAULTS,
    ...overrides,
    tenantFooterLogoUrl:   tenantBranding.footerLogoUrl ?? undefined,
    tenantFooterLogoAlt:   tenantBranding.footerLogoAlt ?? undefined,
    tenantFooterTextColor: tenantBranding.footerTextColor ?? undefined,
  };

  // Apply favicon whenever it changes
  useEffect(() => {
    if (branding.faviconUrl) applyFavicon(branding.faviconUrl);
  }, [branding.faviconUrl]);

  // Apply document title whenever it changes
  useEffect(() => {
    document.title = branding.title;
  }, [branding.title]);

  // Load persisted branding from backend once the server will actually answer us
  useEffect(() => {
    if (!canLoadBranding) {
      return;
    }

    const load = async () => {
      try {
        const res = await fetch(buildServerUrl('/server/branding'));
        if (res.ok) {
          const data = await res.json();
          if (data.success && data.branding && Object.keys(data.branding).length > 0) {
            setOverrides(data.branding);
            setHasBackup(!!data.branding);
          }
        }
        // Check backup availability
        const backupRes = await fetch(buildServerUrl('/server/branding/backup'));
        if (backupRes.ok) {
          const backupData = await backupRes.json();
          setHasBackup(backupData.success && backupData.branding !== null);
        }
      } catch {
        // Backend unreachable — fall back to build-time defaults silently
      } finally {
        setIsLoaded(true);
      }
    };
    load();
  }, [canLoadBranding]);

  const setBranding = useCallback(async (updates: Partial<Branding>) => {
    const next = { ...overrides, ...updates };
    // Auto-derive title from name if title wasn't explicitly set
    if (updates.name && !updates.title && !overrides.title) {
      next.title = `${updates.name} Web Interface`;
    }
    // Optimistic update
    setOverrides(next);
    // Persist to backend
    try {
      const res = await fetch(buildServerUrl('/server/branding'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
      if (res.ok) {
        const data = await res.json();
        setHasBackup(data.backup_available);
      }
    } catch {
      // Persist to localStorage as fallback if backend is unreachable
      localStorage.setItem('vpt_branding_overrides', JSON.stringify(next));
    }
  }, [overrides]);

  const resetBranding = useCallback(async () => {
    try {
      const res = await fetch(buildServerUrl('/server/branding/revert'), { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setOverrides(data.branding || {});
          return;
        }
      }
    } catch {
      // ignore
    }
    // Fallback: clear overrides
    setOverrides({});
    localStorage.removeItem('vpt_branding_overrides');
  }, []);

  return (
    <BrandingContext.Provider value={{ branding, isLoaded, setBranding, resetBranding, hasBackup }}>
      {children}
    </BrandingContext.Provider>
  );
};

export const useBranding = (): BrandingContextValue => useContext(BrandingContext);
