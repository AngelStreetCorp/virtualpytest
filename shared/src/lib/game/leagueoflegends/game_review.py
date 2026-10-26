"""TASK-131: review a recorded League game - one HTML timeline per game and one training-data row per last-hit attempt.

Reads a run folder (``timeline.json``; optional ``lasthit/attempts.json`` + ``lasthit/aNN/*.jpg`` full-resolution frames,
``shots/t*.png``, ``video.mp4``, ``result.json``) from the Garen bot, the benchmark runner or ``auto_record``.
Read-only. ``review_run_dir`` is called by ``score_run.score_run_dir``, so every scored game gets its review.

Dataset row (one JSON line per last-hit attempt, ``<dataset root>/<game_id>.jsonl``), fields ``null`` when the recorder
did not log them (the bot's attempt log should emit all of them):
``game_id, game_t, minion_type, bar_frac, pred_hp, hp_scale, our_ad, our_dmg, action (auto|q), rate (bar drop /s),
wait_s, click_t, cs_before, hp_before, hp_after (health at the last poll before the attempt / 3 s after), outcome (hit|miss), cause, x, y, crop`` (path of the full-resolution crop, relative to the root).
"""

from __future__ import annotations

import glob
import html
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import live_recorder, scorecard as sc

DATASET_ROOT_DEFAULT = r"C:\virtualpytest\lol-dataset"
CROP = 480  # px around the target in the full-resolution frame


