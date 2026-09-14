import {
  CheckCircle,
  Cancel,
  RadioButtonUnchecked,
  OpenInNew,
  Refresh,
  ExpandMore,
  ExpandLess,
  FiberManualRecord,
  HourglassEmpty,
  RestartAlt,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Chip,
  CircularProgress,
  Alert,
  Button,
  IconButton,
  Tooltip,
  Paper,
  Collapse,
  Select,
  MenuItem,
  FormControl,
} from '@mui/material';
import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';

import { buildPrimaryServerUrl } from '../../../frontend/src/utils/buildUrlUtils';
import { getCached, setCached } from '../../../frontend/src/utils/pageCache';

interface RunnerStatus {
  name: string;
  status: 'online' | 'offline';
  busy: boolean;
  project?: string;
  repo?: string;
  labels?: string[];
}

// Runner card model: one per project, derived from that project's latest stored run
// (meta.json `runner`) and joined with the GitHub runner list for liveness.
interface ProjectRunner {
  project: string;
  name: string;
  status: 'online' | 'offline' | 'unknown';
  busy: boolean;
  lastRun?: string;
  lastDate?: string;
  /** What this runner is executing right now, when it is busy (from /cicd/live). */
  current?: { job: string; workflow: string; runNumber?: number; branch?: string; startedAt?: string };
}

/** One in-flight GitHub run as /cicd/live reports it. */
interface LiveRun {
  project: string;
  workflow?: string;
  run_number?: number;
  branch?: string;
  /** GitHub run status: 'queued' | 'in_progress' — queued with no online runner = stuck. */
  status?: string;
  jobs?: { name?: string; status?: string; runner_name?: string | null; started_at?: string | null }[];
}

type RangeKey = '24h' | '7d' | '30d' | 'all';
const RANGE_OPTIONS: { key: RangeKey; label: string; ms: number | null }[] = [
  { key: '24h', label: 'Last 24 hours', ms: 24 * 3600_000 },
  { key: '7d', label: 'Last 7 days', ms: 7 * 24 * 3600_000 },
  { key: '30d', label: 'Last 30 days', ms: 30 * 24 * 3600_000 },
  { key: 'all', label: 'All stored', ms: null },
];

// meta.json dates look like "2026-09-03 07:42 UTC"; legacy runs carry "-".
function parseRunDate(date: string): number | null {
  if (!date || date === '-') return null;
  const t = Date.parse(date.replace(' UTC', 'Z').replace(' ', 'T'));
  return Number.isNaN(t) ? null : t;
}

/**
 * Job sub-path inside a run's report directory, taken from the absolute URL the
 * workflow stored. Older rows point at the retired /server/ci-reports/ path, so only
 * the trailing segment is kept and reportUrl() rebuilds the live one.
 */
function reportSubPath(reportUrl: string | null | undefined, run: string): string | null {
  if (!reportUrl) return null;
  const segments = reportUrl.split('?')[0].split('/').filter(Boolean);
  const last = segments[segments.length - 1];
  if (!last || last === run) return null;   // run-level url, not a job report
  return last;
}

