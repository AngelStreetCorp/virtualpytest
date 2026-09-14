/**
 * Run CI/CD (TASK-06 W8) — Test → Execute › Run CI/CD.
 *
 * Launches a GitHub workflow_dispatch for one project: branch, suite (white / grey /
 * all) and runner target (the self-hosted LAN runner or GitHub-hosted capacity). The
 * runner rows come straight from /server/cicd/runners, so a runner that is OFFLINE is
 * shown as such with a restart button, and a suite the selected runner may not run
 * disables Run with the reason spelled out.
 *
 * Layout follows the mockup in docs/tasks/TASK-06-cicd-feature.md: one compact form row,
 * the runner choice, then Live and Recent dispatches.
 */
import { OpenInNew, PlayArrow, RestartAlt, Settings as SettingsIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Select,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { StyledDialog } from '../../../frontend/src/components/common/StyledDialog';
import { api } from '../../../frontend/src/utils/apiClient';
import { buildPrimaryServerUrl } from '../../../frontend/src/utils/buildUrlUtils';

type Suite = 'all' | 'white' | 'grey';
const SUITES: Suite[] = ['all', 'white', 'grey'];

interface Project {
  project: string;
  repo: string;
  workflow_file: string;
  default_branch: string;
  report_prefix: string;
  suites: Record<string, string[]>;
  runner_labels: string[];
  cloud_suites: string[];
  enabled: boolean;
}

interface Runner {
  name: string;
  status: 'online' | 'offline';
  busy: boolean;
  labels: string[];
  target: 'self-hosted' | 'github-hosted';
  project: string;
  repo: string;
  can_run: Suite[];
}

interface LiveRun {
  github_run_id: number;
  run_number: number;
  project: string;
  branch?: string | null;
  status: string;
  event?: string | null;
  jobs_total: number;
  jobs_done: number;
  runner?: string | null;
  created_at?: string | null;
  html_url?: string | null;
}

interface Dispatch {
  id: number;
  project: string;
  branch: string;
  suite: string;
  runner_target: string;
  requested_by?: string | null;
  requested_at: string;
  github_run_id?: number | null;
  status: string;
}

const elapsed = (iso?: string | null): string => {
  if (!iso) return '';
  const secs = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000));
  return `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`;
};

const shortTime = (iso?: string | null): string =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

