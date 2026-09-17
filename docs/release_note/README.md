# 🚀 Release Notes

What shipped, newest first — the full story of a fix lives in its [bug report](../bugs/README.md).

## When to update this file

- **Not on every commit.** Skip `chore` / `docs` / `refactor` / internal-only changes.
- Finished a **user-facing feature**? Add one line under **`## Unreleased` → ✨ Features**.
- Finished a **user-facing fix**? Log it in the [bug tracker](../bugs/README.md) first, then add
  one line under **`## Unreleased` → 🐛 Bug fixes** with its `[BUG-XXXX]` link. Features and fixes
  stay in separate lists — never mix them.
- **Cutting a build?** Rename `## Unreleased` → `## build <NNNN> — <YYYY-MM-DD>`, start a fresh
  empty `## Unreleased` above it, and set the fixed-in build on those bugs in the tracker.
- **Every build section ends with `### 🚚 Upgrade`**: what an operator has to do to run this
  build — database migrations to
  apply, new `.env` keys, which services restart (and which the deploy script does *not*
  restart), proxy / Grafana files to hand-deploy, and the exact deploy commands with their
  parameters. That block is generated, not remembered:
  `python3 scripts/release/upgrade_notes.py [<previous-tag>]` reads the git diff since the last
  build and prints both headings; paste them, then write the plain-words paragraph. Keep the
  Unreleased section's copy current when a change adds a migration or a new key, so the block
  is never written from memory at cut time.
- **Feature needs a DB migration?** The entry **must** flag it by ending with
  ` · 🗄 DB migration \`<file>\`` — the dated file in `setup/db/migrations/` (or the feature's own
  `db/` dir, e.g. `features/cicd/db/`). `update_core.sh` deploys code but does **not** apply
  migrations, so shipping the code without running the migration first breaks the feature; the flag
  is the reminder to apply it on the DB before/with the deploy. When several entries share one
  migration, flag only the entry that introduces it.
  **The marker is per-database, not per-release.** A migration run on our own deployment is *not*
  done — it must be applied to every database the release reaches, including each customer install
  and any second environment. Treat a flagged entry as outstanding until every one of them has had
  it run.

Format each line as `- **Short title** — short clause · [BUG-XXXX](../bugs/BUG-XXXX-<date>-<slug>.md) · \`shortHash\` · 🗄 DB migration \`<file>\``
— a bug fix links to **its own bug file**, not the index. Drop the `[BUG-XXXX]` link for features
(which have no bug entry), and the `🗄 DB migration` marker for anything that doesn't touch the
schema. Entries that exist only on this branch (`feat/demo`) sit at the end of each list.

---

## Unreleased

### ✨ Features

### 🐛 Bug fixes

---

## build 9151 — 2026-09-17

