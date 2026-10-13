"""Publish the voiced versions of the promo videos: upload new FIRST, delete the old one only after the new one is
confirmed live, so every video stays available even when YouTube rate-limits us. Resumable (publish_state.json).

The API quota (10,000 units/day; one upload = 1,600) allows ~5 uploads a day: run `upload` once a day until done.

  python3 publish_voiced.py plan               # print each new description (chapters re-timed) - nothing sent
  python3 publish_voiced.py upload [--max 5]   # upload the next ones (public, tags, playlist; thumbnail if allowed)
  python3 publish_voiced.py finish             # for uploaded ones: confirm live -> swap ids in the docs -> delete old
  python3 publish_voiced.py thumbs             # retry the thumbnails YouTube refused (account not verified yet)
  python3 publish_voiced.py status

Text: title and tags stay as published (meta/<old id>.json); the description keeps its text, drops any URL line,
and gets its chapter times recomputed from the voiced build. YouTube shows chapters only if the first is 0:00 and
each lasts >= 10 s, so labels closer than that are merged into the previous chapter.
"""
import json
import re
import sys
from pathlib import Path

import youtube_upload as yt
from voiceover import lines

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STATE = HERE / "publish_state.json"
VOICE = "English_Insightful_Speaker"
VIDEOS = {   # build key: (old YouTube id, video number for the thumbnail)
    "consoles": ("ob1LxcZku7Y", "24"), "localize": ("nJNQLd7llBc", "23"), "whatsnew": ("Pz1EFJnR_G8", "22"),
    "subqa": ("Z4jB-E_KNGw", "21"), "grafana": ("6MdT1BnV0bc", "20"), "mcp": ("8snlgWd2rlw", "19"),
    "vscript": ("6GwIDvqtlVI", "18"), "tpzap": ("1KqhV311A74", "17"), "atlas": ("kNS8bacppXc", "16"),
    "nipogi": ("PrxZpLWWo2A", "15"), "aigen": ("mst3HuyKEXA", "14"), "avq": ("nV1NesElnAU", "13"),
    "cicd": ("cwL_e0j0hGY", "11"),
}
DOCS = [REPO / "README.md", REPO / "docs/videos/README.md", REPO / "docs/videos/index.md"]


def mmss(t):
    t = int(t); return f"{t // 60}:{t % 60:02d}"


def description(key):
    import build2
    old = VIDEOS[key][0]
    meta = json.loads((HERE / "meta" / f"{old}.json").read_text())
    raw = meta["description"].splitlines()
    labels = [re.sub(r"^\d+:\d\d\s+", "", l).strip() for l in raw if re.match(r"^\d+:\d\d\s", l)]
    labels = [l for l in labels if not re.match(r"(?i)open source", l)]
    text = "\n".join(l for l in raw if "http" not in l and not re.match(r"^\d+:\d\d\s", l)
                     and not re.match(r"(?i)^\s*chapters\s*:?\s*$", l))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if "open source & free" not in text.lower():
        text += "\n\nOpen source & free."
    # beats: scenes grouped by title (a beat can span two clips), closing card excluded
    _, ls = lines(key)
    scenes = build2.VIDEOS[key][0]()
    beats = []
    for (st, _, _), sc in zip(ls[:-1], scenes[:-1]):
        title = sc[1] if sc[0] == "card" else sc[2]
        if not beats or beats[-1][1] != title:
            beats.append([st, title])
    names = labels if len(labels) == len(beats) else [b[1] for b in beats]
    warn = "" if len(labels) == len(beats) else f"chapter labels from the beat titles ({len(labels)} labels, {len(beats)} beats)"
    kept = []
    for (st, _), lab in zip(beats, names):
        if not kept or st - kept[-1][0] >= 10:
            kept.append([0.0 if not kept else st, lab])
    if len(kept) < 3:
        warn += " (fewer than 3 chapters: YouTube will not show them)"
    desc = text + "\n\nChapters\n" + "\n".join(f"{mmss(t)} {lab}" for t, lab in kept)
    return meta, desc, warn


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(s):
    STATE.write_text(json.dumps(s, indent=1))


