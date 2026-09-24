-- 20260923i_tenant_footer_logo.sql
-- TASK-23 footer-logo follow-up. Add per-tenant branding overrides:
--
--   * footer_logo_url      — optional https URL to the tenant's footer logo
--   * footer_logo_alt      — accessibility label for the logo ("Acme logo")
--   * footer_text_color    — optional hex accent applied to the logo text
--
-- Storage choice was A (URL field) per the maintainer's decision. The binary
-- stays on the tenant's CDN — no upload endpoint, no R2/MinIO churn.
--
-- Idempotent. The columns are all nullable so existing tenants stay untouched.

BEGIN;

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS footer_logo_url    TEXT,
  ADD COLUMN IF NOT EXISTS footer_logo_alt    TEXT,
  ADD COLUMN IF NOT EXISTS footer_text_color  TEXT;

-- Belt-and-braces: refuse non-https URLs at the DB layer so a typo doesn't
-- silently turn the footer into a mixed-content block. NULL is allowed.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'tenants_footer_logo_url_https'
  ) THEN
    ALTER TABLE public.tenants
      ADD CONSTRAINT tenants_footer_logo_url_https
        CHECK (footer_logo_url IS NULL OR footer_logo_url ~* '^https://')
        NOT VALID;
  END IF;
END $$;

-- footer_text_color: hex format (#RGB, #RRGGBB, #RRGGBBAA). Empty allowed.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'tenants_footer_text_color_hex'
  ) THEN
    ALTER TABLE public.tenants
      ADD CONSTRAINT tenants_footer_text_color_hex
        CHECK (footer_text_color IS NULL OR footer_text_color ~* '^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$')
        NOT VALID;
  END IF;
END $$;

COMMIT;