/** ci_runs.started_at is an ISO timestamp; show it compactly in local time. */
function formatRunDate(date: string): string {
  const t = parseRunDate(date);
  if (t == null) return date || '-';
  return new Date(t).toLocaleString([], {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

interface JobStatus {
  status: string;
  report?: string | null;
  category?: string | null;
}

interface RunMeta {
  run: string;
  repo?: string;
  branch: string;
  sha: string;
  date: string;
  runner?: string | null;
  /** push | pull_request | dispatch | schedule — NULL on rows written before TASK-06 W3. */
  trigger?: string | null;
  /** white | grey | all — what the run was asked to execute. */
  suite?: string | null;
  overall: 'passed' | 'failed' | 'partial' | 'unknown';
  jobs: Record<string, JobStatus>;
  /** max(job.finished_at) from the view — moves on every job upsert; feeds the delta cursor. */
  finishedAt?: string | null;
}

/** One ci_run_summary row as /server/cicd/runs returns it. */
interface RunSummaryRow {
  project: string;
  run: string;
  branch?: string | null;
  sha?: string | null;
  runner?: string | null;
  started_at?: string | null;
  trigger?: string | null;
  suite?: string | null;
  overall: 'passed' | 'failed' | 'partial' | 'unknown';
  finished_at?: string | null;
  jobs_detail?: Record<string, { status: string; report_url?: string | null; category?: string | null }>;
}

/**
 * ci_run_summary + jobs -> the shape this page has always rendered. The data source moved
 * from the report directories on disk to the `cicd` schema (TASK-06 W4); the view already
 * computes `overall`, so it is taken as-is instead of being recomputed here.
 */
function toRunMeta(row: RunSummaryRow): RunMeta {
  const jobs: Record<string, JobStatus> = {};
  Object.entries(row.jobs_detail ?? {}).forEach(([name, job]) => {
    jobs[name] = {
      status: job.status,
      report: reportSubPath(job.report_url, row.run),
      category: job.category ?? null,
    };
  });
  return {
    run: row.run,
    repo: row.project,
    branch: row.branch || '-',
    sha: (row.sha || '-').slice(0, 7),
    date: row.started_at || '-',
    runner: row.runner ?? null,
    trigger: row.trigger ?? null,
    suite: row.suite ?? null,
    overall: row.overall,
    jobs,
    finishedAt: row.finished_at ?? null,
  };
}

// ─── run-list cache + delta refresh ───────────────────────────────────────────
//
// The page used to re-read all 200 runs with their jobs on every tick (15 s while a run is
// in flight, 60 s otherwise) and again on every visit. Now the last full list lives in
// localStorage and each refresh asks the server only for runs that started, or had a job
// finish, since the newest timestamp already held (`?changed_since=`), then merges those
// rows over the cached ones by project/run key. A full reload happens when there is no
// cache, when the cache is older than FULL_RESYNC_MS (catches deletions and out-of-band
// edits), or when the schema of the cached shape changes (bump CACHE_KEY).
const CACHE_KEY = 'cicd-runs-v2';
const RUN_LIMIT = 200;
const FULL_RESYNC_MS = 30 * 60_000;
// Re-ask for this much before the cursor: an upsert whose `now()` was taken just before
// the previous read committed would otherwise sit below the cursor forever. Merging by
// key makes the overlap free.
const CURSOR_OVERLAP_MS = 60_000;

interface RunsCache {
  runs: RunMeta[];
  /** When the list was last read in full (not merged) — drives the periodic full resync. */
  fullSyncAt: number;
}

function readRunsCache(): RunsCache | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as RunsCache;
    if (!Array.isArray(parsed.runs) || typeof parsed.fullSyncAt !== 'number') return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeRunsCache(cache: RunsCache): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
  } catch {
    // quota / private mode — the page still works, it just reloads in full next time
  }
}

const runKey = (r: RunMeta) => `${r.repo || 'virtualpytest'}/${r.run}`;

/** ISO timestamp for `?changed_since=`: newest started/finished instant held, minus overlap. */
function deltaCursor(runs: RunMeta[]): string | null {
  let max = 0;
  runs.forEach((r) => {
    [r.date, r.finishedAt].forEach((iso) => {
      const t = iso ? parseRunDate(iso) : null;
      if (t != null && t > max) max = t;
    });
  });
  return max ? new Date(max - CURSOR_OVERLAP_MS).toISOString() : null;
}

/** Changed rows over the cached list: replace by key, newest first, capped like the server. */
function mergeRuns(cached: RunMeta[], changed: RunMeta[]): RunMeta[] {
  const byKey = new Map(cached.map((r) => [runKey(r), r]));
  changed.forEach((r) => byKey.set(runKey(r), r));
  return Array.from(byKey.values())
    .sort((a, b) => (parseRunDate(b.date) ?? 0) - (parseRunDate(a.date) ?? 0))
    .slice(0, RUN_LIMIT);
}

const JOB_CATEGORY_LABEL: Record<string, string> = {
  browser: 'Browser',
  api: 'API',
  unit: 'Unit',
  lint: 'Lint',
  script: 'Script',
};

// What each job proves, in plain words — shown as a tooltip on the job name so anyone can
// tell e2e-pages from frontend-component-tests without reading the workflow.
const JOB_DESCRIPTION: Record<string, string> = {
  lint: 'Code style check (ESLint) on the frontend and feature code. Nothing is run.',
  typecheck: 'TypeScript type check (tsc). Nothing is run.',
  'frontend-component-tests':
    'Each frontend page is rendered in a simulated browser (jsdom) with its data hooks faked. Proves the page mounts and shows its main elements. No real browser, no server.',
  'backend-server-tests':
    'Python tests calling the deployed server over HTTP. Each test checks the exact status and response body of a route, including that admin-only routes reject other roles.',
  'api-routes':
    'Calls every GET route the server registers (list discovered from the server itself, ids filled from list endpoints). Proves no route crashes (no 5xx).',
  'e2e-smoke':
    'A real Chrome (Playwright) opens the deployed site and checks that 8 key pages show their main controls.',
  'e2e-pages':
    'A real Chrome (Playwright) opens all 44 pages of the deployed site: each must load without a console error, and a screenshot is saved.',
  'e2e-viewport':
    'A real Chrome (Playwright) opens key pages at desktop (1280×800) and phone (375×812) sizes and checks nothing overflows horizontally.',
  'web-script-local-debug':
    'Runs the web/* VirtualPyTest scripts (Dailymotion playback check, browser-use task) in a browser on the CI runner itself. Fails when a script reports SCRIPT_SUCCESS:false.',
};

// All jobs expected in a complete run — used to detect in-progress runs
const EXPECTED_JOBS = ['lint', 'backend-server-tests', 'frontend-component-tests', 'e2e-smoke', 'e2e-pages', 'e2e-viewport', 'web-script-local-debug', 'api-routes'];

const CATEGORY_COLOR: Record<string, 'default' | 'primary' | 'secondary' | 'info' | 'warning'> = {
  browser: 'primary',
  api: 'secondary',
  unit: 'info',
  lint: 'default',
  script: 'warning',
};

function OverallChip({ status }: { status: string }) {
  if (status === 'passed') return <Chip label="PASS" color="success" size="small" sx={{ fontWeight: 600 }} />;
  if (status === 'failed') return <Chip label="FAIL" color="error" size="small" sx={{ fontWeight: 600 }} />;
  if (status === 'partial') return <Chip label="PARTIAL" color="warning" size="small" sx={{ fontWeight: 600 }} />;
  return <Chip label="—" size="small" />;
}

function JobIcon({ status }: { status: string }) {
  if (status === 'success') return <CheckCircle sx={{ color: 'success.main', fontSize: 16 }} />;
  if (status === 'failure') return <Cancel sx={{ color: 'error.main', fontSize: 16 }} />;
  return <RadioButtonUnchecked sx={{ color: 'text.disabled', fontSize: 16 }} />;
}

/** "45s", "4m 12s", "1h 03m" — compact enough to sit beside the state label. */
function formatElapsed(fromIso: string, now: number): string | null {
  const start = Date.parse(fromIso);
  if (Number.isNaN(start)) return null;
  const secs = Math.max(0, Math.floor((now - start) / 1000));
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${String(secs % 60).padStart(2, '0')}s`;
  return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`;
}

function RunnerCard({
  runner,
  now,
  onRestart,
}: {
  runner: ProjectRunner;
  now: number;
  onRestart?: (name: string) => void;
}) {
  const isOnline = runner.status === 'online';
  const stateLabel = runner.status === 'unknown' ? 'UNKNOWN' : !isOnline ? 'OFFLINE' : runner.busy ? 'RUNNING' : 'ALIVE';
  const stateColor = runner.status === 'unknown' ? 'text.disabled' : !isOnline ? 'error.main' : runner.busy ? 'warning.main' : 'success.main';
  const elapsed = runner.current?.startedAt ? formatElapsed(runner.current.startedAt, now) : null;
  const [restarting, setRestarting] = React.useState(false);
  const [restartMsg, setRestartMsg] = React.useState<string | null>(null);

  const handleRestart = async () => {
    setRestarting(true);
    setRestartMsg(null);
    try {
      const res = await fetch(buildPrimaryServerUrl(`/server/cicd/runners/${runner.name}/restart`), { method: 'POST' });
      const d = await res.json();
      setRestartMsg(d.success ? 'Restarted' : (d.error ?? 'Failed'));
    } catch {
      setRestartMsg('Request failed');
    } finally {
      setRestarting(false);
      if (onRestart) onRestart(runner.name);
    }
  };

  return (
    <Paper
      variant="outlined"
      // Fixed box so every card in the row is the same size regardless of how long its
      // runner name or job label is — the text inside truncates instead of the card growing.
      sx={{ p: 1.5, width: 300, height: 108, flex: '0 0 auto', display: 'flex', flexDirection: 'column' }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.5 }}>
        <Chip label={runner.project} size="small" sx={{ height: 18, fontSize: '0.65rem', fontWeight: 700 }} />
        <FiberManualRecord sx={{ fontSize: 10, color: stateColor, flexShrink: 0 }} />
        <Typography variant="caption" fontWeight={700} noWrap sx={{ flex: 1 }} title={runner.name}>{runner.name}</Typography>
        {runner.status === 'offline' && (
          <Tooltip title="Restart runner service">
            <span>
              <IconButton size="small" onClick={handleRestart} disabled={restarting} sx={{ p: 0.25 }}>
                {restarting ? <CircularProgress size={12} /> : <RestartAlt sx={{ fontSize: 14 }} />}
              </IconButton>
            </span>
          </Tooltip>
        )}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75 }}>
        <Typography
          variant="body2"
          fontWeight={700}
          color={stateColor}
          lineHeight={1.2}
          sx={{ textTransform: 'lowercase', letterSpacing: '0.02em' }}
        >
          {stateLabel}
        </Typography>
        {elapsed && (
          <Typography variant="caption" color="text.secondary" noWrap>for {elapsed}</Typography>
        )}
      </Box>
      {runner.current ? (
        <Typography
          variant="caption"
          color="text.secondary"
          noWrap
          display="block"
          title={`${runner.current.job}${runner.current.workflow ? ` · ${runner.current.workflow}` : ''}${runner.current.branch ? ` · ${runner.current.branch}` : ''}`}
        >
          {runner.current.runNumber ? `#${runner.current.runNumber} ` : ''}{runner.current.job}
        </Typography>
      ) : (
        <Typography variant="caption" color="text.disabled" noWrap display="block">
          {runner.busy ? 'job details unavailable' : ' '}
        </Typography>
      )}
      <Typography
        variant="caption"
        color="text.disabled"
        display="block"
        sx={{ mt: 'auto', fontSize: '0.68rem' }}
        title={runner.lastDate}
      >
        {runner.lastRun
          ? `last run #${runner.lastRun}${runner.lastDate && runner.lastDate !== '-' ? ` · ${runner.lastDate}` : ''}`
          : 'no runs yet'}
      </Typography>
      {restartMsg && (
        <Typography variant="caption" color={restartMsg === 'Restarted' ? 'success.main' : 'error.main'} display="block" mt={0.5}>
          {restartMsg}
        </Typography>
      )}
    </Paper>
  );
}

