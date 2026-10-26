import { useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useServerManager } from '../useServerManager';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { apiClient } from '../../utils/apiClient';

// Source preparation + deploy/rollback logic of the former Code deployment page, unchanged, moved here so
// Platform update can use it in steps 1 (bundle/source) and 2 (code deployment).

export type DeployAction = 'deploy' | 'rollback';
export type LocalTargetKind = 'server' | 'frontend';

export interface DeployResult {
  target: string;
  action: DeployAction;
  success: boolean;
  message?: string;
  error?: string;
  version_before?: string;
  version_after?: string;
}

export interface ExecutionTarget {
  kind: 'server' | 'frontend' | 'host';
  id: string;
}

export interface RollbackOption {
  backup_id: string;
  label: string;
}

export interface SourceVersionInfo {
  current: string | null;
  before: string | null;
  after: string | null;
  commit: string | null;
}

export interface SourceDiffEntry {
  status: string;
  path: string;
  added: string;
  deleted: string;
}

export interface GitRepositoryOption {
  name: string;
  url: string;
}

export const gitRepositoryName = (url: string | null): string => {
  if (!url) return 'Current origin';
  const path = url.replace(/\.git$/, '').split(/[/:]/).filter(Boolean);
  return path[path.length - 1] || 'Current origin';
};

export interface CodeDeploymentOptions {
  /** Called after a deploy or rollback finished on every selected target. */
  onFinished?: (action: DeployAction, results: DeployResult[], ok: boolean) => void;
}

