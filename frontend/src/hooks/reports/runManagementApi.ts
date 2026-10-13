/**
 * Run management API — the single module that calls the TASK-42 endpoints.
 *
 * Paths and shapes come from `types/reports`. Every authenticated call goes through
 * `apiClient` + `buildServerUrl` (which already appends the active `team_id`), and
 * failures are thrown as `ApiError` so callers can tell 403 / 404 / 409 / 410 apart.
 */

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import {
  ENDPOINTS,
  SHARE_TOKEN_HEADER,
  toCounts,
  toRunStatus,
  type BatchAssignmentInput,
  type BatchAssignmentResponse,
  type CreateManualSessionRequest,
  type CreateShareRequest,
  type CreateShareResponse,
  type CustomReport,
  type CustomReportInput,
  type DeleteLabelResponse,
  type Defect,
  type DefectInput,
  type DefectListParams,
  type FinalizeManualSessionRequest,
  type FinalizeManualSessionResponse,
  type FlakyRow,
  type GroupReportResponse,
  type JiraPushResponse,
  type JiraRefreshResponse,
  type LabelInput,
  type LiveRunStatus,
  type LiveStopResponse,
  type ManualSession,
  type ManualSessionListItem,
  type Milestone,
  type MilestoneInput,
  type NotExecutedRow,
  type Paged,
  type PublicShareResponse,
  type QualityIdentity,
  type QualityParams,
  type QualityResponse,
  type ReportQueryRequest,
  type ReportQueryResponse,
  type RerunRequest,
  type ReportScope,
  type RerunResponse,
  type RunGroup,
  type RunGroupInput,
  type RunIdentity,
  type RunLabel,
  type RunSummaryParams,
  type RunSummaryResponse,
  type ScriptResultGovernanceFilters,
  type ScriptResultRow,
  type ShareSnapshotMeta,
  type ShareRevokeResponse,
  type SlowRow,
  type TestcaseVersion,
  type TqlValidation,
  type UpdateManualSessionRequest,
} from '../../types/reports';

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

export const isApiError = (error: unknown, status?: number): error is ApiError =>
  error instanceof ApiError && (status === undefined || error.status === status);

/** A short, user-facing reason for a failed call. */
export const describeError = (error: unknown): string => {
  if (isApiError(error, 403)) return 'You do not have permission to do this.';
  if (isApiError(error, 404)) return 'Not found, or not visible in this team and workspace.';
  if (error instanceof Error && error.message) return error.message;
  return 'Request failed';
};

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

/** The active workspace scope as sent to the server (`host_filter` / `device_filter`). */
export type ScopeParams = Pick<ReportScope, 'hostFilter' | 'deviceFilter'>;

/**
 * buildServerUrl + query parameters + the workspace scope, via the URL API (never string
 * concatenation). The scope always travels in the query string — also on writes — so a
 * strict body schema on the server never sees it as an unknown field.
 */
const serverUrl = (path: string, query?: Query, scope?: ScopeParams): string => {
  const base = buildServerUrl(path);
  const all: Query = { ...query, host_filter: scope?.hostFilter, device_filter: scope?.deviceFilter };
  const url = new URL(base, window.location.origin);
  for (const [key, value] of Object.entries(all)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      if (value.length) url.searchParams.set(key, JSON.stringify(value));
      continue;
    }
    url.searchParams.set(key, String(value));
  }
  return base.startsWith('http') ? url.toString() : `${url.pathname}${url.search}`;
};

/**
 * URL for the anonymous share read: no team_id, because the visitor has no team and the
 * token alone selects the snapshot.
 */
const publicServerUrl = (path: string): string => {
  const base = buildServerUrl(path);
  const url = new URL(base, window.location.origin);
  url.searchParams.delete('team_id');
  return base.startsWith('http') ? url.toString() : `${url.pathname}${url.search}`;
};

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  skipAuth?: boolean;
  signal?: AbortSignal;
}

const request = async <T>(url: string, options: RequestOptions = {}): Promise<T> => {
  const response = await apiClient(url, {
    method: options.method ?? 'GET',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    headers: options.headers,
    skipAuth: options.skipAuth,
    signal: options.signal,
  });
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const message =
      body && typeof body === 'object' && 'error' in body && typeof (body as { error: unknown }).error === 'string'
        ? (body as { error: string }).error
        : `HTTP ${response.status}`;
    throw new ApiError(response.status, message, body);
  }
  return body as T;
};

