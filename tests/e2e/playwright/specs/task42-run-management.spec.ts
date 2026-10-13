/**
 * Run management (TASK-42) — browser acceptance against a built frontend with every
 * backend call answered by deterministic fixtures. No backend, database or host is used.
 *
 * Run (from tests/e2e/playwright, after `cd frontend && ./node_modules/.bin/vite build`
 * and `./node_modules/.bin/vite preview --host 127.0.0.1 --port 4719 --strictPort`):
 *
 *   E2E_BASE_URL=http://127.0.0.1:4719 npx playwright test --config task42.config.js \
 *     specs/task42-run-management.spec.ts
 *
 * The coordinator's `scripts/task42/run_playwright.sh` does exactly that. The config has
 * no globalSetup: this spec signs in by itself.
 *
 * Auth: the frontend activates an admin auto-sign session from `?auto_signed=<token>`
 * (frontend/src/lib/autoSign.ts + AuthContext). The token is only ever validated by the
 * backend, and here every `/server/**` request is fulfilled by a fixture, so any token
 * works. A reload keeps it (tab sessionStorage, BUG-0392), but a fresh `goto` in a new
 * context does not, so every authenticated `goto` carries it. The share snapshot test uses
 * a fresh context and never sets it — it must work for an anonymous visitor.
 */

import { expect, test, type BrowserContext, type Route } from '@playwright/test';
import fs from 'node:fs';

const AUTO_SIGN = 'task42-e2e-fixture';
const SHARE_ID = 'snap-1';
const SHARE_TOKEN = 'tok-abc_123';

const withAuth = (path: string): string => `${path}${path.includes('?') ? '&' : '?'}auto_signed=${AUTO_SIGN}`;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

type Json = Record<string, unknown> | unknown[];

const iso = (minutesAgo: number) => new Date(Date.UTC(2026, 9, 1, 12, 0, 0) - minutesAgo * 60_000).toISOString();

const trendPoints = () =>
  Array.from({ length: 30 }, (_, i) => {
    const day = new Date(Date.UTC(2026, 8, 2 + i)).toISOString().slice(0, 10);
    return { day, passed: i % 3, failed: i % 5 === 0 ? 1 : 0, other: 0, total: (i % 3) + (i % 5 === 0 ? 1 : 0) };
  });

/** 33 campaign children: 4 failed, 12 skipped, 17 passed. The first name is a CSV formula. */
const campaignChildren = Array.from({ length: 33 }, (_, i) => {
  const status = i < 4 ? 'failed' : i < 16 ? 'skipped' : 'passed';
  return {
    script_result_id: status === 'skipped' ? null : `sr-c-${i}`,
    name: i === 0 ? '=HYPERLINK("http://evil")' : `child_${String(i).padStart(2, '0')}`,
    script_type: 'script',
    status,
    userinterface_name: 'ui-a',
    environment: 'prod',
    host_name: 'host-1',
    device_name: 'device-1',
    started_at: status === 'skipped' ? null : iso(60 - i),
    completed_at: status === 'skipped' ? null : iso(59 - i),
    execution_time_ms: status === 'skipped' ? null : 1000 + i,
    discard: false,
    report_url: null,
    logs_url: null,
    position: i,
    skip_reason: status === 'skipped' ? 'skipped' : null,
  };
});

const summaryEnvelope = {
  scope: { team_id: 'team-e2e', host_names: ['host-1'] },
  generated_at: '2026-10-01T12:00:00+00:00',
};

