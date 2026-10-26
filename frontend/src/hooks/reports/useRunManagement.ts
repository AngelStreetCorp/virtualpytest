/**
 * React Query hooks for the run-management surface.
 *
 * Scope: every read is keyed by the selected server and the active workspace's host
 * names (the same `host_filter` TestReports sends), and the server applies that scope
 * before limits and aggregation. team_id is appended by buildServerUrl.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useServerManager } from '../useServerManager';
import { usePermissions } from '../auth/usePermissions';
import { ALL_SERVERS_SENTINEL } from '../../lib/allServer/scope';
import {
  REPORT_PERMISSIONS,
  type BatchAssignmentInput,
  type CreateShareRequest,
  type CustomReportInput,
  type DefectInput,
  type DefectListParams,
  type LabelInput,
  type MilestoneInput,
  type QualityParams,
  type ReportScope,
  type RunGroupInput,
  type RunIdentity,
  type RunSummaryParams,
} from '../../types/reports';
import * as rmApi from './runManagementApi';

const ROOT = 'run-management';

/**
 * The active workspace scope: its `host:device_id` keys (device_filter) and their host
 * names (host_filter). Endpoints that scope by host only ignore the device keys.
 *
 * TASK-113: when the picker is in ALL mode (`selectedServer ===
 * ALL_SERVERS_SENTINEL), the scope's `serverKey` becomes the literal
 * `'*'`. React Query keys still pass `'*'` through; per-server fetches
 * are not done by this hook — the consumer (e.g. `useRunSummary`)
 * fans out per eligible server using `queryScope` (PR-B) and the
 * individual results land in the React Query cache under their own
 * per-server key. `'*'` is a SCOPE marker for the workspace, not a
 * substitute for `serverId` in a cache key.
 */
export const useReportScope = (): ReportScope => {
  const { activeWorkspace } = useWorkspaceContext();
  const { selectedServer } = useServerManager();
  return useMemo(() => {
    const keys = activeWorkspace?.device_filter;
    const deviceFilter = keys?.length ? Array.from(new Set(keys)).sort() : undefined;
    const hostFilter = deviceFilter
      ? Array.from(new Set(deviceFilter.map((entry) => entry.split(':')[0]).filter(Boolean))).sort()
      : undefined;
    const isAllMode = selectedServer === ALL_SERVERS_SENTINEL;
    return {
      hostFilter,
      deviceFilter,
      serverKey: isAllMode ? '*' : String(selectedServer ?? ''),
    };
  }, [activeWorkspace, selectedServer]);
};

/** What the current user may do on this surface (the server re-checks every call). */
export const useReportPermissions = () => {
  const { hasPermission } = usePermissions();
  return {
    canView: hasPermission(REPORT_PERMISSIONS.view),
    canEdit: hasPermission(REPORT_PERMISSIONS.edit),
    canEditDefects: hasPermission(REPORT_PERMISSIONS.defects),
    canShare: hasPermission(REPORT_PERMISSIONS.share),
    canRunManual: hasPermission(REPORT_PERMISSIONS.manual),
    canRerun: hasPermission(REPORT_PERMISSIONS.rerun),
    canStop: hasPermission(REPORT_PERMISSIONS.stop),
  };
};

const scopeKey = (scope: ReportScope) => [scope.serverKey, scope.deviceFilter?.join(',') ?? '*'] as const;

/** Do not retry permission / not-found answers; they will not change on retry. */
const retryTransient = (failureCount: number, error: unknown) =>
  !(rmApi.isApiError(error) && error.status >= 400 && error.status < 500) && failureCount < 2;

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

export const useRunSummary = (identity: RunIdentity | null, params: RunSummaryParams) => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'summary', ...scopeKey(scope), identity?.kind, identity?.id, params],
    queryFn: () => rmApi.fetchRunSummary(identity as RunIdentity, params, scope),
    enabled: Boolean(identity),
    placeholderData: (previous) => previous,
    retry: retryTransient,
  });
};

// ---------------------------------------------------------------------------
// Governance
// ---------------------------------------------------------------------------

