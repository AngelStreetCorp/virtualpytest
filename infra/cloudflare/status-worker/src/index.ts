/**
 * Cloudflare Worker: origin-status monitor + smart 5xx page.
 *
 * Two responsibilities:
 *  1. Cron trigger every minute: ping `${ORIGIN_URL}${HEALTH_PATH}` and store
 *     `{ok, err, lastChecked, lastOk, consecutiveFailures, alertSent}` in KV —
 *     only when that state changes, plus an hourly heartbeat (free-plan KV
 *     allows 1,000 writes/day; a write per tick would be 1,440).
 *     Send a Resend email on N consecutive failures, post a recovery message
 *     on the ok transition. No spam — the alert flag is sticky until ok flips.
 *     A 200 whose JSON reports supabase/redis not "connected" is DEGRADED:
 *     same N-consecutive email + recovery mail, but `ok` stays true so users
 *     keep the site (a frozen Redis VM must not swap in the error page).
 *  2. fetch handler: forward the request to the origin; if the upstream
 *     returns status >= 500 OR `fetch` itself throws (TCP/DNS/timeout),
 *     return a branded HTML page that includes the latest health status
 *     ("Last healthy 4m ago") plus the CF-Ray request id and a retry button,
 *     replacing Cloudflare's generic "Connection timed out / Error 522".
 *
 * Why both: the frontend bundle and the API are both served by the origin
 * (proxmox VM → nginx → Flask). When the origin is down, both are down, so
 * the Worker is the only layer that can render something useful. Without it
 * users see Cloudflare's bare error page; with it they see a branded page
 * that says "we're aware, retry" plus an email alert fires for the operator.
 *
 * Email via Resend (HTTP API) — Workers cannot open TCP sockets, so SMTP is
 * not an option here. Resend's free tier (100/day, 3k/month) is enough for
 * one DOWN + one RECOVERED mail per incident. Sending domain
 * (virtualpytest.com) must be verified in the Resend dashboard or emails 403.
 *
 * Pair with the static CF Custom Pages 5XX HTML in
 * `infra/cloudflare/custom-pages/5xx-error.html` — that is the fallback when
 * this Worker is not bound to the route.
 *
 * Deploy (see infra/cloudflare/status-worker/README.md):
 *   wrangler login
 *   wrangler kv:namespace create STATUS_KV   # copy id into wrangler.toml
 *   wrangler secret put RESEND_API_KEY        # paste re_... from .env
 *   wrangler deploy
 *   # then in CF dashboard: Workers & Pages → vpt-status-worker → Triggers →
 *   #   Add route: virtualtest.angelstreet.io/*  zone: angelstreet.io
 */

export interface Env {
  STATUS_KV: KVNamespace;
  RESEND_API_KEY?: string;
  RESEND_FROM_ADDRESS: string;   // noreply@virtualpytest.com  (verified domain)
  RESEND_FROM_NAME: string;      // VirtualPyTest
  RESEND_TO_ADDRESS: string;     // comma-separated for multiple recipients
  ORIGIN_URL: string;            // https://virtualtest.angelstreet.io
  HEALTH_PATH: string;           // /server/health
  ALERT_AFTER_FAILURES: string;  // consecutive cron failures before email fires
}

interface OriginStatus {
  ok: boolean;
  err: string | null;
  lastChecked: number;
  lastOk: number | null;
  consecutiveFailures: number;
  alertSent: boolean;
  // Origin answered 200 but a dependency it reports is not "connected"
  // (e.g. "redis=disconnected" while the storage VM is frozen). Email only:
  // `ok` stays true so the fetch handler keeps serving the site.
  degraded: string | null;
  degradedFailures: number;
  degradedAlertSent: boolean;
}

const KV_KEY = "origin-status";
const DEFAULT_EMPTY: OriginStatus = {
  ok: false,
  err: null,
  lastChecked: 0,
  lastOk: null,
  consecutiveFailures: 0,
  alertSent: false,
  degraded: null,
  degradedFailures: 0,
  degradedAlertSent: false,
};

// Free-plan KV allows 1,000 writes/day; a write per cron tick is 1,440. The
// cron only writes when the state changes, plus this heartbeat so the record
// (24 h TTL) never expires and lastChecked stays roughly fresh.
const HEARTBEAT_MS = 60 * 60 * 1000;

