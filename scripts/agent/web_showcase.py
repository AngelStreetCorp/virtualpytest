#!/usr/bin/env python3
"""TASK-161 — build and score the showcase web trees (`web-<site>`) with Forge + build-tree-web.

One site per run, one host lease per run, several sites in parallel on distinct hosts (TASK-146 gives every
run its own Chrome debug port and profile, and lets two browser-isolated runs sit on one device).

    python3 scripts/agent/web_showcase.py sites
    python3 scripts/agent/web_showcase.py pin minimax-m3-1-flash       # Forge routes -> a profile
    python3 scripts/agent/web_showcase.py restore                       # back to the pinned profiles
    python3 scripts/agent/web_showcase.py build --site wikipedia --host host-clone-2
    python3 scripts/agent/web_showcase.py score --site wikipedia
    python3 scripts/agent/web_showcase.py score --all

The site table below holds public URLs only — nothing tier-1 ever enters the repo. Artifacts (events,
run.json, route snapshots) go to `~/vpt-deliverables/web-showcase/`, outside every checkout.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, HERE)
import bench_tree_build as b  # noqa: E402  (plumbing: sql(), mcp(), chat(), q(), auto_sign())

ART = os.path.expanduser(os.environ.get("WEB_SHOWCASE_DIR", "~/vpt-deliverables/web-showcase"))
ROUTE_KEYS = b.ROUTE_KEYS
CTRL = b.CTRL

# ---------------------------------------------------------------- the sites

# screens: (node_id, label, url path or full URL). The path is the node's identity — verifications and
# edge actions are built from it, so a tree keeps verifying when the site shows another language.
SITES = {
    "wikipedia": {
        "ui": "web-wikipedia",
        "start": "https://en.wikipedia.org/wiki/Main_Page",
        "screens": [
            ("home", "Home", "/wiki/Main_Page"),
            ("current_events", "Portal Current events", "/wiki/Portal:Current_events"),
            ("sports", "Portal Sports", "/wiki/Portal:Sports"),
            ("science", "Portal Science", "/wiki/Portal:Science"),
            ("article", "Article", "/wiki/Switzerland"),
            ("article_talk", "Article talk page", "/wiki/Talk:Switzerland"),
            ("article_history", "Article history", "/wiki/Switzerland?action=history"),
            ("all_pages", "Special All pages", "/wiki/Special:AllPages"),
            ("search", "Search results", "/w/index.php?search=matterhorn&title=Special:Search"),
        ],
        "notes": "No cookie banner, no login. Portals are linked from the Main Page sidebar.",
    },
    "hackernews": {
        "ui": "web-hackernews",
        "start": "https://news.ycombinator.com/",
        "screens": [
            ("home", "Front page", "/"),
            ("newest", "Newest", "/newest"),
            ("best", "Best", "/best"),
            ("ask", "Ask HN", "/ask"),
            ("show", "Show HN", "/show"),
            ("comment", "Comment page", "/item?id=1"),
            ("submitted", "Submissions", "/submitted?id=news"),
            ("past", "Past", "/past"),
        ],
        "notes": "The most stable site of the batch: plain server-rendered HTML, no banner, no JS wall.",
    },
    "internetarchive": {
        "ui": "web-internetarchive",
        "start": "https://archive.org/",
        "screens": [
            ("home", "Home", "/"),
            ("texts", "Texts collection", "/details/texts"),
            ("movies", "Movies collection", "/details/movies"),
            ("software", "Software collection", "/details/software"),
            ("search", "Search results", "/search?query=python"),
            ("item", "Item detail", "/details/nasa"),
            ("about", "About", "/about"),
        ],
        "notes": "Details pages are heavy; give each navigation a longer wait.",
    },
    "openstreetmap": {
        "ui": "web-openstreetmap",
        "start": "https://www.openstreetmap.org/",
        "screens": [
            ("home", "Map", "/"),
            ("about", "About", "/about"),
            ("help", "Help", "/help"),
            ("copyright", "Copyright", "/copyright"),
            ("history", "History", "/history"),
            ("tags", "Tags", "/tags"),
            ("directions", "Directions", "/directions"),
            ("search", "Search results", "/search?query=bern"),
        ],
        "notes": "The map is a canvas: dump the page chrome, not the map. No login.",
    },
    "pluto": {
        "ui": "web-pluto",
        "start": "https://pluto.tv/live-tv",
        "screens": [
            ("live_tv", "Live TV", "/live-tv"),
            ("series", "Series on demand", "/on-demand/series"),
            ("movies", "Movies on demand", "/on-demand/movies"),
            ("channel", "Channel page", "/live-tv/5"),
            ("home", "Home", "/"),
            ("guide", "TV guide", "/tvguide"),
        ],
        "notes": "A bare cookie OK button that asks for no personal data is fine; never fill a form. "
                 "BLOCKED: pluto.tv is US-only — it redirects to /intl/ with \"Pluto TV is not available "
                 "in your location\" from the lab hosts (checked 2026-10-23), so no Pluto tree can be "
                 "built from this platform. Kept in the table with that evidence.",
    },
    "pbs": {
        "ui": "web-pbs",
        "start": "https://www.pbs.org/",
        "screens": [
            ("home", "Home", "/"),
            ("news", "Explore news and public affairs", "/explore/news-and-public-affairs/"),
            ("documentaries", "Explore documentaries and indie films", "/explore/documentaries-and-indie-films/"),
            ("frontline", "Show Frontline", "/show/frontline/"),
            ("nature", "Show Nature", "/show/nature/"),
            ("newshour", "PBS NewsHour", "/newshour/"),
            ("search", "Search", "/search/"),
            ("about", "About PBS", "/about/about-pbs/"),
        ],
        "notes": "Free and anonymous, no cookie wall on the paths above. Stands in for Pluto TV in the "
                 "showcase batch, because pluto.tv is US-only and geo-blocked from the lab hosts.",
    },
    "twitch": {
        "ui": "web-twitch",
        "start": "https://www.twitch.tv/browse",
        "screens": [
            ("browse", "Browse", "/browse"),
            ("videos", "Videos", "/videos"),
            ("directory", "Directory category", "/directory/category/Software%20and%20Development"),
            ("search", "Search results", "/search?term=cat"),
            ("channel", "Channel", "/twitch"),
        ],
        "notes": "Browse only: `/` sends an anonymous visitor to a login wall — never try to log in. "
                 "Add 2 more screens you find from /browse if a listed path redirects.",
    },
    "dailymotion": {
        "ui": "web-dailymotion",
        "start": "https://www.dailymotion.com/",
        "extend": True,
        "screens": [
            ("home", "Home", "/"),
            ("search", "Search results", "/search/cat/videos"),
            ("video", "Video player", "/video/xa2wwo4"),
            ("channel", "Channel", "/dailymotion-usa"),
            ("videos", "Videos", "/dailymotion-usa/videos"),
            ("news", "News", "/dailymotion-usa/news"),
            ("sports", "Sports", "/dailymotion-usa/sports"),
            ("short_films", "Short films", "/dailymotion-usa/short-films"),
        ],
        "notes": "A consent iframe (consent.dailymotion.com) can cover the page: accept or reject it with a "
                 "bare click, never with a form. test_scripts/web/dailymotion_video_check.py already opens "
                 "this site, so reuse what it learned about the player. The tree already has home, search, "
                 "video, channel and videos — add news, sports and short-films, and leave what is there alone.",
    },
    "youtube": {
        "ui": "youtube-web",
        "start": "https://www.youtube.com/",
        "extend": True,
        "screens": [
            ("home", "Home", "/"),
            ("trending", "Trending", "/feed/trending"),
            ("explore", "Explore", "/feed/explore"),
            ("playlist", "Playlist", "/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"),
            ("channel", "Channel", "/channel/UCXuqSBlHAE6Xw-yeJA0Tunw"),
            ("search_results", "Search results", "/results?search_query=openstreetmap"),
            ("shorts", "Shorts", "/shorts"),
            ("video_player", "Video player", None),   # stays; the agent reads its current URL
        ],
        "notes": "The tree already exists — EXTEND it, never recreate a node or an edge. `home`, "
                 "`search_results`, `shorts` and `video_player` are there: give `shorts` a verification, "
                 "give every single-action-set edge its missing back action, then add the new screens. "
                 "YouTube answers an EU IP with a consent page: dismiss it with a bare click, never a form. "
                 "`/feed/subscriptions` and `/feed/history` are sign-in walls for an anonymous visitor — "
                 "use trending, explore, a playlist and a channel instead.",
    },
}

# ---------------------------------------------------------------- helpers


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def run_id(site):
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{site}"


# ---------------------------------------------------------------- routes


def profile_by_name(name):
    rows = b.sql(f"select id, name, model from ai_profiles where name={b.q(name)}", as_json=True)
    if not rows:
        raise SystemExit(f"no ai_profiles row named {name}")
    return rows[0]


def cmd_pin(a):
    """Point both Forge routes at one profile, remembering what they were."""
    prof = profile_by_name(a.model)
    snap_path = os.path.join(ART, "routes_snapshot.json")
    if a.model == "restore":
        return cmd_restore(a)
    snap = read_json(snap_path)
    if not snap:
        rows = b.sql(
            f"select id, usage_key, profile_id, priority, enabled, team_id from ai_routes "
            f"where team_id is null and host_name is null and usage_key in "
            f"({','.join(b.q(k) for k in ROUTE_KEYS)})", as_json=True)
        if not rows:
            raise SystemExit("no global Forge route rows to snapshot")
        snap = {"at": b.now_iso(), "routes": rows}
        write_json(snap_path, snap)
    for key in ROUTE_KEYS:
        b.sql(f"update ai_routes set profile_id={b.q(prof['id'])}, updated_at=now() "
              f"where team_id is null and host_name is null and usage_key={b.q(key)}")
    print(f"[pin] {', '.join(ROUTE_KEYS)} -> {prof['name']} ({prof['model']})  snapshot {snap_path}")


def cmd_restore(a):
    snap_path = os.path.join(ART, "routes_snapshot.json")
    snap = read_json(snap_path)
    if not snap:
        raise SystemExit(f"no snapshot at {snap_path}; nothing to restore")
    for r in snap["routes"]:
        # One global row per usage key: drop whatever the pin left, put the snapshot row back verbatim.
        b.sql(f"delete from ai_routes where usage_key={b.q(r['usage_key'])} "
              f"and host_name is null and device_model is null and userinterface_name is null")
        cols = ["id", "usage_key", "profile_id", "priority", "enabled"]
        vals = [b.q(r[c]) for c in cols]
        if r.get("team_id"):
            cols.append("team_id")
            vals.append(b.q(r["team_id"]))
        b.sql(f"insert into ai_routes ({','.join(cols)}) values ({','.join(vals)})")
    print(f"[restore] Forge routes back to their pinned profiles ({len(snap['routes'])} rows)")


# ---------------------------------------------------------------- prompt


PROMPT = """Build the web navigation tree of {title} in the userinterface `{ui}` on {host}/{device}.