// ---------------------------------------------------------------------------
// Normalisers — the UI never trusts a status or count it cannot render
// ---------------------------------------------------------------------------

const normaliseSummary = (raw: RunSummaryResponse): RunSummaryResponse => ({
  ...raw,
  status: toRunStatus(raw.status),
  counts: toCounts(raw.counts as unknown as Record<string, unknown>),
  children: {
    ...raw.children,
    items: (raw.children?.items ?? []).map((child) => ({ ...child, status: toRunStatus(child.status) })),
  },
  trend: { ...raw.trend, window_days: raw.trend?.window_days ?? 0, points: raw.trend?.points ?? [] },
  attempts: raw.attempts ? toCounts(raw.attempts as unknown as Record<string, unknown>) : undefined,
  metadata: raw.metadata ?? {},
  evidence: raw.evidence ?? { report_url: null, logs_url: null, steps: null },
});

const normaliseLive = (raw: LiveRunStatus): LiveRunStatus => ({ ...raw, status: toRunStatus(raw.status) });

// ---------------------------------------------------------------------------
// Summary (server applies registered hosts ∩ host_filter)
// ---------------------------------------------------------------------------

export const fetchRunSummary = async (
  identity: RunIdentity,
  params: RunSummaryParams,
  scope?: ScopeParams,
): Promise<RunSummaryResponse> =>
  normaliseSummary(
    await request<RunSummaryResponse>(
      serverUrl(
        ENDPOINTS.summary(identity.kind, identity.id),
        { limit: params.limit, offset: params.offset, status: params.status ?? undefined, trend_days: params.trendDays },
        scope,
      ),
    ),
  );

// ---------------------------------------------------------------------------
// Run groups (team catalog; reports and reruns are scoped)
// ---------------------------------------------------------------------------

export const fetchRunGroups = (includeArchived: boolean) =>
  request<Paged<RunGroup>>(serverUrl(ENDPOINTS.runGroups(), { include_archived: includeArchived, limit: 200 }));

export const createRunGroup = (input: RunGroupInput) =>
  request<RunGroup>(serverUrl(ENDPOINTS.runGroups()), { method: 'POST', body: input });

export const updateRunGroup = (id: string, input: RunGroupInput) =>
  request<RunGroup>(serverUrl(ENDPOINTS.runGroup(id)), { method: 'PATCH', body: input });

export const archiveRunGroup = (id: string) =>
  request<RunGroup>(serverUrl(ENDPOINTS.runGroupArchive(id)), { method: 'POST' });

export const restoreRunGroup = (id: string) =>
  request<RunGroup>(serverUrl(ENDPOINTS.runGroupRestore(id)), { method: 'POST' });

export const fetchGroupReport = async (id: string, scope?: ScopeParams): Promise<GroupReportResponse> => {
  const raw = await request<GroupReportResponse>(serverUrl(ENDPOINTS.runGroupReport(id), undefined, scope));
  return {
    ...raw,
    counts: toCounts(raw.counts as unknown as Record<string, unknown>),
    attempts: toCounts(raw.attempts as unknown as Record<string, unknown>),
    rows: (raw.rows ?? []).map((row) => ({ ...row, status: toRunStatus(row.status) })),
  };
};

/** 202 on first dispatch, 200 with idempotent_replay on a retry with the same key. */
export const rerunGroup = (id: string, body: RerunRequest, scope?: ScopeParams) =>
  request<RerunResponse>(serverUrl(ENDPOINTS.runGroupRerun(id), undefined, scope), { method: 'POST', body });

// ---------------------------------------------------------------------------
// Milestones (team catalog)
// ---------------------------------------------------------------------------

export const fetchMilestones = (includeArchived: boolean) =>
  request<Paged<Milestone>>(serverUrl(ENDPOINTS.milestones(), { include_archived: includeArchived, limit: 200 }));

export const createMilestone = (input: MilestoneInput) =>
  request<Milestone>(serverUrl(ENDPOINTS.milestones()), { method: 'POST', body: input });

export const updateMilestone = (id: string, input: MilestoneInput) =>
  request<Milestone>(serverUrl(ENDPOINTS.milestone(id)), { method: 'PATCH', body: input });

export const archiveMilestone = (id: string) =>
  request<Milestone>(serverUrl(ENDPOINTS.milestoneArchive(id)), { method: 'POST' });

