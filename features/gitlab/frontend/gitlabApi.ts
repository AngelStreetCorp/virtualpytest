/**
 * GitLab feature — typed calls to /server/gitlab.
 *
 * Thin on purpose: the backend already flattens GitLab's payloads into `cicd_status`,
 * `conclusion` and the same job shape the GitHub provider emits, so the page never has to know
 * GitLab's nine status values.
 *
 * These calls go to the SELECTED server, not the primary one. A GitLab instance is configured per
 * server — each VirtualPyTest server stores its own instances in its own `gitlab_instances.json`,
 * and it is normal for only some of them to have one. Using `buildPrimaryServerUrl` here pinned the
 * whole page to the main server: with another server selected the picker said `vpt-pi4` while the
 * page showed the main server's GitLab, including projects and README from a server the operator
 * was not looking at. The navbar shortcut already used the per-server builder and correctly hid
 * itself on a server with no instance, so the two disagreed on the same screen.
 */
import { buildServerUrl } from '../../../frontend/src/utils/buildUrlUtils';

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

export interface CommitSummary {
  short_id: string;
  title: string | null;
  author_name: string | null;
  committed_date: string | null;
}

export interface Branch {
  name: string;
  commit: CommitSummary | null;
}

export interface ProjectOverview {
  description: string | null;
  visibility: string | null;
  http_url: string | null;
  ssh_url: string | null;
  default_branch: string | null;
  last_activity_at: string | null;
  web_url: string | null;
  commit_count: number | null;
  tag_count: number;
  last_pipeline: GitLabPipeline | null;
}

export interface TreeEntry {
  name: string;
  path: string;
  type: 'tree' | 'blob';
  mode: string;
  last_commit?: CommitSummary | null;
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
  const res = await fetch(buildServerUrl(`/server/gitlab${path}`), {
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

  // The project travels as a QUERY argument, never as a path segment. A GitLab project path is
  // `group/project`, and encodeURIComponent turns that into `%2F` inside one segment — which
  // Flask's default string converter refuses to match. The request then matched no route, fell
  // through to the auto_proxy catch-all and came back 400 "host_name required", a parameter
  // this feature has never used. Every namespaced project — i.e. all of them — failed.
  branches: (project: string) =>
    request<{ branches: Branch[] }>(`/project/branches?project=${encodeURIComponent(project)}`),

  overview: (project: string, ref: string) =>
    request<{ overview: ProjectOverview }>(
      `/project/overview?project=${encodeURIComponent(project)}&ref=${encodeURIComponent(ref)}`,
    ),

  tree: (project: string, ref: string, path: string) =>
    request<{ entries: TreeEntry[] }>(
      `/project/tree?project=${encodeURIComponent(project)}&ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}&with_commits=1`,
    ),

  readme: (project: string, ref: string) =>
    request<{ readme: RepoFile | null }>(
      `/project/readme?project=${encodeURIComponent(project)}&ref=${encodeURIComponent(ref)}`,
    ),

  file: (project: string, ref: string, path: string) =>
    request<{ file: RepoFile | null }>(
      `/project/file?project=${encodeURIComponent(project)}&ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}`,
    ),

  pipelines: (project: string, ref?: string) =>
    request<{ pipelines: GitLabPipeline[] }>(
      `/project/pipelines?project=${encodeURIComponent(project)}${ref ? `&ref=${encodeURIComponent(ref)}` : ''}`,
    ),

  runners: () => request<{ runners: GitLabRunner[] }>('/runners'),
};