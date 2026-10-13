/**
 * GitLab feature — typed calls to /server/gitlab.
 *
 * Thin on purpose: the backend already flattens GitLab's payloads into `cicd_status`,
 * `conclusion` and the same job shape the GitHub provider emits, so the page never has to know
 * GitLab's nine status values.
 */
import { buildPrimaryServerUrl } from '../../../frontend/src/utils/buildUrlUtils';

export interface GitLabInstance {
  id: string;
  name: string;
  base_url: string;
  project: string;
  ref: string;
  has_token: boolean;
}

export interface GitLabPipeline {
  gitlab_pipeline_id: number;
  branch: string;
  sha: string;
  status: string;
  conclusion: string | null;
  source: string;
  created_at: string;
  html_url: string;
}

export interface GitLabProject {
  id: number;
  name: string;
  path: string;
  path_with_namespace: string;
  default_branch: string;
  web_url: string;
  last_activity_at: string | null;
  open_issues_count: number | null;
  last_pipeline: GitLabPipeline | null;
}

export interface TreeEntry {
  name: string;
  path: string;
  type: 'tree' | 'blob';
  mode: string;
}

export interface RepoFile {
  path: string;
  ref: string | null;
  content: string | null;
  binary: boolean;
}

export interface GitLabRunner {
  id: number;
  name: string;
  status: string;
  busy: boolean;
  labels: string[];
}

export interface HealthResponse {
  success: boolean;
  configured: boolean;
  reachable?: boolean;
  version?: string;
  base_url?: string;
  error?: string;
  instances?: GitLabInstance[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(buildPrimaryServerUrl(`/server/gitlab${path}`), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((body as { error?: string }).error || `Request failed (${res.status})`);
  }
  return body as T;
}

/** What the Settings form sends. `id`/`token` are absent on create and blank on edit. */
export interface GitLabInstanceInput {
  id?: string;
  name?: string;
  base_url: string;
  token?: string;
}

export const gitlabApi = {
  health: () => request<HealthResponse>('/health'),
  instances: () => request<{ configured: boolean; instances: GitLabInstance[] }>('/instances'),

  saveInstance: (payload: GitLabInstanceInput) =>
    request<{ success: boolean; instance: GitLabInstance; version?: string }>('/instances', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteInstance: (id: string) =>
    request<{ success: boolean }>(`/instances/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  selectProject: (instanceId: string, project: string, ref?: string) =>
    request<{ success: boolean; instance: GitLabInstance }>(
      `/instances/${encodeURIComponent(instanceId)}/project`,
      { method: 'PUT', body: JSON.stringify({ project, ref }) },
    ),

  projects: () =>
    request<{ projects: GitLabProject[]; truncated: boolean }>('/projects'),

  branches: (project: string) =>
    request<{ branches: string[] }>(`/projects/${encodeURIComponent(project)}/branches`),

  tree: (project: string, ref: string, path: string) =>
    request<{ entries: TreeEntry[] }>(
      `/projects/${encodeURIComponent(project)}/tree?ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}`,
    ),

  readme: (project: string, ref: string) =>
    request<{ readme: RepoFile | null }>(
      `/projects/${encodeURIComponent(project)}/readme?ref=${encodeURIComponent(ref)}`,
    ),

  file: (project: string, ref: string, path: string) =>
    request<{ file: RepoFile | null }>(
      `/projects/${encodeURIComponent(project)}/file?ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}`,
    ),

  pipelines: (project: string, ref?: string) =>
    request<{ pipelines: GitLabPipeline[] }>(
      `/projects/${encodeURIComponent(project)}/pipelines${ref ? `?ref=${encodeURIComponent(ref)}` : ''}`,
    ),

  runners: () => request<{ runners: GitLabRunner[] }>('/runners'),
};