export const useCodeDeployment = (options: CodeDeploymentOptions = {}) => {
  const P = useAgentChatPalette();
  const { serverHostsData, refreshServerData } = useServerManager();
  const [selectedHosts, setSelectedHosts] = useState<string[]>([]);
  const [selectedLocalTargets, setSelectedLocalTargets] = useState<LocalTargetKind[]>([]);
  const [sourcePath, setSourcePath] = useState('/mnt/shared/code/virtualpytest');

  const [gitRef, setGitRef] = useState('debug');
  const [activeGitBranch, setActiveGitBranch] = useState<string | null>(null);
  const [sourceMode, setSourceMode] = useState<'git' | 'zip'>('zip');
  const [detectedGit, setDetectedGit] = useState<boolean | null>(null);
  const [pathExists, setPathExists] = useState(false);
  const [sourceReady, setSourceReady] = useState(false);
  const [gitBranches, setGitBranches] = useState<string[]>([]);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [uploadFilename, setUploadFilename] = useState<string | null>(null);
  const [zipValidated, setZipValidated] = useState(false);
  const [sourceVersionInfo, setSourceVersionInfo] = useState<SourceVersionInfo>({
    current: null,
    before: null,
    after: null,
    commit: null,
  });
  const [sourceDiffEntries, setSourceDiffEntries] = useState<SourceDiffEntry[]>([]);
  const [originUrl, setOriginUrl] = useState<string | null>(null);
  const [remoteUrlDraft, setRemoteUrlDraft] = useState('');
  const [gitRepositories, setGitRepositories] = useState<GitRepositoryOption[]>([]);
  const [needsGitReset, setNeedsGitReset] = useState(false);

  const [rollbackCandidates, setRollbackCandidates] = useState<ExecutionTarget[]>([]);
  const [rollbackOptions, setRollbackOptions] = useState<RollbackOption[]>([
    { backup_id: 'latest_stable', label: 'Last stable' },
  ]);
  const [selectedRollbackId, setSelectedRollbackId] = useState('latest_stable');
  const [isLoadingRollbackOptions, setIsLoadingRollbackOptions] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [results, setResults] = useState<DeployResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Frontend's own deployed version: this page is served by the deployed
  // frontend bundle, so its version is __APP_VERSION__ (Vite build-time
  // constant) with a /version.txt HTTP fallback — identical to Footer.tsx.
  // We do NOT use serverHostsData[].frontend_info here: that comes from the
  // backend server SSHing into the frontend VM and is unreliable (-> 'unknown').
  const embeddedFrontendVersion =
    typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'unknown';
  const [frontendVersion, setFrontendVersion] = useState(embeddedFrontendVersion);

  useEffect(() => {
    if (embeddedFrontendVersion && embeddedFrontendVersion !== 'unknown') {
      setFrontendVersion(embeddedFrontendVersion);
      return;
    }
    let cancelled = false;
    const loadVersion = async () => {
      try {
        const response = await fetch('/version.txt', {
          cache: 'no-store',
          headers: { 'Cache-Control': 'no-cache' },
        });
        if (!response.ok) {
          return;
        }
        const text = await response.text();
        const lines = text.split(/\r?\n/).map((line) => line.trim());
        const currentLine = lines.find((line) => /^current\s*:/i.test(line));
        const nextVersion = currentLine
          ? currentLine.split(':').slice(1).join(':').trim()
          : lines.find((line) => line.length > 0);
        if (!cancelled && nextVersion) {
          setFrontendVersion(nextVersion);
        }
      } catch {
        // Keep the embedded fallback.
      }
    };
    void loadVersion();
    return () => {
      cancelled = true;
    };
  }, [embeddedFrontendVersion]);

  const allHosts = useMemo(() => {
    const names = new Set<string>();
    const hosts = [];
    for (const serverData of serverHostsData) {
      for (const host of serverData.hosts) {
        if (!names.has(host.host_name)) {
          names.add(host.host_name);
          hosts.push(host);
        }
      }
    }
    return hosts;
  }, [serverHostsData]);

  const serverInfo = serverHostsData[0]?.server_info;
  const originOptions = useMemo(() => {
    const options = [...gitRepositories];
    if (originUrl && !options.some((repository) => repository.url === originUrl)) {
      options.unshift({ name: gitRepositoryName(originUrl), url: originUrl });
    }
    return options;
  }, [gitRepositories, originUrl]);
  const allHostsSelected = allHosts.length > 0 && selectedHosts.length === allHosts.length;
  const allTargetsSelected =
    selectedLocalTargets.includes('server') &&
    selectedLocalTargets.includes('frontend') &&
    allHostsSelected;
  const someTargetsSelected =
    selectedLocalTargets.length > 0 || selectedHosts.length > 0;

  const toggleSelectAllTargets = (selectAll: boolean) => {
    setSelectedLocalTargets(selectAll ? ['server', 'frontend'] : []);
    setSelectedHosts(selectAll ? allHosts.map((host) => host.host_name) : []);
  };

  const orderedTargets = useMemo(() => {
    const targets: ExecutionTarget[] = [];
    if (selectedLocalTargets.includes('server')) targets.push({ kind: 'server', id: 'server' });
    if (selectedLocalTargets.includes('frontend')) targets.push({ kind: 'frontend', id: 'frontend' });
    for (const host of allHosts) {
      if (selectedHosts.includes(host.host_name)) targets.push({ kind: 'host', id: host.host_name });
    }
    return targets;
  }, [selectedLocalTargets, allHosts, selectedHosts]);

  useEffect(() => {
    void loadRollbackOptions();
  }, [orderedTargets]);

  const toggleLocalTarget = (target: LocalTargetKind) => {
    setSelectedLocalTargets((previous) =>
      previous.includes(target) ? previous.filter((entry) => entry !== target) : [...previous, target]
    );
  };

  const toggleHost = (hostName: string) => {
    setSelectedHosts((previous) =>
      previous.includes(hostName)
        ? previous.filter((entry) => entry !== hostName)
        : [...previous, hostName]
    );
  };

  const toggleSelectAllHosts = (checked: boolean) => {
    setSelectedHosts(checked ? allHosts.map((host) => host.host_name) : []);
  };

  const setMessage = (message: string | null, isError = false) => {
    if (isError) {
      setError(message);
      setInfo(null);
      return;
    }
    setInfo(message);
    setError(null);
  };

  const targetLabel = (target: ExecutionTarget) => {
    if (target.kind === 'server') return 'SERVER';
    if (target.kind === 'frontend') return 'FRONTEND';
    return target.id;
  };

  const extractHash = (version: string): string => {
    const parts = version.split('-');
    return parts.length >= 2 ? parts[parts.length - 1] : version;
  };

  // Some version files prefix the value with a "current:" label — strip it for display.
  const formatVersion = (version: string): string => version.replace(/^\s*current\s*:\s*/i, '').trim();

  const getVersionColor = (deployedVersion: string | null | undefined) => {
    if (!sourceVersionInfo.current || !deployedVersion) return 'text.secondary';
    return extractHash(deployedVersion) === extractHash(sourceVersionInfo.current) ? 'success.main' : 'error.main';
  };

  const formatRollbackLabel = (entry: Record<string, unknown>) => {
    const version = typeof entry.version === 'string' && entry.version.trim() ? entry.version : 'unknown';
    const createdAt = typeof entry.created_at === 'string' ? entry.created_at.replace('T', ' ').replace('Z', '') : '';
    return createdAt ? `${version} - ${createdAt}` : version;
  };

  const noStableRollbackOption: RollbackOption = {
    backup_id: 'unavailable',
    label: 'No working version',
  };

  const resetSourceState = () => {
    setPathExists(false);
    setActiveGitBranch(null);
    setSourceReady(false);
    setGitBranches([]);
    setUploadId(null);
    setUploadFilename(null);
    setZipValidated(false);
    setSourceVersionInfo({ current: null, before: null, after: null, commit: null });
    setSourceDiffEntries([]);
    setNeedsGitReset(false);
    setOriginUrl(null);
    setRemoteUrlDraft('');
    setGitRepositories([]);
  };

  const readSourceVersion = (payload: Record<string, unknown> | null | undefined) => {
    if (!payload) return null;
    const version =
      typeof payload.version === 'string' && payload.version.trim()
        ? payload.version.trim()
        : typeof payload.short_commit === 'string' && payload.short_commit.trim()
          ? payload.short_commit.trim()
          : null;
    return version;
  };

  const detectSource = async () => {
    setIsSubmitting(true);
    setMessage(null);
    setDetectedGit(null);
    resetSourceState();
    try {
      const response = await apiClient(buildServerUrl('/server/system/source/detect'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage_path: sourcePath }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setMessage(data.error || 'Failed to detect source', true);
        return;
      }
      setSourcePath(data.storage_path || sourcePath);
      setPathExists(Boolean(data.path_exists));
      if (!data.path_exists) return; // the Source panel says so; no page-level error for an unused path
      setDetectedGit(Boolean(data.is_git_repo));
      setSourceMode(data.is_git_repo ? 'git' : 'zip');
      const currentOrigin = typeof data.origin_url === 'string' ? data.origin_url : null;
      setOriginUrl(currentOrigin);
      setRemoteUrlDraft(currentOrigin || '');
      const branches = Array.isArray(data.branches)
        ? data.branches.filter((entry: unknown): entry is string => typeof entry === 'string' && entry.trim().length > 0)
        : [];
      setGitBranches(branches);
      const detectedVersion = readSourceVersion(data);
      setSourceVersionInfo({
        current: detectedVersion,
        before: null,
        after: null,
        commit: null,
      });
      setSourceReady(false);
      if (typeof data.branch === 'string' && data.branch.trim()) {
        setGitRef(data.branch.trim());
        setActiveGitBranch(data.branch.trim());
      } else if (branches.length > 0) {
        setGitRef(branches[0]);
      }
      setInfo(null);
      setError(null);
      if (data.is_git_repo) {
        const repoResponse = await apiClient(buildServerUrl('/server/system/source/git/repositories'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        const repoData = await repoResponse.json();
        if (repoResponse.ok && repoData.success && Array.isArray(repoData.repositories)) {
          const repositories: GitRepositoryOption[] = (repoData.repositories as unknown[]).filter(
              (entry: unknown): entry is GitRepositoryOption =>
                Boolean(entry) &&
                typeof entry === 'object' &&
                typeof (entry as GitRepositoryOption).name === 'string' &&
                typeof (entry as GitRepositoryOption).url === 'string'
            );
          const currentName = gitRepositoryName(currentOrigin);
          setGitRepositories(repositories.map((repository) =>
            repository.name === currentName && currentOrigin
              ? { ...repository, url: currentOrigin }
              : repository
          ));
        }
      }
    } catch (requestError) {
      setMessage(
        `Detect failed: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`,
        true
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const reconfigureGitRemote = async () => {
    if (!remoteUrlDraft.trim()) {
      setMessage('Select or enter an approved repository URL first.', true);
      return;
    }
    setIsSubmitting(true);
    setMessage(null);
    setSourceReady(false);
    try {
      const response = await apiClient(buildServerUrl('/server/system/source/git/remote'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage_path: sourcePath, remote_url: remoteUrlDraft.trim() }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setMessage(data.error || 'Remote reconfiguration failed', true);
        return;
      }
      const updatedOrigin = typeof data.origin_url === 'string' ? data.origin_url : remoteUrlDraft.trim();
      setOriginUrl(updatedOrigin);
      setRemoteUrlDraft(updatedOrigin);
      const branches = Array.isArray(data.branches)
        ? data.branches.filter((entry: unknown): entry is string => typeof entry === 'string' && entry.trim().length > 0)
        : [];
      setGitBranches(branches);
      if (branches.length > 0 && !branches.includes(gitRef)) setGitRef(branches[0]);
      setMessage('Origin updated and fetched. Select a branch, then pull it into the deployment source.');
    } catch (requestError) {
      setMessage(
        `Remote reconfiguration failed: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`,
        true
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const prepareGitSource = async (forceReset = false) => {
    setIsSubmitting(true);
    setMessage(null);
    setSourceReady(false);
    try {
      const response = await apiClient(buildServerUrl('/server/system/source/git/prepare'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          storage_path: sourcePath,
          git_ref: gitRef.trim(),
          force_reset: forceReset,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setNeedsGitReset(!forceReset && Boolean(data.reset_required));
        setMessage(data.error || 'Git source prepare failed', true);
        return;
      }
      setSourcePath(data.storage_path || sourcePath);
      const branch = data.after?.branch || gitRef;
      if (branch) {
        setGitRef(branch);
        setActiveGitBranch(branch);
      }
      const beforeVersion = readSourceVersion(data.before);
      const afterVersion = readSourceVersion(data.after);
      const diffEntries = Array.isArray(data.diff_files)
        ? data.diff_files.filter(
            (entry: unknown): entry is SourceDiffEntry =>
              Boolean(entry) &&
              typeof entry === 'object' &&
              typeof (entry as SourceDiffEntry).status === 'string' &&
              typeof (entry as SourceDiffEntry).path === 'string'
          )
        : [];
      const commitHash = typeof data.after?.commit === 'string' ? data.after.commit : null;
      setSourceVersionInfo({
        current: afterVersion,
        before: beforeVersion,
        after: afterVersion,
        commit: commitHash,
      });
      setSourceDiffEntries(diffEntries);
      setSourceReady(true);
      setNeedsGitReset(false);
      setInfo(null);
      setError(null);
      void refreshServerData(true);
    } catch (requestError) {
      setMessage(
        `Git prepare failed: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`,
        true
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const uploadZip = async (file: File) => {
    setIsSubmitting(true);
    setMessage(null);
    setSourceReady(false);
    setZipValidated(false);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('storage_path', sourcePath);
      const response = await apiClient(buildServerUrl('/server/system/source/zip/upload'), {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setMessage(data.error || 'Zip upload failed', true);
        return;
      }
      setUploadId(data.upload_id);
      setUploadFilename(file.name);
      setSourcePath(data.storage_path || sourcePath);
      setMessage(`Zip uploaded: ${file.name}`);
    } catch (requestError) {
      setMessage(
        `Zip upload failed: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`,
        true
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const validateZip = async () => {
    if (!uploadId) {
      setMessage('Upload a zip first.', true);
      return;
    }
    setIsSubmitting(true);
    setMessage(null);
    setSourceReady(false);
    setZipValidated(false);
    try {
      const response = await apiClient(buildServerUrl('/server/system/source/zip/validate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: uploadId }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setMessage(data.error || 'Zip validation failed', true);
        return;
      }
      setZipValidated(true);
      setMessage('Zip validation passed');
    } catch (requestError) {
      setMessage(
        `Zip validation failed: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`,
        true
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const applyZipToStorage = async () => {
    if (!uploadId || !zipValidated) {
      setMessage('Validate zip before applying.', true);
      return;
    }
    setIsSubmitting(true);
    setMessage(null);
    setSourceReady(false);
    try {
      const response = await apiClient(buildServerUrl('/server/system/source/zip/apply'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: uploadId, storage_path: sourcePath }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setMessage(data.error || 'Failed to apply zip to storage', true);
        return;
      }
      setSourcePath(data.storage_path || sourcePath);
      setSourceReady(true);
      setSourceDiffEntries([]);
      setMessage('ZIP source applied to storage and ready for deployment');
    } catch (requestError) {
      setMessage(
        `Zip apply failed: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`,
        true
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const loadRollbackOptions = async () => {
    if (orderedTargets.length !== 1) {
      setRollbackOptions([{ backup_id: 'latest_stable', label: 'Last stable' }]);
      setSelectedRollbackId('latest_stable');
      return;
    }
    const target = orderedTargets[0];
    setIsLoadingRollbackOptions(true);
    try {
      const endpoint =
        target.kind === 'host' ? '/server/system/listHostCoreBackups' : '/server/system/listCoreBackups';
      const payload = target.kind === 'host' ? { host_name: target.id } : { target_kind: target.kind };
      const response = await apiClient(buildServerUrl(endpoint), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setRollbackOptions([noStableRollbackOption]);
        setSelectedRollbackId(noStableRollbackOption.backup_id);
        return;
      }
      const options = Array.isArray(data.backups)
        ? data.backups
            .filter((entry: unknown): entry is Record<string, unknown> => Boolean(entry) && typeof entry === 'object')
            .map((entry: Record<string, unknown>) => ({
              backup_id: String(entry.backup_id || ''),
              label: formatRollbackLabel(entry),
            }))
            .filter((entry: { backup_id: string }) => entry.backup_id)
        : [];
      if (options.length === 0) {
        setRollbackOptions([noStableRollbackOption]);
        setSelectedRollbackId(noStableRollbackOption.backup_id);
        return;
      }
      setRollbackOptions(options);
      setSelectedRollbackId(String(data.default_backup_id || options[0].backup_id));
    } catch {
      setRollbackOptions([noStableRollbackOption]);
      setSelectedRollbackId(noStableRollbackOption.backup_id);
    } finally {
      setIsLoadingRollbackOptions(false);
    }
  };

  const runTargetAction = async (target: ExecutionTarget, action: DeployAction): Promise<DeployResult> => {
    const source = sourcePath.trim();
    if (target.kind === 'server' || target.kind === 'frontend') {
      const endpoint =
        action === 'deploy' ? '/server/system/updateCoreLocal' : '/server/system/rollbackCoreLocal';
      const payload =
        action === 'deploy'
          ? {
              target_kind: target.kind,
              dry_run: false,
              restart_service: true,
              source_path: source,
            }
          : {
              target_kind: target.kind,
              dry_run: false,
              restart_service: true,
              ...(orderedTargets.length === 1 && selectedRollbackId !== 'latest_stable'
                ? { backup_id: selectedRollbackId }
                : {}),
            };
      const response = await apiClient(buildServerUrl(endpoint), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      return {
        target: targetLabel(target),
        action,
        success: Boolean(data.success),
        message: data.message,
        error: data.error,
        version_before: data.version_before,
        version_after: data.version_after,
      };
    }

    const endpoint =
      action === 'deploy' ? '/server/system/updateHostCore' : '/server/system/rollbackHostCore';
    const payload =
      action === 'deploy'
        ? {
            host_name: target.id,
            dry_run: false,
            target_kind: 'host-linux',
            restart_host_service: true,
            source_path: source,
          }
        : {
            host_name: target.id,
            dry_run: false,
            restart_host_service: true,
            ...(orderedTargets.length === 1 && selectedRollbackId !== 'latest_stable'
              ? { backup_id: selectedRollbackId }
              : {}),
          };
    const response = await apiClient(buildServerUrl(endpoint), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    return {
      target: target.id,
      action,
      success: Boolean(data.success),
      message: data.message,
      error: data.error,
      version_before: data.version_before,
      version_after: data.version_after,
    };
  };

  const executeWithFailFast = async (
    action: DeployAction,
    targets: ExecutionTarget[]
  ): Promise<{ results: DeployResult[]; failedTarget: ExecutionTarget | null; succeeded: ExecutionTarget[] }> => {
    const collected: DeployResult[] = [];
    const succeeded: ExecutionTarget[] = [];
    for (const target of targets) {
      const result = await runTargetAction(target, action);
      collected.push(result);
      if (!result.success) {
        return { results: collected, failedTarget: target, succeeded };
      }
      succeeded.push(target);
    }
    return { results: collected, failedTarget: null, succeeded };
  };

  const executeDeploy = async () => {
    if (!sourceReady) {
      setMessage('Prepare source first before deployment.', true);
      return;
    }
    if (orderedTargets.length === 0) {
      setMessage('Select at least one target (server/frontend/host).', true);
      return;
    }

    setIsSubmitting(true);
    setMessage(null);
    setRollbackCandidates([]);
    try {
      const { results: deployResults, failedTarget, succeeded } = await executeWithFailFast(
        'deploy',
        orderedTargets
      );
      setResults(deployResults);
      options.onFinished?.('deploy', deployResults, !failedTarget);
      if (failedTarget) {
        setRollbackCandidates(succeeded);
        setError(null);
      } else {
        setMessage('Deployment completed successfully.');
      }
    } catch (requestError) {
      setMessage(
        `Failed to execute deploy: ${
          requestError instanceof Error ? requestError.message : 'Unknown error'
        }`,
        true
      );
    } finally {
      setIsSubmitting(false);
      await refreshServerData(true);
    }
  };

  const executeRollbackSelected = async () => {
    if (orderedTargets.length === 0) {
      setMessage('Select at least one target (server/frontend/host).', true);
      return;
    }
    if (selectedRollbackId === noStableRollbackOption.backup_id) {
      setMessage('No working version available for rollback.', true);
      return;
    }
    setIsSubmitting(true);
    setMessage(null);
    try {
      const { results: rollbackResults, failedTarget } = await executeWithFailFast(
        'rollback',
        orderedTargets
      );
      setResults(rollbackResults);
      options.onFinished?.('rollback', rollbackResults, !failedTarget);
      if (failedTarget) {
        setError(null);
      } else {
        setMessage('Rollback completed successfully.');
      }
    } catch (requestError) {
      setMessage(
        `Failed to execute rollback: ${
          requestError instanceof Error ? requestError.message : 'Unknown error'
        }`,
        true
      );
    } finally {
      setIsSubmitting(false);
      await refreshServerData(true);
    }
  };

  const executeRollbackRecovery = async () => {
    if (rollbackCandidates.length === 0) {
      setMessage('No rollback candidates available.', true);
      return;
    }
    setIsSubmitting(true);
    setMessage(null);
    try {
      const targets = [...rollbackCandidates].reverse();
      const { results: rollbackResults, failedTarget } = await executeWithFailFast('rollback', targets);
      setResults((prev) => [...prev, ...rollbackResults]);
      options.onFinished?.('rollback', rollbackResults, !failedTarget);
      if (failedTarget) {
        const failed = rollbackResults[rollbackResults.length - 1];
        setMessage(
          `Recovery rollback stopped on first failure at ${targetLabel(failedTarget)}: ${failed.error || failed.message || 'unknown error'}`,
          true
        );
        return;
      }
      setRollbackCandidates([]);
      setMessage('Recovery rollback completed.');
    } catch (requestError) {
      setMessage(
        `Failed to execute recovery rollback: ${
          requestError instanceof Error ? requestError.message : 'Unknown error'
        }`,
        true
      );
    } finally {
      setIsSubmitting(false);
      await refreshServerData(true);
    }
  };

  const sectionAccordionSx = {
    mb: 0.5,
    '&:before': {
      display: 'none',
    },
    '& .MuiAccordionSummary-root': {
      minHeight: 42,
      px: 1.5,
      py: 0,
    },
    '& .MuiAccordionSummary-content': {
      my: 0.75,
    },
    '& .MuiAccordionSummary-root.Mui-expanded': {
      minHeight: 42,
    },
    '& .MuiAccordionSummary-content.Mui-expanded': {
      my: 0.75,
    },
  };

  const targetTileSx = {
    m: 0,
    px: 1,
    py: 0.75,
    borderRadius: 1.25,
    bgcolor: 'action.hover',
    minHeight: 44,
    alignItems: 'center',
  };


  return { P, selectedHosts, setSelectedHosts, selectedLocalTargets, setSelectedLocalTargets, sourcePath, setSourcePath, gitRef, setGitRef, activeGitBranch, setActiveGitBranch, sourceMode, setSourceMode, detectedGit, setDetectedGit, pathExists, setPathExists, sourceReady, setSourceReady, gitBranches, setGitBranches, uploadId, setUploadId, uploadFilename, setUploadFilename, zipValidated, setZipValidated, sourceVersionInfo, setSourceVersionInfo, sourceDiffEntries, setSourceDiffEntries, originUrl, setOriginUrl, remoteUrlDraft, setRemoteUrlDraft, gitRepositories, setGitRepositories, needsGitReset, setNeedsGitReset, rollbackCandidates, setRollbackCandidates, rollbackOptions, setRollbackOptions, selectedRollbackId, setSelectedRollbackId, isLoadingRollbackOptions, setIsLoadingRollbackOptions, isSubmitting, setIsSubmitting, results, setResults, error, setError, info, setInfo, fileInputRef, embeddedFrontendVersion, frontendVersion, setFrontendVersion, allHosts, serverInfo, originOptions, allHostsSelected, allTargetsSelected, someTargetsSelected, toggleSelectAllTargets, orderedTargets, toggleLocalTarget, toggleHost, toggleSelectAllHosts, setMessage, targetLabel, extractHash, formatVersion, getVersionColor, formatRollbackLabel, resetSourceState, readSourceVersion, detectSource, reconfigureGitRemote, prepareGitSource, uploadZip, validateZip, applyZipToStorage, loadRollbackOptions, runTargetAction, executeWithFailFast, executeDeploy, executeRollbackSelected, executeRollbackRecovery, sectionAccordionSx, targetTileSx, noStableRollbackOption };
};

export type CodeDeploymentState = ReturnType<typeof useCodeDeployment>;