function KpiCard({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string | number;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <Paper
      variant="outlined"
      sx={{ p: 2, flex: 1, minWidth: 100, display: 'flex', flexDirection: 'column', gap: 0.25 }}
    >
      <Typography variant="caption" color="text.secondary" noWrap>{label}</Typography>
      <Typography variant="h5" fontWeight={700} color={valueColor || 'text.primary'} lineHeight={1.2}>
        {value}
      </Typography>
      {sub && (
        <Typography variant="caption" color="text.secondary">{sub}</Typography>
      )}
    </Paper>
  );
}

const CICDReports: React.FC = () => {
  const rowHoverSx = {
    '&:hover': { backgroundColor: 'transparent !important' },
  };

  const [runs, setRuns] = useState<RunMeta[]>(() => readRunsCache()?.runs ?? []);
  const [loading, setLoading] = useState(() => !readRunsCache());
  const [error, setError] = useState<string | null>(null);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [runners, setRunners] = useState<RunnerStatus[]>(() => getCached<RunnerStatus[]>('cicd-runners') ?? []);
  const [repoFilter, setRepoFilter] = useState<string>('all');
  const [rangeFilter, setRangeFilter] = useState<RangeKey>('7d');
  const [liveRuns, setLiveRuns] = useState<LiveRun[]>([]);
  const [runnersOpen, setRunnersOpen] = useState<boolean>(() => getCached<boolean>('cicd-runners-open') ?? true);
  // Ticks once a second purely so the "for 4m 12s" elapsed labels keep counting up
  // while the page sits open between the slower data refreshes.
  const [nowTick, setNowTick] = useState(() => Date.now());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runsRef = useRef<RunMeta[]>(runs);
  runsRef.current = runs;
  const fullSyncAtRef = useRef<number>(readRunsCache()?.fullSyncAt ?? 0);

  const fetchRuns = useCallback(async (mode: 'auto' | 'full' = 'auto') => {
    try {
      const cached = runsRef.current;
      const cursor = deltaCursor(cached);
      const cacheStale = Date.now() - fullSyncAtRef.current > FULL_RESYNC_MS;
      const delta = mode === 'auto' && cursor != null && !cacheStale;
      if (cached.length === 0) setLoading(true);
      setError(null);
      const params = new URLSearchParams({ expand: 'jobs', limit: String(RUN_LIMIT) });
      if (delta) params.set('changed_since', cursor);
      const [runsRes, runnersRes, liveRes] = await Promise.all([
        fetch(buildPrimaryServerUrl(`/server/cicd/runs?${params.toString()}`)),
        fetch(buildPrimaryServerUrl('/server/cicd/runners')),
        // In-flight GitHub runs, so a busy card can name the job it is executing and
        // since when. Failure here is non-fatal: the cards just fall back to "running".
        fetch(buildPrimaryServerUrl('/server/cicd/live')).catch(() => null),
      ]);
      if (!runsRes.ok) throw new Error(`Could not read CI runs (${runsRes.status}).`);
      const data = await runsRes.json();
      if (data.configured === false) throw new Error(`CI/CD not configured: ${data.error ?? 'unknown reason'}`);
      const fetched: RunMeta[] = (data.runs ?? []).map(toRunMeta);
      const newRuns = delta ? mergeRuns(cached, fetched) : fetched;
      if (!delta) fullSyncAtRef.current = Date.now();
      setRuns(newRuns);
      writeRunsCache({ runs: newRuns, fullSyncAt: fullSyncAtRef.current });
      if (runnersRes.ok) {
        const rdata = await runnersRes.json();
        const newRunners = rdata.runners ?? [];
        setRunners(newRunners);
        setCached('cicd-runners', newRunners);
      }
      if (liveRes && liveRes.ok) {
        const ldata = await liveRes.json();
        setLiveRuns(ldata.running ?? []);
      }
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load CI reports');
    } finally {
      setLoading(false);
    }
  }, []);

  // Detect if the latest run is still in progress (missing jobs)
  const latestRunInProgress = useMemo(() => {
    if (runs.length === 0) return false;
    const latest = runs[0];
    const knownJobs = Object.keys(latest.jobs || {});
    // In progress if fewer than expected jobs have reported yet
    return knownJobs.length < EXPECTED_JOBS.length && latest.overall !== 'passed';
  }, [runs]);

  // Auto-refresh every 15s when a run is in progress, every 60s otherwise
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    const delay = latestRunInProgress ? 15_000 : 60_000;
    intervalRef.current = setInterval(() => fetchRuns('auto'), delay);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [latestRunInProgress, fetchRuns]);

  useEffect(() => { fetchRuns('auto'); }, [fetchRuns]);

  // Distinct projects across all fetched runs (repo field defaults to "virtualpytest" for
  // legacy/own runs), for the Project filter — always includes "all".
  const repoOptions = useMemo(
    () => Array.from(new Set(runs.map((r) => r.repo || 'virtualpytest'))).sort(),
    [runs],
  );

  const rangeMs = RANGE_OPTIONS.find((o) => o.key === rangeFilter)?.ms ?? null;
  const rangeLabel = RANGE_OPTIONS.find((o) => o.key === rangeFilter)?.label ?? '';

  const filteredRuns = useMemo(() => {
    const since = rangeMs == null ? null : Date.now() - rangeMs;
    return runs.filter((r) => {
      if (repoFilter !== 'all' && (r.repo || 'virtualpytest') !== repoFilter) return false;
      if (since == null) return true;
      const t = parseRunDate(r.date);
      return t != null && t >= since;
    });
  }, [runs, repoFilter, rangeMs]);

  // One card per *currently registered* runner, so the whole fleet's health is visible —
  // each repo has been served by several runners since 2026-09-07, and drawing one card per
  // project (the runner that executed that project's latest run) hid the rest of the fleet.
  // Liveness comes from the GitHub runner list; each card carries that runner's own most
  // recent stored run, so a freshly registered runner reads "no runs yet" instead of
  // borrowing a sibling's history.
  //
  // Deliberately keyed off the registered list only. Cards for names that appear in stored
  // runs but are no longer registered would be permanent clutter: renaming or rebuilding the
  // fleet leaves every historical row pointing at a dead name (42 runs still name
  // `ci-runner-v3`), which would strand an UNKNOWN card per retired runner forever. The runs
  // table below already shows which runner executed each run, so nothing is lost.
  const projectRunners = useMemo<ProjectRunner[]>(() => {
    const projects = repoFilter === 'all' ? repoOptions : [repoFilter];
    const cards: ProjectRunner[] = [];

    projects.forEach((project) => {
      const projectRuns = runs.filter((r) => (r.repo || 'virtualpytest') === project);
      // The synthetic github-hosted row is always "online" and has nothing to restart.
      const registered = runners.filter((x) => x.project === project && x.name !== 'github-hosted');

      registered
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name))
        .forEach((live) => {
          const latest = projectRuns.find((r) => r.runner === live.name);
          // A runner reports `busy` without saying what it is busy with; /cicd/live has the
          // job list of every in-flight run, so match this runner to its own running job.
          let current: ProjectRunner['current'];
          for (const lr of liveRuns) {
            const job = (lr.jobs ?? []).find(
              (j) => j.runner_name === live.name && j.status === 'in_progress',
            );
            if (job) {
              current = {
                job: job.name ?? 'job',
                workflow: lr.workflow ?? '',
                runNumber: lr.run_number,
                branch: lr.branch,
                startedAt: job.started_at ?? undefined,
              };
              break;
            }
          }
          cards.push({
            project,
            name: live.name,
            status: live.status,
            busy: live.busy,
            lastRun: latest?.run,
            lastDate: latest?.date,
            current,
          });
        });

      // Configured project with no runner registered at all — keep a placeholder so it does
      // not silently disappear from the page.
      if (registered.length === 0) {
        cards.push({ project, name: '—', status: 'unknown', busy: false });
      }
    });

    return cards;
  }, [runs, runners, liveRuns, repoFilter, repoOptions]);

  const busyCount = projectRunners.filter((r) => r.busy).length;
  const offlineRunners = projectRunners.filter((r) => r.status === 'offline');
  const onlineCount = projectRunners.filter((r) => r.status === 'online').length;
  const queuedCount = liveRuns.filter((lr) => lr.status === 'queued').length;
  // Runs queue silently when every runner is offline (2026-09-08: all six listeners lost
  // their GitHub session while their services stayed "active"; four hours of pushes sat in
  // "queued"). Say so where the runs are looked at, and offer the fix in one click.
  const runnersStuck = offlineRunners.length > 0 && onlineCount === 0;
  const [restartingAll, setRestartingAll] = useState(false);
  const restartAllOffline = async () => {
    setRestartingAll(true);
    try {
      for (const r of offlineRunners) {
        await fetch(buildPrimaryServerUrl(`/server/cicd/runners/${r.name}/restart`), { method: 'POST' });
      }
    } finally {
      setRestartingAll(false);
      setTimeout(() => void fetchRuns('auto'), 4000);
    }
  };

  // Keep the elapsed labels on busy cards counting between data refreshes; only runs while
  // something is actually busy, so an idle fleet costs no timer.
  const anyBusy = projectRunners.some((r) => r.current?.startedAt);
  useEffect(() => {
    if (!anyBusy) return;
    const id = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, [anyBusy]);

  // KPI computations
  const kpi = useMemo(() => {
    const total = filteredRuns.length;
    const passed = filteredRuns.filter((r) => r.overall === 'passed').length;
    const passRate = total > 0 ? Math.round((passed / total) * 100) : 0;

    // Per-category stats across all runs
    const catStats: Record<string, { pass: number; total: number }> = {};
    filteredRuns.forEach((run) => {
      Object.values(run.jobs || {}).forEach((job) => {
        const cat = job.category || 'unknown';
        if (!catStats[cat]) catStats[cat] = { pass: 0, total: 0 };
        catStats[cat].total += 1;
        if (job.status === 'success') catStats[cat].pass += 1;
      });
    });

    // Only show known categories in a fixed order
    const catOrder = ['browser', 'api', 'unit', 'script', 'lint'];
    const cats = catOrder.filter((c) => catStats[c]);

    return { total, passed, passRate, catStats, cats };
  }, [filteredRuns]);

  const reportUrl = (run: string, subPath?: string | null) =>
    buildPrimaryServerUrl(`/server/cicd/report/${run}/${subPath != null ? subPath + '/' : ''}`);

  const toggleExpand = (run: string) =>
    setExpandedRun((prev) => (prev === run ? null : run));

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Typography variant="h4" component="h1">CI/CD Reports</Typography>
          {latestRunInProgress && (
            <Chip
              icon={<FiberManualRecord sx={{ fontSize: '10px !important', animation: 'pulse 1.5s infinite' }} />}
              label="LIVE"
              size="small"
              color="error"
              sx={{
                fontWeight: 700,
                fontSize: '0.65rem',
                '@keyframes pulse': { '0%, 100%': { opacity: 1 }, '50%': { opacity: 0.4 } },
              }}
            />
          )}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <Select
              value={rangeFilter}
              onChange={(e) => setRangeFilter(e.target.value as RangeKey)}
              sx={{ fontSize: '0.85rem' }}
            >
              {RANGE_OPTIONS.map((o) => (
                <MenuItem key={o.key} value={o.key}>{o.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <Select
              value={repoOptions.includes(repoFilter) || repoFilter === 'all' ? repoFilter : 'all'}
              onChange={(e) => setRepoFilter(e.target.value)}
              displayEmpty
              sx={{ fontSize: '0.85rem' }}
            >
              <MenuItem value="all">All projects</MenuItem>
              {repoOptions.map((repo) => (
                <MenuItem key={repo} value={repo}>{repo}</MenuItem>
              ))}
            </Select>
          </FormControl>
          {lastUpdated && (
            <Typography variant="caption" color="text.disabled">
              updated {lastUpdated.toLocaleTimeString()}
              {latestRunInProgress ? ' · refreshing every 15s' : ''}
            </Typography>
          )}
          <Tooltip title="Reload the full runs list (auto-refresh only fetches what changed)">
            <IconButton onClick={() => fetchRuns('full')} disabled={loading}><Refresh /></IconButton>
          </Tooltip>
        </Box>
      </Box>

      {error && <Alert severity="warning">{error}</Alert>}

      {loading && runs.length === 0 ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', pt: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          {/* KPI Cards */}
          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', justifyContent: 'center' }}>
            <KpiCard
              label="Total Runs"
              value={kpi.total}
              sub={rangeLabel.toLowerCase()}
            />
            <KpiCard
              label="Pass Rate"
              value={`${kpi.passRate}%`}
              sub={`${kpi.passed} / ${kpi.total} pass`}
              valueColor={
                kpi.passRate >= 80 ? 'success.main' :
                kpi.passRate >= 50 ? 'warning.main' : 'error.main'
              }
            />
            {kpi.cats.map((cat) => {
              const { pass, total } = kpi.catStats[cat];
              const rate = total > 0 ? Math.round((pass / total) * 100) : 0;
              return (
                <KpiCard
                  key={cat}
                  label={JOB_CATEGORY_LABEL[cat] || cat}
                  value={`${rate}%`}
                  sub={`${pass} / ${total} pass`}
                  valueColor={
                    rate === 100 ? 'success.main' :
                    rate > 0 ? 'warning.main' : 'error.main'
                  }
                />
              );
            })}
          </Box>

          {/* Runs Table */}
          {filteredRuns.length === 0 ? (
            <Typography variant="body2" color="text.secondary" align="center" sx={{ py: 4 }}>
              {runs.length > 0 && rangeMs != null
                ? `No runs in ${rangeLabel.toLowerCase()} — widen the time range.`
                : runs.length === 0
                ? 'No reports yet. Reports are saved to /opt/ci-reports/ on the runner after each CI run.'
                : 'No reports for this project yet.'}
            </Typography>
          ) : (
          <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
            <Table size="small" stickyHeader sx={{ tableLayout: 'fixed', width: '100%' }}>
              <TableHead>
                <TableRow>
                  <TableCell width={40} />
                  <TableCell sx={{ width: 90, maxWidth: 90 }}>Project</TableCell>
                  <TableCell sx={{ width: 70, maxWidth: 70 }}>Run</TableCell>
                  <TableCell sx={{ width: 130, maxWidth: 130 }}>Branch</TableCell>
                  <TableCell sx={{ width: 80, maxWidth: 80 }}>Commit</TableCell>
                  <TableCell sx={{ width: 160, maxWidth: 160 }}>Date</TableCell>
                  <TableCell sx={{ width: 90, maxWidth: 90 }}>Trigger</TableCell>
                  <TableCell sx={{ width: 70, maxWidth: 70 }}>Suite</TableCell>
                  <TableCell sx={{ width: 90, maxWidth: 90 }}>Status</TableCell>
                  <TableCell sx={{ width: 220, maxWidth: 220 }}>Jobs</TableCell>
                  <TableCell align="right" sx={{ width: 100, maxWidth: 100 }}>Report</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredRuns.map((run) => {
                  const isExpanded = expandedRun === run.run;
                  const jobEntries = Object.entries(run.jobs || {});
                  const reportJobs = jobEntries.filter(([, j]) => j.report != null);
                  const primaryReport = reportJobs[0];
                  const passCount = jobEntries.filter(([, j]) => j.status === 'success').length;
                  const knownJobNames = new Set(jobEntries.map(([n]) => n));
                  // Show pending slots only for the latest run while it's in progress
                  const pendingJobs = run.run === runs[0]?.run && latestRunInProgress
                    ? EXPECTED_JOBS.filter((j) => !knownJobNames.has(j))
                    : [];

                  return (
                    <React.Fragment key={run.run}>
                      <TableRow
                        hover
                        onClick={() => (jobEntries.length > 0 || pendingJobs.length > 0) && toggleExpand(run.run)}
                        sx={{
                          cursor: (jobEntries.length > 0 || pendingJobs.length > 0) ? 'pointer' : 'default',
                          '& td': { borderBottom: isExpanded ? 0 : undefined },
                          ...rowHoverSx,
                        }}
                      >
                        {/* Expand toggle */}
                        <TableCell padding="none" sx={{ pl: 0.5 }}>
                          {(jobEntries.length > 0 || pendingJobs.length > 0) && (
                            <IconButton
                              size="small"
                              onClick={(e) => { e.stopPropagation(); toggleExpand(run.run); }}
                            >
                              {isExpanded ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
                            </IconButton>
                          )}
                        </TableCell>

                        {/* Project */}
                        <TableCell sx={{ width: 90, maxWidth: 90, overflow: 'hidden' }}>
                          <Chip label={run.repo || 'virtualpytest'} size="small" sx={{ maxWidth: 85 }} />
                        </TableCell>

                        {/* Run # */}
                        <TableCell sx={{ width: 70, maxWidth: 70 }}>
                          <Typography variant="body2" fontWeight={600}>#{run.run}</Typography>
                        </TableCell>

                        {/* Branch */}
                        <TableCell sx={{ width: 130, maxWidth: 130, overflow: 'hidden' }}>
                          <Chip label={run.branch} size="small" variant="outlined" sx={{ maxWidth: 120 }} />
                        </TableCell>

                        {/* Commit */}
                        <TableCell sx={{ width: 80, maxWidth: 80 }}>
                          <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{run.sha}</Typography>
                        </TableCell>

                        {/* Date */}
                        <TableCell sx={{ width: 160, maxWidth: 160 }}>
                          <Typography variant="caption" noWrap>{formatRunDate(run.date)}</Typography>
                        </TableCell>

                        {/* Trigger (push / dispatch / schedule) — NULL on pre-W3 rows */}
                        <TableCell sx={{ width: 90, maxWidth: 90 }}>
                          <Typography variant="caption" noWrap sx={{ color: run.trigger ? 'text.primary' : 'text.disabled' }}>
                            {run.trigger ?? '—'}
                          </Typography>
                        </TableCell>

                        {/* Suite (white / grey / all) — NULL on pre-W3 rows */}
                        <TableCell sx={{ width: 70, maxWidth: 70 }}>
                          <Typography variant="caption" noWrap sx={{ color: run.suite ? 'text.primary' : 'text.disabled' }}>
                            {run.suite ?? '—'}
                          </Typography>
                        </TableCell>

                        {/* Overall status */}
                        <TableCell>
                          <OverallChip status={run.overall} />
                        </TableCell>

                        {/* Jobs summary */}
                        <TableCell>
                          {jobEntries.length > 0 ? (
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography variant="caption" color="text.secondary" sx={{ minWidth: 30 }}>
                                {passCount}/{jobEntries.length}
                              </Typography>
                              <Box sx={{ display: 'flex', gap: 0.5 }}>
                                {jobEntries.map(([name, job]) => (
                                  <Tooltip key={name} title={`${name}: ${job.status}`}>
                                    <Box
                                      sx={{
                                        width: 10,
                                        height: 10,
                                        borderRadius: '2px',
                                        bgcolor:
                                          job.status === 'success' ? 'success.main' :
                                          job.status === 'failure' ? 'error.main' : 'text.disabled',
                                        opacity: job.status === 'skipped' || job.status === 'cancelled' ? 0.3 : 1,
                                        flexShrink: 0,
                                      }}
                                    />
                                  </Tooltip>
                                ))}
                              </Box>
                            </Box>
                          ) : (
                            <Typography variant="caption" color="text.disabled">—</Typography>
                          )}
                        </TableCell>

                        {/* Primary report link */}
                        <TableCell align="right">
                          {primaryReport ? (
                            <Tooltip title={`Open ${primaryReport[0]} report`}>
                              <IconButton
                                size="small"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  window.open(reportUrl(run.run, primaryReport[1].report), '_blank');
                                }}
                              >
                                <OpenInNew fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          ) : null}
                        </TableCell>
                      </TableRow>

                      {/* Expanded: per-job detail */}
                      {(jobEntries.length > 0 || pendingJobs.length > 0) && (
                        <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                          <TableCell colSpan={11} sx={{ py: 0, bgcolor: 'action.hover' }}>
                            <Collapse in={isExpanded} unmountOnExit>
                              <Box sx={{ py: 1, pl: 7, pr: 2 }}>
                                <Table size="small">
                                  <TableBody>
                                    {jobEntries.map(([name, job]) => (
                                      <TableRow key={name} sx={{ '& td': { border: 0, py: 0.4 }, '&:hover': { backgroundColor: 'transparent !important' } }}>
                                        <TableCell width={24} sx={{ pr: 1 }}>
                                          <JobIcon status={job.status} />
                                        </TableCell>
                                        <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.78rem', width: 240 }}>
                                          <Tooltip title={JOB_DESCRIPTION[name] ?? ''} placement="right" arrow enterDelay={300}>
                                            <span style={{ cursor: JOB_DESCRIPTION[name] ? 'help' : 'default', borderBottom: JOB_DESCRIPTION[name] ? '1px dotted currentColor' : 'none' }}>
                                              {name}
                                            </span>
                                          </Tooltip>
                                        </TableCell>
                                        <TableCell width={90}>
                                          <Chip
                                            label={JOB_CATEGORY_LABEL[job.category ?? ''] ?? (job.category || '—')}
                                            size="small"
                                            color={CATEGORY_COLOR[job.category ?? ''] ?? 'default'}
                                            variant="outlined"
                                            sx={{ fontSize: '0.65rem', height: 20 }}
                                          />
                                        </TableCell>
                                        <TableCell width={80}>
                                          <Typography
                                            variant="caption"
                                            color={
                                              job.status === 'success' ? 'success.main' :
                                              job.status === 'failure' ? 'error.main' : 'text.secondary'
                                            }
                                          >
                                            {job.status}
                                          </Typography>
                                        </TableCell>
                                        <TableCell align="right" sx={{ width: 60, maxWidth: 60 }}>
                                          {job.report != null && (
                                            <Tooltip title="Open report in new tab">
                                              <IconButton
                                                size="small"
                                                onClick={() => window.open(reportUrl(run.run, job.report), '_blank')}
                                              >
                                                <OpenInNew fontSize="small" />
                                              </IconButton>
                                            </Tooltip>
                                          )}
                                        </TableCell>
                                      </TableRow>
                                    ))}
                                    {/* Pending slots for in-progress run */}
                                    {pendingJobs.map((name) => (
                                      <TableRow key={`pending-${name}`} sx={{ '& td': { border: 0, py: 0.4 }, '&:hover': { backgroundColor: 'transparent !important' }, opacity: 0.45 }}>
                                        <TableCell width={24} sx={{ pr: 1 }}>
                                          <HourglassEmpty sx={{ color: 'text.disabled', fontSize: 16 }} />
                                        </TableCell>
                                        <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.78rem', width: 240, color: 'text.disabled' }}>
                                          {name}
                                        </TableCell>
                                        <TableCell width={90} />
                                        <TableCell width={80}>
                                          <Typography variant="caption" color="text.disabled">pending</Typography>
                                        </TableCell>
                                        <TableCell align="right" sx={{ width: 60, maxWidth: 60 }} />
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </Box>
                            </Collapse>
                          </TableCell>
                        </TableRow>
                      )}
                    </React.Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </Paper>
          )}

          {/* Runner Cards — one per registered runner, across every project */}
          {(runnersStuck || (offlineRunners.length > 0 && queuedCount > 0)) && (
            <Alert
              severity="error"
              sx={{ mb: 1.5, py: 0.25, alignItems: 'center' }}
              action={
                <Button color="inherit" size="small" onClick={restartAllOffline} disabled={restartingAll} startIcon={restartingAll ? <CircularProgress size={12} color="inherit" /> : <RestartAlt fontSize="small" />}>
                  Restart {offlineRunners.length} offline
                </Button>
              }
            >
              {runnersStuck ? 'All' : `${offlineRunners.length} of ${projectRunners.length}`} runners offline
              {queuedCount > 0 ? ` — ${queuedCount} run${queuedCount > 1 ? 's' : ''} queued on GitHub cannot start` : ''}.
              Their service is usually still running but has lost its GitHub session; a restart reconnects it.
            </Alert>
          )}
          {projectRunners.length > 0 && (
            <Box>
              <Box
                onClick={() => {
                  const next = !runnersOpen;
                  setRunnersOpen(next);
                  setCached('cicd-runners-open', next);
                }}
                sx={{
                  display: 'flex', alignItems: 'center', gap: 0.5, mb: 1,
                  cursor: 'pointer', userSelect: 'none', width: 'fit-content',
                }}
              >
                <ExpandMore
                  sx={{
                    fontSize: 18,
                    transition: 'transform 150ms',
                    transform: runnersOpen ? 'rotate(0deg)' : 'rotate(-90deg)',
                  }}
                />
                <Typography variant="caption" fontWeight={700}>
                  Runners ({projectRunners.length})
                </Typography>
                {busyCount > 0 && (
                  <Typography variant="caption" color="warning.main">· {busyCount} running</Typography>
                )}
                {offlineRunners.length > 0 && (
                  <Typography variant="caption" color="error.main">· {offlineRunners.length} offline</Typography>
                )}
              </Box>
              {/* Never let an offline runner hide behind a collapsed section */}
              <Collapse in={runnersOpen || offlineRunners.length > 0} unmountOnExit>
                <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                  {projectRunners.map((r) => (
                    <RunnerCard
                      key={`${r.project}-${r.name}`}
                      runner={r}
                      now={nowTick}
                      onRestart={() => fetchRuns('auto')}
                    />
                  ))}
                </Box>
              </Collapse>
            </Box>
          )}
        </>
      )}
    </Box>
  );
};

export default CICDReports;
