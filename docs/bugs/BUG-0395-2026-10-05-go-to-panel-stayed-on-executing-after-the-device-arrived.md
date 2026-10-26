# BUG-0395 — Go To panel stayed on "Executing…" after the device had arrived

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0395                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On an Android phone, the navigation editor's Go To panel showed "Executing… Navigating to
library…" long after the phone was already on the library screen, and the Run button did not come
back. It recovered on its own only after about two minutes.

## Root cause

Every non-web navigation is asynchronous: `POST /server/navigation/execute/<tree>` returns an
`execution_id` and the host runs the navigation in a thread, then reports the outcome as an
`execution_update` event (`emit_execution_event` → `/server/system/executionEvent` → `/system`
socket) and keeps it readable at `/server/navigation/execution/<id>/status`.

`executeNavigationAsync` (`frontend/src/utils/navigationExecutionUtils.ts`) used the two in
**series**: it waited up to **120 s** for the socket event and only then started polling the status
endpoint. So any missed event left the panel on "Executing…" for two minutes after the device had
arrived. Ways to miss it:

- the `/system` socket opens only after the POST has returned, so a navigation that finishes
  before the socket has connected and authenticated is never seen;
- a socket the server refuses at handshake does not reconnect and does not raise
  `reconnect_failed`, so the wait just runs out its 120 s;
- the host could not deliver the event (any rejected POST, see BUG-0151 / BUG-0201).

The polling fallback also did not treat `aborted` as an outcome, and kept polling for ten minutes
when the host no longer knew the execution (host restarted).

## Fix

`waitForNavigationOutcome` in `frontend/src/utils/navigationExecutionUtils.ts` races the socket
event and the status poll (every 2 s) from the start: the first terminal status
(`completed` / `error` / `failed` / `aborted`) wins and the other is stopped. A socket failure is
not an outcome; the poll keeps going. Three "execution not found" answers in a row end the wait with
an error, and so does the overall 10-minute limit. The Go To hook (`useNode.executeNavigation`)
already leaves its executing state on any error, so the panel always gets its Run button back.

## Verification

- `cd frontend && ./node_modules/.bin/vitest run src/utils/navigationExecutionUtils.test.ts`: outcome
  from polling with a silent socket, `aborted` is terminal, unknown execution and timeout reject,
  socket event wins when it comes first.
- On the deployed build: Go To on a phone or STB returns to the Run button within about 2 s of the
  host's "navigation completed" log line, also with the socket blocked in DevTools.
