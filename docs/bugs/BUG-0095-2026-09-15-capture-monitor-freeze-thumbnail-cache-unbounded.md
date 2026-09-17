# BUG-0095 — capture_monitor grows to ~4.9 GB: the freeze-thumbnail cache is unbounded, and the cleanup meant to bound it clears the wrong key

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                            |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0095                                                          |
| Reported  | 2026-09-15                                                        |
| Status    | **Fixed in code (pending deploy).**                                |
| Severity  | Medium (host memory pressure; no functional failure observed)      |
| Area      | `backend_host/scripts/detector.py` · `vpt-monitor`                  |
| Fixed in  | build 9151                                                          |

---

## Symptom

`capture_monitor.py` on vpt-pi1 reached **4.84 GB** of private dirty anonymous memory
after 7 days — roughly **700 MB/day** — with `smaps` showing it as one 4.4 GB region
rather than scattered allocator arenas, which points at a single structure growing.

## Ruled out first

- **Per-device caches and work queues** — all keyed by device or capture folder, so
  bounded at four entries; the work queues are `maxsize`-capped and hold only strings.
- **The `inotify` library**, where the main thread sits. Reproduced in isolation on the
  Pi at a matching 20 events/sec: **flat at 12.2 MB over 9831 events**.
- **A stuck thread** — `py-spy dump` showed every worker idle and healthy.

## Root cause — two bugs that only leak together

### 1. The disk-fallback append has no matching pop

The freeze detector compares each frame with the previous three and caches decoded
thumbnails to avoid re-reading JPEGs. Inside the lookup loop (`detector.py:251`):

```python
if prev_img is not None:
    cache.append((prev_frame_num, prev_img.copy()))   # no pop
```

The append at the end of the function is correct:

```python
cache.append((frame_number, current_img.copy()))
if len(cache) > 3:
    cache.pop(0)          # removes exactly ONE
```

The loop runs up to three times per frame and every cache miss appends. The single
`pop(0)` removes one element no matter how many went in, so the list nets **up to +3
entries per frame**, each holding a `.copy()` of a decoded numpy image.

Modelled over the real call pattern:

| frames | before | after |
|---|---|---|
| 1,000 | 3,000 entries | 8 |
| 10,000 | 30,000 entries | 8 |
| 100,000 (~1.4 h at 20 fps over 4 devices) | 300,000 entries | 8 |

### 2. The hourly cleanup clears a key that never exists

`cleanup_old_caches()` exists to bound exactly this, and it *was* being called — with
the wrong key. The caches are stored under `device_key = os.path.dirname(thumbnails_dir)`
(line 161); line 580 called `cleanup_old_caches(capture_dir)`. Verified on the Pi:

```
device_key (cache key): /var/www/html/stream/capture1/hot
capture_dir (cleanup) : /var/www/html/stream/capture1
MATCH? False
```

So `if device_key in _freeze_thumbnail_cache` never matched. It freed nothing, wrote a
timestamp under a key nobody reads, and logged **"Memory cache cleanup completed"** —
28 times in the journal. The same trap as BUG-0094's archiver: **the log said it ran.**

It also silently disabled the `_freeze_result_cache` and `_blackscreen_result_cache`
cleanups, which are keyed the same way.

Either defect alone is survivable. Together, nothing bounds the list.

## Fix

Bound the structure rather than patch the call sites, so no future caller can
reintroduce this:

```python
FREEZE_THUMBNAIL_CACHE_MAXLEN = 8
_freeze_thumbnail_cache[device_key] = deque(maxlen=FREEZE_THUMBNAIL_CACHE_MAXLEN)
```

- 8 = the three previous frames the comparison needs, the current one, and headroom so
  a burst of disk-fallback inserts cannot evict a frame about to be read.
- Both hand-rolled `pop(0)` trims removed — `maxlen` evicts.
- `cleanup_old_caches()` now uses `.clear()`, not `= []`; reassigning would drop the
  `maxlen` bound.
- The cleanup call moved to *after* `thumbnails_dir` is resolved and is passed
  `os.path.dirname(thumbnails_dir)`. It sat before that line only because the key was
  not available yet — which is how it came to be given `capture_dir`.

## Verification

Deploy, then confirm RSS is flat rather than climbing ~700 MB/day:

```bash
ssh vpt-pi1 'ps -eo pid,rss,etime,args | grep [c]apture_monitor'
# and the cleanup should now report real work:
ssh vpt-pi1 'journalctl -u vpt-monitor --since today | grep "Cache cleanup: Freed"'
```

Note `vpt-monitor` must be **restarted** for this to take effect — see BUG-0094, where a
long-lived service ran three-month-old code because file sync alone changes nothing.
