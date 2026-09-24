-- 20260923i_tenant_footer_logo_rollback.sql
-- Inverse of 20260923i. Drops the three columns and the two CHECK constraints.

BEGIN;

ALTER TABLE public.tenants
  DROP CONSTRAINT IF EXISTS tenants_footer_logo_url_https,
  DROP CONSTRAINT IF EXISTS tenants_footer_text_color_hex;

ALTER TABLE public.tenants
  DROP COLUMN IF EXISTS footer_text_color,
  DROP COLUMN IF EXISTS footer_logo_alt,
  DROP COLUMN IF EXISTS footer_logo_url;

COMMIT;