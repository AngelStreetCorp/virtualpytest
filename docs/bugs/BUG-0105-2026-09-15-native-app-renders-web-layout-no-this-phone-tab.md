# BUG-0105 — Inside the APK the app renders its web layout, with no working "This phone" tab

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|------------------------------------------------------------------------------|
| ID        | BUG-0105                                                                     |
| Reported  | 2026-09-15 (Samsung Galaxy S21 Ultra, SM-G998B)                              |
| Status    | Fixed (deployed)                                                             |
| Severity  | High (the phone-agent feature is unreachable inside the app it ships in)      |
| Area      | `features/mobile-app/app/.../MainActivity.kt`, `frontend/src/config/runtimeConfig.ts` |
| Fixed in  | build 9151                                                                   |
| Commit    | this commit (first, partly-wrong attempt in `8caa913cab35` / app 1.0.10)      |

---

## Symptom

On a real Samsung the installed app showed the **web** page
(`features/mobile-app/frontend/MobileAppPage.tsx`) — a "Download the app" card and a table of
phone slots each displaying its own pairing QR — behind a 5-tab bottom nav. It should show
`ThisPhonePage.tsx` via a direct 6th "This phone" tab: the phone running the app is the one
being paired, so it *scans* a QR rather than displaying one.

The same APK was correct on an emulator, so the code path was fine and the failure was
environment-specific.

## Root cause

**The app was displaying the deployment's remote website, not its own bundled assets.**

Confirmed over CDP against the phone's WebView: the page was
`https://virtualpytest.angelstreet.io/mobile-app/this-phone`, not `https://localhost/…`, with
`document.referrer === "https://localhost/"` and a Supabase token in `localStorage` — so the app
had started on its own origin and navigated away during sign-in.

That is the OAuth change in `be5af5b8d2`, working as written but landing in the wrong place.
`redirectTo` is `${window.location.origin}/auth/callback` (`AuthContext.tsx`), i.e.
`https://localhost/auth/callback` inside the app. GoTrue only honours a `redirectTo` that is in
its allow-list and otherwise **silently falls back to the project's Site URL** — the public
website. `shouldOverrideUrlLoading` deliberately lets the deployment's own hosts load in this
WebView (that was the point of `be5af5b8d2`), so the WebView simply stayed there.

On a remote origin Capacitor injects no bridge: `typeof window.Capacitor === "undefined"`, no
`PhoneAgent` plugin. `isNativeApp()` was therefore false and the bundle rendered its web layout —
download card, QR table, five tabs. The app had quietly become a browser, with every native page
unreachable until it was killed and relaunched. The emulator never reproduced it for the dull
reason that it was never signed in, so it never left `https://localhost`.

### The first attempt was wrong, and made it worse

`8caa913cab35` (app 1.0.10) diagnosed this as a *timing race* — the bundle rendering before
Capacitor's injected bridge script defines `window.Capacitor`. That hypothesis was plausible,
consistent with the emulator-vs-phone split, and **wrong**; it was adopted without device
evidence, because the phone was not yet connected.

It also regressed: the `/config.js` interception matched on path alone, so it injected the
phone's prefs — including the new `VITE_IS_NATIVE_APP` flag — into the *remote* page too. The
bundle then believed it was native on an origin with no bridge, so 1.0.10 showed a "This phone"
tab whose page could only render "This page is part of the VirtualPyTest mobile app." That is
the empty tab the reporter saw next, and their instinct that it "should be in More" was correct
for that origin. It also placed the deployment's Supabase URL and anon key into a page we do not
serve.

## Fix

Both in `MainActivity.kt`:

1. **Origin-scope the config injection** — `shouldInterceptRequest` serves the native config only
   for the app's own origin (`bridge.getLocalUrl()`), never a remote host. The remote site now
   gets its own empty `config.js` back, so the bundle correctly behaves as the web build there.
2. **Don't let the chain end on the website** — `shouldOverrideUrlLoading` still loads the OAuth
   provider and Supabase's own endpoints in place, but a landing on the deployment's *website* is
   rewritten onto the app origin with path, query and fragment preserved, so the session lands in
   the browsing context that has the bridge. Fixing this in the app rather than allow-listing
   `https://localhost` in every deployment's GoTrue keeps the "one APK serves any deployment"
   property.

The 1.0.10 work is kept, now that it is correctly scoped: `VITE_IS_NATIVE_APP` is a deterministic
native signal on the app's own origin, and `useIsNativeApp()` re-checks after mount. Neither was
the cause, and neither is load-bearing for this fix.

> Watch the Kotlin string escaping here: an over-escaped `"${'$'}prefix/"` is the *literal*
> `$prefix/`, which silently made `isSupabaseEndpoint()` never match — that would have rewritten
> Supabase's own callback onto the app origin and broken sign-in outright. Caught only because
> the logcat line printed a literal `$host`.

## Verification

On the reporter's Samsung (SM-G998B, WebView 153.0.8010.36), over `adb` + CDP:

- **App origin** `https://localhost/login`: `window.Capacitor` object, `isNativePlatform()` true,
  `PhoneAgent` plugin present, `VITE_IS_NATIVE_APP: "true"`.
- **Remote origin**: `window.__VPT_CONFIG__` is now `{}` — no flag, no bridge — so the nav shows
  **5 tabs** and `/mobile-app/this-phone` resolves to the web page. No more dead "This phone".
- **Bring-home**: a link to `<site>/auth/callback?code=…` navigates to
  `https://localhost/auth/callback?code=…`, query intact (logcat: "carried back to the app
  origin").
- **Supabase exemption**: a link to `<site>/supabase/auth/v1/callback?code=…` loads *remotely* and
  reaches GoTrue, which answers `bad_oauth_callback` for the fabricated code; that redirect is
  then carried home. The whole chain terminates on the app origin, which is the point.

End-to-end sign-in with real credentials was not exercised — the redirect mechanics above were
verified with a synthetic code.