const summaryFixture = (kind: string, id: string, url: URL): Json => {
  const limit = Number(url.searchParams.get('limit') ?? 25);
  const offset = Number(url.searchParams.get('offset') ?? 0);
  const statusFilter = url.searchParams.get('status');
  if (kind === 'campaign' && id === 'ce-33') {
    const filtered = statusFilter ? campaignChildren.filter((c) => c.status === statusFilter) : campaignChildren;
    return {
      identity: { kind, id },
      title: 'Nightly regression',
      status: 'failed',
      started_at: iso(70),
      completed_at: iso(20),
      execution_time_ms: 3_000_000,
      counts: { total: 33, passed: 17, failed: 4, skipped: 12, running: 0, pending: 0, cancelled: 0, unknown: 0 },
      children: { items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset },
      trend: { window_days: 30, points: trendPoints(), excluded: { discarded: 0, not_terminal: 0 } },
      metadata: {
        script_type: 'campaign',
        campaign_name: 'Nightly regression',
        host_name: 'host-1',
        device_name: 'device-1',
        milestone: null,
        run_group: null,
        labels: [],
      },
      evidence: { report_url: null, logs_url: null, steps: null },
      ...summaryEnvelope,
    };
  }
  if (kind === 'script' && id === 'sr-1') {
    return {
      identity: { kind, id },
      title: 'dns_lookuptime.py',
      status: 'passed',
      started_at: iso(30),
      completed_at: iso(29),
      execution_time_ms: 42_000,
      counts: { total: 1, passed: 1, failed: 0, skipped: 0, running: 0, pending: 0, cancelled: 0, unknown: 0 },
      children: {
        items: [
          {
            script_result_id: 'sr-1',
            name: 'dns_lookuptime.py',
            script_type: 'script',
            status: 'passed',
            userinterface_name: 'ui-a',
            environment: 'prod',
            host_name: 'host-1',
            device_name: 'device-1',
            started_at: iso(30),
            completed_at: iso(29),
            execution_time_ms: 42_000,
            discard: false,
            report_url: null,
            logs_url: null,
          },
        ],
        total: 1,
        limit,
        offset,
      },
      trend: { window_days: 30, points: trendPoints(), excluded: { discarded: 0, not_terminal: 0 } },
      metadata: {
        script_type: 'dns_lookuptime.py',
        host_name: 'host-1',
        device_name: 'device-1',
        milestone: null,
        run_group: null,
        labels: [],
      },
      evidence: { report_url: null, logs_url: null, steps: null },
      ...summaryEnvelope,
    };
  }
  return { error: 'not found' };
};

const groupFixture = {
  id: 'g-1',
  name: 'Release 4.2 candidates',
  description: null,
  color: null,
  pinned: true,
  archived: false,
  created_at: iso(5000),
  updated_at: iso(100),
};

// GET /server/run-groups/:id/report — member/attempt counts exist only here, not in the list.
const groupReport = {
  group: { ...groupFixture, member_count: 2, attempt_count: 5 },
  merge: 'latest',
  counts: { total: 2, passed: 1, failed: 1, skipped: 0, running: 0, pending: 0, cancelled: 0, unknown: 0 },
  attempts_total: 5,
  attempts: { total: 5, passed: 2, failed: 3, skipped: 0, running: 0, pending: 0, cancelled: 0, unknown: 0 },
  rerun_preview: { all: { targets: 2, skipped: [] }, failures: { targets: 1, skipped: [] } },
  recent_reruns: [],
  rows: [
    { ...campaignChildren[0], name: 'login_flow', script_result_id: 'sr-g-1', status: 'failed', attempts: 3 },
    { ...campaignChildren[20], name: 'zap_channels', script_result_id: 'sr-g-2', status: 'passed', attempts: 2 },
  ],
};

const flakyFixture = {
  window_days: 14,
  window_start: '2026-09-17T00:00:00Z',
  window_end: '2026-10-01T00:00:00Z',
  sample_size: 48,
  min_attempts: 5,
  row_total: 1,
  scope: { host_count: 1, device_filter_applied: false },
  identities_evaluated: 3,
  metric: 'adjacent pass/fail transitions / (attempts - 1)',
  rows: [
    {
      identity: {
        script_name: 'dns_lookuptime.py',
        script_type: 'dns_lookuptime.py',
        userinterface_name: 'ui-a',
        environment: 'prod',
        host_name: 'host-1',
        device_name: 'device-1',
      },
      attempts: 5,
      passes: 3,
      failures: 2,
      transitions: 4,
      flaky_score: 1,
      last_status: 'passed',
      first_started_at: iso(3000),
      last_started_at: iso(30),
      latest_script_result_id: 'sr-1',
    },
  ],
};

const scriptResultRow = (overrides: Record<string, unknown>) => ({
  id: 'sr-1',
  team_id: 'team-e2e',
  script_name: 'dns_lookuptime.py',
  script_type: 'script',
  userinterface_name: 'ui-a',
  host_name: 'host-1',
  device_name: 'device-1',
  success: true,
  execution_time_ms: 42_000,
  started_at: iso(30),
  completed_at: iso(29),
  html_report_r2_path: 'reports/sr-1/report.html',
  html_report_r2_url: 'https://storage.invalid/reports/sr-1/report.html',
  logs_r2_path: 'reports/sr-1/logs.txt',
  logs_r2_url: 'https://storage.invalid/reports/sr-1/logs.txt',
  discard: false,
  error_msg: null,
  metadata: {},
  created_at: iso(30),
  updated_at: iso(29),
  checked: true,
  check_type: 'ai',
  milestone_id: null,
  run_group_id: null,
  labels: [],
  discard_type: 'valid',
  discard_comment: 'Looks legitimate',
  rerun_payload: { type: 'script', scriptName: 'dns_lookuptime.py', hostName: 'host-1', deviceId: 'device1', parameters: '' },
  ...overrides,
});

