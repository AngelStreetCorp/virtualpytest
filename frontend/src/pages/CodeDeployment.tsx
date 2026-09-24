import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Select,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import UploadFileIcon from '@mui/icons-material/UploadFile';

import { useServerManager } from '../hooks/useServerManager';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { apiClient } from '../utils/apiClient';

type DeployAction = 'deploy' | 'rollback';
type LocalTargetKind = 'server' | 'frontend';

interface DeployResult {
  target: string;
  action: DeployAction;
  success: boolean;
  message?: string;
  error?: string;
  version_before?: string;
  version_after?: string;
}

interface ExecutionTarget {
  kind: 'server' | 'frontend' | 'host';
  id: string;
}

interface RollbackOption {
  backup_id: string;
  label: string;
}

interface SourceVersionInfo {
  current: string | null;
  before: string | null;
  after: string | null;
  commit: string | null;
}

interface SourceDiffEntry {
  status: string;
  path: string;
  added: string;
  deleted: string;
}

interface GitRepositoryOption {
  name: string;
  url: string;
}

const gitRepositoryName = (url: string | null): string => {
  if (!url) return 'Current origin';
  const path = url.replace(/\.git$/, '').split(/[/:]/).filter(Boolean);
  return path[path.length - 1] || 'Current origin';
};

