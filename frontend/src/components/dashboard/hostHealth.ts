/**
 * One verdict per host for everything outside the Services card: the "N in
 * error" badge, the "errors only" filter, the starred-device chips and the
 * Auto-fix button.
 *
 * The badge and the card MUST agree (BUG-0758). They used to disagree because
 * the badge asked "is this service optional?" while the Services panel asked
 * "does this host need it?" — two different questions with two different
 * answers on a healthy host:
 *
 *   - TASK-144 stops services no device profile asks for. The backend keeps
 *     `optional: false` on them and flips `critical: false` instead
 *     (backend_host/src/lib/utils/system_info_utils.py), so an "optional"
 *     test flags them as errors.
 *   - The panel builds its rows from the same expectation test, routes them to
 *     the muted "Optional (N)" group, and keeps its LED green.
 *
 * The user saw "1 in error" on vpt-nipogi and found nothing red on the card.
 * So the verdict is now DERIVED from the panel's own model (buildHostServices)
 * rather than from a second, drifting copy of the rule: `counts.down > 0` is
 * precisely what turns that LED red, so the badge can never fire without
 * something red on screen.
 */

import type { Host } from '../../types/common/Host_Types';
import { buildHostServices, type ProfileInput, type RawService, type ServiceRow } from './hostServices';

export type HostSeverity = 'ok' | 'warning' | 'error';

/**
 * Disk thresholds on the worst monitored mount (TASK-156). Higher than the infra
 * VM page (80/90) on purpose: a full-profile host with 4 capture devices sits at
 * ~84 % while working correctly, because the archiver keeps the 24 h window full.
 * 85 would still flag it, so it is a "look at it" amber, and 95 is the line past
 * which ENOSPC is minutes away (the outage that started this: 100 % on /).
 */
export const DISK_WARNING_PERCENT = 85;
export const DISK_ERROR_PERCENT = 95;

export interface HostHealth {
  /** Drives the red badge, the errors-only filter and the favourite chips. */
  severity: HostSeverity;
  /** Rows the Services card renders in red ("down"). The badge never fires without one. */
  downRows: ServiceRow[];
  /** The raw services behind those rows — what Auto-fix restarts. vpt-host excluded. */
  downServices: RawService[];
  /** The host runs a different build than the server it reports to. */
  versionMismatch: boolean;
  /** Backend says degraded: something expected is missing or unreadable. */
  degraded: boolean;
  /** Fullest monitored mount, percent. null when the host did not report it. */
  diskPercent: number | null;
  /** Which threshold the disk crossed; null while below the warning line. */
  diskLevel: 'warning' | 'error' | null;
}

/** The device profiles the Services panel reads, straight off the host payload. */
export const hostProfiles = (host: Host): ProfileInput => ({
  monitorProfiles: host.system_stats?.monitor_profiles,
  profileServices: host.system_stats?.monitor_profile_services,
  deviceCount: host.devices?.length ?? 0,
});

/** VERSION.txt may carry an optional "current:" prefix. Mirrors CodeDeployment's extractHash. */
export const normalizeVersion = (value?: string | null): string => {
  if (!value) return '';
  const cleaned = value.trim().replace(/^current\s*:/i, '');
  const parts = cleaned.split('-');
  return parts.length >= 2 ? parts[parts.length - 1] : cleaned;
};

/**
 * The server is the source of truth. A version is "mismatched" when both it
 * and the reference (server) version are known and their build ids differ.
 */
export const isVersionMismatch = (version?: string | null, reference?: string | null): boolean =>
  !!version && !!reference && normalizeVersion(version) !== normalizeVersion(reference);

/**
 * The whole verdict, in one place.
 *
 * error   — a service this host actually needs is down (a red row on the card),
 *           or the backend itself says the host is in error.
 * warning — nothing is down, but something is worth a look: the host runs a
 *           different build than the server (a code mismatch is not a fault —
 *           a redeploy fixes it, nothing is broken), or the backend reports the
 *           host degraded because an expected service is missing/unreadable.
 *           Degraded used to count as an error, which produced a red badge with
 *           nothing red on screen: a critical-but-not-installed service is filed
 *           under the collapsed "Not installed (N)" list and never gets a dot.
 */
export const hostHealth = (host: Host, serverVersion?: string | null): HostHealth => {
  const services = host.system_stats?.service_health?.services || [];
  const model = buildHostServices(services, hostProfiles(host));
  const downRows = [...model.groups.core, ...model.groups.monitoring, ...model.groups.optional].filter(
    (row) => row.state === 'down',
  );
  // vpt-host has its own restart/reboot buttons, so it never joins the Auto-fix list.
  const downServices = downRows
    .flatMap((row) => row.members)
    .filter((s) => s.name !== 'vpt-host' && s.status !== 'not_installed');

  const operationalStatus =
    host.system_stats?.operational_status ??
    host.system_stats?.service_health?.overall_status ??
    (host.status === 'online' ? 'online' : 'error');
  const degraded = operationalStatus === 'degraded';
  const versionMismatch = isVersionMismatch(host.deployed_version, serverVersion);

  // disk_percent is the worst mount, not `/` (BUG-0198), straight from the payload the cards render.
  const rawDisk = host.system_stats?.disk_percent;
  const diskPercent = typeof rawDisk === 'number' && Number.isFinite(rawDisk) ? rawDisk : null;
  const diskLevel =
    diskPercent === null ? null : diskPercent >= DISK_ERROR_PERCENT ? 'error' : diskPercent >= DISK_WARNING_PERCENT ? 'warning' : null;

  let severity: HostSeverity = 'ok';
  if (operationalStatus === 'error' || downRows.length > 0 || diskLevel === 'error') severity = 'error';
  else if (degraded || versionMismatch || diskLevel === 'warning') severity = 'warning';

  return { severity, downRows, downServices, versionMismatch, degraded, diskPercent, diskLevel };
};

export const hostHasError = (host: Host, serverVersion?: string | null): boolean =>
  hostHealth(host, serverVersion).severity === 'error';

export const hostHasWarning = (host: Host, serverVersion?: string | null): boolean =>
  hostHealth(host, serverVersion).severity === 'warning';

/** Why a host is amber. */
export type HostWarningReason = 'version' | 'degraded' | 'disk';

/**
 * The reasons behind the amber verdict, in the order they are reported.
 *
 * The "N in warning" badge counts HOSTS, but its tooltip used to claim
 * "version mismatch" for every one of them — so a host that was amber for a
 * full disk or a degraded backend was announced as a version mismatch, and a
 * count the user could not reconcile with the screen. The badge and the card
 * now speak about the same reasons: this list is what the badge counts and
 * what the tooltip names.
 *
 * Empty for a healthy host and for a host in error (red wins over amber).
 */
export const hostWarningReasons = (host: Host, serverVersion?: string | null): HostWarningReason[] => {
  const health = hostHealth(host, serverVersion);
  if (health.severity !== 'warning') return [];
  const reasons: HostWarningReason[] = [];
  if (health.versionMismatch) reasons.push('version');
  if (health.degraded) reasons.push('degraded');
  if (health.diskLevel === 'warning') reasons.push('disk');
  return reasons;
};