// Stored snapshot payload (server allowlist) + keys a regression could leak.
const sharePayload = {
  schema_version: 1,
  kind: 'campaign',
  generated_at: iso(10),
  rows_truncated: false,
  title: 'Nightly regression',
  status: 'failed',
  counts: { total: 33, passed: 17, failed: 4, skipped: 12, running: 0, pending: 0, cancelled: 0, unknown: 0 },
  durations: { started_at: iso(70), completed_at: iso(20), execution_time_ms: 3_000_000 },
  safe_labels: ['release'],
  rows: [
    { name: 'child_04', status: 'skipped', execution_time_ms: null, started_at: null, environment: null },
    { name: 'child_20', status: 'passed', execution_time_ms: 1020, started_at: iso(40), environment: 'prod' },
  ],
  // Must never be rendered, even if a server regression leaked it.
  host_name: 'secret-host.internal',
  logs_url: 'https://storage.invalid/private/logs.txt',
};

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

interface MockLog {
  requests: Array<{ method: string; path: string; search: string; headers: Record<string, string>; body: string | null }>;
}

const json = (route: Route, status: number, body: Json) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function installServerMocks(context: BrowserContext, log: MockLog): Promise<void> {
  await context.route(/\/server\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*?(\/server\/)/, '/server/');
    log.requests.push({ method: request.method(), path, search: url.search, headers: request.headers(), body: request.postData() });

    let m: RegExpMatchArray | null;
    if ((m = path.match(/^\/server\/run-management\/summary\/(\w+)\/([^/]+)$/))) {
      const body = summaryFixture(m[1], decodeURIComponent(m[2]), url);
      return json(route, 'error' in body ? 404 : 200, body);
    }
    if (path === '/server/run-groups') return json(route, 200, { items: [groupFixture], total: 1, limit: 200, offset: 0 });
    if (path === '/server/run-groups/g-1/report') return json(route, 200, groupReport);
    if (path === '/server/run-groups/g-1/rerun') {
      // 202: queued one-shot deployments; there is never a live task id at this point.
      return json(route, 202, {
        request_id: 'rr-1',
        run_group_id: 'g-1',
        mode: 'failures',
        status: 'dispatched',
        idempotent_replay: false,
        dispatched: [
          { source_script_result_id: 'sr-g-1', script_result_id: 'sr-g-1', deployment_id: 'dep-1', task_id: null },
        ],
        skipped_manual: [],
        skipped_not_in_mode: ['sr-g-2'],
        skipped: [{ script_result_id: 'sr-g-2', script_name: 'zap_channels', reason: 'not_failed' }],
        error: null,
      });
    }
    const emptyPage = { items: [], total: 0, limit: 200, offset: 0 };
    if (path === '/server/milestones') return json(route, 200, emptyPage);
    if (path === '/server/run-labels') return json(route, 200, emptyPage);
    if (path === '/server/defects') return json(route, 200, emptyPage);
    if (path === '/server/run-share-snapshots') return json(route, 200, { items: [] });
    if (path === '/server/script-results/flaky') return json(route, 200, flakyFixture);
    if (path === '/server/script-results/getAllScriptResults') {
      return json(route, 200, [
        scriptResultRow({}),
        scriptResultRow({
          id: 'sr-manual',
          script_name: 'manual: checkout smoke',
          script_type: 'manual',
          rerun_payload: null,
          html_report_r2_url: null,
          html_report_r2_path: null,
          logs_r2_url: null,
          logs_r2_path: null,
        }),
      ]);
    }
    if (path === '/server/campaign-results/getAllCampaignResults') return json(route, 200, []);
    if ((m = path.match(/^\/server\/share\/run\/([^/]+)$/))) {
      const token = request.headers()['x-share-token'];
      if (decodeURIComponent(m[1]) === SHARE_ID && token === SHARE_TOKEN) {
        return json(route, 200, {
          snapshot: {
            id: SHARE_ID,
            run_kind: 'campaign',
            created_at: iso(10),
            expires_at: '2026-10-08T12:00:00Z',
            payload: sharePayload,
          },
        });
      }
      // Every failure is the same 404 (unknown id, wrong token, expired, revoked).
      return json(route, 404, { error: 'snapshot not found' });
    }
    // Everything else the app shell asks for (hosts, branding, workspaces, sockets…)
    // answers like an unavailable backend, which every provider already tolerates.
    return json(route, 404, { error: 'not mocked in task42 e2e' });
  });
  // Supabase is never needed with auto-sign; refuse it so nothing leaves the machine.
  await context.route(/\/(auth|rest)\/v1\//, (route) => json(route, 401, { error: 'not mocked' }));
}