const CodeDeployment: React.FC = () => {
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
    void detectSource();
  }, []);

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
      if (!data.path_exists) {
        setMessage(
          `Storage path is not reachable from server: ${data.storage_path}. Check NFS mount or path.`,
          true
        );
        return;
      }
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

  return (
    <Box>
      <Typography variant="h4" component="h1" mb={0.75}>
        Code Deployment
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}
      {info && (
        <Alert severity="info" sx={{ mb: 1 }}>
          {info}
        </Alert>
      )}

      <Accordion defaultExpanded sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', gap: 1 }}>
            <Typography sx={{ fontWeight: 600 }}>1. Source</Typography>
            {pathExists ? (
              <Box sx={{ ml: 'auto' }} onClick={(event) => event.stopPropagation()}>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={sourceMode}
                  onChange={(_, nextMode: 'git' | 'zip' | null) => nextMode && setSourceMode(nextMode)}
                  aria-label="Deployment source type"
                >
                  {detectedGit ? <ToggleButton value="git">Git</ToggleButton> : null}
                  <ToggleButton value="zip">ZIP</ToggleButton>
                </ToggleButtonGroup>
              </Box>
            ) : null}
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.25, pb: 0.75, px: 1.5 }}>
          {!pathExists && !isSubmitting ? (
            <Typography variant="body2" color="error.main" sx={{ mb: 0.75 }}>
              Source storage is not reachable from server.
            </Typography>
          ) : null}

          {pathExists && detectedGit && sourceMode === 'git' ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 0.5 }}>
              <Typography variant="caption" color="success.main" sx={{ whiteSpace: 'nowrap' }}>
                {`Current: ${gitRepositoryName(originUrl)} · ${activeGitBranch || 'unknown'} · ${sourceVersionInfo.current || 'unknown'}`}
              </Typography>
              <TextField
                select
                label="Origin"
                size="small"
                value={remoteUrlDraft}
                onChange={(event) => setRemoteUrlDraft(event.target.value)}
                sx={{ minWidth: 190 }}
                disabled={isSubmitting || originOptions.length === 0}
                SelectProps={{
                  renderValue: (value) => {
                    const repository = originOptions.find((entry) => entry.url === value);
                    return repository
                      ? `${repository.url === originUrl ? '✓ ' : ''}${repository.name}`
                      : 'Select origin';
                  },
                }}
              >
                <MenuItem value="" disabled>
                  Select an approved repository
                </MenuItem>
                {originOptions.map((repository) => (
                  <MenuItem key={repository.url} value={repository.url}>
                    {repository.url === originUrl ? '✓ ' : ''}{repository.name}
                  </MenuItem>
                ))}
              </TextField>
              <Button
                variant="outlined"
                size="small"
                onClick={reconfigureGitRemote}
                disabled={isSubmitting || !remoteUrlDraft.trim() || remoteUrlDraft.trim() === originUrl}
              >
                {isSubmitting ? <CircularProgress size={16} color="inherit" /> : 'Reconfigure'}
              </Button>
                <TextField
                  select
                  label="Branch"
                  size="small"
                  value={gitRef}
                  onChange={(event) => setGitRef(event.target.value)}
                  sx={{ minWidth: 150 }}
                >
                  {(gitBranches.length > 0 ? gitBranches : [gitRef]).map((branch) => (
                    <MenuItem key={branch} value={branch}>
                      {branch}
                    </MenuItem>
                  ))}
                </TextField>
                <Button variant="contained" size="small" onClick={() => prepareGitSource()} disabled={isSubmitting || !gitRef.trim()}>
                  {isSubmitting ? <CircularProgress size={16} color="inherit" /> : 'Fetch & pull'}
                </Button>
                {activeGitBranch && gitRef !== activeGitBranch ? (
                  <Typography variant="caption" color="error.main" sx={{ whiteSpace: 'nowrap' }}>
                    {`Target: ${gitRef}`}
                  </Typography>
                ) : null}
              {needsGitReset ? (
                <Button color="warning" size="small" onClick={() => prepareGitSource(true)} disabled={isSubmitting || !gitRef.trim()}>
                  Force reset
                </Button>
              ) : null}
            </Box>
          ) : null}

          {pathExists && sourceMode === 'zip' ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                style={{ display: 'none' }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) uploadZip(file);
                }}
              />
              <Button
                variant="outlined"
                size="small"
                startIcon={<UploadFileIcon />}
                onClick={() => fileInputRef.current?.click()}
                disabled={isSubmitting}
              >
                Upload ZIP
              </Button>
              {uploadFilename ? <Typography variant="caption">{uploadFilename}</Typography> : null}
              <Button variant="outlined" size="small" onClick={validateZip} disabled={isSubmitting || !uploadId}>
                Validate ZIP
              </Button>
              <Button
                variant="contained"
                size="small"
                onClick={applyZipToStorage}
                disabled={isSubmitting || !zipValidated}
              >
                Apply to Storage
              </Button>
            </Box>
          ) : null}

          {sourceDiffEntries.length > 0 ? (
            <Accordion disableGutters elevation={0} sx={{ mt: 0.75, '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 30, px: 0 }}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  Changed files ({sourceDiffEntries.length})
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ pt: 0, px: 0 }}>
                <Box sx={{ display: 'grid', gap: 0.25 }}>
                  {sourceDiffEntries.map((entry) => (
                    <Typography
                      key={`${entry.status}-${entry.path}`}
                      variant="caption"
                      sx={{ fontFamily: 'monospace', display: 'block' }}
                    >
                      {entry.status} {entry.path} +{entry.added} -{entry.deleted}
                    </Typography>
                  ))}
                </Box>
              </AccordionDetails>
            </Accordion>
          ) : null}
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography sx={{ fontWeight: 600 }}>2. Targets</Typography>
            <Typography variant="caption" color="text.secondary">|</Typography>
            <Typography
              variant="caption"
              color={allTargetsSelected ? 'text.disabled' : 'primary.main'}
              sx={{ cursor: allTargetsSelected ? 'default' : 'pointer' }}
              onClick={e => { e.stopPropagation(); if (!allTargetsSelected) toggleSelectAllTargets(true); }}
            >
              Select All
            </Typography>
            <Typography variant="caption" color="text.secondary">/</Typography>
            <Typography
              variant="caption"
              color={someTargetsSelected ? 'primary.main' : 'text.disabled'}
              sx={{ cursor: someTargetsSelected ? 'pointer' : 'default' }}
              onClick={e => { e.stopPropagation(); if (someTargetsSelected) toggleSelectAllTargets(false); }}
            >
              Unselect All
            </Typography>
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.125, pb: 0.75, px: 1.5 }}>
          <Box sx={{ display: 'grid', gap: 0.5 }}>
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: {
                  xs: '1fr',
                  md: 'repeat(2, minmax(0, 1fr))',
                },
                gap: 0.75,
              }}
            >
              <FormControlLabel
                sx={targetTileSx}
                control={
                  <Checkbox
                    size="small"
                    checked={selectedLocalTargets.includes('server')}
                    onChange={() => toggleLocalTarget('server')}
                    sx={{ p: 0.375, pt: 0.5 }}
                  />
                }
                label={
                  <Box sx={{ py: 0.25 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.15 }}>
                      Server
                    </Typography>
                    {serverInfo?.deployed_version ? (
                      <Typography variant="caption" color={getVersionColor(serverInfo.deployed_version)}>
                        {formatVersion(serverInfo.deployed_version)}
                      </Typography>
                    ) : null}
                  </Box>
                }
              />
              <FormControlLabel
                sx={targetTileSx}
                control={
                  <Checkbox
                    size="small"
                    checked={selectedLocalTargets.includes('frontend')}
                    onChange={() => toggleLocalTarget('frontend')}
                    sx={{ p: 0.375, pt: 0.5 }}
                  />
                }
                label={
                  <Box sx={{ py: 0.25 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.15 }}>
                      Frontend
                    </Typography>
                    {frontendVersion && frontendVersion !== 'unknown' ? (
                      <Typography variant="caption" color={getVersionColor(frontendVersion)}>
                        {formatVersion(frontendVersion)}
                      </Typography>
                    ) : null}
                  </Box>
                }
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.125, mb: 0 }}>
              <Checkbox
                size="small"
                checked={allHostsSelected}
                indeterminate={selectedHosts.length > 0 && !allHostsSelected}
                onChange={(_, checked) => toggleSelectAllHosts(checked)}
                sx={{ p: 0.25 }}
              />
              <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.2 }}>
                Hosts ({allHosts.length})
              </Typography>
            </Box>
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: {
                  xs: '1fr',
                  md: 'repeat(2, minmax(0, 1fr))',
                  lg: 'repeat(3, minmax(0, 1fr))',
                },
                gap: 0.75,
              }}
            >
              {allHosts.map((host) => (
                <FormControlLabel
                  key={host.host_name}
                  sx={targetTileSx}
                  control={
                    <Checkbox
                      size="small"
                      checked={selectedHosts.includes(host.host_name)}
                      onChange={() => toggleHost(host.host_name)}
                      sx={{ p: 0.375 }}
                    />
                  }
                  label={
                    <Box sx={{ py: 0.25 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.15 }}>
                        {host.host_name}
                      </Typography>
                      {host.deployed_version ? (
                        <Typography variant="caption" color={getVersionColor(host.deployed_version)}>
                          {formatVersion(host.deployed_version)}
                        </Typography>
                      ) : null}
                    </Box>
                  }
                />
              ))}
            </Box>
          </Box>
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography sx={{ fontWeight: 600 }}>3. Execute</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.125, pb: 0.75, px: 1.5 }}>
          <Box display="flex" alignItems="center" gap={0.5} mb={0.5} flexWrap="wrap">
            <Button
              variant="contained"
              size="small"
              onClick={executeDeploy}
              disabled={isSubmitting || orderedTargets.length === 0 || !sourceReady}
            >
              Deploy
            </Button>
            {isSubmitting ? <CircularProgress size={16} /> : null}
            <Typography variant="caption" color="text.secondary">
              Selected targets: {orderedTargets.length}
            </Typography>
          </Box>

          {results.length > 0 ? (
            <Box display="flex" flexDirection="column" gap={0.375}>
              {results.map((result, index) => (
                <Alert
                  key={`${result.action}-${result.target}-${index}`}
                  severity={result.success ? 'success' : 'error'}
                  variant="outlined"
                  sx={{ py: 0 }}
                >
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {result.target} - {result.action.toUpperCase()}
                  </Typography>
                  <Typography variant="caption" display="block">
                    {result.message || result.error || 'No message'}
                  </Typography>
                  <Typography variant="caption" display="block">
                    Version: {result.version_before || 'unknown'} -&gt; {result.version_after || 'unknown'}
                  </Typography>
                </Alert>
              ))}
            </Box>
          ) : null}
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded={false} sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography sx={{ fontWeight: 600 }}>4. Rollback</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.125, pb: 0.75, px: 1.5 }}>
          <Box display="flex" alignItems="center" gap={0.5} mb={0.5} flexWrap="wrap">
            <Button
              variant="outlined"
              color="warning"
              size="small"
              onClick={executeRollbackSelected}
              disabled={
                isSubmitting ||
                orderedTargets.length === 0 ||
                selectedRollbackId === noStableRollbackOption.backup_id
              }
            >
              Rollback
            </Button>
            <Select
              size="small"
              value={selectedRollbackId}
              onChange={(event) => setSelectedRollbackId(String(event.target.value))}
              disabled={isSubmitting || orderedTargets.length === 0 || isLoadingRollbackOptions}
              sx={{ minWidth: 260 }}
            >
              {rollbackOptions.map((option) => (
                <MenuItem key={option.backup_id} value={option.backup_id}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
            {isLoadingRollbackOptions ? <CircularProgress size={16} /> : null}
          </Box>

          {rollbackCandidates.length > 0 ? (
            <Box mb={0.75}>
              <Button
                variant="text"
                color="error"
                size="small"
                onClick={executeRollbackRecovery}
                disabled={isSubmitting}
              >
                Rollback completed targets
              </Button>
            </Box>
          ) : null}
        </AccordionDetails>
      </Accordion>
    </Box>
  );
};

export default CodeDeployment;