export const useRunGroups = (includeArchived: boolean) => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'groups', scope.serverKey, includeArchived],
    queryFn: () => rmApi.fetchRunGroups(includeArchived),
    retry: retryTransient,
  });
};

export const useGroupReport = (groupId: string | undefined) => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'group-report', ...scopeKey(scope), groupId],
    queryFn: () => rmApi.fetchGroupReport(groupId as string, scope),
    enabled: Boolean(groupId),
    retry: retryTransient,
  });
};

export const useMilestones = (includeArchived: boolean) => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'milestones', scope.serverKey, includeArchived],
    queryFn: () => rmApi.fetchMilestones(includeArchived),
    retry: retryTransient,
  });
};

export const useLabels = () => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'labels', scope.serverKey],
    queryFn: rmApi.fetchLabels,
    retry: retryTransient,
  });
};

export const useGovernanceResults = (
  filters: { milestone_id?: string | null; run_group_id?: string | null; label_id?: string | null },
  enabled = true,
) => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'governance-results', ...scopeKey(scope), filters],
    queryFn: () => rmApi.fetchScriptResults(filters, scope),
    enabled,
    retry: retryTransient,
  });
};

/** Invalidate everything a governance mutation can change. */
const useInvalidateRunManagement = () => {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: [ROOT] });
};

export const useGovernanceMutations = () => {
  const invalidate = useInvalidateRunManagement();
  const scope = useReportScope();
  const opts = { onSuccess: invalidate };
  return {
    createGroup: useMutation({ mutationFn: (input: RunGroupInput) => rmApi.createRunGroup(input), ...opts }),
    updateGroup: useMutation({
      mutationFn: ({ id, input }: { id: string; input: RunGroupInput }) => rmApi.updateRunGroup(id, input),
      ...opts,
    }),
    archiveGroup: useMutation({ mutationFn: (id: string) => rmApi.archiveRunGroup(id), ...opts }),
    restoreGroup: useMutation({ mutationFn: (id: string) => rmApi.restoreRunGroup(id), ...opts }),
    createMilestone: useMutation({ mutationFn: (input: MilestoneInput) => rmApi.createMilestone(input), ...opts }),
    updateMilestone: useMutation({
      mutationFn: ({ id, input }: { id: string; input: MilestoneInput }) => rmApi.updateMilestone(id, input),
      ...opts,
    }),
    archiveMilestone: useMutation({ mutationFn: (id: string) => rmApi.archiveMilestone(id), ...opts }),
    restoreMilestone: useMutation({ mutationFn: (id: string) => rmApi.restoreMilestone(id), ...opts }),
    createLabel: useMutation({ mutationFn: (input: LabelInput) => rmApi.createLabel(input), ...opts }),
    updateLabel: useMutation({
      mutationFn: ({ id, input }: { id: string; input: LabelInput }) => rmApi.updateLabel(id, input),
      ...opts,
    }),
    deleteLabel: useMutation({ mutationFn: (id: string) => rmApi.deleteLabel(id), ...opts }),
    setResultLabels: useMutation({
      mutationFn: ({ resultId, labelIds }: { resultId: string; labelIds: string[] }) =>
        rmApi.setResultLabels(resultId, labelIds, scope),
      ...opts,
    }),
    setResultMilestone: useMutation({
      mutationFn: ({ resultId, milestoneId }: { resultId: string; milestoneId: string | null }) =>
        rmApi.setResultMilestone(resultId, milestoneId, scope),
      ...opts,
    }),
    setResultRunGroup: useMutation({
      mutationFn: ({ resultId, runGroupId }: { resultId: string; runGroupId: string | null }) =>
        rmApi.setResultRunGroup(resultId, runGroupId, scope),
      ...opts,
    }),
    batchAssign: useMutation({
      mutationFn: (input: BatchAssignmentInput) => rmApi.batchAssign(input, scope),
      ...opts,
    }),
  };
};

// ---------------------------------------------------------------------------
// Defects
// ---------------------------------------------------------------------------