def video_file(key):
    import build2
    return HERE / "out" / build2.VIDEOS[key][1].replace(".mp4", f"_voice-{VOICE}.mp4")


def thumb(key):
    f = sorted((HERE / "out").glob(f"thumb_{VIDEOS[key][1]}_*.jpg"))
    return f[0] if f else None


def cmd_plan():
    for key in VIDEOS:
        meta, desc, warn = description(key)
        print(f"===== {key}  ({VIDEOS[key][0]})  {meta['title']}\n{desc}\n{('!! ' + warn) if warn else ''}")


def cmd_upload(maxn):
    s = state(); done = 0
    for key, (old, num) in VIDEOS.items():
        if s.get(key, {}).get("new_id") or done >= maxn:
            continue
        meta, desc, warn = description(key)
        body = {"title": meta["title"], "description": desc, "tags": meta["tags"], "privacy": "public",
                "category": meta.get("category", "28")}
        mf = HERE / "meta" / f"_pending_{key}.json"; mf.write_text(json.dumps(body, ensure_ascii=False, indent=1))
        try:
            vid = yt.upload_id(str(video_file(key)), body, None)
        except SystemExit as e:
            print(f"{key}: upload stopped: {str(e)[:200]}"); break      # quota or rate limit: resume tomorrow
        s[key] = {"new_id": vid, "old_id": old, "thumb": False, "old_deleted": False}; save(s); done += 1
        mf.unlink(missing_ok=True)
        (HERE / "meta" / f"{vid}.json").write_text(json.dumps({**body, "id": vid}, ensure_ascii=False, indent=1))
        t = thumb(key)
        if t:
            try:
                yt.set_thumb(vid, str(t)); s[key]["thumb"] = True; save(s)
            except SystemExit as e:
                print(f"{key}: thumbnail later ({str(e)[:80]})")
        print(f"{key}: {old} -> {vid}  https://youtu.be/{vid}")


def live(vid):
    r, _ = yt.http("GET", f"{yt.API}/videos?part=status&id={vid}", headers=yt.auth_h())
    it = r.get("items") or [{}]
    st = it[0].get("status", {})
    return st.get("uploadStatus") == "processed" and st.get("privacyStatus") == "public"


def cmd_finish():
    s = state(); swapped = []
    for key, v in s.items():
        if v.get("old_deleted") or not live(v["new_id"]):
            continue
        for f in DOCS:
            t = f.read_text(); f.write_text(t.replace(v["old_id"], v["new_id"]))
        swapped.append(key)
        yt.delete(v["old_id"]); v["old_deleted"] = True; save(s)
        print(f"{key}: docs now {v['new_id']}, old {v['old_id']} deleted")
    if swapped:
        print("docs changed: commit README.md docs/videos/*.md and deploy the frontend")


def cmd_thumbs():
    s = state()
    for key, v in s.items():
        if v.get("thumb") or not thumb(key):
            continue
        try:
            yt.set_thumb(v["new_id"], str(thumb(key))); v["thumb"] = True; save(s); print(f"{key}: thumbnail set")
        except SystemExit as e:
            print(f"{key}: still refused ({str(e)[:80]})"); break


def cmd_status():
    s = state()
    for key, (old, num) in VIDEOS.items():
        v = s.get(key, {})
        print(f"{num} {key:9} old {old}  new {v.get('new_id', '-'):11}  thumb {v.get('thumb', '-')!s:5}  old deleted {v.get('old_deleted', '-')}")


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"plan": cmd_plan, "finish": cmd_finish, "thumbs": cmd_thumbs, "status": cmd_status,
     "upload": lambda: cmd_upload(int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 5)}[c]()