export const restoreMilestone = (id: string) =>
  request<Milestone>(serverUrl(ENDPOINTS.milestoneRestore(id)), { method: 'POST' });

// ---------------------------------------------------------------------------
// Labels and assignments (assignments are scope-checked per result)
// ---------------------------------------------------------------------------

export const fetchLabels = () => request<Paged<RunLabel>>(serverUrl(ENDPOINTS.labels(), { limit: 500 }));

export const createLabel = (input: LabelInput) =>
  request<RunLabel>(serverUrl(ENDPOINTS.labels()), { method: 'POST', body: input });

export const updateLabel = (id: string, input: LabelInput) =>
  request<RunLabel>(serverUrl(ENDPOINTS.label(id)), { method: 'PATCH', body: input });

export const deleteLabel = (id: string) =>
  request<DeleteLabelResponse>(serverUrl(ENDPOINTS.label(id)), { method: 'DELETE' });

export const setResultLabels = (resultId: string, labelIds: string[], scope?: ScopeParams) =>
  request<{ script_result_id: string; labels: RunLabel[] }>(
    serverUrl(ENDPOINTS.resultLabels(resultId), undefined, scope),
    { method: 'PUT', body: { label_ids: labelIds } },
  );

export const setResultMilestone = (resultId: string, milestoneId: string | null, scope?: ScopeParams) =>
  request<{ script_result_id: string; milestone_id: string | null }>(
    serverUrl(ENDPOINTS.resultMilestone(resultId), undefined, scope),
    { method: 'PUT', body: { milestone_id: milestoneId } },
  );

export const setResultRunGroup = (resultId: string, runGroupId: string | null, scope?: ScopeParams) =>
  request<{ script_result_id: string; run_group_id: string | null }>(
    serverUrl(ENDPOINTS.resultRunGroup(resultId), undefined, scope),
    { method: 'PUT', body: { run_group_id: runGroupId } },
  );

/** Atomic: every result is scope-checked and the whole batch commits or nothing does. */
export const batchAssign = (input: BatchAssignmentInput, scope?: ScopeParams) =>
  request<BatchAssignmentResponse>(serverUrl(ENDPOINTS.batchAssignments(), undefined, scope), {
    method: 'PUT',
    body: input,
  });

export const fetchTestcaseLabels = (testcaseId: string) =>
  request<{ testcase_id: string; labels: RunLabel[] }>(serverUrl(ENDPOINTS.testcaseLabels(testcaseId)));

export const setTestcaseLabels = (testcaseId: string, labelIds: string[]) =>
  request<{ testcase_id: string; labels: RunLabel[] }>(serverUrl(ENDPOINTS.testcaseLabels(testcaseId)), {
    method: 'PUT',
    body: { label_ids: labelIds },
  });

/** Existing script-results list (rows carry `labels`), narrowed server-side by governance filters. */
export const fetchScriptResults = (
  filters: ScriptResultGovernanceFilters & { script_name?: string; limit?: number },
  scope?: ScopeParams,
) =>
  request<ScriptResultRow[]>(
    serverUrl(
      ENDPOINTS.scriptResults(),
      {
        script_name: filters.script_name,
        milestone_id: filters.milestone_id,
        run_group_id: filters.run_group_id,
        label_id: filters.label_id,
        limit: filters.limit ?? 100,
      },
      // getAllScriptResults scopes by host only.
      { hostFilter: scope?.hostFilter },
    ),
  );

// ---------------------------------------------------------------------------
// Defects (team objects; evidence links are scope-checked)
// ---------------------------------------------------------------------------

export const fetchDefects = (params: DefectListParams = {}, scope?: ScopeParams) =>
  request<Paged<Defect>>(
    serverUrl(
      ENDPOINTS.defects(),
      { status: params.status, severity: params.severity, script_result_id: params.script_result_id, limit: 200 },
      scope,
    ),
  );

export const createDefect = (
  input: DefectInput & { title: string; script_result_ids?: string[] },
  scope?: ScopeParams,
) => request<Defect>(serverUrl(ENDPOINTS.defects(), undefined, scope), { method: 'POST', body: input });

export const updateDefect = (id: string, input: DefectInput) =>
  request<Defect>(serverUrl(ENDPOINTS.defect(id)), { method: 'PATCH', body: input });

export const linkDefectEvidence = (id: string, scriptResultId: string, scope?: ScopeParams) =>
  request<{ defect_id: string; linked_script_result_ids: string[] }>(
    serverUrl(ENDPOINTS.defectEvidence(id), undefined, scope),
    { method: 'POST', body: { script_result_id: scriptResultId } },
  );

