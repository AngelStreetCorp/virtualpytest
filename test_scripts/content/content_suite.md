# content_suite — the whole content surface, one case per feature

Tests the content surface of the TV apps on any platform the suite has an adapter for:
**radio**, **replay**, **video on demand** and **recording**.

A case is a surface, not a device. The same four cases run on the STB remote,
on the STB web UI and on the mobile UI; the adapter for the platform does the
mechanics, the harness does the lifecycle.

## Cases

| case | what it does | what "pass" means |
|------|--------------|-------------------|
| `radio` | opens the radio / tuner source, walks the stations at runtime and plays one | a station really played |
| `replay` | opens the replay catalogue, starts a programme and plays it | the programme really played |
| `vod` | opens the movies & series catalogue, starts a title and plays it | the title really played |
| `recording` | records a live programme, checks it is **listed**, then plays it **back** | the recording is listed AND plays back |

`recording` is deliberately three steps in one case. A recording that is listed
but does not play back is a **FAIL**, and a recording that never appears is a
**FAIL** too — the reason names the step that broke.

## The result line

Every case prints exactly one machine-readable line:

```
VPT_CASE_RESULT {"case":"radio","platform":"web","host":"host-clone-2","device":"host","status":"FAIL","cause":"product","duration_s":31.2,"reason":"playback did not start: video element paused after 8s"}
```

and the run ends with one summary line:

```
VPT_CASE_SUMMARY {"cases":4,"pass":2,"fail":1,"skip":1,"product":1,"infra":0,"coverage":1}
```

`status` is `PASS` / `FAIL` / `SKIP`. `cause` is the attribution, kept apart
from the status on purpose:

| cause | meaning | a defect to fix? |
|-------|---------|------------------|
| `product` | the surface was reached and behaved wrongly | **yes** |
| `infra` | the platform could not do the job: lease, deploy, connectivity, geo-block, no session | no |
| `coverage` | the surface is not reachable / not mapped in this UI | no — the test could not exercise it |

A case that fails because the device was busy, the host was down or the
account was geo-blocked is **not** a product defect. That split is the whole
point: an earlier benchmark was invalidated by mixing the two.

The rows are also written to `context.metadata['content_cases']`, so the
dispatcher can read them back from the persisted script result and not only
from stdout.

## Arguments

| argument | default | meaning |
|----------|---------|---------|
| `--cases` | `radio,replay,vod,recording` | which cases to run |
| `--platform` | `auto` | `auto`, `stb`, `web`, `mobile` |
| `--max_items` | `3` | how many catalogue items to try per case |
| `--play_seconds` | `12` | how long an item may play before it counts as not started |
| `--settle_ms` | `800` | pause after a navigation or a key press |
| `--motion_threshold` | `1.0` | frame-change percent that counts as playback on screen |
| `--motion_window_s` | `2.0` | seconds between the two frames compared by the motion probe |
| `--record_wait_s` | `45` | seconds to wait for a recording to appear in the list |
| `--continue_on_failure` | `true` | keep running the remaining cases after one fails |

## Platforms

| platform | device model | userinterface | how it plays |
|----------|--------------|---------------|--------------|
| `stb` | `stb` | `stb_tv` | IR remote keys + screen motion probe |
| `web` | `web` | the browser UI | Playwright; the `<video>` element's frame counter is the authority |
| `mobile` | `android_mobile` | `stb_android_mobile` | appium / element clicks + screen motion probe |

The platform is detected from the device model when `--platform auto`.

## Notes

* The web session is expected to be logged in before the run (the dispatcher
  does it). Without a session the web cases report `SKIP` / `infra`; no
  password is ever read from the repository, logged or put in a report.
* The operator's brand, domain and account live outside the repository. The
  web adapter takes the app URL from the platform's own tree at runtime.
* Run it over the fleet with `scripts/agent/vod_radio_dispatch.py`, which
  claims the leases, keeps one whole device per job and splits the failures
  into product and infra.
