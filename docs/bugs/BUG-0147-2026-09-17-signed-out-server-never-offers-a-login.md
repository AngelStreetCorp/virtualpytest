# BUG-0144 — A signed-out server showed a padlock and "No servers connected", and never offered a login

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|------------------------------------------------------------------------------|
| ID        | BUG-0144                                                                     |
| Reported  | 2026-09-17                                                                   |
| Status    | Fixed (committed; needs a frontend deploy and an APK rebuild)                 |
| Severity  | High (a fresh mobile-app install cannot sign in at all — no path to the dialog) |
| Area      | `frontend/src/components/common/ServerSelector.tsx`                          |
| Fixed in  | Unreleased                                                                   |
| Commit    | `9dfb6231f5`                                                                      |

---

## Symptom

A fresh install of the mobile app, configured with a server URL, showed the server named
correctly in the picker with a padlock beside it — and underneath, "No servers connected".
Nothing ever asked for a login. Reported as: *"if I am not signed in I should have a pop up to
login, I don't see it."*

## Root cause

The sign-in dialog existed and worked. It was simply unreachable.

`ServerSelector` opened it from exactly one place — `handleChange`, the Select's `onChange`:

```tsx
const handleChange = (serverUrl: string) => {
  if (serverAuthStates[serverUrl] === 'needs-auth') {
    setPendingAuthServer(serverUrl);   // the only caller
    return;
  }
  ...
```

MUI's `Select` fires `onChange` only when the value actually **changes**. So the dialog could be
reached only by *switching to* a signed-out server from a different one. If the signed-out server
was already the selected one, re-picking it from the dropdown emitted no event and nothing
happened.

On a deployment with a single server that is a closed loop with no exit:

1. The one configured server is `needs-auth`.
2. It is therefore already `selectedServer` — there is nothing else to switch from.
3. `ServerManagerProvider` filters `needs-auth` servers out of the authenticated hosts fetch
   (`serverAuthStatesRef.current[serverUrl] !== 'needs-auth'`), so the page renders
   "No servers connected".
4. The padlock's tooltip says "Different login — sign in to use this server", and there is no
   way to act on it.

Every fresh mobile-app install lands in exactly this state, because a new install has no session
for any server. The one case where the prompt matters most was the one case it never fired.

It went unnoticed because the dialog was built for a different story — TASK-18's *multi*-server
switching, where you always arrive by changing servers, and where `onChange` is a fine trigger.

## Fix

Prompt for the server that is already selected, not only for one being switched to: an effect
opens the dialog whenever `selectedServer` is `needs-auth`.

Cancelling has to stay cancellable, so a `dismissedAuthFor` guard remembers the server the user
dismissed and stops the effect reopening it. Picking that server from the dropdown clears the
guard — choosing it *is* asking for the dialog — as does a successful sign-in.

## Not to be confused with

[BUG-0143](BUG-0143-2026-09-17-stream-gate-locks-the-mobile-app-out-of-every-stream.md). Both
surfaced in the same session and both look like "the app cannot reach the server", but they are
unrelated: that one was CORS and cookies on the stream path, this one is a UI trigger that never
fires. This bug was exposed by reinstalling the app (which clears the stored session), not caused
by it — it was reachable any time a session expired on a single-server deployment.