### ✨ Features
- **New optional feature `mobile-app` — a phone as a test device, plus a native mobile app** — scan a QR code from Settings → Mobile app & phones and a paired phone streams its screen to a host (existing HLS/capture pipeline, device model `phone_agent`) and accepts taps/swipes/keys/text through an AccessibilityService; the same APK opens the platform itself, in the phone layout the web UI already has. See [Mobile App](../features/mobile-app.md) and, for slots and pairing, [MOBILE_APP.md](../technical/MOBILE_APP.md) ⚠️ **Adding a phone slot to a host `.env` also requires `sudo ./setup/local/linux/backend_host/setup_ram_hot_storage.sh`** — nothing calls it automatically, and a capture folder with no `/hot` leaves the archiver in SD mode, which silently truncates that device's report videos to the live window (~30 s). Per slot, not per pairing
- **Every customer delivery now comes with a delivery note** — a bundle build writes `DELIVERY-<archive>.md` next to the `.tar.gz`: the versions it carries, the features that customer gets, the changelog since the pin they are running, and the rollout checklist (migrations, new `.env` keys, which services restart by hand). Those three facts existed before but in three places — the changelog in the platform repo at a tag, the feature list inside the 35 MB archive, and the checklist only as terminal output nobody saved — so a past delivery could not be looked up from the overlay repo or its GitHub release, and nothing handed to the operator said a migration had to be applied before restarting. The note is committed to the overlay under `deliveries/` and used as the GitHub Release body. `scripts/release/delivery_note.sh` also runs standalone, to backfill a past delivery
- **Two verifications that watch an element instead of a picture** — `waitForElementToChange` and `waitForElementToStopChanging` watch one element's label and pass when it moves, or when it holds still. With the default `SeekBar` that reads a player's own position, so "is this playing?" is answered directly and in about a second, where a motion check samples the captured stream for up to a minute and cannot tell *not drawing yet* from *stuck*. Nothing about them is video-specific — they watch whichever element `search_term` selects, which is also how they answer "has this screen settled?" — and both the adb controller and a paired phone's answer them through the same implementation, so a tree using them behaves identically on either
- **The stream modal says "running" like the preview card does** — the device card shows a blue `running` chip while a script drives the device, but opening that device's stream dropped it: the modal header carried only the lock icon, so the one state where it matters whether you touch the device was invisible on the page you touch it from. The same chip (stuck → `error`, script → `running`, else online/offline) is now one shared component used by both
- **A phone can start an app clean instead of resuming it** — `close_app` on a phone does not close anything: unrooted Android has no force-stop API, so the agent presses HOME and the app carries on exactly as it was. The familiar close-then-launch pair therefore means "go to the launcher, then put the app back where it was" — leave YouTube on a video and that is where you return, not the feed, which is enough to fail a first step that verifies the feed's bottom nav. `launch_app` now takes `reset: true` (offered as **Restart App**), which clears the app's task on launch for the same end state as a force-stop and no permission. Off by default in both directions: a tree that relies on resuming is unaffected, and an agent older than 1.0.39 ignores the flag. It replaces `close_app` rather than following it. Verified on a Galaxy S21 from a full-screen player: a plain launch stays on the player, `reset` reaches the feed in under 5s · APK 1.0.39
- **A run reaches the phone in seconds, not minutes** — before a single command was sent, `goto` spent 101 seconds asking "am I already at the target?" and "am I at home?", both honouring node timeouts written for *waiting* for a screen (60s + 20s + 20s) rather than *checking* for one. Those probes are capped at 5s, so the first command lands at 26s instead of 111s; and the phone's "under test" badge now comes up at ~4s, while the controllers are still being built, because the controller asks the phone its own name instead of reading the host's cached slot
- **A report names the phone, not the slot it sits in** — a paired phone's runs were recorded against the `.env` slot label ("Phone slot 1") rather than the device in it ("samsung SM-G998B"). vpt-host renames the device when a phone pairs, but a script runs in its own process and builds its devices straight from `.env`, so it never saw that. A remote controller can now report the connected hardware's own name and the device takes it; Test Reports also carries the full target as a tooltip, since the column is narrow enough to cut it
- **Every UI dump a run takes is in its report** — the accessibility tree behind each dump is uploaded beside `execution.txt` and linked from the summary as **🔍 UI dumps** (and from the verification review's Log Sources), carrying only the attributes a selector can match on and dropping unlabelled layout nodes — 39 useful of 111 on a real YouTube screen. Each entry is labelled with what the caller was doing (`click_element(' seconds|!Sponsored')`), and the outcome is appended to it (`-> clicked 'Spaceship…'`), so a run that passed while tapping the wrong card is visible from the report alone — which is how the sponsored-card bug below was found. Polls are included, because "we looked eight times and it never changed" answers most questions about a stuck screen; an identical tree collapses to a one-line back-reference and the file keeps the most recent 500 entries. Works the same on adb devices, not just paired phones
- **Home dashboard** — one Grafana page for the checks worth watching: a Sanity Check table over a fixed script list, then one collapsed row per script (Ookla, Superping, DNS, Facebook, YouTube) with totals, KPIs, a chart and a run table with report links; every panel honours Host, Device, the gateway filters, Success and the time range, and reads gateway facts from `gw_info_latest`
- **Execution overlay: a phone under test shows what is being done to it** — every command the host sends now draws itself on the phone's own screen: a ripple where a tap landed, a trail following a swipe, and a caption naming the command (`tap 540,1200`, `swipe left`, `key BACK`, `dump UI`). Before this a paired phone just looked possessed, and a command that never arrived was indistinguishable from one that arrived and was ignored. Drawn by the accessibility service the agent already needs, so it costs no extra permission, and every visual clears itself well inside the shortest step wait — the overlay is part of the screen, so the capture records it like anything else. `screenshot` is announced after the grab rather than before, and typed text is never echoed. A phone being driven also says so continuously, not just per action: a pulsing `● UNDER TEST` badge in the top-right and a blue "under test" notification, so a glance at a phone on a desk tells you whether a script has it. The protocol carries no run boundaries, so that state is inferred from traffic and drops after 45s of quiet. The badge is the one visual here that deliberately persists, which means it is in the captured frames while a script runs — it is small, pinned above app content, and behind the same switch as everything else. Turn it off under This phone → "Execution overlay"
- **Android emulators now have audio** — the emulator's own sound reaches the host's PulseAudio and is recorded into the device's stream, so emulator devices get a real audio level and audio-loss detection instead of N/A. Two traps kept it from working before: `-no-window` selects a headless QEMU that has no PulseAudio client at all, and the launcher's `XDG_RUNTIME_DIR=/tmp` sends libpulse to a socket that does not exist. `vpt-emulator.service` now runs `-qt-hide-window -audio pa` with `PULSE_SERVER=tcp:127.0.0.1:4713`, the grabber prefers that same endpoint so both sides always meet at one daemon, and it stamps the emulator's frames with the wall clock so the sound stays in step with the picture instead of sliding behind it. Verified with a 1 kHz tone in the guest at -25 dB on the host (-91 dB before)
- **Run Tests is one page at every width** — a phone no longer gets a cut-down Run Tests. The simplified page was built on the assumption that the real one could not work on a small screen; it can, once the Selected Items parameter row stops laying its fixed-width controls out with `nowrap` and overlapping the target chip. A narrow window now keeps the whole page — targets, campaigns, Start/Repeat scheduling and Last Executions with Report/Logs/rerun — none of which the simplified page had.
- **Provisioned accounts say which platform they came from, and get a name instead of a blank** — `/server/users` accepts `provider_type` (e.g. `dmacp`) so an external system marks the accounts it administers; everything created inside VirtualPyTest stays `virtualpytest`, and a reset that omits it never reassigns someone else's user. `full_name` now defaults to the part before the `@` (`marie.dupont@x` → `marie.dupont`) rather than NULL, and an existing chosen name is never overwritten · 🗄 DB migration `20260915_profiles_provider_type_and_default_full_name.sql`
- **Device IP on the Dashboard is an icon, not a column of text** — each device's IP was rendered inline in monospace, taking horizontal space on every card in the fleet. It is now a small network icon pinned right, with the address in its tooltip: the same information on hover, and the card has room for the badges that matter at a glance
- **The frontend is configured at runtime, so nothing compiles on a user's machine** — Vite bakes `VITE_*` into the bundle, which meant a built frontend could only ever serve the address it was built for and no frontend image could be published. The container now writes `dist/config.js` from its own environment on every start and `getEnv()` prefers that, so one published image serves any `PUBLIC_HOST`. `launch.sh` pulls all three images; changing `PUBLIC_HOST` needs a restart, not a rebuild. Every `VITE_*` read now goes through that one funnel (16 files, 38 call sites converted — 19 of them used a `(import.meta as any).env` cast form that a naive grep misses), and 8 new tests cover the precedence (a runtime empty string must not blank out a working baked-in value)
- **Install is one download and one command** — `vpt-docker-<tag>.tar.gz` ships the ~0.5 MB the stack actually mounts (compose files, schema, Grafana dashboards, test scripts) instead of asking for a 330 MB clone to reach it. New client-facing [Install](../get-started/install.md) page: what you get, the one file you ever edit (`backend_host/src/.env`), and why Hetzner/AWS/Azure are the same install. New [Add a machine with devices](../get-started/add-a-host.md) page covers `--host-only` including the reachability problem nothing documented — the browser talks to the host directly, so a host behind NAT needs Tailscale or a Cloudflare Tunnel. CI builds the bundle, extracts it with no repo above it and fails if any mount escapes it
- **MinIO, Redis and VNC passwords are generated per install** — all three shipped as one fixed literal published in the repo, so every deployment in the world had the same credential and the docs said which value to try. `write_env.sh` now generates `MINIO_SECRET_KEY` and `REDIS_PASSWORD`, the storage installers configure the services *from* those values instead of carrying their own, `install_host.sh` generates `HOST_VNC_PASSWORD`, and the published host image no longer bakes one (the entrypoint writes it per container). The shipped noVNC page took the password from a literal anyone could read — it now comes from the URL. Existing installs keep whatever their `.env` holds and are never rotated behind your back; the production checklist says how to rotate. TASK-14 item A6
- **Docker install can skip the build** — CI publishes the two backend images to GHCR on every `release-*` tag, and `VPT_IMAGE_TAG` in `setup/docker/.env` makes `launch.sh` pull them instead of building. A first run drops from 5–15 min to about two, and the user gets the exact images the release smoke-tested. The frontend still builds locally (it bakes `PUBLIC_HOST` in), the pull falls back to a build when it fails, and publishing is gated to the public repo
- **The server picker signs in per server** — servers in the picker do not all authenticate against the same Supabase, and the frontend used to hold one session and send it to every one of them. Sessions are now keyed by Supabase identity: servers sharing one share the login, a server with a different one shows a lock and asks once, then stays signed in across switches and reloads
- **CI now runs the platform's own smoke tests** — new `vpt-smoke` job drives all five `test_scripts/vpt/smoke_*` scripts (TC050–TC054) through the real execute path against the deployed environment and reports per-script pass/fail to the CI/CD dashboard. Nothing had ever run them, which is how two of the five came to be broken with no signal at all

### 🔒 Security
- **CORS no longer reflects any origin** — `backend_server`/`backend_host` shipped
  `origins="*", supports_credentials=True`, which Flask-CORS turns into echoing back whatever
  `Origin` a caller sends with credentials allowed; nginx has no IP/origin restriction of its own
  on `/server/*` or `/host/*`, so this was the only gate. Now an explicit `CORS_ALLOWED_ORIGINS`
  allowlist, no wildcard fallback. Deployed and verified live on our own server: a fake origin no
  longer gets `access-control-allow-origin` back, the real frontend still does. **Every other
  deployment (customer instances, self-hosted installs) needs its own redeploy to pick this up —
  it does not happen automatically** — verify with the check in
  the [production checklist](../get-started/production-checklist.md#2b-cors--the-only-origin-gate-in-front-of-the-api) ·
  [BUG-0092](../bugs/BUG-0092-2026-09-15-cors-reflected-any-origin-with-credentials.md) · `this commit`
- **A device console is no longer a remote desktop for the open internet** — `/host/<name>/vnc_lite.html` and `/host/<name>/websockify` were proxied with no session check at all: a WebSocket upgrade from any internet host answered `101` and a live `RFB 003.008` handshake on five hosts, and the page each host serves auto-submits the published default VNC password, so a guessed host name was a desktop. Both paths and the noVNC assets are now gated at the proxy, and the password no longer rides in the URL (where it landed in history, `Referer` and every proxy's access log) — the console supplies it itself · [BUG-0107](../bugs/BUG-0107-2026-09-15-vnc-console-and-websockify-open-to-the-internet.md)
- **Open mode no longer waives the server API key** — `SERVER_OPEN_MODE=true` (the installer default) is about skipping the *browser login*, but it also skipped the `X-API-Key` check, so every `/server/*` route answered an unauthenticated `curl` as `admin`. The two are now separate: open mode waives the login only, a non-browser call still presents `X-API-Key` whenever `API_KEY` is set, and a present-but-wrong key is a hard `401` instead of falling through to the next branch · [BUG-0098](../bugs/BUG-0098-2026-09-15-open-mode-waives-the-api-key.md)

### 🐛 Bug fixes
- **A host's capture folders grew without bound** — the hot/cold archiver rotated the chunk trees it owns and nothing else, so everything a *report* leaves in the capture root — `reports/`, `original_with_crop_*.png`, `verification_failure_*.html` — accumulated forever: 1.3 GB of reports 7544 files past their own 30-day retention, and 1.8 GB of crops going back to May on one Pi. Those paths are now swept on the same retention as everything else. A second trap made it invisible: a long-lived archiver keeps running the code it started with, so a host that was not restarted after the fix goes on behaving exactly as before · [BUG-0094](../bugs/BUG-0094-2026-09-15-archiver-never-rotates-capture-root-artifacts.md) · `edefe4cff9`
- **`capture_monitor` grew by 700 MB a day until the host ran out of memory** — 4.84 GB after seven days on one Pi. The freeze-detector keeps recent thumbnails to compare frames against, in a cache that had no bound at all, and the cleanup written to bound it reassigned the list instead of clearing it — so every reader kept the old one alive and the trim freed nothing. The cache is now a `deque(maxlen=8)`, which cannot grow whatever a future caller does · [BUG-0095](../bugs/BUG-0095-2026-09-15-capture-monitor-freeze-thumbnail-cache-unbounded.md) · `89833d56e1`
- **Inside the APK the app showed the website's layout instead of the phone's** — on a real handset the installed app rendered the web page — "Download the app" and a table of slots each showing a pairing QR — when the phone running it is the one being paired and should be *scanning* one. The native config was injected into any origin the WebView reached, and an OAuth round-trip landed the session on the deployment's website, a context with no bridge to the phone at all. The config is now served only to the app's own origin and a landing on the website is rewritten back onto it, path and query intact — fixed in the app, so one APK still serves any deployment · [BUG-0105](../bugs/BUG-0105-2026-09-15-native-app-renders-web-layout-no-this-phone-tab.md) · `8caa913cab`
- **Another server's devices streamed from this server's proxy** — with the picker on a second server, its devices sat on "Loading stream..." or showed a Bad gateway — and one card showed a real desktop that belonged to *this* server's identically-named host, which is the dangerous case: nothing looks broken, it is simply the wrong machine. Stream URLs were resolved against the browser's origin rather than the origin of the server that owns the host; `useStream` kept doing so after the same class of bug was fixed elsewhere, and it is the path that actually produces the URL the preview consumes · [BUG-0106](../bugs/BUG-0106-2026-09-15-cross-server-stream-urls-resolve-against-wrong-origin.md) · `fc2432150b`
- **A failed incident insert uploaded a million orphan thumbnails and filled the object store** — the UI said heatmap data was stale and restarting the processor changed nothing, because the processor was fine: every upload failed. A `create_incident` that errors was retried about five times a second, each attempt re-uploading its images before the insert that would have given them an owner, until MinIO ran out of **inodes** — not bytes, so every free-space check looked healthy. A failed create now backs off 60 s and a retry reuses the images it already uploaded · [BUG-0109](../bugs/BUG-0109-2026-09-16-failed-incident-insert-uploads-a-million-orphan-thumbnails.md) · `ebf7cde42b`
- **The events API, the navigate endpoint and the OpenAPI docs were unreachable in production** — three route groups were mounted outside `/server/*`, the only prefix the proxy forwards to the backend, so every request to them was answered by the website instead. An alert posted to the events API got a 200 back and was never delivered. They now live at `/server/events`, `/server/frontend` and `/server/docs/api`, behind the same login check as everything else — and the twelve tests that had been marked unrunnable now run on every push · [BUG-0131](../bugs/BUG-0131-2026-09-16-three-route-groups-were-unreachable-in-production.md) · `b812e50329`
- **Reusing a workspace name reported a server error** — creating a workspace whose name was already taken answered "Failed to create workspace" with a 500, so a name clash looked like an outage rather than something to rename. It now answers 409 and says which name is in use · [BUG-0132](../bugs/BUG-0132-2026-09-16-a-taken-workspace-slug-answered-500.md) · `40716b6ca5`
- **A read-only account could start a run on a device** — `POST /server/script/execute`, the route behind the Run Tests button, carried no authorization check at all, so any authenticated caller — a `viewer`, whose whole permission set is `*:view` — could launch a script on shared hardware by calling it directly. It now requires `execution.run:run_test`, the same permission `/server/testcase/execute` has always carried; admin and the shared service key are unaffected, so host callbacks, dmacp and MCP keep working. The test that asserts exactly this existed all along and had never once run: its host fixture read a route that does not exist, so it skipped itself on every CI run · [BUG-0130](../bugs/BUG-0130-2026-09-16-a-viewer-can-launch-a-script-on-a-device.md)
- **The Atlas session list went 500 after the first tool call** — `GET /server/agent/sessions` answered `Object of type ToolResultCache is not JSON serializable` for every session once any of them had run a tool, and stayed broken until `vpt-server` restarted. A session's `context` is a free-form bag agents write to — including a live tool cache — and it was handed straight to `jsonify`; it is now filtered at the serialization boundary · [BUG-0129](../bugs/BUG-0129-2026-09-16-agent-sessions-listing-500s-on-a-live-tool-cache.md)
- **The agent could not read or edit navigation trees, and never said so** — one missing import made the whole `tree` tool category fail to load on every agent start, so Atlas ran with 92 tools instead of 102 and answered tree questions without the tools for them. The only trace was a single warning line in the server log · [BUG-0127](../bugs/BUG-0127-2026-09-16-tree-tools-missing-import-drops-ten-agent-tools.md) · `4480b0275d`
- **Publishing an event always failed with a 500** — `/api/events/publish` and the blackscreen, device-offline and build-deployed shortcuts rejected every well-formed request, because the router asked the agent registry for team-scoped agents when the registry has none. The route tests only ever posted incomplete bodies to check the 400, so nothing noticed · [BUG-0128](../bugs/BUG-0128-2026-09-16-event-routes-500-on-a-stale-registry-call.md) · `4480b0275d`
- **Atlas chat stopped answering, server-wide, until a restart** — a message showed "Received..." and then nothing, in every conversation, with no error and nothing in the UI to say why. A helper used by the agent-runtime and event routes kept a background asyncio loop alive for the life of the process; under gevent that loop lives in the worker's only thread, which makes asyncio treat the whole worker as busy and every later chat message fail instantly. One 404 on `POST /server/runtime/instances/<id>/stop` was enough — and the regression suite posts exactly that on every CI run, so production chat had been dead for weeks. The loop no longer outlives its request, and a crashed chat turn now ends with a visible error instead of hanging · [BUG-0126](../bugs/BUG-0126-2026-09-16-runtime-route-background-loop-kills-atlas-chat.md) · `4002680226`
- **A video check measures the player, not the page around it** — `WaitForVideoToAppear` failed for a minute at a time on a phone playing a video that was plainly visible in its own stream. Motion detection defaults to the centre 60% of the frame, which is written for a TV; a portrait phone draws its player across the top ~28% and fills the middle with title, Subscribe and comments, so the default region measured a static block (0.9–2.9% against a 3.0% threshold, where the player band read 4.1–7.6%). The playback verifications could not be pointed elsewhere either — motion detection has taken an `area` for a long time, but nothing forwarded one. Both now take it, declare it and record it · [BUG-0122](../bugs/BUG-0122-2026-09-16-motion-check-measures-below-a-portrait-players-video.md)
- **A YouTube test opens a video instead of the ad above it** — the feed's first card is often promoted, and a promoted card carries a duration like any other, so the tree's " seconds" selector matched it and the run ended on an advertiser's web page. A term prefixed with `!` now disqualifies a match, and it excludes by screen area rather than by label — the word "Sponsored" sits on the button wrapping an ad while the duration sits on a child that says nothing about being one, so skipping only the labelled node would have tapped the child and opened the same ad · [BUG-0121](../bugs/BUG-0121-2026-09-16-youtube-selector-opens-the-sponsored-card.md)
- **Report pages respond to clicks again** — a code comment inside the video-modal's JS template literal used backticks, which prematurely closed the string and left the rest as invalid JavaScript; that syntax error silently disabled every `onclick` in the report's script block — step rows, section toggles, screenshot and video modals — on every generated report, not just ones with a video · [BUG-0119](../bugs/BUG-0119-2026-09-16-report-video-modal-comment-breaks-every-report-click.md)
- **`traceroute` ships on runner hosts too** — network-diagnostic scripts (`superping`, etc.) run on any host type, but `install_host.sh` only installed `traceroute` for full hosts; added it to the runner package list and reinstalled it across both VirtualPyTest environments wherever it had drifted away · [BUG-0120](../bugs/BUG-0120-2026-09-16-runner-hosts-never-got-traceroute.md)
- **Tablet emulator crash-looped on restart, then never booted** — the emulator's own free-space check refused a 30 GB host at 6 GB free five times, and the one-core AVD then spent 90 min in the boot animation under host load; the labox AVDs now run 4 guest cores (45 s boot), the tablet disk is 50 GB, the installer writes 4 cores / 576M heap for new AVDs, and a boot-storm ANR dialog no longer sits on a test device's capture · [BUG-0117](../bugs/BUG-0117-2026-09-16-tablet-emulator-crash-loops-on-disk-check-then-never-boots.md) · `dea2fca924`
- **Scripts sent to a busy device through the API now queue instead of piling on** — an external scheduler firing six scripts at one device got all six running at once, because "same user, different session" quietly took over the running script's lock (a browser tab, which keeps one session, was refused and queued instead). A running script's lock is no longer taken over implicitly — `force_unlock` is the explicit way — and on a busy device the server itself queues the run as a one-shot deployment, answers `202 {queued: true}`, and completes the caller's `task_id` with the real result once the run happens. The Run Tests page understands the new answer; its rerun button still fails fast on a locked device · [BUG-0118](../bugs/BUG-0118-2026-09-16-api-callers-run-scripts-on-a-busy-device-instead-of-queueing.md)
- **Host Monitoring opens without the pause** — its Host filter no longer scans every metric row (a DISTINCT over 913K rows, seconds per open); it walks the host index one host at a time, 733 ms → 32 ms · [BUG-0116](../bugs/BUG-0116-2026-09-16-host-filter-scans-every-metric-row.md) · `a554774`
- **Dashboards no longer attach gateway facts per result row** — every gateway-filtered panel joins `gw_info_latest` (one row per host) instead of a per-row lookup on `gw_info`, and script labels come from `executable_identity`; a 7-day table on a 1.7M-row DB went from seconds to 42 ms · [BUG-0115](../bugs/BUG-0115-2026-09-16-dashboards-attach-gateway-facts-per-result-row.md) · `fa44ce6`
- **Two web tests in a row no longer kill each other's browser** — a web script that started while another was still running tore down the first one's browser, so the victim died mid-navigation on `Page.goto: Connection closed while reading from the driver`. Clearing the debug port matched every process with a connection *to* it, not just the browser, so it killed the other run's Playwright driver too. The kill can now only reach the browser itself, never a driver, and a script that finds another run\'s browser still on the port waits for that run to finish (up to 300s, `VPT_WEB_BUSY_WAIT`) instead of launching over it · [BUG-0114](../bugs/BUG-0114-2026-09-16-a-second-web-script-kills-the-first-ones-browser.md)
- **An emulator's or a phone's report video covers the whole test again** — every imagefile device archived nothing at all, so its report video was silently capped at the live stream window: a 94-second run came back as 30 seconds of footage, with the missing 79s recorded only in a log line. The branch segmented at `hls_list_size 30` while the archiver needs 60 one-second segments before it will build the 1-minute MP4 the 10-minute chunks are appended from, so it never built one and cold storage stayed permanently empty. Retention now matches every other source type. Note that a newly added device also needs `setup_ram_hot_storage.sh` run on its host — nothing calls it automatically · [BUG-0113](../bugs/BUG-0113-2026-09-16-imagefile-devices-never-archive-so-report-videos-are-truncated.md)
- **The first click after a deploy no longer dead-ends** — a tab that was open when a new build shipped now reloads itself onto it instead of showing "Failed to fetch dynamically imported module" · [BUG-0112](../bugs/BUG-0112-2026-09-16-first-click-after-a-deploy-dead-ends-on-a-missing-chunk.md)
- **Devices that capture no audio get their picture analysis back** — on an emulator or phone device, where the capture pipeline has no audio input at all, the audio probe correctly reports N/A; the monitor then formatted that None into a log line, crashed the frame's save, and wrote a placeholder in place of the real analysis — once per frame. Blackscreen, freeze, localize and thumbnails were all computed and thrown away, and the UI showed the missing fields as a reassuring "No". Such a device was also counted as being in permanent audio loss, opening an incident (and its thumbnail uploads) that could never clear. Audio N/A is now N/A everywhere: no crash, no incident · [BUG-0111](../bugs/BUG-0111-2026-09-16-no-audio-device-loses-its-whole-frame-analysis.md)
- **A long mobile page no longer hides its last rows behind the bottom nav** — the mobile layout reserved the nav's 64px, but the box holding that padding was capped at the screen height, so any page taller than the screen overflowed it and the reservation ended up above the escaped content instead of below it. On Run Tests that left the last card showing 4 of 5 rows with the 4th sliced in half, and only 48px of scroll for 88px of overhang; the Dashboard's last host card went the same way. The container now sizes to its content when the content is taller than the screen, and still fills the screen when it is not · [BUG-0124](../bugs/BUG-0124-2026-09-16-mobile-pages-clip-their-last-content-under-the-bottom-nav.md)
- **The heatmap no longer passes yesterday's frame off as this minute, and the Dashboard agrees with it** — heatmap files are a 24h circular buffer named by HHMM alone, so a minute the processor skips leaves the previous day's file at that name; the page loaded it, noticed it was over 24h old, showed a warning that the backend was not generating data — and rendered the stale mosaic underneath anyway. A frame is now accepted only when its timestamp matches the slot it was fetched for, nothing is drawn for one that doesn't, and the banner names the missing minute instead of accusing the backend. The Dashboard's Heatmap chip reads the frames the processor actually produced rather than `systemctl is-active`, so a running-but-silent processor shows as `stuck` there too; and the hosts fetch retries, so one refused connection from the single-worker server costs a retry instead of a minute · [BUG-0110](../bugs/BUG-0110-2026-09-16-heatmap-shows-yesterdays-frame-for-a-skipped-minute.md)
- **A paired phone can finally be tested by a script, not just poked by hand** — the phone drove fine from the remote panel but every script against it died on its first action with `Remote controller not available`. Scripts run as their own subprocess, which builds its own controllers with no Flask app, so the `phone_agent` implementation — registered by the feature's `register(app)` and backed by the socket that lives in vpt-host — simply did not exist there. A feature can now also register controllers without an app, and the phone's does so against an HTTP client that calls back into vpt-host. The model row `device_models` never had is added too, so a navigation tree can be built for a phone at all · [BUG-0108](../bugs/BUG-0108-2026-09-16-no-script-can-drive-a-paired-phone.md) · 🗄 DB migration `features/mobile-app/db/001_phone_agent_device_model.sql`
- **A stream on another server loads instead of hanging on "Loading stream…"** — the URL builder strips the redundant `host/` from an endpoint by testing the host's URL, and once that URL carried another server's origin the test stopped firing, leaving a stray segment. The resulting address answers `200` with the SPA's `index.html`, so hls.js waited on a manifest that was never coming, in silence. It now tests the host's registered path · [BUG-0103](../bugs/BUG-0103-2026-09-15-cross-server-stream-url-keeps-stray-host-segment.md)
- **Deploying the frontend no longer takes the site down for four minutes** — `systemctl restart vpt-frontend-prod` stopped `serve` and *then* regenerated every document and ran the full Vite build, so every restart was 4m20s of hard downtime; the doc cache built to avoid that had never once hit, because the four doc steps shared a single 120s budget and a single hash, the security scan was always the step killed by that budget, and any step's failure vetoed the cached snapshot for all of them. The bundle is now built before the restart — into `dist.new`, swapped in at the end, while the old bundle keeps serving — and stamped, so the restart itself is about a second; each doc step owns its own hash and its own budget, so a backend change no longer re-renders the API reference and a slow security scan no longer costs anything but itself · [BUG-0123](../bugs/BUG-0123-2026-09-15-frontend-restart-rebuilds-with-the-site-down.md)
- **Dump UI element boxes stay on the phone screen** — in the REC stream modal the Android UI-dump overlay scaled its rectangles with `cover` logic against the full panel, but that player uses `objectFit: 'contain'`: a portrait phone in a landscape panel came out ~1.22x too large and ~1053 px too high, so the boxes painted over the navigation bar and the remote panel, and nothing clipped them. The overlay now computes the content rect for the fit mode the player actually uses, both layers are clipped to it, and the modal's stream dimensions follow window resizes instead of going stale · [BUG-0102](../bugs/BUG-0102-2026-09-15-dump-ui-elements-paint-outside-stream-area.md)
- **A missing stream reports 404 instead of "blocked by CORS policy"** — the host's stream routes attached the CORS headers next to each file it served, so every error response went out without them; a cross-origin viewer then could not see the status at all and one dead device looked like a site-wide CORS misconfiguration. The headers now come from one `after_request` that covers errors too, and the `/host/<name>/stream|vnc_lite` proxy locations set them with `always` (hiding the upstream's copy first, so there is exactly one) · [BUG-0125](../bugs/BUG-0125-2026-09-15-stream-errors-answer-without-cors-headers.md)
- **A capture whose input stalls now restarts itself instead of going quietly dark** — the stream watchdog judged a grabber by its log (mtime, and size for an error flood), so an ffmpeg whose input froze kept printing the same progress line forever and looked perfectly healthy while writing no segments at all: `vpt-pi1`/`S21x` had no stream for ~67 h until someone restarted the service by hand. It now also watches what comes *out* — no new segment for 60 s and the grabber is restarted, under the same rate limit, flap back-off and dormant cap as the other checks · [BUG-0101](../bugs/BUG-0101-2026-09-15-ffmpeg-watchdog-blind-to-stalled-input.md)
- **A host on another server loads its stream from that server, not from whichever frontend you happen to be on** — selecting a second server in the picker left every tile on "Loading stream…": hosts register a *relative* `host_url` (`/host/<name>`), which the browser resolved against the current origin, so the main proxy was asked for hosts it does not serve and answered 502 — and for a name that exists on both servers (`host-clone-2`) it would have quietly shown the wrong machine. Hosts now carry the server they came from and relative URLs resolve against it, for streams, VNC, captures and host API calls alike · [BUG-0100](../bugs/BUG-0100-2026-09-15-cross-server-host-urls-resolve-against-wrong-proxy.md)
- **One script no longer has a different name on every screen** — a test called `[TC015] Windows Network Assessment` in Run Tests could appear under a completely unrelated, hand-typed title on its own Grafana dashboard, and `GET /server/script/list` returned only the raw file name. The `[prefix] display_name` label now has one definition (`format_script_label()`), the script list carries it as `items[].label` beside `script_ref`, a rename on the Test Cases page shows up immediately instead of after the cache TTL, and `check_dashboard_titles.py` fails on a dashboard title that drifts from the identity map · [BUG-0099](../bugs/BUG-0099-2026-09-15-one-script-four-names-across-ui-grafana-api.md)
- **A password reset sent as a `GET` answered `200` and looked like it worked** — dropping `-X PUT` from the provisioning curl hit the read-only status check, which reported `"status":"ok"` while changing nothing; a `GET` carrying a password or `?grafana=` now returns `405` and names the `PUT` to send · [BUG-0097](../bugs/BUG-0097-2026-09-15-password-reset-get-answers-200-like-success.md)
- **Host registration crashed for a device without `DEVICEn_VIDEO_STREAM_PATH`** — undefined `host_name` in the fallback; the path is now derived from the capture folder · [BUG-0096](../bugs/BUG-0096-2026-09-15-device-stream-path-fallback-nameerror.md)

### 🚚 Upgrade

**Compared with** `main-2026.09.15-8887` → `main-2026.09.17-9151` (692 files changed).

**Database** — apply these once per database:
- `setup/db/migrations/20260915_profiles_provider_type_and_default_full_name.sql`
- `setup/db/migrations/20260915b_profiles_backfill_blank_full_name.sql`
- `features/mobile-app/db/001_phone_agent_device_model.sql` (feature `mobile-app`)

**Settings** — add to the `.env` on each machine:
- server: `SUPABASE_PUBLIC_URL`

**Services** — restart by hand (the deploy restarts the rest itself): `vpt-discard-incidents`, `vpt-discard-scripts`, `vpt-heatmap`

Unit templates changed, reinstall where they run: `archiver.service`, `host.service`, `kpi.service`, `monitor.service`, `subtitle.service`, `transcript.service`

**Proxy** — `docker.conf`, `local-http.conf`, `production-https.conf`, `proxmox.https.conf`, `proxmox.local.conf`, `proxmox.local.https.conf`

**Grafana** — `dns-lookup.json`, `home-dashboard.json`, `ookla-speedtest.json`, `script-results.json`, `superping.json`, `system-host-monitoring.json`

## build 8887 — 2026-09-15

### ✨ Features
- **Edit TC prefixes from the Test Cases page** — the `TCnnn` prefix and display name shown on Test Cases, Run Tests and in reports are now DB rows (`executable_identity`) instead of two hand-edited `script_identity_map.json` copies: click the prefix chip on any row to edit it (rows with none show a faint `+TC`), and it applies to the next run. The JSON files stay as a read-only fallback for one release; `scripts/import_script_identity_map.py` loads an existing map in one go. Testcase runs now carry a prefix too, which they never did · 🗄 DB migration `setup/db/migrations/20260914_executable_identity.sql`
- **Convert disk scripts to virtual scripts automatically** — converting a script now follows its `from test_scripts.…` helper imports, converts each helper into its own virtual script, rewrites the imports and declares them in `_script_libs`; the script is named by its basename and filed under its disk folder, and the sibling `.md` becomes its doc. `POST /server/virtual-script/convert-batch` and `scripts/sync_virtual_scripts.py` migrate whole folders in one operation, planning first and writing nothing if anything fails. A script's `sys.path` bootstrap is rewritten to derive the project root from the executor's working directory instead of `__file__`, which is off by one from a virtual script's location; scripts that read a *sibling data file* have no equivalent and are reported and refused rather than silently converted into something that breaks at run time
- **Workspace device filters carry device names** — every `/server/workspaces` response now ships a `device_filter_names` map beside `device_filter`, resolving each `host:device_id` key to the device's real name from the live host registry, so the saved filter is readable without cross-referencing `/server/system/getAllHosts` by hand. Keys whose host is offline or lives on another backend_server are omitted — fall back to the raw key
- **The user API accepts an email everywhere** — every `/server/users` route now takes an email address in place of the internal user ID: create, reset password, read status, delete, and now also `assign-team`, `remove-team` and `permissions`, which were UUID-only and forced an external system to look the UUID up first. Email is the join key an identity system already holds, so provisioning works without ever seeing a VirtualPyTest ID · `c9c0b7c223`
- **Local AI provider** — Settings → AI gains a *Local model server* block (base URL, model, optional key); pick **Local** for the agent, vision or text task to run VirtualPyTest against any OpenAI-compatible server on your network (Ollama, vLLM, llama.cpp, LM Studio, Colibri) instead of a hosted provider. `.env`: `AI_PROVIDER=local`, `LOCAL_AI_BASE_URL`, `LOCAL_AI_MODEL`, optional `LOCAL_AI_API_KEY` / `LOCAL_AI_TIMEOUT` (default 300 s)
- **Android emulator VM sizing page** — new QuickGuide 5 gives the exact Proxmox config for mobile/tablet/TV emulator VMs (8 vCPU / 12 GB / 40 GB, `cpu host` for KVM), the measured load behind those numbers, the per-form-factor AVD profiles and system images, the emulator flags, and how many emulators fit on a given machine; QuickGuide 1's emulator row corrected from 4 vCPU / 8 GB / 60 GB
- **Recommended Hardware page** — QuickGuide 1 now says what to buy, with pictures and links: Raspberry Pi 5 16 GB kit (standalone), Minisforum MS-A2 with Proxmox VM sizing (lab), the €7 HDMI→USB capture card, and an optional local-LLM VM layout; the docs site now ships `docs/<section>/images/`
- **Public "Ask AI" for the marketing website** — anonymous `POST /server/public/ask` answers visitor questions from `docs/` (MiniMax, docs tools only) behind an Origin allowlist, per-IP and global daily limits, off-topic decline without doc reads, and a similar-question answer cache flushed on each deploy; served at `api.virtualpytest.com`
- **One entry point for installing** — `docs/get-started/README.md` chooses Docker / one VM / Proxmox fleet / developer; every path documented against the scripts (ports, versions, auth posture), `configuration.md` lists every variable; the QuickGuide folder is folded in and the docs path check runs in CI
- **One-VM install fills its own `.env`** — `install_all.sh` gets `--no-grafana/--no-storage/--no-host/--public-host/--open-mode`, writes the three `.env` files from the Supabase install and the LAN address (`write_env.sh`), starts the services and prints the URLs
- **Docker install: one command brings up the whole platform** — `setup/docker/launch.sh` starts a vendored self-hosted Supabase, MinIO, Redis, server, host, frontend and Grafana from committed compose files, generating every secret; `--host-only` joins an existing server
- **`VITE_SHOW_PROJECT_NAME=false` hides the project name next to a wordmark logo** — header, footer and mobile bar then show the logo alone and the login page puts the logo where the title was, instead of spelling the name twice (once as the image, once as text)
- **CI `api-routes` job sweeps every GET route the server registers** — replaces the 11-path
  `api-smoke` list: `run_api_tests.py --discover` reads the server's own route table, resolves
  path ids from the list endpoints, reports unresolvable routes as SKIP with the reason; 150 of
  185 GET rules exercised against prod (0 failures, 35 reasoned skips) · 🗄 DB migration `features/cicd/db/004_rename_api_smoke_job.sql`
- **`backend-server-tests` report shows every HTTP call** — each pytest case now logs
  `METHOD url -> status (ms)` plus params and a 500-char body under *Captured stdout*, instead of
  "No log output captured"; job category relabelled `unit` → `api` (it always was live HTTP)

- **`frontend-component-tests` report rows expand to the test source** — file, the `it(...)` block and
  vitest's failure text per test, runner output appended; generator moved to `tests/frontend/vitest_html_report.py`
- **CI/CD Reports page flags stuck runners** — when runners are offline while runs are queued on GitHub, a banner says so and a single button restarts every offline runner; the header shows the offline count and the section cannot collapse over an offline runner
- **CI/CD Reports page explains each job** — hover a job name for a plain-language tooltip saying what it
  proves (simulated-browser component render vs real Chrome on the deployed site vs HTTP against the server)

### 🔒 Security
- **Self-hosted installer no longer ships Supabase's public default JWT secret** — `install_supabase.sh` hard-coded `config.toml`'s `jwt_secret` to the Supabase CLI's well-known local-dev value; anyone who could reach an install's REST API could forge a `service_role` token with a string copied from Supabase's own docs and bypass every RLS policy. A fresh install now generates its own secret; the script also warns if an existing install (including this deployment's own database) is still on the default and gives the rotation steps · [BUG-0082](../bugs/BUG-0082-2026-09-14-supabase-cli-default-jwt-secret-in-tree.md) · `this commit`
- **One-VM install shipped the public Supabase CLI JWT secret** — anyone reaching port 54321 could mint a service-role token; now a random per-install secret · [BUG-0084](../bugs/BUG-0084-2026-09-09-vm-install-public-jwt-secret-and-unfilled-env.md) · `this commit`
- **E2E reports no longer print the auto-sign token** — Playwright stdout attachments showed the full
  `auto_signed=` URL · [BUG-0068](../bugs/BUG-0068-2026-09-08-e2e-report-prints-auto-sign-token.md) · `this commit`

### 🐛 Bug fixes
- **The VPT device-control and video-stream smoke tests could never pass** — both built the host address by prefixing the backend server's origin onto the browser-relative `/host/<name>` route, which only the reverse proxy resolves, so every host call 404'd; they now use the direct host API origin the server itself calls. Neither script runs in CI, which is why it went unnoticed · [BUG-0091](../bugs/BUG-0091-2026-09-15-vpt-smoke-scripts-build-host-url-from-server-origin.md)
- **A run that never started is no longer recorded as passed** — the server derived a run's outcome as "the host reported no error", so a host that failed before launching the script (virtual-script materialization denied by filesystem permissions) produced a green run with no report. It now reads the executor's own verdict and exit code, and treats a callback carrying no evidence at all as a failure — and that one verdict is what the run record, the task status and the completion webhook all report, instead of three places deciding separately · [BUG-0089](../bugs/BUG-0089-2026-09-15-virtual-script-materialize-failure-reported-as-success.md)
- **Deployed hosts keep the file ownership the runtime needs** — the deploy pushed with `rsync -a` as root, so it stamped every target tree with the *source's* numeric uid/gid on each run, leaving `test_scripts/` unwritable by `vpt_user`. Every virtual script then failed to materialize — and failed *silently*, recorded as a successful run with no report. The push now sets ownership itself (`--chown`), which also works on a host that grants no passwordless `sudo`, and a deploy that still cannot get there names the host and the consequence · [BUG-0089](../bugs/BUG-0089-2026-09-15-virtual-script-materialize-failure-reported-as-success.md)
- **Virtual-script libraries no longer appear as runnable** — a virtual script named `utils_*`/`lib_*`/`common_*` is a library other scripts pull in through `_script_libs`, but the run pickers listed it like any script and offered to execute it; disk and virtual scripts now share one discoverability rule, and the Virtual Scripts editor still lists libraries so they stay editable
- **Customer bundles no longer carry internal documentation** — `build_customer_bundle.sh` and `deploy_customer.sh` exclude `docs/tasks/`, `docs/agent/` and the rest of the public deny-list; the bundle builder fails instead of packing them. [BUG-0088](../bugs/BUG-0088-2026-09-15-customer-bundle-ships-internal-docs.md)
- **MinIO had no retention rules at all, filled up, and failed every artifact upload** — `/data` hit 95% and MinIO refused every `PutObject` with `XMinioStorageFull`, so runs that passed were recorded as failures with no report; 14-day expiry now applies to all 11 artifact prefixes (`script-screenshots/`, `reports/` and `fleet-health/` had never had one), `navigation/` and `reference-images/` deliberately excluded · [BUG-0087](../bugs/BUG-0087-2026-09-14-minio-no-lifecycle-rules-storage-full.md)
- **An Android emulator that boots with a black screen now heals itself** — the emulator regularly comes up with its display composing nothing: services report healthy, frames keep flowing, and every capture, verification and report screenshot is black. The screencap loop now samples its own output and power-cycles the guest display when it goes black, so the picture is back within about a minute instead of needing someone to notice · [BUG-0086](../bugs/BUG-0086-2026-09-14-android-emulator-boots-with-black-display.md) · `this commit`
- **Failed runs now appear on the Ookla, Superping and DNS dashboards** — the detail tables hardcoded a passing-only filter on top of the PASS/FAIL selector, so a failed speedtest, ping or lookup was counted but never listed; they now follow the selector and show a Status and an Error column · [BUG-0085](../bugs/BUG-0085-2026-09-14-gw-dashboards-hide-failed-runs.md) · `43d5293faf`
- **The Bugs section of the docs is back** — it had been dropped from the published site, but the Docs menu still linked to it, so **Docs → Bugs** could only ever show *Error Loading Documentation*. The reports that named internal addresses or a customer are anonymized instead, and the release note's links back to each bug report work again · [BUG-0081](../bugs/BUG-0081-2026-09-14-docs-bugs-section-unpublished-error.md) · `this commit`
- **A `group` that cannot be applied is now reported instead of silently dropped** — provisioning swallowed every team error into "no team" and still answered `200` with `"team": null`, so a caller believed the group had been applied when it never was; it now returns `500` with the reason, and retrying converges · [BUG-0080](../bugs/BUG-0080-2026-09-14-ensure-team-swallows-errors-into-null-group.md) · `7c1261d50d`
- **Deleting a user can no longer report success when it failed** — the route ignored the delete result and returned `200 "deleted"` regardless, then still removed the Grafana account: the person lost dashboards but kept a working platform login, and the offboarding looked clean · [BUG-0078](../bugs/BUG-0078-2026-09-14-user-delete-reports-success-on-failure.md) · `daa7efb31c`
- **A user who created a deployment can be deleted** — `deployments.created_by` had no `ON DELETE` action, so the foreign key would have blocked removing that account permanently; now `SET NULL`, keeping the deployment as team history · [BUG-0079](../bugs/BUG-0079-2026-09-14-deployments-created-by-fk-blocks-user-delete.md) · `daa7efb31c` · 🗄 DB migration `setup/db/migrations/20260914_deployments_created_by_on_delete_set_null.sql` — **must be run on every database, including each customer install**
- **A provisioned `group` now actually creates and assigns the team** — external user provisioning accepted a `group`, failed to insert the team (missing NOT NULL `tenant_id`), swallowed the error and still returned `200` with `"team": null`, so the group was silently discarded on every call · [BUG-0077](../bugs/BUG-0077-2026-09-14-provisioning-group-dropped-team-insert-no-tenant-id.md) · `d224ff6c03`
- **A platform redeploy no longer deletes a customer's `frontend/.env.production`** — the deploy host's `update_core.sh` was an older copy without that exclude, so `--delete` wiped the overlay's branding config while `public/brand/` (excluded) kept the customer logo: half-rolled-back site, customer logo with platform text. The repo script is now the single lineage (it also regained the opt-in `--restart [service]` and the rsync failure check that only existed on the deploy host)
- **Docker standalone stack could neither build nor run** — Dockerfiles copied a `.env.example` the build context excludes, supervisord used a non-existent user, the bundled Postgres was never read, no auth variables were set · [BUG-0083](../bugs/BUG-0083-2026-09-09-docker-standalone-could-not-build-or-run.md) · `this commit`
- **Customer bundles build again from an older release pin** — the packaging `.env` guard checked the platform checkout's current branch instead of the commit it had just staged, aborting on any `*.env.example` template the pin carried and `main` has since deleted · [BUG-0076](../bugs/BUG-0076-2026-09-11-bundle-env-guard-checks-wrong-ref.md)
- **Hosts list no longer waits 8 s for gateway info on large databases; gateway filter dropdowns read a 50-row table** —
  the gateway views recomputed "latest `gw_info` scan per device" by scanning every `gw_info` row
  per read (killed by PostgREST's 8 s timeout every minute on the customer DB, silently); a
  trigger on `script_results` now keeps `gw_info_latest` (per device) and `gw_info_values`
  (every model / firmware / MAC / access / LAN value seen), the views read the table, and the
  Grafana HGW variables read `gw_info_values` ·
  [BUG-0075](../bugs/BUG-0075-2026-09-10-gateway-info-corrected-view-statement-timeout.md) ·
  `this commit` · 🗄 DB migration `setup/db/migrations/20260910c_gw_info_latest.sql`
- **Grafana dashboard filters no longer error intermittently on large databases** — a dashboard
  load fires its variable and panel queries at once; on a big `script_results` each got a
  parallel plan and together they exhausted the DB container's 64 MB `/dev/shm`
  (`could not resize shared memory segment … No space left on device`, 103× in 48 h on the
  customer DB); the Grafana/admin `postgres` role now runs without parallel workers, and
  `(script_name, success)` is indexed ·
  [BUG-0074](../bugs/BUG-0074-2026-09-10-grafana-queries-fail-postgres-shm-exhausted.md) ·
  `this commit` · 🗄 DB migration `setup/db/migrations/20260910b_postgres_role_no_parallel_workers.sql` + `20260910_script_results_script_name_success_index.sql`
- **Windows hosts no longer crash-loop after a deploy** — the push created the new `features/`
  folder with a Cygwin ACL the host task could not read, and the optional-feature scan turned that
  `PermissionError` into a fatal startup error; the scan now logs and continues without features,
  and the Windows rsync push writes destination-default permissions (`--no-perms --chmod=ugo=rwX`)
  so new folders inherit the parent's ACL ·
  [BUG-0073](../bugs/BUG-0073-2026-09-09-windows-host-crash-loop-features-dir-acl.md)
- **Host VNC stream no longer cropped with the remote/web panel open** — the desktop is re-fitted to the measured stream width (panel width subtracted) on every panel toggle and window resize · [BUG-0072](../bugs/BUG-0072-2026-09-09-vnc-stream-cropped-with-side-panel.md) · `this commit`
- **Admin routes work on a no-login site (Run Command 500)** — `@require_user_auth` now honours the
  principal the global `/server/*` guard already established (open mode, `X-Server-Key`, service key,
  or a JWT it verified) instead of re-running the JWT-only path, which answered 500 without a secret
  and 401 with one on all 15 `@require_user_auth`+`@require_role` routes ·
  [BUG-0071](../bugs/BUG-0071-2026-09-09-require-user-auth-ignores-global-guard.md)
- **`SERVER_OPEN_MODE=true` now wins over a leftover JWT secret** — on a site without browser
  login the server `.env` still carried a `SUPABASE_JWT_SECRET` from its database install, which
  made the guard enforce JWT and answer 401 to every browser call while the explicit open-mode
  line was silently ignored; open mode is now evaluated before the JWT branch and the startup
  banner says so when a secret is being ignored ·
  [BUG-0070](../bugs/BUG-0070-2026-09-09-open-mode-defeated-by-stale-jwt-secret.md)
- **`backend_server/requirements.txt` installs again** — the `h2` 4.4.1 bump left `hpack` pinned
  at 4.1.0, below what `h2` requires, and `packaging==25.0` sat above what the pinned langfuse v2
  SDK allows, so `pip install -r` aborted with ResolutionImpossible and none of the security bumps
  in that file could land; now `hpack` 4.2.0 and `packaging` 24.2, full file verified to resolve ·
  [BUG-0069](../bugs/BUG-0069-2026-09-09-backend-server-requirements-unresolvable-h2-hpack.md)
- **Customer identity maps reach the UI** — script display names and `TCnnn` prefixes on Run
  Tests, reports and campaign tables came from a platform file frozen in June, while the
  customer's own `script_identity_map.json` only fed the server and was even left out of the
  release bundle; both copies are now customer configuration deployed from the overlay like the
  branding, and the platform ships an empty map ·
  [BUG-0066](../bugs/BUG-0066-2026-09-09-identity-map-ui-reads-stale-platform-copy.md)
- **CI `web-script-local-debug` could not fail** — the job now requires `SCRIPT_SUCCESS:true` from each script instead of trusting the always-0 exit code; `browser-use` is installed for `browser_task`; the playback smoke is now `dailymotion_video_check` because YouTube's anti-bot wall blocks the runner's datacenter IP, and `youtube_video_check` names that interstitial instead of "playback not confirmed" · [BUG-0067](../bugs/BUG-0067-2026-09-08-web-script-ci-job-green-on-script-success-false.md) · `this commit`
- **`/server/api-testing/categories`, `/run`, `/quick` always 500** — `TEST_CONFIG` was read but
  never defined · [BUG-0066](../bugs/BUG-0066-2026-09-08-api-testing-test-config-undefined-500.md) · `this commit`

## build 8713 — 2026-09-08

### ✨ Features
- **Run Tests: VS/S/TC filter, common-file hiding, per-script environment** — the
  type filter splits virtual scripts into their own **VS** chip (previously lumped
  into **S**); `common_*.py` library files are hidden from the runnable list, same
  convention as the existing `utils_`/`lib_` exclusion; the single global dev/test/prod
  Environment selector next to Run is replaced by a per-selected-item selector
  (Selected Items row) restricted to the rows that actually exist for that script, so
  a prod-only script just shows Prod instead of silently falling back · `988ed4a83`
- **CI/CD Reports page caches the runs list and refreshes only what changed** — the page
  re-read all 200 runs with their jobs on every tick (every 15 s while a run was in flight) and
  again on every visit. The list now persists in the browser and each refresh asks the server
  only for runs that started or had a job finish since the newest timestamp already held
  (`GET /server/cicd/runs?changed_since=<ISO>`), merged over the cached rows; a full reload
  still happens on the toolbar Refresh button, when nothing is cached, and every 30 min. Jobs
  re-ingested through `/server/cicd/ingest` now bump `finished_at` like the self-hosted psql
  path, so a re-run job is picked up by the delta
- **Heatmap incidents click through to the Alerts page** — in the Data Analysis table, a red
  Audio No / Blackscreen Yes / Freeze Yes cell opens the Alerts page in a new tab focused on that
  host/device incident at the frame time (row expanded, scrolled into view, outlined); a warning
  says so when no matching incident exists
- **Virtual scripts can be grouped into folders** — the Virtual Scripts editor's "Scripts"
  rail was one flat alphabetical list; it now has a **Folder** field (select existing or
  type new, same UX as testcases) and groups the rail by folder, reusing the shared
  `folders` table testcases and disk scripts already use. Folder carries forward on
  promote (dev → test → prod) · `features/virtual-scripts/` · TASK-11 · 🗄 DB migration
  `20260907c_virtual_scripts_folder.sql`
- **CI/CD Reports shows every runner, not just the last one used** — the page drew one card
  per project (the runner that executed that project's latest run), which hid the rest of the
  fleet now that each repo is served by several runners. It now renders a card per registered
  runner with that runner's own last run, and skips the synthetic github-hosted row. The
  section is collapsible, cards are fixed-size, and a busy runner names the job it is
  executing and how long it has been going ·
  `features/cicd/frontend/CICDReportsPage.tsx`
- **Audio/Video quality metrics (AVQ)** — every monitored device records a per-minute quality row
  (`quality_metrics`): video availability with black/freeze/macroblock coverage, audio loudness
  (LKFS) and level (dB), plus optional subtitle (OCR), speech transcription (Whisper) and
  translation availability with the recognised text; a per-minute video/audio MOS summarises the
  channel. 7-day retention; surfaced on the device page and the live overlay ·
  `backend_host/scripts/avq_monitor.py` · 🗄 DB migration `setup/db/schema/039–044_quality_metrics*.sql`
- **Virtual scripts get a dev/test/prod lifecycle** — editing always writes the **dev**
  version; **Promote** copies dev → test → prod. Promote-to-prod stamps a prod version
  and keeps the previous prod source for one-click rollback (click the prod chip →
  Restore). The Virtual Scripts editor shows env chips + a Promote button; the scripts
  rail shows per-env dots · `features/virtual-scripts/` · TASK-07 · 🗄 DB migration `20260904_virtual_scripts_environments.sql`
- **Convert a disk script to a virtual script** — a **Convert to virtual** button on
  Run Tests turns a selected on-disk Python script into an identical virtual script (its
  dev version), editable in-app with no redeploy; re-converting overwrites the dev source ·
  `features/virtual-scripts/` · TASK-07
- **Run a dev vs prod virtual-script version in parallel** — Run Tests' Environment
  selector now resolves a virtual script to its dev/test/prod row, so a dev run and a prod
  run of the same script go at once on separate devices · TASK-07
- **CI/CD is now an optional feature with its own pages** — `features/cicd/`: **Test → Report ›
  CI/CD Reports** (moved out of Settings, reads the `cicd` schema instead of the report dirs,
  with Trigger and Suite columns) and a new **Test → Execute › Run CI/CD** that launches a
  workflow for a chosen project, branch, suite (white / grey / all) and runner (the LAN
  runner or GitHub-hosted capacity), shows queued/running runs live and logs every dispatch.
  Registry lives in `ci_projects`, editable from the page; deny-listed for the customer
  overlay · `features/cicd/`
- **CI/CD results in their own database + Grafana** — every project's workflow (virtualpytest,
  sample-app) records runs and jobs (white-box / grey-box layer) in a dedicated `cicd` Postgres
  database; new Grafana datasource *CI/CD Database* and dashboard *CI/CD Quality* (pass rates,
  per-layer trend, jobs and runs tables with report links); existing report dirs backfilled ·
  `features/cicd/db/` · 🗄 DB migration `features/cicd/db/` (001_cicd_schema, 002_ci_projects, 003_app_role_writes — separate `cicd` Postgres db)
- **CI/CD Reports: time range + live runner per project** — Grafana-style range picker
  (24h / 7d / 30d / all) drives the stat tiles and the run table; one runner card per project
  shows the runner that executed its latest run with ALIVE / RUNNING / OFFLINE from GitHub ·
  `da2fff51b`
- **Backend pytest report reads as a run, not a file** — header is
  `virtualpytest #<run> · <branch> · <sha> · <date>` and results list Passed → Failed → Skipped ·
  `da2fff51b`
- **Self-Test dashboard: per-script table** — last run / result / report per script with runs
  and pass % over the selected window; stat tiles follow the time range; the vpt `smoke_*`
  scripts record under `virtualpytest_web` so they feed the dashboard · `fe422bf56` `8eedde984`
- **Script report: step mosaic** — one compressed JPEG (one tile per step, OK/FAIL header,
  ~60 KB for 10 steps) built from local screenshots and uploaded next to `report.html`; shown
  in a "Test Mosaic" section (collapsed by default, click to zoom) and as a new-tab link in
  the summary bar; URL kept in `script_results.metadata.mosaic_r2_url` for later Grafana use ·
  `dd20a2074` `6d4f1d723`
- **Step mosaic actually builds on real runs now** — it was built after the executor had
  already uploaded-and-deleted the local screenshots it needed, so it silently never appeared;
  now built before that upload ·
  [BUG-0046](../bugs/BUG-0046-2026-09-03-step-mosaic-never-appears-on-real-runs.md) · `a4982b67b`
- **Campaign report: one row per script, no expanding** — type, duration, result id and the
  Report / Logs / Source links sit on the row itself; a details panel only remains for scripts
  with inputs, outputs or an error
- **Offline customer deployments** — `build_customer_bundle.sh` packs platform + customer overlay
  into one `vpt-<name>-<version>.tar.gz` for sites without GitHub access; `update_core.sh` deploys
  it as usual and now reconciles feature systemd units on every host via
  `reconcile_feature_units.sh`
- **Script executions are tagged dev / test / prod** — every script run now records which
  capacity it executed in (`script_results.environment`, default `prod` when unspecified);
  Run Tests gets an Environment selector (defaulting to Prod), and the `execute_script` MCP
  tool takes an optional `environment` param · `12a74b8c2` · 🗄 DB migration `20260901_script_results_environment.sql`
- **Grafana dashboards filter by Environment** — script-results, kpi-measurement,
  ookla-speedtest, dns-lookup, superping, campaign-results, fullzap-results, and
  all-zapping-events all get a dev/test/prod filter; the discard-review queue is hardcoded to
  prod only, since only real production failures should feed that workflow ·
  `96884c077` `99b3839e2`
- **Network/host diagnostic scripts skip screenshot & video capture** — `device_get_info`,
  `dns_lookuptime`, `ookla_speedtest`, and `superping` no longer capture or upload initial/final
  screenshots or an execution video, since these scripts have no meaningful visual state; new
  `capture_artifacts` flag on `@script(...)` controls this per script · `714c905b8`
- **Playwright browser closes automatically after web test scripts finish** — Facebook/YouTube/
  Netflix/etc. runs no longer leave Chrome/WebKit running on the host; set `VPT_KEEP_BROWSER_OPEN=true`
  on a host to opt back into the old always-on behavior · `b1215e846`
- **KPI scan mosaic always shows the action, before-match, and after-match frames** — near-duplicate
  frames are still collapsed for readability, but the frame right after the button press and the
  frames immediately bracketing the match are now force-kept (orange border) so the transition is
  always visible, plus a permanent legend under the mosaic explains the frame selection · `1646ffc8a`
- **Zap script reports link the per-event zap measurement report** — `zap_digit` / `zap_chup`
  now show a **View Zap Report** link on each zap step and a **Zap Report** link in the header,
  opening vpt-monitor's full measurement report (transition frames, total/freeze durations,
  audio silence) for that zap · `459c162d1`
- **Zapping dashboard aligned with KPI Measurement** — All Zapping Events gets the same header
  stats (Total Zaps / Failures / Success Rate; failure = zap script run without detected zapping),
  a Global Activity panel, and a Failed Zap Runs table listing those failed runs with error and
  report link · `48349a268` `07002a7f6`
- **Script and KPI report links on the zapping events table** — the All Zapping Events table gets
  the same Script Report / KPI Report link columns as the SRI KPI-measurement Details table · `93c2d5c2b`
- **Web tests log their Playwright flow and diagnose browser deaths** — local-debug web scripts now
  print CDP connect + per-phase/per-action trails, confirm the browser actually closes at test end
  (SIGTERM→SIGKILL), name any browser already holding the CDP port, and on a "browser has been
  closed" failure report whether the tab, the whole browser, or an external process was the cause
  (filled values like passwords never logged) · `e0533c094`
- **Bulk-select targets in the device filter** — the "All Targets" dropdown gets a Select all /
  Clear row below the search box; both act on the currently searched options · `e5c98af82`
- **KPI runs end on a user-selected closing edge** — Run Tests gets an optional `closing_edge`
  dropdown; when set, the run executes that edge after measurement (e.g. to fully close an app)
  instead of always returning to `home`; left blank, the device is left where the run ended. The
  closure runs after the verdict so it never affects the result · `817a30910`
- **KPI reports show the measurement start and end timestamps** — the header leads with
  Measurement Start (key press) and Measurement End (match frame) instead of burying them · `aaf166e24`
- **Run a script against multiple variants at once** — the Run Tests variant dropdown is a
  checkbox multi-select producing a composition (e.g. `variant1+variant2`) · `bb0370618`
- **Selection panels flag variant scope** — a variant edge/node panel gets a blue outline and a
  "v" badge so it's obvious you're editing a variant, not base · `038c087a5`
- **UserInterface dev/prod versioning** — every interface is an editable dev copy publishable to a
  read-only prod snapshot (gold `prod` badge); republish syncs in place so prod's KPI/metric trends
  survive, with a per-publish history log; pick dev or prod on the Interface page, editor and Run
  Tests (`--ui-mode prod`) · `0024ccce8`..`cd815be14` · 🗄 DB migration `20260723_userinterface_dev_prod.sql`
- **Web script reports include per-page DOM captures** — every navigated page's DOM is saved once
  per execution (re-captured only on change), uploaded next to `execution.txt` and listed under an
  expandable **🌐 DOM captures (N)** row; captures are stripped and line-broken so two executions
  diff cleanly · `255ac8f33`, `7d7a3eedc`, `11914ac50`

### 🔒 Security
- **User, team and workspace administration is admin-only** — those routes authenticated the
  caller but never checked their role, so any signed-in tester or viewer could list every user
  account and create or delete teams and workspaces; they now return 403 for non-admins (the
  service `X-API-Key` still passes, and a signed-in user keeps reading their own workspace
  memberships) · [BUG-0061](../bugs/BUG-0061-2026-09-08-user-team-workspace-routes-had-no-role-check.md)

### 🐛 Bug fixes
- **Web-test hosts get working audio capture and stable X11 auth** — the host installer
  never wrote `xhost +local:` into the VNC xstartup, so x11grab depended entirely on
  `.Xauthority` cookie matching and could fail with "Authorization required"; it also never
  enabled `HOST_VIDEO_AUDIO`, so a crashed PulseAudio daemon had no self-heal path and could
  stay dead for hours with nothing noticing · `install_host.sh` now writes both by default ·
  [BUG-0065](../bugs/BUG-0065-2026-09-08-web-host-vnc-pulseaudio-xhost-install-gap.md)
- **Open-mode servers can save test cases again** — with `SERVER_OPEN_MODE=true` the guard let
  requests through without naming a principal, so every permission- or role-gated write (QuickTest
  / test case save, campaign create/execute, user admin) answered 500 "Configuration error"; open
  mode now grants `SERVER_PUBLIC_ROLE` (default admin), like the no-JWT `X-Server-Key` path ·
  [BUG-0064](../bugs/BUG-0064-2026-09-08-open-mode-gated-routes-500-no-principal.md)
- **Run Tests loads on deployments without the virtual-scripts schema** — the executables list
  always queried the optional `virtual_scripts` table, so a customer install with the feature
  disabled and its migrations never applied lost the entire Run Tests list (disk scripts and test
  cases included); the table being absent now just lists no virtual scripts ·
  [BUG-0063](../bugs/BUG-0063-2026-09-08-run-tests-list-fails-without-virtual-scripts-table.md)
- **Team membership rows now reference their team** — `team_members` had no foreign key on
  `team_id`, so nothing stopped a membership pointing at a deleted team, and PostgREST could not
  resolve the `team_members → teams` relationship, which made every single-user lookup fail ·
  [BUG-0062](../bugs/BUG-0062-2026-09-08-anon-key-server-blocked-by-profiles-rls.md) · 🗄 DB migration `20260908c_team_members_teams_fk.sql`
- **User admin, role edits and team membership work again** — the server reads Supabase with the
  anon key and no auth context, so every direct `profiles`/`team_members` access was filtered out
  by RLS: opening any user 404'd, permission edits reported "User not found", and adding a team
  member silently added nothing; single-row reads and writes now go through SECURITY DEFINER RPCs
  like the users list already did · [BUG-0062](../bugs/BUG-0062-2026-09-08-anon-key-server-blocked-by-profiles-rls.md) · 🗄 DB migration `20260908a_admin_profile_team_member_rpcs.sql`
- **In-app documentation is back** — every `/docs` page showed "Error Loading Documentation"
  after the doc build was killed by its own timeout part-way through replacing `public/docs`;
  the docs are now staged and swapped in only when complete, so a slow build leaves the previous
  docs serving instead of none · [BUG-0060](../bugs/BUG-0060-2026-09-07-docs-pipeline-timeout-wipes-public-docs.md)
- **Pathfinding stats/status/alternatives return a proper 400 JSON when team_id is missing** — a GET
  with a JSON content-type and no body hit werkzeug's generic 400 instead; storage health is a public
  liveness probe again; four CI-only test fixes · [BUG-0059](../bugs/BUG-0059-2026-09-07-seven-standing-backend-ci-test-failures.md) · `11850f82c`
- **Queued, scheduled, and batch runs of a virtual script now run the right
  dev/test/prod row** — the deployment scheduler already knew how to run a virtual
  script but was never given its id: a script queued because its device was locked,
  part of a 2+-script batch run, or scheduled for later either ran the wrong version
  or was misclassified as a DB campaign · [BUG-0059](../bugs/BUG-0059-2026-09-07-deployment-scheduler-drops-virtual-script-id.md) ·
  `988ed4a83` · 🗄 DB migration `20260907d_deployments_virtual_script_id.sql` (already applied on DB)
- **CI backend test job no longer reports green with a missing report** — a test overrunning the
  30 s timeout aborted pytest before the HTML was written; the job now fails that test only, keeps
  the report, and only links a report that exists · [BUG-0058](../bugs/BUG-0058-2026-09-07-ci-backend-report-missing-after-timeout-abort.md) · `ee4a5693d` `40037aa60`
- **Report pages open again in a new tab while logged in** — CI/CD, DOM and API-testing reports
  answered 401 after the `/server/*` lockdown because a browser tab cannot send the JWT header;
  the session credential is now mirrored into a `Path=/server/`, `SameSite=Strict` cookie the
  server accepts for GET only · [BUG-0057](../bugs/BUG-0057-2026-09-07-report-pages-401-new-tab-after-server-lockdown.md) · `0224543ad`
- **Heatmap refreshes again after the /server/* lockdown** — the heatmap processor, MCP client, agent
  alerts tool and DB-backup status POST now send the service `X-API-Key`; they had been getting 401
  from their own server since build 8654 · [BUG-0055](../bugs/BUG-0055-2026-09-07-heatmap-processor-401-after-server-lockdown.md) · `1d2e70e0f`
- **Team permissions are applied again** — every direct read of `team_members` by a signed-in
  user (or the anon key) failed with "infinite recursion detected in policy"; the frontend
  swallowed it, so the union of team permissions was always empty. Policies rebuilt on
  SECURITY DEFINER helpers `is_team_member()` / `is_team_owner()` ·
  [BUG-0054](../bugs/BUG-0054-2026-09-07-team-members-rls-infinite-recursion.md) ·
  🗄 DB migration `20260907b_studio_lint_hardening.sql` (already applied on prod DB)
- **Supabase Studio advisor cleared of ERRORs and perf warnings** — five views now run as
  the caller (`security_invoker`), 50 functions pin `search_path`, trigger / unused SECURITY
  DEFINER functions are no longer callable by anon, open RLS policies no longer call
  `auth.*` per row, `profiles` / `team_members` have one policy per command ·
  [BUG-0053](../bugs/BUG-0053-2026-09-07-studio-advisor-security-performance-warnings.md)
- **Five tables no longer flagged "RLS disabled" in Supabase Studio** — the newer
  `ai_userinterface_*` tables, `device_control_sessions` and `quality_metrics` were created by
  migrations that skipped the standard RLS-on + open-policy block; now aligned with every
  other table (no change in effective access — authz lives in the server layer) ·
  [BUG-0052](../bugs/BUG-0052-2026-09-07-rls-disabled-on-five-public-tables.md) ·
  🗄 DB migration `20260907_enable_rls_missing_tables.sql` (already applied on prod DB)
- **CI/CD runner restart button now restarts the runner you clicked** — with several runners
  per VM it resolved every unknown name to VM 163 and then picked the first `actions.runner.*`
  unit on the box, so restarting a virtualpytest runner restarted the sample-app one ·
  [BUG-0050](../bugs/BUG-0050-2026-09-07-cicd-restart-button-targets-wrong-runner.md)
- **`GET /server/campaigns/results` no longer 500s** — it built its response from keys
  (`campaign_results`, `count`) that `get_campaign_results()` never returns (it returns `data`),
  raising a `KeyError` on every successful call ·
  [BUG-0049](../bugs/BUG-0049-2026-09-06-campaign-results-route-keyerror-500.md) · `e0b95183c`
- **Re-running a virtual script works** — the rerun (↻) icon dropped `virtual_script_id`,
  so a virtual-script rerun looked for a non-existent disk file; it now replays the exact
  dev/test/prod version that ran · [BUG-0048](../bugs/BUG-0048-2026-09-04-virtual-script-rerun-loses-id.md) · `3cb7388ad`
- **Rec lock badge now shows who AND what** — a script launched while a user holds
  the device runs under that user's lock, so only the user's name ever showed; the
  badge/tooltip now show the lock owner and the running script together ·
  [BUG-0047](../bugs/BUG-0047-2026-09-04-rec-lock-badge-shows-owner-or-script-never-both.md) · `9de8c8dd4`
- **Agent Dashboard "Failed to fetch"** — `/server/agents` answered a 308 to the slash URL built as `http://` behind the proxy, blocked as mixed content · [BUG-0045](../bugs/BUG-0045-2026-09-03-agent-dashboard-failed-to-fetch-http-redirect.md) · `25e138f1e`
- **CI pipeline dead** — runner VM lost DNS and its GitHub registration, and an invalid
  `runner.labels` guard had skipped every report upload since July · [BUG-0043](../bugs/BUG-0043-2026-09-03-ci-pipeline-dead-runner-offline-reports-never-saved.md) · `140d5794e` `da2fff51b`
- **vpt smoke scripts always failed on host checks** — relative `/host/<name>` URL used without
  the server origin · [BUG-0044](../bugs/BUG-0044-2026-09-03-vpt-smoke-scripts-relative-host-url.md) · `8eedde984`
- **Script report: "Test Steps" header now collapses/expands the step list** — the container
  carried a permanent `steps-expanded` override so the toggle never hid anything, and the
  expanded arrow rendered as ◀ (rotation stacked on the glyph swap) ·
  [BUG-0042](../bugs/BUG-0042-2026-09-03-report-steps-section-never-collapses.md) · `59b1ff96e`
- **BLE remote: pairing window closes once a bond exists** — a foreign BLE device could pair or
  simply connect to an already-bonded dongle and lock the STB out ("lost pairing"); the daemon now
  keeps Pairable off while bonded, drops unbonded peers, the agent rejects other addresses, and
  the advert is locked to the bonded STB through the controller's filter accept list ·
  [BUG-0041](../bugs/BUG-0041-2026-09-02-ble-foreign-central-grabs-bonded-adapter.md) · `5c1fb1518` `bba5922de`
- **BLE daemon no longer floods the journal on every keypress** — dropped needless `sudo` audit
  lines when already root and log the multi-bond warning once per change; `diagnose_ble.sh`
  now writes clipboard-sized per-section files with squashed logs and a time window ·
  [BUG-0039](../bugs/BUG-0039-2026-09-02-ble-daemon-journal-flood-hides-incidents.md) · `7c091bf8e`
- **Status page: fixed 403-on-refresh and misleading health/backup/runner info** — nginx's
  internal metrics endpoint was shadowing the app's `/status` route (403 on a real page
  refresh), and DB Backup / GitHub Runners were reading whichever server was selected in
  the picker instead of the primary server, showing "no backup" / "GITHUB_TOKEN not set"
  when a secondary server was selected ·
  [BUG-0038](../bugs/BUG-0038-2026-09-01-status-page-secondary-server-and-status-route-collision.md) · `fdba2d6fc` `7b7ee83d2`
- **Android TV remote button overlays recentered on the artwork** — the floating remote
  panel's hit-boxes had drifted off their icons (worse the further down the remote),
  and the scale used to place them now comes from the container's actual rendered size
  instead of an estimate ·
  [BUG-0037](../bugs/BUG-0037-2026-08-21-android-tv-remote-button-overlay-misalignment.md) · `219a86689` `63b83217b` `17e9878dc`
- **Conditional edges no longer log false KPI failures** — when an edge diverges to a valid
  conditional sibling (e.g. `apps_disney → disney_home` lands on `disney_profile`) and the nav
  recovers, the executor no longer records a corrupting skip/failure KPI on the intended edge;
  instead it measures the transition that actually happened (`apps_disney → disney_profile`) as a
  success alongside the recovered `disney_profile → disney_home` — two clean measurements ·
  [BUG-0036](../bugs/BUG-0036-2026-07-29-kpi-conditional-divergence-recorded-as-failure.md) · `a3d1ad0f7`
- **Rec lock badge shows for every running script** — the preview/modal lock icon no longer
  depends on parsing a script name out of the lock: scheduler and campaign locks (whose
  lock_reason carries a UUID) now show it too, the scheduler lock names the deployment, and
  script execute announces its lock immediately instead of at the next 15s poll ·
  [BUG-0035](../bugs/BUG-0035-2026-07-29-rec-lock-badge-missing-for-execution-locks.md) · `9e406abf3`
- **KPI reports show every hop of a conditional multi-hop path** — a run whose selected edge
  crosses a conditional intermediate node (e.g. `apps_disney → disney_home` via `disney_profile`)
  no longer reports FAILED with "no KPI rows"; the recovered continuation hop is attributed and
  each traversed edge gets its own titled KPI block, so both hops are visible and the run reads
  SUCCESS (recovered) ·
  [BUG-0034](../bugs/BUG-0034-2026-07-29-kpi-conditional-multihop-recovered-edge-dropped.md) · `a18a83bbc`
- **Force take-control really stops the running script** — abort/timeout now kill the script's
  whole process group; previously only the `bash -c` wrapper died and the orphaned python kept
  driving the device while the takeover reported success ·
  [BUG-0033](../bugs/BUG-0033-2026-07-29-abort-kills-bash-wrapper-python-orphaned.md) · `e9111a393`
- **Report videos actually show the test** — COLD-chunk backfill now maps wall-clock time onto
  each chunk's real timeline (mtime + ffprobe) instead of the nominal 10-min boundary (was up
  to 60s of pre-test footage), missing seconds at the COLD→HOT seam are reported as gaps, and
  every extraction logs `FINAL VIDEO: window … | media … | missing …`; the merged file's
  duration is now accurate (was inflated ~9× by a concat timescale mismatch) ·
  [BUG-0032](../bugs/BUG-0032-2026-07-28-report-video-cold-chunk-time-shift.md) · `4d255ee81`
- **Zap runs stop failing on near-static live content** — the post-zap motion check widens its
  compare window to 2s and treats the first (warm-up) channel entry as non-blocking, so a
  playing-but-static scene no longer sinks the run or loses the KPI; `zap_chup` also now
  actually enforces the motion verdict (was always-pass) ·
  [BUG-0031](../bugs/BUG-0031-2026-07-28-zap-motion-false-positive-static-content.md) · `96e1afa9e`
- **Goto verifications survive a mid-run cache clear** — a whole-tree navigation cache clear
  landing during an action's wait no longer fails the run with "no unified graph loaded"; the
  verifier re-syncs the graph like the execute path ·
  [BUG-0030](../bugs/BUG-0030-2026-07-28-goto-verification-graph-blanked-by-cache-clear.md) · `dd2207b71`
- **Standby edge picker follows a re-wired variant** — selecting a variant that moves the
  into-standby edge (e.g. `home → standby`) refreshes the Run Tests edge dropdown instead of
  greying it out · [BUG-0029](../bugs/BUG-0029-2026-07-28-standby-edge-variant-rewire-filter.md) · `9a90800e6`
- **Fleet health report stops flagging VNC hosts as DEGRADED** — static desktop and missing audio
  are normal on `host_vnc` models, not freeze/audio-loss faults ·
  [BUG-0028](../bugs/BUG-0028-2026-07-26-fleet-report-vnc-host-false-degraded.md) · `fda35f908`
- **In-app bug links open again** — clicking a bug in Docs › Bugs no longer errors "received HTML
  instead of Markdown"; the viewer resolves bare relative links against the current section ·
  [BUG-0027](../bugs/BUG-0027-2026-07-24-docs-viewer-relative-link-drops-section.md) · `3ed999f34`
- **Device tags survive service restarts** — host registration no longer wipes `device_flags`;
  Grafana filter label renamed Flag → Tag on all dashboards · [BUG-0026](../bugs/BUG-0026-2026-07-24-device-tags-wiped-on-restart.md) · `16a7ae5a5`
- **Single-iteration KPI runs skip the reverse leg** — no wasted walk-back on `--iterations 1` ·
  [BUG-0025](../bugs/BUG-0025-2026-07-24-single-iteration-kpi-reverse-leg.md) · `a3705d03c`
- **BLE remote won't chase a stale duplicate bond, and Resume can't silently re-pair** — the wake
  picker prefers the connected/HID-subscribed bond · [BUG-0024](../bugs/BUG-0024-2026-07-24-ble-stale-duplicate-bond.md) · `352c288b5`
- **Editing a conditional sibling's KPI name/threshold no longer unlinks it** — the dialog shows and
  saves the sibling's own values; unlink only when action lists change · [BUG-0023](../bugs/BUG-0023-2026-07-24-conditional-sibling-kpi-edit-unlinks.md) · `5cf930321`
- **Navigation edges draw in the direction you connected** — dropped the lexicographic handle
  normalization; the panel shows both directions in one orientation · [BUG-0022](../bugs/BUG-0022-2026-07-23-nav-edges-wrong-normalized-direction.md) · `93f30c43f`
- **Variant node moves stage, save, and survive reload** — ReactFlow drag-end + composition resolver
  fixes · [BUG-0021](../bugs/BUG-0021-2026-07-23-variant-node-moves-not-staged.md) · `4dcc21ac6`
- **Variant edits stage like base** — yellow Save arms, one write persists, Discard reverts (edge row
  + enable marker on the same Save) · [BUG-0020](../bugs/BUG-0020-2026-07-23-variant-edits-not-staged.md) · `fe70ba488`
- **Deleting a variant cleans up its orphaned nodes/edges** — plus a `sweep-orphans` repair endpoint ·
  [BUG-0019](../bugs/BUG-0019-2026-07-23-variant-delete-orphans-hidden-rows.md) · `1a1d3a284`
- **KPI report drill-down links no longer 404** — prefixed with the `/grafana` subpath ·
  [BUG-0018](../bugs/BUG-0018-2026-07-23-kpi-report-drilldown-404.md) · `523fa9b72`
- **Variant edge panel refreshes live on action-set delete** — the selection tracks its recomposed
  counterpart · [BUG-0017](../bugs/BUG-0017-2026-07-23-variant-edge-panel-no-refresh-on-action-set-delete.md) · `aac39d5ff`
- **No "Confirm Action" flash on dialog close** — the dialog keeps its title through the fade-out ·
  [BUG-0016](../bugs/BUG-0016-2026-07-23-confirm-action-dialog-flash.md) · `c677f54c4`
- **Docs pages render inline code inline and hide process sections** — react-markdown v10 renderer fix ·
  [BUG-0015](../bugs/BUG-0015-2026-07-23-docs-viewer-inline-code-process-sections.md) · `045df5a2d`
- **Variant edge authoring: draw-over-hidden reveals, create works with its "v" badge** — scope-aware
  reveal + synchronous enable-marker write · [BUG-0014](../bugs/BUG-0014-2026-07-23-onconnect-blocked-by-hidden-edge.md) · `e42a720a9`
- **Atlas chat no longer hangs on the second message of a conversation** — a reused session's
  completion event was mistaken for a stale duplicate; byte-identical tool-result payloads no longer
  wedge "Waiting for response…" · `499836aa7`
- **Atlas no longer confuses device names with device_ids** — its device context lists each device's
  `host_name` and per-host `device_id` explicitly · `0d050b599`
- **Report step timing shows h/m/s only** — Start/End render as `14H32m33s` (was `14H32m33s.864ms`)
  and sub-second durations as `0.9s` (was `864ms`) · `1fb1729df`
- **Agent docs deduplicated on the demo branch** — 51 stale top-level `docs/agent/` copies removed,
  Langfuse section folded into `infra/INFRA.md`, docs index regenerated · `acb31b1ac`

### 🔒 Security
- **Path traversal and SSRF closed in host and server routes** — capture/image/stream/transcript
  paths, heatmap storage keys, the JIRA domain, `proxyImage` parameters, the Postman runner's
  targets, the code-deployment `storage_path`, CI/CD report ids and the MCP screenshot fetch's `Host` are now validated (realpath
  containment, hostname/port/id character sets, registered-host allow-list); `/server/system/source/*`
  requires an admin JWT. Snyk's 78 `jsonify` XSS hits triaged as false positives in `.snyk`;
  the security dashboard header now counts npm audit too. **Host deploy step:** run
  `sudo -u vpt_user /opt/virtualpytest/venv/bin/pip install 'defusedxml>=0.7.1'` on every host
  (adb XML parser; `update_core.sh` does not pip install) ·
  [BUG-0056](../bugs/BUG-0056-2026-09-07-path-traversal-ssrf-hardening-security-dashboard-highs.md) · `ba876e7c1` `d78e4e4df` `86705b065` `056cac3e4`
- **Live credentials and hard-coded auth defaults removed from the tree** — the production MCP
  secret in a fixture, the real Supabase JWT secret as the installer default, a well-known default
  MCP bearer (the route now fails closed with `503` when `MCP_SECRET_KEY` is unset), the anon key in
  docs/examples, and Google API keys inside stale Snyk SARIF reports; screenshot fetch keeps TLS
  verification on for non-local URLs. Key rotation tracked in TASK-08 ·
  [BUG-0051](../bugs/BUG-0051-2026-09-07-live-credentials-committed-in-tree.md) · `969a714a5` `997499a06`
- **Production frontend no longer runs an internet-exposed Vite dev server** — switched to a
  build+serve service and restored `fs.strict:true`, closing an arbitrary-file-read hole an
  automated scanner was actively probing (world-readable `.env` with the auto-sign auth-bypass
  token was one guessed path away); nginx origin also now only accepts Cloudflare + LAN traffic ·
  [BUG-0040](../bugs/BUG-0040-2026-09-02-vite-dev-server-prod-exposure-arbitrary-file-read.md) · `92c933fa2` `6790814c4`

---

## build 8414 — 2026-07-23

### ✨ Features
- **Release notes and bug reports are browsable in the app** — a new Docs › Release Note page and
  linked bug reports
- **KPI report: browse every analyzed frame's verification evidence** — a frame-selector strip swaps
  each reference card to that frame's crop/overlay/score · `93fee87b1`
- **KPI Measurement dashboard counts real failures and drills into a per-script report** — Model
  filter, failure + over-threshold counts, and a KPI Test Report drill-down · `c82e89976`
- **Filter Grafana dashboards by device flags/tags** — a Flag dropdown across KPI, Script Results,
  Navigation Metrics, Occupancy and more, reusing the `device_flags` table
- **Variants can lay out shared nodes differently on the map** — per-variant node positions; cosmetic
  only, no execution/KPI change · `472ad0dd1`
- **Export / import a user interface** — download any interface as a portable `.vptree` bundle (tree +
  variants + reference images) and import it back · `343b783f1`
- **Reference and key dropdowns are searchable** — one shared `SearchableSelect` with auto-focused
  filtering replaces 7 copy-pasted Selects · `c1ad60d33`
- **Search box on the Device (Rec) page target filter** — free-text substring filter alongside the
  multi-select · `73bf61887`
- **Controlling user's name shown on manual device locks** — the Rec badge/tooltip shows who holds
  control instead of a generic label · `f575a924b`
- **Device occupancy history in DB** — every lock session recorded in `device_control_sessions` for
  occupancy dashboards · `a59b637c0`
- **AI prompt panel simpler and above the transcript overlay** — one Send → Run flow, no jargon · `67ed05907`
- **Interface page loads ~7× faster, tree saves ~10× faster** — single-request variant priming +
  one-query hierarchy read · `6d231e35b`
- **Interface page row actions moved into a single ⋮ menu** — frees the Variants/Models column width · `1acaf16b8`
- **Master documentation index for Atlas** — `docs/INDEX.md` gives every doc family a one-line
  "read this when…" entry; the `search-docs` skill reads it first · `b2440a7e2`
- **Atlas answers API questions from the OpenAPI specs** — the docs tools now cover
  `docs/api/specs/*.yaml`; the missing script-abort endpoint was documented · `3ca4c5bd8`
- **Auto-build: live-certified from-scratch rebuild of stb3, 50/50 edges** — profile screen
  discovered, per-validation certification report with presigned link, `--under <node>` subtree
  deepening; runbook `docs/agent/navigation/AUTOBUILD.md` · `9a818ef55`
- **Auto-builder models the hero Watch chip as its own node (`home_watch`)** — accent-fill focus
  detection, sibling rings always close, corpus-backed offline simulator (42/42 edges) · `727e51974`

### 🐛 Bug fixes
- **Deleting an edge direction on a variant no longer deletes it from base** — writes to each
  variant's override · [BUG-0013](../bugs/BUG-0013-2026-07-23-variant-edge-direction-delete-hits-base.md) · `51a32d479`
- **Deleting a userinterface clears its reference screenshots from storage** — removes the
  `reference-images/<id>/` and `navigation/<name>/` folders · [BUG-0012](../bugs/BUG-0012-2026-07-23-userinterface-delete-orphans-reference-storage.md) · `80fc0453e`
- **Test Reports filters reset when you switch workspace** — dropdowns and selection rebuild for the
  new workspace · [BUG-0011](../bugs/BUG-0011-2026-07-22-test-reports-filters-not-reset-on-workspace-change.md) · `66eb486e1`
- **Host-diagnostic script report steps show real timing** — timing centralized in the executor ·
  [BUG-0010](../bugs/BUG-0010-2026-07-22-script-steps-na-timing.md) · `ce9ba8ae6`
- **Capture streams no longer corrupt when the hot tmpfs fills** — catch-all stale sweep + OCR self-purge ·
  [BUG-0009](../bugs/BUG-0009-2026-07-21-hot-tmpfs-filled-by-unrotated-ocr-artifacts.md) · `718954808`
- **Rec preview no longer wedges on "Loading stream…"** — no native-HLS fallback on MSE browsers;
  in-place media recovery · [BUG-0008](../bugs/BUG-0008-2026-07-21-hls-preview-native-fallback-wedge.md) · `649a28500`
- **Virtual Scripts opens on the first saved script; "New" starts genuinely clean** — stale
  Interface/Variant seeds cleared on New and Delete ·
  [BUG-0007](../bugs/BUG-0007-2026-07-20-virtual-scripts-empty-editor-and-stale-new.md) · `6af64583e`
- **Force take-control now actually stops a scheduled test run** — correct device-id registration +
  honest abort reporting · [BUG-0006](../bugs/BUG-0006-2026-07-20-scheduled-script-survives-force-take-control.md) · `320490598`
- **KPI Measurement dashboard honours the Action Set filter** — all 18 panels now filter on it ·
  [BUG-0005](../bugs/BUG-0005-2026-07-20-kpi-dashboard-action-set-filter-ignored.md) · `407030187`
- **Edge KPI "Any can pass" verification setting now saves** — writes into the edge's `kpi_references` ·
  [BUG-0004](../bugs/BUG-0004-2026-07-20-edge-kpi-any-can-pass-not-saved.md) · `fd7bbca91`
- **BLE remote survives bluetoothd restarts** — the daemons detect the new bluetoothd and re-register ·
  [BUG-0003](../bugs/BUG-0003-2026-07-16-ble-gatt-lost-on-bluetoothd-restart.md) · `bd620fc5c`
- **BLE remote keys no longer dropped on stb4** — an exclusive per-adapter run lock stops a duplicate
  daemon splitting the key stream · [BUG-0002](../bugs/BUG-0002-2026-07-16-ble-duplicate-daemon-key-drops.md) · `bed7e2e07`
- **/remote-control metrics timeout on large interfaces** — added the partial composite index the RPC
  assumed · [BUG-0001](../bugs/BUG-0001-2026-07-15-remote-control-metrics-timeout.md) · `8a1906888`
- **Drawing an edge over a hidden one reveals it instead of dead-ending** — initial reveal fix (see
  BUG-0014 for the full authoring rework) · [BUG-0014](../bugs/BUG-0014-2026-07-23-onconnect-blocked-by-hidden-edge.md) · `f3804d7de`
- **Interface table action icons/headers no longer clipped** — Version/Variants columns retrimmed · `04fac380e`
- **Duplicating a userinterface is much faster; deleting no longer blocks** — parallel image copy,
  background storage reclaim · `04fac380e`
- **KPI report text verification badge reads "✓ MATCH / ✗ NO MATCH"** — matches the image card wording · `3f9229908`
- **Device page no longer keeps a filter from another workspace** — filters pruned to the active
  workspace's options · `6d0553d74`
- **Moving a node on a variant shows the unsaved indicator and saves on Save** — earlier variant-move
  staging fix · `13b138fa5`
- **Renaming a navigation node updates its connected edge labels** — labels derived live + rewritten on
  rename · `16d6df67d`
- **Variant "show disabled rows" toggle moved into the viewing-scope dropdown** — keeps the toolbar
  layout static
- **"Force Takeover" works against a device held by another manual session** — preempts a zombie/stale
  manual lock too
- **"Remote connection error" popups no longer stack** — a stable per-device toast id replaces piling up
- **A flapping USB video grabber no longer thrashes forever** — the watchdog detects the flap and idles
  the port before one clean restart · `674a6dfa5`
- **`vpt-host` no longer needs a manual restart after a cold reboot** — waits on `network-online.target` · `68678df41`
- **`kpi_display_label` migration backfill now runs** — rewritten as an id-keyed subquery, applied to dev · `943be2f44`
- **Imported/duplicated interfaces keep their system protection** — `is_system_protected` +
  `hidden_in_base` carried through · `119eefa0c`
- **Navigation tree "Restore version" works again — in place** — same ids preserved, batched statements · `f6474363c`
- **Root node's left handle is reserved for the entry edge** — server + editor reject other edges there · `08f44b7e8`
- **Parallel Atlas chat threads work, and switching the Server dropdown really moves the chat** —
  per-conversation sessions, per-worker serialized processing, `session_id`-stamped events
- **Atlas chat self-heals dead sockets** — endless reconnection, tab-wake liveness probe, and a 4s
  send-ack watchdog that rebuilds the socket and resends transparently
- **Atlas router always offers the docs tools** — `read_doc`/`search_docs` are reserved router slots;
  20/20 stability (was 13/20)
- **Two more MiniMax chat killers fixed** — hallucinated `LOAD SKILL` honored as a skill load ·
  `0388ab425`; thinking-only empty turns retried · `bbe0de16b`
- **Langfuse traces show latency, cost, and the question/answer** — real start/end times + model
  pricing for qwen3-next-80b and minimax-m2.7 · `d1cb67247`
- **Atlas no longer shows a premature "I don't have this information"** — narration alongside tool
  calls restricted to brief status notes · `358c6dd73`
- **Atlas chat survives parallel tool calls** — only the first tool call per round is kept in
  history, avoiding MiniMax error 2013 dead-ends · `40f8d2993`
- **Auto-build re-anchors to a pane row without needing the CV to see the row bar** — the row's
  index among its pane's rows drives the press count; clamp detection works with focus absent
- **Auto-build survives a transient capture outage and follows non-OK dives** — retried grabs never
  re-press keys; an already-classified node keeps its recorded kind/depth whatever key reached it
- **Auto-build certifies its BACK edges and tells settings dialogs apart** — late-render re-look
  kills the spurious second BACK, distinct modals split by dialog body, read-only panels no longer
  abort the explore round; new offline guard `depth2_identity_test.py` (78/78)
- **Auto-build validation stops goto-storming and certifies its reverse edges** — home-ring identity
  by underline x, off-ring fail-fast, repositioning cost surfaced in the certification report;
  50/50 edges pass (was 12 unreachable); offline device model `depth2_sim_stb3.py` · `ec08422f9`

### 🔒 Security
- **Frontend dependency CVEs cleared** — removed unused `redoc-cli`, bumped `postcss`; audit 0 critical /
  0 high · `b37bd2f85`
- **`.vptree` import hardened** — reject path-traversal/absolute reference paths; restrict report image
  fetch to http/https (SSRF) · `7d8f451cd`, `ab4470aad`
- **Security scanner now covers `shared/src`** — the Bandit/Snyk generator previously skipped it · `ab4470aad`