Load the `build-tree-web` skill first and follow it. This is one round; {cap} create_node calls, about
{minutes} minutes.

Screens to map ({n} of them, one level deep from the home screen). The URL path IS the screen's identity:
create one node per screen, and build every node's first verification from its path.

{numbered}

{notes}

Rules that decide whether this round is worth anything:
- Anonymous browsing only. Never log in, never sign up, never answer anything that identifies a person.
  A bare cookie/consent button that asks for no personal data is fine.
- Every node gets a `waitForUrlToMatch` verification on its own path (language-free; the shortest path only
  this screen has) and a `save_node_screenshot` — the screenshot is what carries the node's fingerprint.
- Every edge gets both directions: action set `<src>_to_<dst>` with `navigate_to_url` on the target path,
  and `<dst>_to_<src>` back. A back action never names a language or a translated label.
- The entry edge `edge-entry-node-to-home` opens {start} — `update_edge` with action set `entry_to_home`.
- Test every node before you report: `navigate_to_node`, then `verify_node`, then `save_node_screenshot`.
  A node you never verified does not count as done.
- One `dump_ui_elements` per screen, no read-back of what you just wrote, no `get_node`/`get_edge` after a
  create, no `list_verifications`.
- If a call says the device is in use by another job, wait 30-60 s and retry. Never `force_unlock`.
- When {cap} create_node calls are close, stop exploring and spend the remaining turns testing nodes.
- Finish with `auto_layout_tree(userinterface_name='{ui}')`.