let log: MockLog;

test.beforeEach(async ({ context }) => {
  log = { requests: [] };
  await installServerMocks(context, log);
});

// ---------------------------------------------------------------------------
// Specs
// ---------------------------------------------------------------------------

test('campaign summary shows exactly 33 = 4 failed / 12 skipped / 17 passed', async ({ page }) => {
  await page.goto(withAuth('/test-results/runs/campaign/ce-33'));
  await expect(page.getByTestId('count-total').first()).toHaveText('33');
  await expect(page.getByTestId('count-failed').first()).toHaveText('4');
  await expect(page.getByTestId('count-skipped').first()).toHaveText('12');
  await expect(page.getByTestId('count-passed').first()).toHaveText('17');
  for (const status of ['running', 'pending', 'cancelled', 'unknown']) {
    await expect(page.getByTestId(`count-${status}`).first()).toHaveText('0');
  }
  // Children are paged independently of the aggregate counts.
  await expect(page.getByTestId('child-row')).toHaveCount(25);
});

// Meaningful only on a build with Supabase configured (VITE_SUPABASE_URL/ANON_KEY set to any
// value — the spec refuses /auth/v1): without it the login gate is off and the reload passes anyway.
test('reload keeps an auto-signed session (BUG-0392)', async ({ page }) => {
  await page.goto(withAuth('/test-results/runs/script/sr-1'));
  await expect(page.getByRole('heading', { name: 'dns_lookuptime.py' })).toBeVisible();
  await expect(page).not.toHaveURL(/auto_signed=/);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'dns_lookuptime.py' })).toBeVisible();
  await expect(page).toHaveURL(/\/test-results\/runs\/script\/sr-1$/);
});

test('summary tabs are URL-keyed', async ({ page }) => {
  await page.goto(withAuth('/test-results/runs/campaign/ce-33'));
  await page.getByRole('tab', { name: 'Statistics' }).click();
  await expect(page).toHaveURL(/[?&]tab=statistics/);
  await page.getByRole('tab', { name: 'Defects' }).click();
  await expect(page).toHaveURL(/[?&]tab=defects/);

  await page.goto(withAuth('/test-results/runs/campaign/ce-33?tab=statistics'));
  await expect(page.getByRole('tab', { name: 'Statistics' })).toHaveAttribute('aria-selected', 'true');
});

test('script summary shows one verdict', async ({ page }) => {
  await page.goto(withAuth('/test-results/runs/script/sr-1'));
  await expect(page.getByRole('heading', { name: 'dns_lookuptime.py' })).toBeVisible();
  await expect(page.getByTestId('count-total').first()).toHaveText('1');
  await expect(page.getByTestId('count-passed').first()).toHaveText('1');
});

test('CSV export escapes spreadsheet formulas', async ({ page }) => {
  await page.goto(withAuth('/test-results/runs/campaign/ce-33'));
  await expect(page.getByTestId('child-row').first()).toBeVisible();
  await page.getByRole('button', { name: 'Export' }).click();
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('menuitem', { name: 'CSV' }).click()]);
  const filePath = await download.path();
  expect(filePath).toBeTruthy();
  const csv = fs.readFileSync(filePath as string, 'utf-8');
  expect(csv).toContain(`"'=HYPERLINK(""http://evil"")"`);
  expect(csv).not.toMatch(/(^|,)"=HYPERLINK/m);
});

test('run group detail shows attempts and dispatches a confirmed rerun once', async ({ page }) => {
  await page.goto(withAuth('/test-results/groups/g-1'));
  await expect(page.getByText('Release 4.2 candidates').first()).toBeVisible();
  await expect(page.getByTestId('count-failed').first()).toHaveText('1');
  await page.getByRole('button', { name: 'Rerun failures' }).click();
  await page.getByRole('button', { name: 'Rerun', exact: true }).click();
  await expect.poll(() => log.requests.filter((r) => r.path.endsWith('/rerun')).length).toBe(1);
  const body = JSON.parse(log.requests.find((r) => r.path.endsWith('/rerun'))?.body ?? '{}');
  expect(body.mode).toBe('failures');
  expect(typeof body.idempotency_key).toBe('string');
  expect(body.idempotency_key.length).toBeGreaterThan(8);
  await expect(page.getByTestId('rerun-result')).toContainText('Dispatched 1 run');
  // A queued deployment has no live task yet: no live link is offered.
  await expect(page.getByRole('link', { name: /live/i })).toHaveCount(0);
});