export default function RunCICDPage() {
  // Global CSS paints a grey row hover; every table here forces it transparent.
  const rowSx = { '&:hover': { backgroundColor: 'transparent !important' } };

  const [projects, setProjects] = useState<Project[]>([]);
  const [runners, setRunners] = useState<Runner[]>([]);
  const [branches, setBranches] = useState<string[]>([]);
  const [live, setLive] = useState<LiveRun[]>([]);
  const [dispatches, setDispatches] = useState<Dispatch[]>([]);

  const [project, setProject] = useState<string>('');
  const [branch, setBranch] = useState<string>('');
  const [suite, setSuite] = useState<Suite>('all');
  const [runnerName, setRunnerName] = useState<string>('');

  // `loading` is an explicit flag: an empty runner list is a valid loaded state.
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [notice, setNotice] = useState<{ kind: 'success' | 'error' | 'info'; text: string } | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);

  const selectedProject = useMemo(
    () => projects.find((p) => p.project === project) ?? null,
    [projects, project],
  );
  const projectRunners = useMemo(
    () => runners.filter((r) => r.project === project),
    [runners, project],
  );
  const selectedRunner = useMemo(
    () => projectRunners.find((r) => r.name === runnerName) ?? null,
    [projectRunners, runnerName],
  );

  // Why Run is disabled, or null when it may be pressed.
  const blockedReason = useMemo<string | null>(() => {
    if (!selectedProject) return 'pick a project';
    if (!selectedRunner) return 'pick a runner';
    if (!branch.trim()) return 'pick a branch';
    if (selectedRunner.target === 'self-hosted' && selectedRunner.status !== 'online')
      return `${selectedRunner.name} is offline`;
    if (!selectedRunner.can_run.includes(suite)) {
      const allowed = selectedRunner.can_run.join(', ') || 'nothing';
      return selectedRunner.target === 'github-hosted'
        ? `${suite} needs the LAN runner (cloud may run: ${allowed})`
        : `${suite} is not allowed on ${selectedRunner.name} (may run: ${allowed})`;
    }
    return null;
  }, [selectedProject, selectedRunner, branch, suite]);

  const loadProjects = useCallback(async () => {
    try {
      const data = await api.get<any>(buildPrimaryServerUrl('/server/cicd/projects'));
      if (data.configured === false) {
        setConfigError(data.error ?? 'the cicd schema is not reachable');
        return;
      }
      setConfigError(null);
      const rows: Project[] = data.projects ?? [];
      setProjects(rows);
      setProject((prev) => prev || rows.find((p) => p.enabled)?.project || rows[0]?.project || '');
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : 'failed to load projects');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRunners = useCallback(async () => {
    if (!project) return;
    try {
      const data = await api.get<any>(buildPrimaryServerUrl(`/server/cicd/runners?project=${encodeURIComponent(project)}`));
      const rows: Runner[] = data.runners ?? [];
      setRunners(rows);
      // Prefer an idle self-hosted runner, else whatever is first for the project.
      setRunnerName((prev) => {
        if (prev && rows.some((r) => r.name === prev && r.project === project)) return prev;
        const mine = rows.filter((r) => r.project === project);
        return (
          mine.find((r) => r.target === 'self-hosted' && r.status === 'online' && !r.busy)?.name ??
          mine[0]?.name ?? ''
        );
      });
      if (data.errors && Object.keys(data.errors).length > 0) {
        setNotice({ kind: 'info', text: `GitHub runner list: ${Object.values(data.errors).join('; ')}` });
      }
    } catch {
      setRunners([]);
    }
  }, [project]);

  const loadBranches = useCallback(async () => {
    if (!project) return;
    try {
      const data = await api.get<any>(buildPrimaryServerUrl(`/server/cicd/branches?project=${encodeURIComponent(project)}`));
      const names: string[] = data.branches ?? [];
      setBranches(names);
      setBranch((prev) => {
        if (prev && names.includes(prev)) return prev;
        const fallback = projects.find((p) => p.project === project)?.default_branch ?? 'main';
        return names.includes(fallback) ? fallback : names[0] ?? fallback;
      });
    } catch {
      const fallback = projects.find((p) => p.project === project)?.default_branch ?? 'main';
      setBranches([fallback]);
      setBranch((prev) => prev || fallback);
    }
  }, [project, projects]);

  const loadLive = useCallback(async () => {
    if (!project) return;
    try {
      const data = await api.get<any>(buildPrimaryServerUrl(`/server/cicd/live?project=${encodeURIComponent(project)}`));
      if (data.configured === false) return;
      setLive(data.running ?? []);
      setDispatches(data.dispatches ?? []);
    } catch {
      /* transient — the next tick retries */
    }
  }, [project]);

  useEffect(() => { loadProjects(); }, [loadProjects]);
  useEffect(() => { loadRunners(); loadBranches(); loadLive(); }, [loadRunners, loadBranches, loadLive]);

  // Poll faster while something is running, so a launch is visibly picked up.
  useEffect(() => {
    const delay = live.length > 0 ? 10_000 : 30_000;
    const timer = setInterval(() => { loadLive(); loadRunners(); }, delay);
    return () => clearInterval(timer);
  }, [live.length, loadLive, loadRunners]);

  const handleRun = async () => {
    if (!selectedProject || !selectedRunner || blockedReason) return;
    setLaunching(true);
    setNotice(null);
    try {
      const data = await api.post<any>(buildPrimaryServerUrl('/server/cicd/dispatch'), {
        project: selectedProject.project,
        branch,
        suite,
        runner: selectedRunner.target,
      });
      if (data.success) {
        const num = data.run?.run_number;
        setNotice({
          kind: 'success',
          text: num
            ? `Launched run #${num} (${suite} on ${selectedRunner.target})`
            : `Dispatched ${suite} on ${selectedRunner.target} — waiting for GitHub to register the run`,
        });
        loadLive();
      } else {
        setNotice({ kind: 'error', text: data.error ?? 'dispatch failed' });
      }
    } catch (e) {
      setNotice({ kind: 'error', text: e instanceof Error ? e.message : 'dispatch failed' });
    } finally {
      setLaunching(false);
    }
  };

  const handleRestart = async (name: string) => {
    setNotice({ kind: 'info', text: `Restarting ${name}…` });
    try {
      const res = await fetch(buildPrimaryServerUrl(`/server/cicd/runners/${name}/restart`), { method: 'POST' });
      const data = await res.json();
      setNotice({ kind: data.success ? 'success' : 'error', text: data.success ? `${name} restarted` : (data.error ?? 'restart failed') });
    } catch {
      setNotice({ kind: 'error', text: 'restart request failed' });
    } finally {
      loadRunners();
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (configError) {
    return <Alert severity="warning">CI/CD not configured: {configError}</Alert>;
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Typography variant="h6">Run CI/CD</Typography>

      {notice && (
        <Alert severity={notice.kind} onClose={() => setNotice(null)}>
          {notice.text}
        </Alert>
      )}

      {/* ── form ─────────────────────────────────────────────────────────── */}
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <FormControl size="small" sx={{ minWidth: 170 }}>
            <Select value={project} onChange={(e) => setProject(e.target.value)} displayEmpty>
              {projects.map((p) => (
                <MenuItem key={p.project} value={p.project} disabled={!p.enabled}>
                  {p.project}{!p.enabled ? ' (disabled)' : ''}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 170 }}>
            <Select value={branch || ''} onChange={(e) => setBranch(e.target.value)} displayEmpty>
              {branches.map((b) => (
                <MenuItem key={b} value={b}>{b}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <RadioGroup row value={suite} onChange={(e) => setSuite(e.target.value as Suite)}>
            {SUITES.map((s) => (
              <FormControlLabel
                key={s}
                value={s}
                control={<Radio size="small" />}
                label={<Typography variant="body2">{s}</Typography>}
              />
            ))}
          </RadioGroup>

          <Box sx={{ flex: 1 }} />

          <Tooltip title={blockedReason ?? `Dispatch ${selectedProject?.workflow_file ?? ''} on ${branch}`}>
            <span>
              <Button
                variant="contained"
                size="small"
                startIcon={<PlayArrow />}
                disabled={!!blockedReason || launching}
                onClick={handleRun}
              >
                {launching ? 'Launching…' : 'Run'}
              </Button>
            </span>
          </Tooltip>
          <Button variant="outlined" size="small" startIcon={<SettingsIcon />} onClick={() => setEditorOpen(true)}>
            Edit projects
          </Button>
        </Box>

        {/* runner choice — one row per runner, plus the synthetic cloud row */}
        <RadioGroup value={runnerName} onChange={(e) => setRunnerName(e.target.value)}>
          {projectRunners.length === 0 && (
            <Typography variant="caption" color="text.secondary">
              No runner reported for {project}. Check GITHUB_TOKEN on the server.
            </Typography>
          )}
          {projectRunners.map((r) => {
            const offline = r.target === 'self-hosted' && r.status !== 'online';
            const state = r.target === 'github-hosted'
              ? 'cloud · always available'
              : `${r.status === 'online' ? (r.busy ? 'ALIVE · busy' : 'ALIVE · idle') : 'OFFLINE'}`;
            return (
              <Box key={r.name} sx={{ display: 'flex', alignItems: 'center', gap: 1, opacity: offline ? 0.6 : 1 }}>
                <FormControlLabel
                  value={r.name}
                  control={<Radio size="small" />}
                  label={
                    <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                      {r.name}
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        {r.target} · {r.labels.join(', ')} · {state}
                      </Typography>
                    </Typography>
                  }
                />
                <Chip size="small" variant="outlined" label={`can run: ${r.can_run.join(', ') || '—'}`} />
                {offline && (
                  <Tooltip title={`Restart ${r.name}`}>
                    <IconButton size="small" onClick={() => handleRestart(r.name)}>
                      <RestartAlt fontSize="small" />
                    </IconButton>
                  </Tooltip>
                )}
              </Box>
            );
          })}
        </RadioGroup>
      </Paper>

      {/* ── live ─────────────────────────────────────────────────────────── */}
      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>Live</Typography>
        {live.length === 0 ? (
          <Typography variant="caption" color="text.secondary">Nothing running.</Typography>
        ) : (
          <Table size="small">
            <TableBody>
              {live.map((r) => (
                <TableRow key={r.github_run_id} sx={rowSx}>
                  <TableCell sx={{ width: 70 }}>#{r.run_number}</TableCell>
                  <TableCell sx={{ width: 130 }}>{r.branch}</TableCell>
                  <TableCell sx={{ width: 220 }}>
                    <Typography variant="caption" color="text.secondary">
                      {r.event === 'workflow_dispatch' ? 'dispatch' : r.event} · {r.runner ?? 'assigning…'}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ width: 110 }}>
                    <Chip
                      size="small"
                      color={r.status === 'queued' ? 'default' : 'warning'}
                      label={r.status === 'queued' ? 'QUEUED' : 'RUNNING'}
                    />
                  </TableCell>
                  <TableCell sx={{ width: 90 }}>{r.jobs_done}/{r.jobs_total} jobs</TableCell>
                  <TableCell sx={{ width: 70 }}>{elapsed(r.created_at)}</TableCell>
                  <TableCell align="right">
                    {r.html_url && (
                      <Tooltip title="Open on GitHub">
                        <IconButton size="small" onClick={() => window.open(r.html_url!, '_blank')}>
                          <OpenInNew fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      {/* ── recent dispatches ────────────────────────────────────────────── */}
      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>Recent dispatches</Typography>
        {dispatches.length === 0 ? (
          <Typography variant="caption" color="text.secondary">
            Nothing launched from this page yet.
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow sx={rowSx}>
                <TableCell sx={{ width: 70 }}>Time</TableCell>
                <TableCell sx={{ width: 120 }}>Project</TableCell>
                <TableCell sx={{ width: 130 }}>Branch</TableCell>
                <TableCell sx={{ width: 70 }}>Suite</TableCell>
                <TableCell sx={{ width: 130 }}>Runner</TableCell>
                <TableCell sx={{ width: 160 }}>By</TableCell>
                <TableCell sx={{ width: 90 }}>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {dispatches.map((d) => (
                <TableRow key={d.id} sx={rowSx}>
                  <TableCell>{shortTime(d.requested_at)}</TableCell>
                  <TableCell>{d.project}</TableCell>
                  <TableCell>{d.branch}</TableCell>
                  <TableCell>{d.suite}</TableCell>
                  <TableCell>{d.runner_target}</TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary" noWrap>
                      {d.requested_by ?? '—'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      variant="outlined"
                      color={d.status === 'error' ? 'error' : d.status === 'running' ? 'warning' : 'default'}
                      label={d.status}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      <ProjectEditor
        open={editorOpen}
        projects={projects}
        onClose={() => setEditorOpen(false)}
        onSaved={(text, ok) => {
          setNotice({ kind: ok ? 'success' : 'error', text });
          loadProjects();
        }}
      />
    </Box>
  );
}

/**
 * Compact editor for ci_projects. PUT /server/cicd/projects/<name> is admin-only, so a
 * non-admin simply gets the server's 403 surfaced as the save message.
 */
function ProjectEditor({
  open,
  projects,
  onClose,
  onSaved,
}: {
  open: boolean;
  projects: Project[];
  onClose: () => void;
  onSaved: (text: string, ok: boolean) => void;
}) {
  const [name, setName] = useState('');
  const [form, setForm] = useState<Partial<Project>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const first = projects[0];
    setName(first?.project ?? '');
    setForm(first ?? {});
  }, [open, projects]);

  const pick = (project: string) => {
    setName(project);
    setForm(projects.find((p) => p.project === project) ?? {});
  };

  const save = async () => {
    setSaving(true);
    try {
      const data = await api.put<any>(buildPrimaryServerUrl(`/server/cicd/projects/${encodeURIComponent(name)}`), {
        repo: form.repo,
        workflow_file: form.workflow_file,
        default_branch: form.default_branch,
        report_prefix: form.report_prefix,
        cloud_suites: form.cloud_suites,
        enabled: form.enabled,
      });
      onSaved(data.success ? `${name} saved` : (data.error ?? 'save failed'), !!data.success);
      if (data.success) onClose();
    } catch (e) {
      onSaved(e instanceof Error ? e.message : 'save failed (admin role required)', false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ pb: 1 }}>Edit projects</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, pt: 1 }}>
        <FormControl size="small">
          <Select value={name} onChange={(e) => pick(e.target.value)}>
            {projects.map((p) => (
              <MenuItem key={p.project} value={p.project}>{p.project}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          size="small" label="Repo" value={form.repo ?? ''}
          onChange={(e) => setForm({ ...form, repo: e.target.value })}
        />
        <TextField
          size="small" label="Workflow file" value={form.workflow_file ?? ''}
          onChange={(e) => setForm({ ...form, workflow_file: e.target.value })}
        />
        <TextField
          size="small" label="Default branch" value={form.default_branch ?? ''}
          onChange={(e) => setForm({ ...form, default_branch: e.target.value })}
        />
        <TextField
          size="small" label="Report prefix" value={form.report_prefix ?? ''}
          helperText="Run directory prefix on the reports server — empty for virtualpytest, 'sample-app-' for sample-app"
          onChange={(e) => setForm({ ...form, report_prefix: e.target.value })}
        />
        <TextField
          size="small" label="Cloud suites" value={(form.cloud_suites ?? []).join(', ')}
          helperText="Suites allowed on GitHub-hosted runners, comma separated (white, grey)"
          onChange={(e) =>
            setForm({
              ...form,
              cloud_suites: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
            })
          }
        />
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={form.enabled ?? true}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
          }
          label={<Typography variant="body2">Enabled</Typography>}
        />
      </DialogContent>
      <DialogActions>
        <Button size="small" onClick={onClose}>Cancel</Button>
        <Button size="small" variant="contained" onClick={save} disabled={saving || !name}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
}
