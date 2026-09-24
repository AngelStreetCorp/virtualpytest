# BUG-0145 — Typing the server URL left the app in open mode, with no real login and no JWT

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                    |
|-----------|--------------------------------------------------------------------------|
| ID        | BUG-0145                                                                 |
| Reported  | 2026-09-17                                                               |
| Status    | Fixed (committed; needs an APK rebuild)                                  |
| Severity  | High (app runs unauthenticated: `ProtectedRoute` inert, API calls carry no JWT) |
| Area      | `features/mobile-app/frontend/ThisPhonePage.tsx`                         |
| Fixed in  | Unreleased                                                               |
| Commit    | `bb9efab1de`                                                                 |

---

## Symptom

Configuring a phone with **This phone → Enter server URL** instead of scanning the QR appeared
to work — the server was named correctly in the picker. But the app never showed the normal
`LoginPage`. Reported as: *"why do I see a different login prompt now."*

The prompt that did appear was `ServerAuthDialog` — the per-server one from TASK-18, which by its
own docstring is "deliberately minimal — email + password only. Sign-up, password reset and OAuth
stay on the full LoginPage". So the user was handed a cut-down dialog with no way to sign up,
reset a password, or use OAuth.

## Root cause

Two paths configure the app, and only one of them was complete.

| Path | Native call | Fetches `runtime-config.json`? |
|---|---|---|
| Scan QR | `applyConfig` → `PayloadApplier` | **yes** |
| Enter server URL | `setServer` | **no** |

`setServer` stores only what it is handed:

```kotlin
val values = mutableMapOf<String, String?>(PhoneAgentPrefs.KEY_SERVER_URL to serverUrl)
call.getString("supabaseUrl")?.let { values[PhoneAgentPrefs.KEY_SUPABASE_URL] = it }
```

…and the dialog has only a URL to hand it. So `supabase_url` and `supabase_anon_key` stayed
empty. `MainActivity` builds `/config.js` from those prefs, and `lib/supabase.ts` computes:

```ts
export const isAuthEnabled = !!(getSupabaseUrl() && getSupabaseAnonKey());
```

With both empty, `isAuthEnabled` is **false** — and `ProtectedRoute`'s first line is:

```tsx
if (!isAuthEnabled) {
  return children ? <>{children}</> : <Outlet />;   // every route open
}
```

So the app rendered its whole UI with no session and never routed to `/login`. The only component
that still noticed was the independent per-server probe (`serverIdentity.ts`), which marks the
server `needs-auth` — hence the padlock, and hence the minimal dialog.

**The invisible half is the more serious one.** `lib/supabase.ts` says exactly what open mode
means, and logs it as a security error:

> `[SECURITY][OPEN_MODE] Supabase authentication is DISABLED … Frontend -> Server API requests
> will be sent without JWT Authorization headers.`

A phone configured this way is not just missing a login screen; it is an unauthenticated client.

The QR path was the one anybody tested, because it is the documented flow. The URL entry exists
for "a camera that will not read the code" and quietly did four-fifths of the job.

## Fix

Route the typed URL through `applyConfig`, the same native call the scanner uses. `PayloadApplier`
already accepts a bare URL, derives the origin, and fetches `<origin>/runtime-config.json` for the
Supabase fields. Its plugin method resolves only after that fetch completes, so the status it
returns already says whether the app ended up configured — no second `getStatus` needed.

## Not to be confused with

[BUG-0144](BUG-0144-2026-09-17-signed-out-server-never-offers-a-login.md), fixed an hour earlier
in the same session. That one is why *no* prompt appeared at all; this one is why the prompt that
did appear was the wrong one. Both had to be fixed before a typed-URL install could reach a
normal login.
