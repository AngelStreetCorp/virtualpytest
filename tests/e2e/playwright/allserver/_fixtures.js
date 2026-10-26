/**
 * TASK-113 — All-servers E2E fixture.
 *
 * The test plan (§tasks/TASK-113-test-plan.md) names 6 servers (A–F):
 *   A  http://localhost:5109   admin on A, tester on B
 *   B  http://localhost:5110   same Supabase, ID-collision seed
 *   C  http://localhost:5111   same Supabase
 *   D  http://localhost:5112   other Supabase
 *   E  http://localhost:5113   offline mid-list
 *   F  http://localhost:5114   needs-auth
 *
 * The plan's prerequisites (TASK-113-feasibility-report.md §14) list a
 * `spin-up.sh` to start the multi-server topology. Until that lands the
 * specs can still run as stubs by mocking every `/server/*` response via
 * `page.route()`.
 *
 * `mockServer(page, …)` is the single seam for the mocks. The hosts list
 * is per-spec: T01 wants a single server, T02 wants A+B with the same
 * host_name to exercise the collision, T06 wants one offline mid-list.
 */
const SIO_PATH = '/socket.io/';

function buildHosts({ count = 1, collision = false, offlineIndex = -1, withAuthChallenge = false } = {}) {
  const hostNames = ['e2e-a', 'e2e-b', 'e2e-c', 'e2e-d', 'e2e-e', 'e2e-f'];
  return Array.from({ length: count }, (_, i) => ({
    host_name: collision && i < 2 ? 'host-poci' : hostNames[i] || `e2e-${i}`,
    host_url: `https://e2e.invalid/host/${collision && i < 2 ? 'poci' : hostNames[i] || i}`,
    host_port: 6109 + i,
    status: i === offlineIndex ? 'offline' : 'online',
    needs_auth: withAuthChallenge && i === count - 1,
    devices: [
      {
        device_id: collision && i < 2 ? '42' : `device${i + 1}`,
        device_name: `Box ${i + 1}`,
        device_model: 'stb',
        device_capabilities: { av: 'hdmi_stream', remote: 'ir_remote' },
        remote_profiles: ['ir:stb'],
        ir_type: 'stb',
        video_stream_path: `/host/stream/capture${i + 1}`,
        video_capture_path: `/var/www/html/stream/capture${i + 1}`,
      },
    ],
  }));
}

function buildServers({ count = 1, collision = false, offlineIndex = -1, withAuthChallenge = false } = {}) {
  const baseUrls = [
    'http://localhost:5109', 'http://localhost:5110', 'http://localhost:5111',
    'http://localhost:5112', 'http://localhost:5113', 'http://localhost:5114',
  ];
  return Array.from({ length: count }, (_, i) => ({
    server_url: baseUrls[i],
    server_name: `e2e-${String.fromCharCode(97 + i)}`,
    auth_state: withAuthChallenge && i === count - 1 ? 'needs-auth' : 'authenticated',
    hosts: buildHosts({ count: 1, collision, offlineIndex: i === offlineIndex ? 0 : -1 }),
  }));
}

/**
 * Mocks every `/server/*` response that the spec needs. The defaults
 * cover the "happy path" used by most stubs (one server, one host, one
 * device). T02 and T03 pass `count: 2, collision: true` to exercise the
 * ID-collision path; T06 passes `offlineIndex: 1` to put a peer offline.
 */
async function mockServer(page, opts = {}) {
  const { count = 1, collision = false, offlineIndex = -1, withAuthChallenge = false } = opts;
  const servers = buildServers({ count, collision, offlineIndex, withAuthChallenge });
  const calls = { allHosts: 0, authCheck: 0 };

  await page.route(/\/server\/auth\/check/, async (route) => {
    calls.authCheck++;
    return route.fulfill({ json: { success: true, authenticated: true } });
  });

  await page.route(/\/server\/system\/getAllHosts/, async (route) => {
    calls.allHosts++;
    const req = route.request();
    const url = new URL(req.url());
    const serverParam = url.searchParams.get('server_url');
    const match = serverParam
      ? servers.find((s) => s.server_url === serverParam) ?? servers[0]
      : servers[0];
    return route.fulfill({ json: { success: true, hosts: match.hosts, servers } });
  });

  // Generic catch-all so any other /server/* call (per-row actions) doesn't 404.
  await page.route(/\/server\//, async (route) => {
    return route.fulfill({ json: { success: true } });
  });

  // The frontend's WebSocket upgrade for device control / streaming — silence
  // the polling-fallback 404s the real backend would answer.
  await page.route(/\/host\//, async (route) => {
    return route.fulfill({ json: { success: true } });
  });
  await page.route(/\/stream\//, async (route) => {
    return route.fulfill({ json: { success: true } });
  });

  return { calls, servers };
}

module.exports = {
  SIO_PATH,
  buildHosts,
  buildServers,
  mockServer,
};