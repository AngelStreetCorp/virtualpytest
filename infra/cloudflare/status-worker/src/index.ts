/**
 * Cloudflare Worker: origin-status monitor (cron only).
 *
 * Single responsibility: cron trigger every minute, ping
 * `${ORIGIN_URL}${HEALTH_PATH}`, store
 * `{ok, err, lastChecked, lastOk, consecutiveFailures, alertSent}` in KV —
 * only when that state changes, plus an hourly heartbeat (free-plan KV
 * allows 1,000 writes/day; a write per tick would be 1,440).
 *
 * Sends a Resend email on N consecutive failures, posts a recovery message
 * on the ok transition. No spam — the alert flag is sticky until ok flips.
 * A 200 whose JSON reports supabase/redis not "connected" is DEGRADED:
 * same N-consecutive email + recovery mail, but `ok` stays true so users
 * keep the site (a frozen Redis VM must not swap in the error page).
 *
 * There is no `fetch` handler on purpose: this Worker is NOT bound to a
 * route. Visitor traffic flows browser → CF edge → tunnel → proxmox nginx
 * → backend, and proxying it through the Worker would burn the 100,000
 * requests/day limit on the Free plan (see BUG-0570). The branded
 * "Service temporarily unavailable" page is provided separately via the
 * CF dashboard's Custom Pages → 500_errors, sourced from
 * `infra/cloudflare/custom-pages/5xx-error.html`.
 *
 * Email via Resend (HTTP API) — Workers cannot open TCP sockets, so SMTP is
 * not an option here. Resend's free tier (100/day, 3k/month) is enough for
 * one DOWN + one RECOVERED mail per incident. Sending domain
 * (virtualpytest.com) must be verified in the Resend dashboard or emails 403.
 *
 * Deploy (see infra/cloudflare/status-worker/README.md):
 *   wrangler login
 *   wrangler kv:namespace create STATUS_KV   # copy id into wrangler.toml
 *   wrangler secret put RESEND_API_KEY        # paste re_... from .env
 *   wrangler deploy
 *   # Do NOT bind a route on this Worker in the CF dashboard — see above.
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
  // ── scheduled: minute-by-minute health probe ────────────────────────────
  // No `fetch` handler: this Worker is intentionally not bound to a route.
  // See BUG-0570 — binding a route would burn the 100k/day Free-plan limit
  // by proxying every visitor request through the Worker.
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