// A KV error (e.g. daily read quota hit) must never take the site down:
// fall back to the "never probed" default, which the fetch handler ignores.
async function readStatus(kv: KVNamespace): Promise<OriginStatus> {
  try {
    const raw = await kv.get<OriginStatus>(KV_KEY, "json");
    return raw ? { ...DEFAULT_EMPTY, ...raw } : DEFAULT_EMPTY;
  } catch (e) {
    console.error("kv read failed", (e as Error).message);
    return DEFAULT_EMPTY;
  }
}

function fmtAgo(epochMs: number | null): string {
  if (!epochMs) return "never recorded";
  const sec = Math.max(0, Math.round((Date.now() - epochMs) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  return `${hr}h ago`;
}

// Static branded error page (kept in sync with
// infra/cloudflare/custom-pages/5xx-error.html). Embedded as a string
// constant so the Worker renders the same HTML the operator pastes into
// CF dashboard → Custom Pages → 500_errors. The renderErrorPage function
// returns this verbatim with only the trailing reference line swapped.
const CUSTOM_ERROR_PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>VirtualPyTest — Service temporarily unavailable</title>
<style>
  :root { color-scheme: dark light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh;
    background: #1a1a1a; color: #f0f0f0;
    font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
  }
  @media (prefers-color-scheme: light) {
    body { background: #f2f0ec; color: #141414; }
    .card { background: #fff; border-color: #d9d4cc; }
    .meta, .muted { color: #4a4a4a; }
  }
  .card {
    max-width: 560px; width: 100%;
    background: #242424; border: 1px solid #383838; border-radius: 12px;
    padding: 32px;
  }
  .badge {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    background: #d4a57426; color: #d4a574;
    font-size: 12px; font-weight: 600; letter-spacing: .04em;
  }
  h1 { margin: 16px 0 8px; font-size: 24px; font-weight: 600; }
  p  { margin: 0 0 16px; color: #9a9a9a; }
  .muted { color: #9a9a9a; font-size: 14px; }
  button {
    appearance: none; border: 0; cursor: pointer;
    background: #d4a574; color: #1a1611;
    padding: 10px 20px; border-radius: 6px; font-weight: 600;
    font-size: 14px;
  }
  button:hover { background: #c49464; }
  code { font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
</head>
<body>
  <main class="card">
    <span class="badge">VirtualPyTest</span>
    <h1>Service temporarily unavailable</h1>
    <p>The backend on the Hetzner server (proxmox VM → nginx → Flask) is not reachable from Cloudflare. This page replaces Cloudflare's generic "Connection timed out" so you know it's our end, not yours.</p>
    <p class="muted">Most outages resolve in under a minute (server reboot, deploy, OOM). If you reached this page from a saved URL, just retry.</p>
    <button onclick="location.reload()">Retry</button>
    <p class="muted" style="margin-top:24px">
      Reference: <code>virtualpytest.angelstreet.io</code> · Cloudflare error 522 / 524
    </p>
  </main>
</body>
</html>`;

function renderErrorPage(status: OriginStatus, upstreamStatus: number, requestId: string): string {
  // Return the static custom-page HTML (kept in sync with
  // infra/cloudflare/custom-pages/5xx-error.html) verbatim. The only
  // substitution is the trailing reference line, which gets the cf-ray
  // request id (for grep in CF Events) and the upstream status code
  // appended when present.
  const lastHealthyLine = status.lastOk
    ? `<p class="muted" style="margin-top:8px">Last seen healthy: ${escapeHtml(fmtAgo(status.lastOk))} ago</p>`
    : "";
  const metaLine =
    `<p class="muted" style="margin-top:24px">` +
    `Reference: <code>virtualpytest.angelstreet.io</code> · ` +
    (requestId !== "n/a" ? `request <code>${escapeHtml(requestId)}</code> · ` : "") +
    `upstream HTTP ${upstreamStatus}` +
    `</p>`;
  return CUSTOM_ERROR_PAGE
    .replace(
      '<p class="muted" style="margin-top:24px">\n      Reference: <code>virtualpytest.angelstreet.io</code> · Cloudflare error 522 / 524\n    </p>',
      lastHealthyLine + metaLine,
    );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderAlertEmail(opts: {
  originState: OriginStatus;
  consecutiveFailures: number;
  downForSeconds: number;
  err: string | null;
  threshold: number;
}): { subject: string; html: string; text: string } {
  const { originState, consecutiveFailures, downForSeconds, err, threshold } = opts;
  const subject = `[VirtualPyTest] origin DOWN — ${consecutiveFailures} consecutive failures`;
  const lastOk = originState.lastOk ? new Date(originState.lastOk).toISOString() : "never";
  const downFor = downForSeconds > 0 ? `${downForSeconds}s ago` : "—";
  const html = `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;color:#1a1a1a;max-width:600px">
      <h2 style="color:#b91c1c;margin:0 0 8px">🚨 virtualtest.angelstreet.io origin is DOWN</h2>
      <p style="margin:0 0 16px;color:#4a4a4a">
        <strong>${consecutiveFailures}</strong> consecutive failures
        (threshold ${threshold}). Last error:
        <code style="background:#f5f5f5;padding:2px 6px;border-radius:4px">${escapeHtml(err ?? "unknown")}</code>
      </p>
      <table style="border-collapse:collapse;font-size:14px">
        <tr><td style="padding:4px 12px 4px 0;color:#6e6e6e">Origin URL</td><td>https://virtualtest.angelstreet.io</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#6e6e6e">Last healthy</td><td>${escapeHtml(lastOk)}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#6e6e6e">Down for</td><td>${escapeHtml(downFor)}</td></tr>
      </table>
      <p style="margin:16px 0 0;color:#6e6e6e;font-size:12px">
        Sent by <code>vpt-status-worker</code> · one mail per incident (sticky until recovery).
      </p>
    </div>`;
  const text =
    `🚨 virtualtest.angelstreet.io origin is DOWN\n` +
    `${consecutiveFailures} consecutive failures (threshold ${threshold}).\n` +
    `Last error: ${err ?? "unknown"}\n` +
    `Last healthy: ${lastOk}\n` +
    `Down for: ${downFor}\n` +
    `\nSent by vpt-status-worker.`;
  return { subject, html, text };
}

function renderRecoveryEmail(downForSeconds: number): { subject: string; html: string; text: string } {
  const subject = `[VirtualPyTest] origin RECOVERED after ${downForSeconds}s`;
  const html = `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;color:#1a1a1a;max-width:600px">
      <h2 style="color:#15803d;margin:0 0 8px">✅ virtualtest.angelstreet.io origin RECOVERED</h2>
      <p style="margin:0;color:#4a4a4a">The proxmox VM is responding again after <strong>${downForSeconds}s</strong> down.</p>
      <p style="margin:16px 0 0;color:#6e6e6e;font-size:12px">Sent by <code>vpt-status-worker</code>.</p>
    </div>`;
  const text =
    `✅ virtualtest.angelstreet.io origin RECOVERED after ${downForSeconds}s down.\n` +
    `\nSent by vpt-status-worker.`;
  return { subject, html, text };
}

// /server/health fields that must read "connected" (backend_server/src/routes/server_core_routes.py).
const DEPENDENCY_FIELDS = ["supabase", "redis"];

function renderDegradedEmail(degraded: string | null, failures: number): { subject: string; html: string; text: string } {
  const what = degraded ?? "recovered";
  const subject = degraded
    ? `[VirtualPyTest] DEGRADED — ${degraded}`
    : `[VirtualPyTest] dependencies RECOVERED`;
  const line = degraded
    ? `/server/health answers but reports <code>${escapeHtml(what)}</code> for ${failures} consecutive probes. The site stays up; queued scripts and storage on that dependency fail.`
    : `/server/health reports every dependency connected again.`;
  const html = `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;color:#1a1a1a;max-width:600px">
      <h2 style="color:${degraded ? "#b45309" : "#15803d"};margin:0 0 8px">${degraded ? "⚠️ virtualpytest.angelstreet.io DEGRADED" : "✅ dependencies RECOVERED"}</h2>
      <p style="margin:0;color:#4a4a4a">${line}</p>
      <p style="margin:16px 0 0;color:#6e6e6e;font-size:12px">Sent by <code>vpt-status-worker</code>.</p>
    </div>`;
  const text = `${subject}\n${line.replace(/<[^>]+>/g, "")}\n\nSent by vpt-status-worker.`;
  return { subject, html, text };
}

async function sendEmail(env: Env, subject: string, html: string, text: string): Promise<void> {
  if (!env.RESEND_API_KEY) return;
  const to = env.RESEND_TO_ADDRESS.split(",").map(s => s.trim()).filter(Boolean);
  if (to.length === 0) return;
  try {
    await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: `${env.RESEND_FROM_NAME} <${env.RESEND_FROM_ADDRESS}>`,
        to,
        subject,
        html,
        text,
      }),
    });
  } catch (e) {
    // best-effort: do not throw from inside waitUntil
    console.error("resend send failed", (e as Error).message);
  }
}

export default {
  // ── fetch: smart 5xx page ────────────────────────────────────────────────
  async fetch(req: Request, env: Env): Promise<Response> {
    // Owner-device mTLS check: what Cloudflare saw of this client's certificate.
    // Served by the Worker itself, so it answers even when the WAF would block.
    if (new URL(req.url).pathname === "/__mtls") {
      const cf = (req.cf ?? {}) as Record<string, unknown>;
      const auth = (cf.tlsClientAuth ?? {}) as Record<string, string>;
      return Response.json({
        certPresented: auth.certPresented === "1",
        certVerified: auth.certVerified,
        certRevoked: auth.certRevoked === "1",
        certSubject: auth.certSubjectDN || null,
        clientIp: req.headers.get("cf-connecting-ip"),
        country: cf.country ?? null,
        httpProtocol: cf.httpProtocol ?? null,
        tlsVersion: cf.tlsVersion ?? null,
      }, { headers: { "cache-control": "no-store" } });
    }
    // Build an origin-bound URL so we never feed the request back to ourselves
    // (the route is bound to virtualtest.angelstreet.io — a literal fetch(req)
    // can re-enter the Worker when called via the workers.dev preview URL or
    // when CF re-routes the subrequest through the same route).
    const incoming = new URL(req.url);
    const originUrl = new URL(env.ORIGIN_URL);
    const target = new URL(incoming.pathname + incoming.search, originUrl);

    // Strip the incoming Host header — let CF set Host to the target so the
    // tunnel / nginx routes by the right vhost. Re-adding Host to a Workers
    // fetch would echo the workers.dev preview hostname, which the tunnel
    // can't route and which nginx then serves the wrong vhost for.
    const fwdHeaders = new Headers(req.headers);
    fwdHeaders.delete("Host");

    // The cron marks origin ok=false in KV when /server/health fails. If the
    // user's request and the cron agree origin is sick, render the branded
    // page even if the upstream returned a non-5xx (e.g. nginx 404 because
    // Flask is down). cronProbeChecked = the cron has actually run at least
    // once (lastChecked > 0); without that, ok=false is the empty default.
    const kvStatus = await readStatus(env.STATUS_KV);
    const cronProbeChecked = kvStatus.lastChecked > 0;
    const cronKnowsOriginDown = cronProbeChecked && !kvStatus.ok;

    let res: Response;
    let fetchErr: Error | null = null;
    try {
      res = await fetch(target.toString(), {
        method: req.method,
        headers: fwdHeaders,
        body: req.method === "GET" || req.method === "HEAD" ? null : req.body,
        redirect: "manual",
        cf: { cacheTtl: 0, cacheEverything: false },
      });
    } catch (e) {
      fetchErr = e as Error;
      res = new Response("", { status: 522 });
    }

    if (fetchErr || res.status >= 500 || cronKnowsOriginDown) {
      const requestId = req.headers.get("cf-ray") ?? "n/a";
      const upstreamStatus = fetchErr ? 522 : res.status;
      return new Response(renderErrorPage(kvStatus, upstreamStatus, requestId), {
        status: upstreamStatus,
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }
    return res;
  },

  // ── scheduled: minute-by-minute health probe ────────────────────────────
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const url = `${env.ORIGIN_URL}${env.HEALTH_PATH}`;
    const startedAt = Date.now();
    let ok = false;
    let err: string | null = null;
    let degraded: string | null = null;
    try {
      // /server/health checks Supabase + Redis and can take 10-20 s while the app is
      // otherwise fine (BUG-0468 follow-up); 25 s separates slow from down.
      const r = await fetch(url, {
        signal: AbortSignal.timeout(25000),
        headers: { "user-agent": "vpt-cf-status-worker/1.0 (+https://virtualpytest.angelstreet.io)" },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      ok = r.ok;
      if (ok) {
        const body = await r.json<Record<string, unknown>>().catch(() => null);
        if (body) {
          const bad = DEPENDENCY_FIELDS
            .filter(k => k in body && body[k] !== "connected")
            .map(k => `${k}=${String(body[k])}`);
          degraded = bad.length ? bad.join(", ") : null;
        }
      }
      if (!ok) {
        err = `HTTP ${r.status}`;
        // Who refused: a Cloudflare block carries cf-mitigated / a CF error page,
        // nginx answers with its own server header and body.
        const html = await r.text();
        const body = [
          html.match(/<title>([^<]*)/i)?.[1],
          html.match(/Error code:?\s*<[^>]*>?\s*(\d+)|error code: (\d+)|Error (\d{4})/i)?.slice(1).find(Boolean),
        ].filter(Boolean).join(" | ");
        console.log("probe refused", r.status, r.headers.get("server"), r.headers.get("cf-mitigated"), body);
      }
    } catch (e) {
      err = (e as Error).message || String(e);
    }
    void startedAt; // referenced for clarity; elapsed not currently used in the alert payload

    const prev = await readStatus(env.STATUS_KV);
    const consecutiveFailures = ok ? 0 : prev.consecutiveFailures + 1;
    // KV is no longer written on every healthy tick, so prev.lastOk can be up to
    // HEARTBEAT_MS old. A stored ok=true means every probe since then was ok, so
    // on the first failure the last good probe was the previous tick.
    const lastOk = ok ? Date.now() : prev.ok ? Date.now() - 60_000 : prev.lastOk;
    let alertSent = prev.alertSent;
    const threshold = Number(env.ALERT_AFTER_FAILURES || "2");

    // Alert on N-th consecutive failure (sticky until ok).
    if (!ok && consecutiveFailures >= threshold && !alertSent && env.RESEND_API_KEY) {
      const downForSeconds = lastOk ? Math.round((Date.now() - lastOk) / 1000) : 0;
      const m = renderAlertEmail({
        originState: { ...prev, lastOk },
        consecutiveFailures,
        downForSeconds,
        err,
        threshold,
      });
      ctx.waitUntil(sendEmail(env, m.subject, m.html, m.text));
      alertSent = true;
    }
    // Recovery message: one ping, then flip the alert flag back so we can fire again next time.
    if (ok && alertSent && env.RESEND_API_KEY) {
      const downForSeconds = prev.lastOk ? Math.round((Date.now() - prev.lastOk) / 1000) : 0;
      const m = renderRecoveryEmail(downForSeconds);
      ctx.waitUntil(sendEmail(env, m.subject, m.html, m.text));
      alertSent = false;
    }

    if (!ok) console.log("probe failed", url, err);

    // Degraded: same N-consecutive / sticky-until-clear rule as the DOWN alert.
    // A down origin says nothing about its dependencies, so the count holds.
    const degradedFailures = !ok ? prev.degradedFailures : degraded ? prev.degradedFailures + 1 : 0;
    let degradedAlertSent = prev.degradedAlertSent;
    if (ok && degraded && degradedFailures >= threshold && !degradedAlertSent && env.RESEND_API_KEY) {
      const m = renderDegradedEmail(degraded, degradedFailures);
      ctx.waitUntil(sendEmail(env, m.subject, m.html, m.text));
      degradedAlertSent = true;
    }
    if (ok && !degraded && degradedAlertSent && env.RESEND_API_KEY) {
      const m = renderDegradedEmail(null, 0);
      ctx.waitUntil(sendEmail(env, m.subject, m.html, m.text));
      degradedAlertSent = false;
    }
    if (degraded) console.log("probe degraded", url, degraded);
    const storedDegraded = ok ? degraded : prev.degraded;

    // Write only on a state change: up/down flip, a new error, alert flag flip,
    // or a failure count still climbing towards the alert threshold. Past the
    // threshold the stored count stops at `threshold` — it only feeds the alert email.
    const changed =
      ok !== prev.ok ||
      err !== prev.err ||
      alertSent !== prev.alertSent ||
      (!ok && consecutiveFailures <= threshold) ||
      storedDegraded !== prev.degraded ||
      degradedAlertSent !== prev.degradedAlertSent ||
      (!!degraded && degradedFailures <= threshold);
    if (!changed && Date.now() - prev.lastChecked < HEARTBEAT_MS) return;

    const next: OriginStatus = {
      ok,
      err,
      lastChecked: Date.now(),
      lastOk,
      consecutiveFailures: Math.min(consecutiveFailures, threshold),
      alertSent,
      degraded: storedDegraded,
      degradedFailures: Math.min(degradedFailures, threshold),
      degradedAlertSent,
    };
    try {
      await env.STATUS_KV.put(KV_KEY, JSON.stringify(next), { expirationTtl: 86400 });
    } catch (e) {
      console.error("kv write failed", (e as Error).message);
    }
  },
};