test('flaky tests list shows sample and window', async ({ page }) => {
  // The old per-insight URL redirects to the Flaky tab of the Quality page.
  await page.goto(withAuth('/test-results/quality/flaky'));
  await expect(page).toHaveURL(/\/test-results\/quality\?(.*&)?tab=flaky/);
  await expect(page.getByTestId('quality-tab-flaky')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('flaky-row')).toHaveCount(1);
  await expect(page.getByText(/48/).first()).toBeVisible();
  await expect(page.getByText(/14 days/).first()).toBeVisible();
});

test('run management: old list URLs open their tab with its help line', async ({ page }) => {
  await page.goto(withAuth('/test-results/labels'));
  await expect(page).toHaveURL(/\/test-results\/run-management\?(.*&)?tab=labels/);
  await expect(page.getByTestId('run-management-tab-labels')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('run-management-help')).toContainText('Free tags you put on runs');
  await page.getByTestId('run-management-tab-milestones').click();
  await expect(page).toHaveURL(/tab=milestones/);
  await expect(page.getByTestId('run-management-help')).toContainText('A dated target');
});

test('TestReports keeps rerun, checked, discard, report and log controls', async ({ page }) => {
  await page.goto(withAuth('/test-results/reports'));
  await expect(page.getByRole('columnheader', { name: 'Rerun' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Report' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Logs' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open Report' }).or(page.getByLabel('Open Report')).first()).toBeVisible();
  await page.getByRole('button', { name: 'Show Analysis' }).or(page.getByLabel('Show Analysis')).first().click();
  await expect(page.getByRole('columnheader', { name: 'Checked' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Discard' })).toBeVisible();
  // New: a summary link per row, and the flaky badge from one quality call.
  await expect(page.getByLabel('Open run summary').first()).toBeVisible();
  await expect(page.getByTestId('flaky-badge').first()).toBeVisible();
  expect(log.requests.filter((r) => r.path === '/server/script-results/flaky').length).toBeLessThanOrEqual(2);
});

test.describe('anonymous share snapshot', () => {
  test('renders only the sanitized snapshot, token sent as a header', async ({ browser }) => {
    const context = await browser.newContext();
    const anonLog: MockLog = { requests: [] };
    await installServerMocks(context, anonLog);
    const page = await context.newPage();
    await page.goto(`/share/run/${SHARE_ID}#t=${SHARE_TOKEN}`);

    await expect(page.getByTestId('share-title')).toHaveText('Nightly regression');
    await expect(page.getByTestId('count-total')).toHaveText('33');
    await expect(page.getByTestId('count-failed')).toHaveText('4');
    await expect(page.getByTestId('count-skipped')).toHaveText('12');
    await expect(page.getByTestId('count-passed')).toHaveText('17');
    await expect(page.getByTestId('share-row')).toHaveCount(2);
    await expect(page.getByText('secret-host.internal')).toHaveCount(0);
    await expect(page.getByText(/storage\.invalid/)).toHaveCount(0);

    const shareCall = anonLog.requests.find((r) => r.path.startsWith('/server/share/run/'));
    expect(shareCall?.headers['x-share-token']).toBe(SHARE_TOKEN);
    expect(shareCall?.headers.authorization).toBeUndefined();
    // The token never travels in a query string, and the fragment is cleared after reading.
    expect(anonLog.requests.some((r) => `${r.path}${r.search}`.includes(SHARE_TOKEN))).toBe(false);
    expect(shareCall?.search ?? '').not.toContain('team_id');
    expect(page.url()).not.toContain(SHARE_TOKEN);
    await context.close();
  });

  test('wrong token shows the invalid/expired state', async ({ browser }) => {
    const context = await browser.newContext();
    await installServerMocks(context, { requests: [] });
    const page = await context.newPage();
    await page.goto(`/share/run/${SHARE_ID}#t=wrong`);
    await expect(page.getByTestId('share-invalid')).toBeVisible();
    await expect(page.getByTestId('share-title')).toHaveCount(0);
    await context.close();
  });
});
