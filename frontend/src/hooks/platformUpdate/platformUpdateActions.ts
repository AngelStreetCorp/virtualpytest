import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

/** Admin actions of Platform update that change files on the server or a machine (TASK-128 G6, G7). */
const post = async (path: string, body: Record<string, unknown>) => {
  const response = await apiClient(buildServerUrl(path), { method: 'POST', body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) throw new Error(data.error || data.message || `HTTP ${response.status}`);
  return data;
};

export interface CleanupItem {
  name: string;
  path: string;
  bytes: number;
}

export interface CleanupGroup {
  kind: 'backups' | 'bundles' | 'bak';
  label: string;
  dir: string;
  keep: CleanupItem[];
  delete: CleanupItem[];
  refused: { name: string; reason: string }[];
}

/** POST /server/platform-update/cleanup: the plan (dry run) or the result (freed bytes). Server only, never a host. */
export interface CleanupResult {
  dry_run: boolean;
  keep_newest: number;
  groups: CleanupGroup[];
  total_bytes: number;
  count: number;
  freed_bytes: number;
  deleted: number;
  errors: { path: string; error: string }[];
}

export const requestCleanup = async (dryRun: boolean): Promise<CleanupResult> =>
  (await post('/server/platform-update/cleanup', { dry_run: dryRun })) as CleanupResult;

/** The command to run so the restored file takes effect. The app never restarts a service by itself. */
export interface RestoreResult {
  restored: string;
  machine: string;
  backup_of_current: string;
  restart: { machine: string; command: string };
  note: string;
}

export const requestRestore = async (folder: string, itemId: string, file: string): Promise<RestoreResult> =>
  (await post('/server/platform-update/restore', { folder, item_id: itemId, file })) as RestoreResult;

/** What the existing core update answers (`/server/system/updateHostCore`); only the fields the page shows. */
export interface HostCoreUpdate {
  version_before?: string;
  version_after?: string;
  restart_scheduled?: boolean;
}

const updateHostCore = async (hostName: string, dryRun: boolean): Promise<HostCoreUpdate> => {
  const response = await apiClient(buildServerUrl('/server/system/updateHostCore'), {
    method: 'POST',
    body: JSON.stringify({ host_name: hostName, dry_run: dryRun, restart_host_service: true, target_kind: 'host-linux' }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    const detail = String(data.stderr || data.stdout || '').trim().split('\n').slice(-2).join(' ');
    throw new Error([data.error || data.message || `HTTP ${response.status}`, detail].filter(Boolean).join(': '));
  }
  return data as HostCoreUpdate;
};

/**
 * TASK-128 G11: the first update of an old host (no `updatePrereqs`), through the shared-source update every host already has.
 * A dry run first proves the host reaches the shared source; only then the real run, which schedules the host restart.
 */
export const requestHostUpdateOnce = async (hostName: string): Promise<HostCoreUpdate> => {
  await updateHostCore(hostName, true);
  return updateHostCore(hostName, false);
};

// ---- TASK-128 G12: pause / abort / roll back a running deploy -------------------------------------------------------
const RUNS = '/server/platform-update/runs';

export type DeployControlAction = 'pause' | 'resume' | 'abort';

export const requestDeployControl = (runId: string, action: DeployControlAction) =>
  post(`${RUNS}/${runId}/control`, { action });

export type MachineOutcome = 'new' | 'rolled_back' | 'untouched' | 'failed';

export interface ImpactMachine {
  role: string;
  name: string;
  before: string;
  now: string;
  state: MachineOutcome;
  has_backup: boolean;
}

export interface ImpactMigration {
  file: string;
  rollback_file: string;
  has_rollback: boolean;
}

export interface RollbackAction {
  role: string;
  name: string;
  state: 'running' | 'ok' | 'failed';
  detail: string;
}

export interface DeployImpact {
  machines: ImpactMachine[];
  migrations: { applied: string[]; rolled_back: string[]; plan: ImpactMigration[]; restore_command: string; needs_dump_restore: boolean };
  expected_version: string;
  mixed: boolean;
  mixed_summary: string;
  aborted: boolean;
  can_rollback: boolean;
  rollback: { state: 'running' | 'awaiting_confirmation' | 'done' | 'failed'; actions: RollbackAction[]; error?: string } | null;
  partial: { by: string; summary: string } | null;
  rollback_order: { role: string; name: string }[];
}

export const fetchDeployImpact = async (runId: string): Promise<DeployImpact> => {
  const response = await apiClient(buildServerUrl(`${RUNS}/${runId}/impact`));
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) throw new Error(data.error || data.message || `HTTP ${response.status}`);
  return data.impact as DeployImpact;
};

/** Starts the roll back of the machines (hosts newest first, the frontend VM, the server last). */
export const requestRollback = (runId: string) => post(`${RUNS}/${runId}/rollback`, { confirm: true });

/** After the server restarted onto the restored tree. */
export const confirmRollbackRestart = (runId: string) => post(`${RUNS}/${runId}/rollback`, { action: 'confirm_restart' });

/** Second confirm: the exact list the operator saw (newest first). */
export const requestMigrationRollback = (runId: string, filenames: string[]) =>
  post(`${RUNS}/${runId}/rollback/migrations`, { confirm: true, filenames });

export const requestLeavePartial = (runId: string) => post(`${RUNS}/${runId}/leave-partial`, { confirm: true });

/** POST /settings/frontend-setup (TASK-128 G13): one run, one password, never kept. `ok` false = a step failed (see `steps`). */
export interface FrontendSetupResult {
  ok: boolean;
  steps: { name: string; ok: boolean; detail: string }[];
}

export const requestFrontendSetup = async (host: string, adminUser: string, password: string): Promise<FrontendSetupResult> =>
  (await post('/server/platform-update/settings/frontend-setup', { host, admin_user: adminUser, password })) as FrontendSetupResult;
