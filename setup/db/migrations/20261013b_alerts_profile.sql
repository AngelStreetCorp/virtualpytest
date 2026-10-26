-- 20261013b_alerts_profile.sql — TASK-90 goal 4: an alert belongs to a monitor profile.
-- The CHECK on alerts.incident_type listed only the five TV incident types; a profile (counting_cars, intrusion, ...) declares its own, so the CHECK
-- goes and the profile column says which vocabulary an alert uses. The incident manager validates the type against the profile's declared incidents
-- instead. profile defaults to 'tv_app': every existing row, and every insert that omits it (the monitors do for tv_app), stays valid.
--
-- no_signal: since origin/main was merged into the TASK-90 branch, tv_app raises 'no_signal' alerts (BUG-0504), and main's CHECK lists only the five
-- older types. On a database that has neither this migration nor 20261013c the insert is refused by the CHECK; the incident manager says so once per
-- device, keeps the incident pending and retries hourly, so nothing is lost and nothing spams, but no no_signal alert exists until one of the two is
-- applied. Dropping the CHECK here lets no_signal in; 20261013c adds ONLY no_signal to the CHECK (for a host that goes to production with tv_app
-- alone, without the profile column) and is a no-op after this migration.
--
-- Idempotent. Twin: setup/db/schema/005_monitoring_analytics.sql. Inverse: 20261013b_alerts_profile_rollback.sql.
-- Not applied anywhere yet (owner decision). Until it (or 20261013c) is applied, tv_app works as before except that no_signal alerts are refused;
-- a profile other than tv_app that declares incidents needs this one (the profile column).

BEGIN;

ALTER TABLE public.alerts DROP CONSTRAINT IF EXISTS alerts_incident_type_check;

ALTER TABLE public.alerts ADD COLUMN IF NOT EXISTS profile text NOT NULL DEFAULT 'tv_app';

CREATE INDEX IF NOT EXISTS idx_alerts_profile ON public.alerts (profile) WHERE profile <> 'tv_app';

COMMIT;
