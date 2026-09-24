# BUG-0134 — The auto-sign token was published to the internet in the frontend bundle

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0134                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed — both hosts closed; rotation declined, exposed value still valid      |
| Severity  | High (a live auth-bypass credential was world-readable on a public host)     |
| Area      | `frontend/.env` on both frontend VMs, `docs/agent/validation/TESTING.md`     |
| Fixed in  | — (internal)                                                                |
| Commit    | `1ed2b33db6`                                                                |

---

> **Redacted for publication.** This report is published at `/docs/bugs` and ships in customer bundles. The credential values, the reproduction URL and the current state of the affected hosts have been removed: they are an attack recipe, not an engineering record. The full account is in this repository's history and in the internal task notes.

## Symptom

None. Nothing failed, nothing logged, and every control that was supposed to prevent this
*was* in place. The exposure was only visible by fetching the site as an anonymous visitor.

## What was wrong

Vite inlines the **entire** `import.meta.env` object into the built bundle — every `VITE_*`
variable, whether or not any code reads it. `frontend/.env` on the prod frontend VM contained

```env
VITE_AUTO_SIGN_ENABLED=false
VITE_AUTO_SIGN_TOKEN=<64-hex>
```

so `https://<prod-host>/assets/main-*.js` served, to anyone:

```js
const ba={...,VITE_AUTO_SIGN_ENABLED:"false",VITE_AUTO_SIGN_TOKEN:"<64-hex>"}
```

`AUTO_SIGN_TOKEN` is the credential that bypasses `ProtectedRoute` in the browser and the
`API_KEY` check on the backend, with `AUTO_SIGN_ROLE=admin`.

**`VITE_AUTO_SIGN_ENABLED=false` did not help.** The flag governs whether the *frontend*
auto-activates; it has no bearing on what Vite inlines. The value shipped regardless.

## Why the existing mitigations did not cover it

Every deliberate control was correct and deployed — which is why this went unnoticed:

- `TRUSTED_AUTO_SIGN_HOSTS` is empty (verified in the live bundle as `new Set([])`), so no
  public host silently auto-signs.
- Silent activation is restricted to `192.168.x.0/24` by exact-match regex.
- `getAutoSignHeaderToken()` prefers the URL-supplied token specifically "so the credential
  need not be baked into the public bundle".

All of that governs *code paths*. None of it governs *what the bundler emits*. The protection
was written at the wrong layer for this failure.

## Contributing: a stale assumption

The host was believed to be behind a Cloudflare allow-list. It is not, and has not been —
`curl` from an ordinary laptop with no VPN returns HTTP 200 and the full SPA. TASK-19 had
already recorded that the allow-list claim was stale; the risk assessment for this token had
not been revisited since.

## Fix

Nothing needed the frontend's copy. CI authenticates by passing `?auto_signed=<token>` in the
URL, taken from the `E2E_AUTO_SIGN_TOKEN` GitHub secret (`tests/e2e/playwright/global-setup.js`),
and `tryActivateAutoSign()` prefers that runtime token. The build-time value is the
"last resort ... dev/LAN builds" branch the CI path never reaches.

On the prod frontend VM: back up `.env`, delete the `VITE_AUTO_SIGN_TOKEN` line, rebuild into
`dist_new`, confirm the new bundle is clean, then swap. No downtime, no service restart, CI
unaffected. Verified from the public internet that the served bundle no longer carries it.

`docs/agent/validation/TESTING.md` no longer tells readers to source the token from a frontend
variable, and states that a build-time token belongs to dev/LAN builds only.

**TASK-09 §73 already prescribed this exact action.** It was planned and never executed.

## node3 / QualiAI — the same token, fixed the same way

`virtualpytest.qualiai.io` serves the second environment and answers HTTP 200 to the open
internet. It runs a Vite **dev server**, not a build: `@vite/client` and `/src/main.tsx` are
served, so `GET /src/lib/autoSign.ts` returned transformed source carrying
`"VITE_AUTO_SIGN_TOKEN": "<64-hex>"` — compared byte-for-byte, **the identical credential**.

One token shared across both environments, so closing the main node alone did not retire the
value. Fixed the same way on 2026-09-17: `.env` backed up, the `VITE_AUTO_SIGN_TOKEN` line
removed, `vpt-frontend.service` restarted (the dev server, not `-prod`; Vite came back in 459 ms
on :5073). Verified from the public internet that the served module no longer contains it.

## Full sweep of what that prefix was publishing

With the token gone, every remaining `VITE_*` value served publicly by both hosts was audited.
They are URLs (server, slave server, Grafana, Supabase, Langfuse, mobile app), display strings,
and `VITE_SUPABASE_ANON_KEY` — which is public by design, and is denied on app tables anyway
since the service-role lockdown. **`AUTO_SIGN_TOKEN` was the only true secret in the set.**

## Follow-up

New exposure has stopped on both hosts. Credential rotation, and the related dev-server
exposure of the same class as BUG-0040, are tracked in the internal task notes.

## Lesson

A `VITE_`-prefixed variable is a **publication instruction**, not a configuration choice. Secrets
must not carry that prefix; if the frontend genuinely needs one, it has to arrive at runtime.
Verifying a secret is absent means fetching the built artifact as an anonymous client — reading
the source or the `.env` cannot tell you what the bundler emitted.