export const unlinkDefectEvidence = (id: string, scriptResultId: string, scope?: ScopeParams) =>
  request<{ defect_id: string; unlinked_script_result_id: string }>(
    serverUrl(ENDPOINTS.defectEvidence(id), { script_result_id: scriptResultId }, scope),
    { method: 'DELETE' },
  );

/**
 * Explicit push. The server keeps one push record per defect, so a retry can never create a
 * second issue: 201 created, 200 already created, 409 in flight, 502 refused, 504 outcome
 * unknown (retry after the lease).
 */
export const pushDefectToJira = (id: string, scope?: ScopeParams) =>
  request<JiraPushResponse>(serverUrl(ENDPOINTS.defectPushJira(id), undefined, scope), { method: 'POST' });

export const refreshDefectFromJira = (id: string) =>
  request<JiraRefreshResponse>(serverUrl(ENDPOINTS.defectRefreshJira(id)), { method: 'POST' });

// ---------------------------------------------------------------------------
// Quality
// ---------------------------------------------------------------------------

const qualityQuery = (params: QualityParams): Query => ({ window_days: params.windowDays, limit: params.limit ?? 200 });

const normaliseIdentity = <R extends { identity: QualityIdentity }>(row: R): R => ({
  ...row,
  identity: { ...row.identity, script_type: row.identity?.script_type ?? null },
});

export const fetchFlaky = async (params: QualityParams, scope?: ScopeParams) => {
  const raw = await request<QualityResponse<FlakyRow>>(serverUrl(ENDPOINTS.flaky(), qualityQuery(params), scope));
  return {
    ...raw,
    rows: (raw.rows ?? []).map((row) => normaliseIdentity({ ...row, last_status: toRunStatus(row.last_status) })),
  };
};

export const fetchSlow = async (params: QualityParams, scope?: ScopeParams) => {
  const raw = await request<QualityResponse<SlowRow>>(serverUrl(ENDPOINTS.slow(), qualityQuery(params), scope));
  return { ...raw, rows: (raw.rows ?? []).map(normaliseIdentity) };
};

export const fetchNotExecuted = (params: QualityParams, scope?: ScopeParams) =>
  request<QualityResponse<NotExecutedRow>>(serverUrl(ENDPOINTS.notExecuted(), qualityQuery(params), scope));

// ---------------------------------------------------------------------------
// TQL, query and custom reports
// ---------------------------------------------------------------------------

/** Server-side TQL validation. A 400 is a validation answer, not a transport failure. */
export const validateTql = async (q: string, signal?: AbortSignal): Promise<TqlValidation> => {
  try {
    return await request<TqlValidation>(serverUrl(ENDPOINTS.tql(), { q }), { signal });
  } catch (error) {
    if (isApiError(error, 400)) {
      const body = (error.body ?? {}) as Partial<TqlValidation>;
      return { ok: false, error: body.error ?? error.message, position: body.position ?? null };
    }
    throw error;
  }
};

/** The scope travels in the query string, the definition in the body. */
export const runReportQuery = async (body: ReportQueryRequest, scope?: ScopeParams): Promise<ReportQueryResponse> => {
  const raw = await request<ReportQueryResponse>(serverUrl(ENDPOINTS.query(), undefined, scope), {
    method: 'POST',
    body,
  });
  return {
    ...raw,
    counts: toCounts(raw.counts as unknown as Record<string, unknown>),
    chart: raw.chart ?? { type: body.chart.type, points: [] },
  };
};

export const fetchCustomReports = () => request<Paged<CustomReport>>(serverUrl(ENDPOINTS.customReports()));

export const createCustomReport = (input: CustomReportInput) =>
  request<CustomReport>(serverUrl(ENDPOINTS.customReports()), { method: 'POST', body: input });

export const updateCustomReport = (id: string, input: CustomReportInput) =>
  request<CustomReport>(serverUrl(ENDPOINTS.customReport(id)), { method: 'PATCH', body: input });

export const deleteCustomReport = (id: string) =>
  request<{ deleted: boolean; id: string }>(serverUrl(ENDPOINTS.customReport(id)), { method: 'DELETE' });

// ---------------------------------------------------------------------------
// Sharing
// ---------------------------------------------------------------------------