Report: the nodes and edges you built, which nodes passed `verify_node`, which edges you could not test, and
what is left. Do not claim a node works if you did not verify it in this session."""

EXTEND_PROMPT = """EXTEND the web navigation tree of {title} in the userinterface `{ui}` on {host}/{device}.

Load the `build-tree-web` skill first and follow it. This is one round; {cap} create_node calls, about
{minutes} minutes.

The tree already exists. These nodes are in it — do NOT create them again and do NOT delete one:
{existing}

Add only the screens that are missing ({n} of them):
{missing}

{notes}

Rules that decide whether this round is worth anything:
- Anonymous browsing only. Never log in, never sign up, never answer anything that identifies a person.
  A bare cookie/consent button that asks for no personal data is fine.
- Create one node per missing screen and build its first verification from its path.
- Every new node gets a `waitForUrlToMatch` verification on its own path (language-free; the shortest path only
  this screen has) and a `save_node_screenshot` — the screenshot is what carries the node's fingerprint.
- Every new edge gets both directions: action set `<src>_to_<dst>` with `navigate_to_url` on the target path,
  and `<dst>_to_<src>` back. A back action never names a language or a translated label.
- An edge that has only one action set gets its missing back action with `update_edge` — never create a second
  edge for the same pair.
- The entry edge `edge-entry-node-to-home` opens {start}: leave it alone.
- Test every node you touched: `navigate_to_node`, then `verify_node`, then `save_node_screenshot`.
  A node you never verified does not count as done.
- One `dump_ui_elements` per screen, no read-back of what you just wrote, no `get_node`/`get_edge` after a
  create, no `list_verifications`.
- If a call says the device is in use by another job, wait 30-60 s and retry. Never `force_unlock`.
- Finish with `auto_layout_tree(userinterface_name='{ui}')`.