def load_run(run_dir: str) -> Dict[str, Any]:
    tl = live_recorder.load_timeline(os.path.join(run_dir, "timeline.json"))
    tl["meta"].setdefault("champion", "Garen")
    if (tl["meta"].get("assigned_position") or "NONE").upper() == "NONE":
        tl["meta"]["assigned_position"] = "top"  # Practice Tool reports no position; the bot and TASK-132 play top
    if not tl.get("cs_exact"):  # exact CS from the shots (HUD counter), as the scorecard uses
        from . import score_run

        tl["cs_exact"] = score_run.cs_from_shots(run_dir)
    att: Dict[str, Any] = {}
    p = os.path.join(run_dir, "lasthit", "attempts.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            att = json.load(f)
    return {"tl": tl, "attempts": att.get("attempts", []), "hp_scale": att.get("hp_scale"), "dir": run_dir,
            "video": os.path.exists(os.path.join(run_dir, "video.mp4"))}


def game_id(run_dir: str) -> str:
    return os.path.basename(os.path.abspath(run_dir))


def attempt_cause(a: Dict[str, Any]) -> Optional[str]:
    """Why an attempt missed, from what the bot logged (None for a hit)."""
    if a.get("result") == "hit":
        return None
    dmg, pred = a.get("dmg"), a.get("pred_hp")
    if dmg is None or pred is None:
        return "unknown (no prediction logged)"
    if pred > dmg * 1.1:
        return "too early: predicted health at impact was above our damage"
    if pred < 0:
        return "too late: the minion was predicted dead before our hit landed"
    return "close call: damage covered the prediction but the minion was killed by another unit or out of reach"


def unattempted_deaths(run: Dict[str, Any], window: float = 3.0) -> List[Dict[str, Any]]:
    """Minion deaths near us that we did not win and had no attempt on (within ``window`` s)."""
    out = []
    for d in run["tl"].get("minion_deaths") or []:
        if d.get("ours"):
            continue
        if not any(abs(a["t"] - d["t"]) <= window for a in run["attempts"]):
            out.append(d)
    return out


# ---------------------------------------------------------------- dataset
def _hp_around(tl: Dict[str, Any], t: float, after_s: float = 3.0) -> Tuple[Optional[float], Optional[float]]:
    """Health (absolute) at the last poll at or before the attempt and at the first poll ``after_s`` later."""
    ss = tl.get("samples", [])
    before = [s for s in ss if s["t"] <= t]
    after = [s for s in ss if s["t"] >= t + after_s]
    return (round(before[-1]["hp"], 1) if before else None, round(after[0]["hp"], 1) if after else None)


def _frames(run_dir: str, idx: int) -> List[Tuple[float, str]]:
    out = []
    for p in sorted(glob.glob(os.path.join(run_dir, "lasthit", f"a{idx:02d}", "t*.jpg"))):
        m = re.search(r"t([\d.]+)\.jpg$", p)
        if m:
            out.append((float(m.group(1)), p))
    return out


def write_dataset(run_dir: str, root: str = DATASET_ROOT_DEFAULT) -> List[Dict[str, Any]]:
    """Rows + crops for every attempt of the run; rewrites ``<root>/<game_id>.jsonl`` (idempotent)."""
    run = load_run(run_dir)
    gid = game_id(run_dir)
    rows = []
    os.makedirs(os.path.join(root, "crops", gid), exist_ok=True)
    for i, a in enumerate(run["attempts"]):
        if a.get("result") is None:
            continue
        crop_rel = None
        fr = _frames(run_dir, i)
        if fr:
            tt, path = min(fr, key=lambda f: abs(f[0] - (a["t"] + 0.3)))  # the frame just after the click
            try:
                from PIL import Image

                im = Image.open(path)
                x, y = int(a.get("x", im.width // 2)), int(a.get("y", im.height // 2))
                box = (max(0, x - CROP // 2), max(0, y - CROP // 2), min(im.width, x + CROP // 2), min(im.height, y + CROP // 2))
                crop_rel = f"crops/{gid}/a{i:02d}.jpg"
                im.crop(box).save(os.path.join(root, crop_rel), quality=92)
            except Exception:  # noqa: BLE001 - a missing crop must not lose the row
                crop_rel = None
        hp_b, hp_a = _hp_around(run["tl"], a["t"])
        rows.append({
            "game_id": gid, "game_t": a.get("t"), "minion_type": a.get("type") or "minion",
            "bar_frac": a.get("bar_frac"), "est_hp": a.get("est_hp"), "pred_hp": a.get("pred_hp"), "hp_scale": run["hp_scale"],
            "our_ad": a.get("ad"), "our_dmg": a.get("dmg"), "action": a.get("action"), "rate": a.get("rate"),
            "wait_s": a.get("wait"), "click_t": a.get("t_click"), "cs_before": a.get("cs0"),
            "hp_before": hp_b, "hp_after": hp_a, "outcome": a.get("result"), "cause": attempt_cause(a), "x": a.get("x"), "y": a.get("y"), "crop": crop_rel,
        })
    with open(os.path.join(root, gid + ".jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return rows


# ---------------------------------------------------------------- html timeline
def _events(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    tl, ev = run["tl"], []
    ref = sc.reference_for(tl) if tl.get("samples") else None
    for m in (sc.bad_moments(tl, ref) if ref else []):
        ev.append({"t": m["t"], "row": "deaths" if m["kind"] == "death" else "recalls" if "recall" in m["kind"] else "moments",
                   "label": f"{m['kind']}: {m['detail']}", "bad": True})
    for b in sc.hp_drops(tl):  # damage taken, marked on the HP row with its source
        if b["dmg"] >= 0.05 * (b.get("hp_max") or 1000):
            ev.append({"t": b["t1"], "row": "hp", "label": f"took {int(b['dmg'])} damage ({b['source']}), health {int(b['hp_before'])} -> {int(b['hp_after'])}",
                       "bad": True})
    for r in sc.detect_recalls(tl):
        ev.append({"t": r["t"], "row": "recalls", "label": f"recall with {int(r['gold_before'])} gold, health {r['hp_frac']}", "bad": False})
    for i, a in enumerate(run["attempts"]):
        if a.get("result") is None:
            continue
        hit = a["result"] == "hit"
        ev.append({"t": a["t"], "row": "last-hits", "label": f"{a.get('type') or 'minion'} {'HIT' if hit else 'MISS'}"
                   + ("" if hit else f" - {attempt_cause(a)}"), "bad": not hit, "attempt": i})
    for d in unattempted_deaths(run):
        ev.append({"t": d["t"], "row": "last-hits", "label": f"{d.get('kind', 'minion')} died near us, no attempt", "bad": True})
    prev_items: List[str] = []
    for s in tl.get("samples", []):
        if s["items"] != prev_items and prev_items is not None:
            new = [i for i in s["items"] if i not in prev_items]
            if new:
                ev.append({"t": s["t"], "row": "items", "label": "bought " + ", ".join(new), "bad": False})
        prev_items = s["items"]
    return sorted(ev, key=lambda e: e["t"])


def _frame_index(run_dir: str) -> List[Dict[str, Any]]:
    out = []
    for p in glob.glob(os.path.join(run_dir, "lasthit", "a*", "t*.jpg")):
        m = re.search(r"t([\d.]+)\.jpg$", p)
        if m:
            out.append({"t": float(m.group(1)), "src": os.path.relpath(p, run_dir).replace(os.sep, "/")})
    for p in glob.glob(os.path.join(run_dir, "shots", "t*.png")):
        out.append({"t": float(os.path.basename(p)[1:-4]), "src": os.path.relpath(p, run_dir).replace(os.sep, "/")})
    return sorted(out, key=lambda f: f["t"])


def build_html(run_dir: str, out_name: str = "review.html", video_offset_s: float = 0.0) -> str:
    run = load_run(run_dir)
    tl = run["tl"]
    ss = tl.get("samples", [])
    data = {
        "id": game_id(run_dir), "end": ss[-1]["t"] if ss else 0, "video": "video.mp4" if run["video"] else None, "offset": video_offset_s,
        "gold": [[s["t"], s["gold"]] for s in ss], "hp": [[s["t"], round(s["hp"] / s["hp_max"], 3) if s["hp_max"] else 0] for s in ss],
        "cs": [[c["t"], c["cs"]] for c in tl["cs_exact"]] if tl.get("cs_exact") else [[s["t"], s["scores"]["cs"]] for s in ss],
        "cs_exact": bool(tl.get("cs_exact")), "events": _events(run), "frames": _frame_index(run_dir), "laning_end": sc.LANING_END_S,
        "headlines": [{"at": k, "data": v} for k, v in sc.headlines(sc.window_timeline(tl, sc.LANING_END_S), sc.reference_for(tl), run["attempts"] or None).items()],
    }
    reward = ""
    try:  # per-action table (reward_summary.json from outcomes.finalize), shown under the timeline
        from .outcomes import reward_html

        reward = reward_html(json.load(open(os.path.join(run_dir, "reward_summary.json"), encoding="utf-8")))
    except (OSError, ValueError, ImportError):
        pass
    page = _PAGE.replace("__DATA__", json.dumps(data)).replace("__TITLE__", html.escape(data["id"])).replace("__REWARD__", reward)
    p = os.path.join(run_dir, out_name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(page)
    return p


_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Game review __TITLE__</title>
<style>:root{--bg:#fff;--fg:#1a1a1a;--mut:#777;--ln:#ddd;--ok:#2a7;--bad:#c33;--acc:#b8860b}
@media(prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e8e8e8;--mut:#999;--ln:#333;--ok:#4c9;--bad:#e66;--acc:#d4a72c}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui}header{padding:12px 16px;border-bottom:1px solid var(--ln)}
h1{font-size:16px;margin:0}main{display:grid;grid-template-columns:1fr 420px;gap:0}@media(max-width:900px){main{grid-template-columns:1fr}}
#tl{overflow-x:auto;padding:8px 16px}svg{display:block}.lbl{fill:var(--mut);font-size:11px}.ev{cursor:pointer}.ev:hover{stroke:var(--fg)}
#side{border-left:1px solid var(--ln);padding:12px;position:sticky;top:0;align-self:start}#side img,#side video{width:100%;border-radius:4px}
#info{margin:8px 0;min-height:3em}</style>
<header><h1>Game review __TITLE__</h1><span class=lbl id=sub></span> <button id=tog></button><div id=hl style="margin-top:6px"></div></header>
<main><div id=tl></div><div id=side><div id=info>Click an event to see the frame and the video at that moment.</div><img id=fr hidden><video id=vd controls hidden></video></div></main>
<script>const D=__DATA__;const PXS=6,H=38,L=70,rows=["cs","gold","hp","items","deaths","recalls","last-hits","moments"];
const NS="http://www.w3.org/2000/svg";let END=Math.min(D.end,D.laning_end+15),FULL=false;
const hl=document.getElementById("hl");hl.innerHTML=D.headlines.map(h=>h.data?`<b>${h.at}</b> CS ${h.data.cs} (${h.data.cs_per_min}/min) · last-hit ${h.data.lasthit_rate==null?"-":h.data.lasthit_rate} (${h.data.lasthit_attempts}) · damage ${h.data.damage_per_min}/min · gold ${h.data.gold}${h.data.first_recall_s==null?"":" · first recall "+Math.floor(h.data.first_recall_s/60)+":"+String(h.data.first_recall_s%60).padStart(2,"0")}`:`<b>${h.at}</b> game ended earlier`).join("<br>");
function line(a,y0,h,max,col){a=a.filter(p=>p[0]<=END);const p=a.map(([t,v])=>(L+t*PXS).toFixed(1)+","+(y0+h-h*Math.min(v,max)/max).toFixed(1)).join(" ");return `<polyline points="${p}" fill=none stroke="${col}" stroke-width=1.5 />`}
function draw(){const W=L+Math.ceil(END*PXS)+40;
document.getElementById("sub").textContent=" "+Math.round(D.end/60*10)/10+" min recorded, CS "+(D.cs_exact?"exact (HUD counter)":"creepScore (steps of 10)")+"; showing "+(FULL?"the full game":"the laning phase 0:00-8:00");
document.getElementById("tog").textContent=FULL?"Show laning phase (0:00-8:00)":"Show full game";
let s=`<svg xmlns="${NS}" width=${W} height=${rows.length*H+30}>`;
for(let t=0;t<=END;t+=30){const x=L+t*PXS;s+=`<line x1=${x} x2=${x} y1=18 y2=${rows.length*H+22} stroke="var(--ln)" /><text class=lbl x=${x+2} y=12>${Math.floor(t/60)}:${String(t%60).padStart(2,"0")}</text>`}
[300,480].forEach(t=>{if(t<=END){const x=L+t*PXS;s+=`<line x1=${x} x2=${x} y1=18 y2=${rows.length*H+22} stroke="var(--acc)" stroke-width=2 /><text class=lbl x=${x+3} y=${rows.length*H+28} style="fill:var(--acc)">${t==300?"5:00":"8:00"}</text>`}});
rows.forEach((r,i)=>{const y=22+i*H;s+=`<text class=lbl x=4 y=${y+H/2}>${r}</text>`});
const mx=a=>Math.max(1,...a.filter(p=>p[0]<=END).map(p=>p[1]));
s+=line(D.cs,22,H-6,mx(D.cs),"var(--acc)")+line(D.gold,22+H,H-6,mx(D.gold),"var(--acc)")+line(D.hp,22+2*H,H-6,1,"var(--ok)");
D.events.forEach((e,i)=>{if(e.t>END)return;const r=rows.indexOf(e.row);if(r<0)return;const x=L+e.t*PXS,y=22+r*H+H/2;
s+=`<circle class=ev data-i=${i} cx=${x} cy=${y} r=6 fill="${e.bad?"var(--bad)":"var(--ok)"}"><title>${Math.floor(e.t/60)}:${String(Math.floor(e.t%60)).padStart(2,"0")} ${e.label.replace(/</g,"&lt;")}</title></circle>`});
document.getElementById("tl").innerHTML=s+"</svg>";
document.querySelectorAll(".ev").forEach(c=>c.onclick=()=>{const e=D.events[c.dataset.i];
document.getElementById("info").textContent=Math.floor(e.t/60)+":"+String(Math.floor(e.t%60)).padStart(2,"0")+"  "+e.label;
let best=null;D.frames.forEach(f=>{if(!best||Math.abs(f.t-e.t)<Math.abs(best.t-e.t))best=f});
const im=document.getElementById("fr");if(best){im.src=best.src;im.hidden=false;im.title="frame at "+best.t+" s"}else im.hidden=true;
const v=document.getElementById("vd");if(D.video){v.hidden=false;if(!v.src)v.src=D.video;v.currentTime=Math.max(0,e.t+D.offset-1)}})}
document.getElementById("tog").onclick=()=>{FULL=!FULL;END=FULL?D.end:Math.min(D.end,D.laning_end+15);draw()};draw();
</script>
<section style="padding:0 16px 24px">__REWARD__</section>"""