export const fetchShareSnapshots = (identity: RunIdentity) =>
  request<Paged<ShareSnapshotMeta>>(
    serverUrl(ENDPOINTS.shareSnapshots(), { run_kind: identity.kind, run_id: identity.id }),
  );

/** The snapshot is built from the run as the caller sees it in this scope. */
export const createShareSnapshot = (body: CreateShareRequest, scope?: ScopeParams) =>
  request<CreateShareResponse>(serverUrl(ENDPOINTS.shareSnapshots(), undefined, scope), { method: 'POST', body });

export const revokeShareSnapshot = (id: string) =>
  request<ShareRevokeResponse>(serverUrl(ENDPOINTS.shareSnapshot(id)), { method: 'DELETE' });

/**
 * Anonymous read: no JWT, no auto-sign header, no team_id; the token travels in a header.
 * Every failure is a 404 (429 when rate limited).
 */
export const fetchPublicShare = async (snapshotId: string, token: string): Promise<PublicShareResponse> => {
  const raw = await request<PublicShareResponse>(publicServerUrl(ENDPOINTS.publicShare(snapshotId)), {
    skipAuth: true,
    headers: { [SHARE_TOKEN_HEADER]: token },
  });
  const payload = raw.snapshot.payload;
  return {
    snapshot: {
      ...raw.snapshot,
      payload: {
        ...payload,
        status: toRunStatus(payload.status),
        counts: toCounts(payload.counts as unknown as Record<string, unknown>),
        rows: (payload.rows ?? []).map((row) => ({ ...row, status: toRunStatus(row.status) })),
        safe_labels: payload.safe_labels ?? [],
      },
    },
  };
};

// ---------------------------------------------------------------------------
// Manual sessions (scoped by host/device; only the session actor may change one)
// ---------------------------------------------------------------------------

export const fetchManualSessions = (scope?: ScopeParams) =>
  request<{ items: ManualSessionListItem[] }>(
    serverUrl(ENDPOINTS.manualSessions(), { status: 'in_progress' }, scope),
  );

export const fetchManualSession = (id: string, scope?: ScopeParams) =>
  request<ManualSession>(serverUrl(ENDPOINTS.manualSession(id), undefined, scope));

/** 201 new, 200 replay of the same idempotency key. */
export const createManualSession = (body: CreateManualSessionRequest, scope?: ScopeParams) =>
  request<ManualSession & { created: boolean }>(serverUrl(ENDPOINTS.manualSessions(), undefined, scope), {
    method: 'POST',
    body,
  });

/** 409 `{code, current}` = someone else saved first; the caller reloads and shows the current state. */
export const updateManualSession = (id: string, body: UpdateManualSessionRequest, scope?: ScopeParams) =>
  request<ManualSession>(serverUrl(ENDPOINTS.manualSession(id), undefined, scope), { method: 'PATCH', body });

/** Idempotent per session: 201 first, 200 repeat with the same script_result_id; 422 missing outcomes. */
export const finalizeManualSession = (id: string, body: FinalizeManualSessionRequest, scope?: ScopeParams) =>
  request<FinalizeManualSessionResponse>(serverUrl(ENDPOINTS.manualFinalize(id), undefined, scope), {
    method: 'POST',
    body,
  });

export const fetchTestcases = () =>
  request<{ success?: boolean; testcases?: Array<{ testcase_id: string; testcase_name: string }> }>(
    serverUrl(ENDPOINTS.testcaseList()),
  );

export const fetchTestcaseVersions = (testcaseId: string) =>
  request<{ success: boolean; versions: TestcaseVersion[] }>(serverUrl(ENDPOINTS.testcaseVersions(testcaseId)));

// ---------------------------------------------------------------------------
// Live
// ---------------------------------------------------------------------------

/** 404 carries `{status: 'unknown'}`: the task is not known to this server (or out of scope). */
export const fetchLiveStatus = async (taskId: string, signal?: AbortSignal, scope?: ScopeParams) =>
  normaliseLive(await request<LiveRunStatus>(serverUrl(ENDPOINTS.live(taskId), undefined, scope), { signal }));

/** 202 = stop requested; the task reaches a terminal status on a later poll. */
export const stopLiveRun = (taskId: string, scope?: ScopeParams) =>
  request<LiveStopResponse>(serverUrl(ENDPOINTS.liveStop(taskId), undefined, scope), { method: 'POST' });

/** A fresh idempotency key; generate once per user action and reuse it on retry. */
export const newIdempotencyKey = (): string =>
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