export const useDefects = (params: DefectListParams, enabled = true) => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'defects', ...scopeKey(scope), params],
    queryFn: () => rmApi.fetchDefects(params, scope),
    enabled,
    retry: retryTransient,
  });
};

export const useDefectMutations = () => {
  const invalidate = useInvalidateRunManagement();
  const scope = useReportScope();
  const opts = { onSuccess: invalidate };
  return {
    create: useMutation({
      mutationFn: (input: Parameters<typeof rmApi.createDefect>[0]) => rmApi.createDefect(input, scope),
      ...opts,
    }),
    update: useMutation({
      mutationFn: ({ id, input }: { id: string; input: DefectInput }) => rmApi.updateDefect(id, input),
      ...opts,
    }),
    link: useMutation({
      mutationFn: ({ id, scriptResultId }: { id: string; scriptResultId: string }) =>
        rmApi.linkDefectEvidence(id, scriptResultId, scope),
      ...opts,
    }),
    unlink: useMutation({
      mutationFn: ({ id, scriptResultId }: { id: string; scriptResultId: string }) =>
        rmApi.unlinkDefectEvidence(id, scriptResultId, scope),
      ...opts,
    }),
    pushJira: useMutation({ mutationFn: (id: string) => rmApi.pushDefectToJira(id, scope), ...opts }),
    refreshJira: useMutation({ mutationFn: (id: string) => rmApi.refreshDefectFromJira(id), ...opts }),
  };
};

// ---------------------------------------------------------------------------
// Quality — one scoped query hook for the three insight pages and TestReports badges
// ---------------------------------------------------------------------------

export type QualityKind = 'flaky' | 'slow' | 'notExecuted';

const QUALITY_FETCHERS = {
  flaky: rmApi.fetchFlaky,
  slow: rmApi.fetchSlow,
  notExecuted: rmApi.fetchNotExecuted,
} as const;

type QualityResult<K extends QualityKind> = Awaited<ReturnType<(typeof QUALITY_FETCHERS)[K]>>;

export const useQualityQuery = <K extends QualityKind>(kind: K, params: QualityParams, enabled = true) => {
  const scope = useReportScope();
  return useQuery<QualityResult<K>>({
    queryKey: [ROOT, 'quality', kind, ...scopeKey(scope), params],
    queryFn: () => QUALITY_FETCHERS[kind](params, scope) as Promise<QualityResult<K>>,
    enabled,
    retry: retryTransient,
  });
};

// ---------------------------------------------------------------------------
// Custom reports
// ---------------------------------------------------------------------------

export const useCustomReports = () => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'custom-reports', scope.serverKey],
    queryFn: rmApi.fetchCustomReports,
    retry: retryTransient,
  });
};

export const useCustomReportMutations = () => {
  const invalidate = useInvalidateRunManagement();
  const opts = { onSuccess: invalidate };
  return {
    create: useMutation({ mutationFn: (input: CustomReportInput) => rmApi.createCustomReport(input), ...opts }),
    update: useMutation({
      mutationFn: ({ id, input }: { id: string; input: CustomReportInput }) => rmApi.updateCustomReport(id, input),
      ...opts,
    }),
    remove: useMutation({ mutationFn: (id: string) => rmApi.deleteCustomReport(id), ...opts }),
  };
};

// ---------------------------------------------------------------------------
// Sharing
// ---------------------------------------------------------------------------

export const useShareSnapshots = (identity: RunIdentity, enabled: boolean) => {
  const scope = useReportScope();
  return useQuery({
    queryKey: [ROOT, 'share-snapshots', scope.serverKey, identity.kind, identity.id],
    queryFn: () => rmApi.fetchShareSnapshots(identity),
    enabled,
    retry: retryTransient,
  });
};

export const useShareMutations = () => {
  const invalidate = useInvalidateRunManagement();
  const scope = useReportScope();
  const opts = { onSuccess: invalidate };
  return {
    create: useMutation({
      mutationFn: (body: CreateShareRequest) => rmApi.createShareSnapshot(body, scope),
      ...opts,
    }),
    revoke: useMutation({ mutationFn: (id: string) => rmApi.revokeShareSnapshot(id), ...opts }),
  };
};