Report: the nodes and edges you added, which nodes passed `verify_node`, which edges you could not test, and
what is left. Do not claim a node works if you did not verify it in this session."""


def existing_nodes(ui):
    """The content nodes a tree already has, so an extend round never recreates one."""
    uid = ui_exists(ui)
    if not uid:
        return []
    return b.sql(
        f"select n.node_id, n.label from navigation_nodes n join navigation_trees t on t.id=n.tree_id "
        f"where t.userinterface_id={b.q(uid)} and n.node_id <> 'entry-node' order by n.node_id", as_json=True)


def build_prompt(site, ui, host, device, cap):
    s = SITES[site]
    lines = []
    if s.get("extend"):
        have = {n["node_id"] for n in existing_nodes(ui)}
        todo = [sc for sc in s["screens"] if sc[0] not in have]
        existing = "\n".join(f"  - `{n['node_id']}` \"{n['label']}\""
                             for n in existing_nodes(ui)) or "  (none yet)"
    else:
        todo = s["screens"]
        existing = ""
    for node_id, label, path in todo:
        target = path or "(keep the URL it already has — read it with execute_javascript 'location.pathname')"
        lines.append(f"  {len(lines) + 1}. node_id `{node_id}`, label \"{label}\", path `{target}`")
    if s.get("extend"):
        return EXTEND_PROMPT.format(
            title=site, ui=ui, host=host, device=device, cap=cap, minutes=cap * 3 // 2,
            n=len(lines), existing=existing, missing="\n".join(lines) or "  (nothing missing)",
            notes=s.get("notes", ""), start=s["start"])
    return PROMPT.format(
        title=site, ui=ui, host=host, device=device, cap=cap, minutes=cap * 3 // 2,
        n=len(lines), numbered="\n".join(lines), notes=s.get("notes", ""), start=s["start"])


# ---------------------------------------------------------------- build


def ui_exists(name):
    rows = b.sql(f"select id from userinterfaces where name={b.q(name)} "
                 f"and team_id={b.q(b.TEAM)}", as_json=True)
    return rows[0]["id"] if rows else None


def ensure_ui(name):
    uid = ui_exists(name)
    if uid:
        return uid
    import requests
    tok = b.auto_sign()
    r = requests.post(f"{b.SERVER}/server/userinterface/createUserInterface",
                      params={"team_id": b.TEAM},
                      headers={"X-Auto-Sign": tok},
                      json={"name": name, "models": ["web"], "min_version": "", "max_version": ""},
                      timeout=60)
    r.raise_for_status()
    return ui_exists(name)


def lease_claim(host, purpose, ttl=30):
    """vpt-lease via proxmox. Blocks (--wait) until the device is free; never --force."""
    cmd = ["ssh", *CTRL, "proxmox",
           f"~/bin/vpt-lease claim node1-vpt {host}/host --kind host --priority P2 "
           f"--purpose {b.q(purpose)} --agent codebox:web-showcase --ttl {ttl} --wait"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=ttl * 60 + 120)
    if p.returncode != 0:
        raise RuntimeError(f"lease claim failed: {p.stderr.strip()[:400]}")
    return p.stdout.strip()


def lease_release(lease_id):
    subprocess.run(["ssh", *CTRL, "proxmox", f"~/bin/vpt-lease release {lease_id}"],
                   capture_output=True, text=True, timeout=120)


class LeaseHeartbeat:
    """Keep a device lease alive for the whole run.

    A P2 lease is capped at 10 minutes by the registry, and a tree build takes 13-20. Without a
    renew loop the lease lapses mid-chat and the next run claims the same device: two Forge chats
    then take turns on one browser, and the second one's prompt times out while it waits. Renew
    every `every_s`, well inside the cap, and stop the moment the run ends.
    """

    def __init__(self, lease_id: str, every_s: int = 240):
        self.lease_id = lease_id
        self.every_s = every_s
        self._stop = threading.Event()
        self._thread = None
        self.renewals = 0
        self.failures = 0

    def __enter__(self):
        def loop():
            while not self._stop.wait(self.every_s):
                p = subprocess.run(["ssh", *CTRL, "proxmox", f"~/bin/vpt-lease renew {self.lease_id}"],
                                   capture_output=True, text=True, timeout=90)
                if p.returncode == 0:
                    self.renewals += 1
                else:
                    self.failures += 1
                    print(f"[lease] renew failed: {p.stderr.strip()[:200]}", flush=True)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return False


def wait_device_idle(host, max_s=420, poll=15, ignore_stale=False):
    """Bounded preflight on the device lock.

    `bench_tree_build.wait_device_idle` blocks up to 30 minutes, which is right for a benchmark
    and wrong for a batch: a run that waits behind a dead lock burns its lease for nothing. A lock
    whose heartbeat is older than `stale_s` is reported as such and the caller picks another host —
    it is never force-unlocked from here (that call stops whoever's run it still is).

    `stale_s` is 10 minutes because a script that is still running does not always refresh its
    lock heartbeat: when the server loses the execution (a restart), the run keeps going on the
    host and its heartbeat stops, so the lock looks stale while the device is in fact busy. A
    caller that treats "stale" as "free" walks straight into that run. `stale_s` is therefore
    reported, not treated as idle — and `ignore_stale=True` keeps waiting it out instead of
    giving up on the site.
    """
    import requests
    tok = b.auto_sign()
    deadline = time.time() + max_s
    stale_s = 600
    while time.time() < deadline:
        r = requests.get(f"{b.SERVER}/server/control/lockedDevices", params={"team_id": b.TEAM},
                         headers={"X-Auto-Sign": tok}, timeout=30).json().get("locked_devices") or {}
        lock = r.get(f"{host}:host")
        if not lock or not lock.get("isLocked"):
            return {"host": host, "idle": True}
        hb_age = time.time() - (lock.get("last_heartbeat_at") or 0)
        if hb_age > stale_s and not ignore_stale:
            return {"host": host, "idle": False, "stale": True,
                    "lock_reason": lock.get("lock_reason"), "heartbeat_age_s": int(hb_age)}
        time.sleep(poll)
    return {"host": host, "idle": False, "stale": False, "lock_reason": (lock or {}).get("lock_reason")}


def cmd_build(a):
    site = a.site
    s = SITES[site]
    ui = a.ui or s["ui"]
    host = a.host
    b.HOST, b.DEVICE = host, "host"
    rid = a.run_id or run_id(site)
    art = os.path.join(ART, rid)
    os.makedirs(art, exist_ok=True)

    meta = {"run_id": rid, "run_ids": [rid], "site": site, "ui": ui, "host": host, "device": "host",
            "cap": a.cap, "timeout_s": a.timeout, "started": b.now_iso()}
    prof = b.sql(f"select p.name, p.model from ai_routes r join ai_profiles p on p.id=r.profile_id "
                 f"where r.team_id is null and r.host_name is null and r.usage_key='agent.forge'", as_json=True)
    meta["forge_profile"] = (prof or [{}])[0]
    write_json(os.path.join(art, "run.json"), meta)
    print(f"[build] {rid} site={site} ui={ui} host={host} model={meta['forge_profile']}", flush=True)

    lease = lease_claim(host, f"TASK-161 web-showcase {site}")
    print(f"[lease] {lease}", flush=True)
    try:
        idle = wait_device_idle(host)
        meta["preflight"] = idle
        if not idle["idle"]:
            print(f"[preflight] {host} is locked ({idle.get('lock_reason')}), releasing the lease", flush=True)
            write_json(os.path.join(art, "run.json"), meta)
            return meta
        uid = ensure_ui(ui)
        meta["userinterface_id"] = uid
        write_json(os.path.join(art, "run.json"), meta)
        prompt = build_prompt(site, ui, host, "host", a.cap)
        with open(os.path.join(art, "prompt.md"), "w") as f:
            f.write(prompt)
        try:
            with LeaseHeartbeat(lease.split()[-1]) as hb:
                res = b.chat(prompt, ui, os.path.join(art, "events.jsonl"), [], a.cap, a.timeout)
                meta["lease_renewals"] = hb.renewals
                meta["lease_renew_failures"] = hb.failures
        except Exception as e:
            # The device can be taken by another session between the preflight and the chat, and
            # the provider can refuse the first call. Neither says anything about the site.
            name = type(e).__name__
            msg = str(e)[:200]
            if name == "DeviceBusy":
                meta["device_busy"] = msg
                print(f"[build] device busy: {msg}", flush=True)
            else:
                meta["error"] = f"{name}: {msg}"
                print(f"[build] failed: {name}: {msg}", flush=True)
            write_json(os.path.join(art, "run.json"), meta)
            return meta
        meta["chat"] = res
        meta["rate_limited"] = _saw_rate_limit(os.path.join(art, "events.jsonl"))
        meta["ended"] = b.now_iso()
    finally:
        lease_release(lease.split()[-1] if lease else "")
    meta["score"] = score_ui(ui)
    write_json(os.path.join(art, "run.json"), meta)
    sc = meta["score"]
    print(f"[done] {rid} nodes={sc['nodes']} verified={sc['nodes_with_verification']} "
          f"fingerprints={sc['nodes_with_fingerprint']} edges={sc['edges']} "
          f"bidirectional={sc['bidirectional_edges']}", flush=True)
    return meta


# ---------------------------------------------------------------- score


def _verification_list(raw):
    """Count a node's verifications whatever shape the tree stores them in.

    A tree built today stores a plain list. `youtube-web`, built before that
    convention, stores `{"item": [...]}` — and `{"item": {"item": {...}}}` on one
    node. `jsonb_array_length` on those raises and takes the scorer down with it.
    """
    v = raw
    for _ in range(3):
        if isinstance(v, list):
            return v
        if not isinstance(v, dict):
            return []
        if "command" in v or "verification_type" in v:
            return [v]
        v = v.get("item")
    return v if isinstance(v, list) else []


def score_ui(ui):
    uid = ui_exists(ui)
    out = {"ui": ui, "userinterface_id": uid}
    if not uid:
        return out
    # `verifications` is a list on every tree built today, but `youtube-web` (built
    # before that convention) stores `{"item": [...]}` — and `{"item": {"item": {...}}}`
    # on one node. `jsonb_array_length` on that raises and takes the whole scorer down,
    # so fetch the raw value and count it here, where the shapes are easy to read.
    nodes = b.sql(
        f"select n.node_id, n.label, n.verifications as vraw, "
        f"(n.data->>'screenshot') is not null as shot, (n.data->'fingerprint') is not null as fp, "
        f"n.position_x, n.position_y from navigation_nodes n join navigation_trees t on t.id=n.tree_id "
        f"where t.userinterface_id={b.q(uid)} order by n.node_id", as_json=True)
    for n in nodes:
        n["nver"] = len(_verification_list(n.get("vraw")))
    edges = b.sql(
        f"select e.edge_id, e.source_node_id, e.target_node_id, jsonb_array_length(e.action_sets) as nsets, "
        f"e.action_sets from navigation_edges e join navigation_trees t on t.id=e.tree_id "
        f"where t.userinterface_id={b.q(uid)} order by e.edge_id", as_json=True)
    real = [n for n in nodes if n["node_id"] != "entry-node"]
    out.update({
        "nodes": len(nodes),
        "content_nodes": len(real),
        "nodes_with_verification": sum(1 for n in nodes if n["nver"]),
        "nodes_with_screenshot": sum(1 for n in nodes if n["shot"]),
        "nodes_with_fingerprint": sum(1 for n in nodes if n["fp"]),
        "unverified": [n["node_id"] for n in real if not n["nver"]],
        "no_fingerprint": [n["node_id"] for n in real if not n["fp"]],
        "stacked": [n["node_id"] for n in real if n["position_x"] == 0 and n["position_y"] == 0],
        "edges": len(edges),
        # The entry edge has one action set by design (`entry_to_home`); it opens the site, it is
        # not a pair of nodes. Only a real pair needs both directions.
        "bidirectional_edges": sum(1 for e in edges if e["nsets"] and e["nsets"] >= 2),
        "one_way_edges": [e["edge_id"] for e in edges
                          if (e["nsets"] or 0) < 2 and e["edge_id"] != "edge-entry-node-to-home"],
        "node_list": nodes,
        "edge_list": [{"edge_id": e["edge_id"], "source": e["source_node_id"],
                       "target": e["target_node_id"], "action_sets": e["nsets"]} for e in edges],
    })
    return out


def cmd_score(a):
    if a.all or not a.site:
        sites = a.all and list(SITES) or [a.site]
        table = {s: score_ui(SITES[s]["ui"]) for s in sites}
        for s, sc in table.items():
            print(f"{s:16s} ui={sc['ui']:18s} nodes={sc.get('nodes', 0):2d} "
                  f"verified={sc.get('nodes_with_verification', 0):2d} "
                  f"fp={sc.get('nodes_with_fingerprint', 0):2d} edges={sc.get('edges', 0):2d} "
                  f"both={sc.get('bidirectional_edges', 0):2d} "
                  f"unverified={','.join(sc.get('unverified', [])) or '-'}")
        write_json(os.path.join(ART, "score_all.json"), table)
        return table
    sc = score_ui(a.ui or SITES[a.site]["ui"])
    print(json.dumps({k: v for k, v in sc.items() if k not in ("node_list",)}, indent=2, default=str))
    write_json(os.path.join(ART, f"score-{a.site}.json"), sc)
    return sc


def cmd_sites(a):
    for k, s in SITES.items():
        print(f"{k:16s} ui={s['ui']:18s} screens={len(s['screens']):2d} start={s['start']}")
    return SITES


def cmd_finish(a):
    """Finish the two mechanical steps a run leaves out: screenshots/fingerprints and the layout.

    These need no model — a capture and a position assignment — and they do not need the agent
    conversation slot either (they are plain MCP device calls), so they run while the next site is
    being built. The list of nodes to capture comes from the DB, never from the tree's own reply:
    a node counts as done only when `data.fingerprint` is really there.
    """
    b.HOST, b.DEVICE = a.host, "host"
    lease = lease_claim(a.host, f"TASK-161 web-showcase finish {a.ui}")
    out = {"ui": a.ui, "host": a.host, "screenshots": {}, "layout": None}
    try:
        idle = wait_device_idle(a.host)
        out["preflight"] = idle
        if not idle["idle"]:
            print(f"[finish] {a.host} is locked ({idle.get('lock_reason')}); nothing done", flush=True)
            return out
        before = score_ui(a.ui)
        out["missing_screenshots"] = before.get("no_fingerprint", [])
        txt, _, err = b.mcp("get_userinterface_complete", userinterface_name=a.ui)
        if err:
            out["error"] = "get_userinterface_complete failed"
            return out
        tree = _tree_from_complete(txt)
        out["tree_id"] = tree.get("tree_id")
        labels = {n.get("node_id"): n.get("label") or n.get("node_id") for n in tree.get("nodes", [])}
        for nid in out["missing_screenshots"]:
            label = labels.get(nid, nid)
            _, _, e1 = b.mcp("navigate_to_node", userinterface_name=a.ui, target_node_label=label,
                             host_name=a.host, device_id="host", include_screenshot=False)
            _, _, e2 = b.mcp("save_node_screenshot", userinterface_name=a.ui, tree_id=out["tree_id"],
                             node_id=nid, label=label, host_name=a.host, device_id="host")
            ok = not (e1 or e2)
            out["screenshots"][nid] = {"ok": ok, "nav_error": e1, "shot_error": e2}
            print(f"[finish] {nid}: {'ok' if ok else 'FAILED'}", flush=True)
        _, _, e3 = b.mcp("auto_layout_tree", userinterface_name=a.ui)
        out["layout"] = {"ok": not e3, "error": e3}
        print(f"[finish] auto_layout_tree: {'ok' if not e3 else 'FAILED'}", flush=True)
    finally:
        lease_release(lease.split()[-1] if lease else "")
    out["score"] = score_ui(a.ui)
    write_json(os.path.join(ART, f"finish-{a.ui}.json"), out)
    return out


def cmd_smoke(a):
    """Run a site's smoke script `--runs` times in a row and report each run's verdict.

    "Twice in a row" is the point: a tree that only walks on the first try is a tree that depends
    on the state the previous run left behind. Each run is a separate platform execution with its
    own execution_id, so two runs cannot help each other.

    A run whose execution disappears (a server deploy restarts the platform and the host loses its
    registration) is not a verdict: it is retried, up to `a.max_attempts` times per run.
    """
    import re
    b.HOST, b.DEVICE = a.host, "host"
    key = a.site or (a.ui[len("web-"):] if a.ui.startswith("web-") else a.ui)
    script = a.script or f"web/web_{key}_smoke.py"
    out = {"ui": a.ui, "host": a.host, "script": script, "runs": []}
    lease = lease_claim(a.host, f"TASK-161 web-showcase smoke {a.ui}", ttl=30)
    try:
        # A smoke holds the device for the whole run (minutes per pass), so the lease is renewed
        # like a build's: an expired lease lets another workload take the device mid-walk.
        with LeaseHeartbeat(lease.split()[-1]):
            done = 0
            attempts = 0
            while done < a.runs and attempts < a.max_attempts:
                attempts += 1
                idle = wait_device_idle(a.host, max_s=a.idle_wait_s, ignore_stale=True)
                if not idle["idle"]:
                    # The device was never free inside the wait: the site is reported as
                    # not run, never as a failed tree. It is the honest difference between
                    # "the walk failed" and "the walk never started".
                    out["runs"].append({"n": done + 1, "error": f"device busy ({idle.get('lock_reason')})",
                                         "not_run": True})
                    write_json(os.path.join(ART, f"smoke-{a.ui}.json"), out)
                    break
                txt, _, err = b.mcp("execute_script", script_name=script, host_name=a.host,
                                    device_id="host",
                                    parameters=f"--userinterface {a.ui} --passes {a.passes}",
                                    environment="test")
                m = re.search(r"execution_id['\"]?\s*[:=]\s*['\"]?([\w-]+)", txt)
                if err or not m:
                    out["runs"].append({"n": done + 1, "error": (txt or "no execution_id")[:300]})
                    write_json(os.path.join(ART, f"smoke-{a.ui}.json"), out)
                    break
                eid = m.group(1)
                raw = ""
                # 400 x 15 s = 100 min. The old 30-min cap killed a walk that was still
                # making progress: the script kept running on the host, the driver gave
                # up on it, and the orphan held the device so every later site in the
                # batch reported "device busy" without a single attempt.
                for _ in range(400):
                    raw, _, _ = b.mcp("get_script_execution_status", execution_id=eid, wait_seconds=15)
                    if re.search(r"done['\"]?\s*[:=]\s*true|Script completed|Script failed", raw, re.I):
                        break
                # The status reply is assembled in parts: the first reply that says
                # "Script failed" can arrive before its "Logs:" line, so the log URL can
                # be missing even though the run produced a log. Ask again for it before
                # calling the execution lost — a lost execution is retried, and the retry
                # finds the device busy and reports the site as not run.
                if not _smoke_url(raw):
                    for _ in range(12):
                        raw2, _, _ = b.mcp("get_script_execution_status",
                                           execution_id=eid, wait_seconds=5)
                        if _smoke_url(raw2):
                            raw = raw2
                            break
                verdict = _smoke_verdict(_smoke_log(raw))
                lost = (not verdict.get("passed")
                        and verdict.get("reason") == "no log in the execution status reply")
                out["runs"].append({"n": done + 1, "execution_id": eid, **verdict,
                                    "log_url": (_smoke_url(raw) or ""), "lost": lost})
                write_json(os.path.join(ART, f"smoke-{a.ui}.json"), out)
                if lost:
                    print(f"[smoke] {a.ui}: the execution was lost (a deploy?), retrying", flush=True)
                    continue
                done += 1
                print(f"[smoke] {a.ui} run {done}/{a.runs}: {verdict}", flush=True)
    finally:
        lease_release(lease.split()[-1] if lease else "")
    ok = [r for r in out["runs"] if r.get("passed")]
    # "Twice in a row" is what the brief asks for, and the walk can prove it two ways:
    # two executions in a row (`--runs 2`), or one execution that walks the tree twice,
    # each pass starting from the entry edge (`--passes 2`). Counting only the runs
    # reported `False` on a perfectly green two-pass walk.
    out["consecutive_passes"] = (len(ok) == a.runs and a.runs >= 1
                                 and (a.runs >= 2 or a.passes >= 2))
    write_json(os.path.join(ART, f"smoke-{a.ui}.json"), out)
    return out


def _smoke_url(raw):
    import re
    m = (re.search(r"(https?://[^\s)\"']*script-logs/[^\s)\"']*)", raw or "")
         or re.search(r"logs?_url['\"]?\s*[:=]\s*['\"]?(https?://[^\s'\",]+)", raw or ""))
    return m.group(1) if m else None


def _smoke_log(raw):
    url = _smoke_url(raw)
    if not url:
        return ""
    data = b.fetch(url)
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data or "")


def _smoke_verdict(log):
    import re
    head = re.search(r"(\d+) pass\(es\), (\d+) checks, (\d+) failure\(s\)", log)
    result = re.search(r"Result: (SUCCESS|FAILED)", log)
    if not log:
        return {"passed": False, "reason": "no log in the execution status reply"}
    return {"passed": bool(result and result.group(1) == "SUCCESS"),
            "checks": int(head.group(2)) if head else None,
            "failures": int(head.group(3)) if head else None,
            "result": result.group(1) if result else None}


def _tree_from_complete(text):
    """get_userinterface_complete answers `tree_id:… nodes:N edges:M` then one JSON line."""
    import json as _json
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("{") and '"nodes"' in line:
            try:
                return _json.loads(line)
            except ValueError:
                continue
    return {}


def _saw_rate_limit(events_path):
    """True when the provider refused the run (rate limit) instead of the model working."""
    try:
        for ln in open(events_path):
            if "rate limit" in ln.lower():
                return True
    except OSError:
        pass
    return False


def cmd_batch(a):
    """Run several sites on one host, SEQUENTIALLY, re-running a site that did not reach the bar.

    Sequential is not a style choice: `server_agent_routes.run_agent_coroutine` takes the
    per-worker processing lock, so the server runs **one agent conversation at a time**. A second
    chat is accepted and answered in turn ("Waiting for another conversation to finish..."), which
    burns its own timeout while it queues. Extra hosts and extra leases buy nothing for Forge runs —
    they matter for script runs (TASK-146), not for tree builds.

    A run can fail for a reason that has nothing to do with the site — a busy device, a lease queue,
    a session that dies. Those must not be reported as a model result, so a site is retried until it
    reaches `min_nodes` verified nodes with a fingerprint, up to `attempts` tries.
    """
    results = {}
    for site in a.sites:
        for attempt in range(1, a.attempts + 1):
            if results.get(site, {}).get("ok"):
                break
            args = argparse.Namespace(site=site, host=a.host, ui=None, run_id=None,
                                      cap=a.cap, timeout=a.timeout)
            meta = cmd_build(args)
            sc = meta.get("score") or {}
            good = (sc.get("nodes_with_verification", 0) >= a.min_nodes
                    and sc.get("nodes_with_fingerprint", 0) >= a.min_nodes)
            if not good and meta.get("rate_limited"):
                # The provider refused the first model call (rate limit). Nothing was built, so
                # this says nothing about the site: back off and try again.
                print(f"[batch] {site}: the provider rate-limited the run, backing off "
                      f"{a.cooldown}s", flush=True)
                time.sleep(a.cooldown)
            results[site] = {"attempts": attempt, "score": sc, "ok": good,
                             "run_ids": meta.get("run_ids", [])}
            print(f"[batch] {site} attempt {attempt}: "
                  f"verified={sc.get('nodes_with_verification', 0)} "
                  f"fingerprinted={sc.get('nodes_with_fingerprint', 0)} ok={good}", flush=True)
            if good:
                break
            print(f"[batch] {site} below the bar ({a.min_nodes} nodes), retrying", flush=True)
            time.sleep(max(30, a.cooldown))
    write_json(os.path.join(ART, f"batch-{a.host}.json"), results)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sites").set_defaults(fn=cmd_sites)

    p = sub.add_parser("pin")
    p.add_argument("model", help="ai_profiles.name, or 'restore'")
    p.set_defaults(fn=cmd_pin)

    p = sub.add_parser("restore")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("build")
    p.add_argument("--site", required=True, choices=sorted(SITES))
    p.add_argument("--host", required=True)
    p.add_argument("--ui")
    p.add_argument("--run-id")
    p.add_argument("--cap", type=int, default=14, help="create_node cap (default 14)")
    p.add_argument("--timeout", type=int, default=1500)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("score")
    p.add_argument("--site", choices=sorted(SITES))
    p.add_argument("--ui")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("finish")
    p.add_argument("--ui", required=True, help="userinterface to finish (screenshots + layout)")
    p.add_argument("--host", required=True)
    p.set_defaults(fn=cmd_finish)

    p = sub.add_parser("smoke")
    p.add_argument("--ui", required=True)
    p.add_argument("--site", choices=sorted(SITES))
    p.add_argument("--host", required=True)
    p.add_argument("--script")
    p.add_argument("--runs", type=int, default=2, help="consecutive runs (default 2)")
    p.add_argument("--passes", type=int, default=2, help="passes per run (default 2)")
    p.add_argument("--idle-wait-s", type=int, default=2400,
                   help="how long to wait for a free device before giving up on a run")
    p.add_argument("--max-attempts", type=int, default=4,
                   help="attempts per run: a lost execution (a deploy) is retried, not counted")
    p.set_defaults(fn=cmd_smoke)

    p = sub.add_parser("batch")
    p.add_argument("--host", required=True)
    p.add_argument("--sites", required=True, help="comma-separated site keys, run one after another")
    p.add_argument("--cap", type=int, default=14)
    p.add_argument("--timeout", type=int, default=1500)
    p.add_argument("--attempts", type=int, default=3, help="tries per site before it is reported short")
    p.add_argument("--min-nodes", type=int, default=6)
    p.add_argument("--cooldown", type=int, default=90,
                   help="seconds to wait between runs: the provider rate-limits back-to-back starts")
    p.set_defaults(fn=cmd_batch)

    a = ap.parse_args()
    a.sites = getattr(a, "sites", None)
    if a.cmd == "batch":
        a.sites = [s.strip() for s in a.sites.split(",") if s.strip()]
        for s in a.sites:
            if s not in SITES:
                raise SystemExit(f"unknown site {s}")
    return a.fn(a) and 0 or 0


if __name__ == "__main__":
    sys.exit(main())