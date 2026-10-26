#!/usr/bin/env python3
"""Per-frame viewer for one elite game: python3 scripts/lol_practice/elite_viewer.py <game_dir>
Writes <game_dir>/viewer.html (open it in a browser; no server). Needs frames as <file>.jpg and turns.jsonl (elite_video_extract.py).
Shows the frame with the detected units boxed (ally green, enemy magenta, Garen yellow), a scrubber, and the row's data."""
import json, os, sys

HTML = """<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>
body{{font:14px system-ui;margin:0;background:#111;color:#eee}}
header{{padding:8px 12px;background:#1b1b1b;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
#wrap{{display:flex;gap:12px;padding:12px}}
#stage{{position:relative;flex:0 0 auto}}
#stage img,#cv{{position:absolute;left:0;top:0;width:100%}}
#cv{{pointer-events:none}}
#side{{flex:1;min-width:260px}}
pre{{background:#1b1b1b;padding:8px;white-space:pre-wrap;max-height:50vh;overflow:auto;margin:0}}
input[type=range]{{width:60vw}}
button{{background:#2a2a2a;color:#eee;border:1px solid #444;padding:4px 10px;cursor:pointer}}
.legend span{{margin-right:10px}}
</style>
<header>
  <b>{title}</b>
  <button id="prev">&larr;</button><button id="play">play</button><button id="next">&rarr;</button>
  <input id="s" type="range" min="0" max="{last}" value="0">
  <span id="pos"></span>
  <span class="legend"><span style="color:#0f0">ally</span><span style="color:#f0f">enemy</span><span style="color:#ff0">Garen</span></span>
</header>
<div id="wrap">
  <div id="stage"><img id="img"><canvas id="cv" width="1920" height="1200"></canvas></div>
  <div id="side">
    <h3 id="t"></h3>
    <pre id="data"></pre>
  </div>
</div>
<script>
const ROWS = {rows};
const $ = id => document.getElementById(id);
const cv = $("cv"), ctx = cv.getContext("2d");
let i = 0, timer = null;
function box(x, y, color, label) {{
  ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.strokeRect(x - 31, y - 56, 62, 12);
  if (label) {{ ctx.fillStyle = color; ctx.font = "bold 22px sans-serif"; ctx.fillText(label, x - 22, y - 62); }}
}}
function show(k) {{
  i = Math.max(0, Math.min(ROWS.length - 1, k));
  const r = ROWS[i];
  $("img").src = r.file; $("s").value = i;
  $("t").textContent = "t = " + r.t.toFixed(2) + " s  (frame " + i + " / " + (ROWS.length - 1) + ")";
  ctx.clearRect(0, 0, 1920, 1200);
  for (const u of r.units) {{
    const c = u.kind.startsWith("enemy") ? "#f0f" : "#0f0";
    box(u.x, u.y, c, Math.round(u.hp * 100) + "%");
  }}
  if (r.garen) {{ ctx.strokeStyle = "#ff0"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(r.garen[0], r.garen[1], 22, 0, 7); ctx.stroke(); }}
  $("pos").textContent = "";
  $("data").textContent = JSON.stringify(r.data, null, 1);
}}
$("s").oninput = e => show(+e.target.value);
$("prev").onclick = () => show(i - 1);
$("next").onclick = () => show(i + 1);
$("play").onclick = () => {{
  if (timer) {{ clearInterval(timer); timer = null; $("play").textContent = "play"; return; }}
  $("play").textContent = "pause";
  timer = setInterval(() => {{ if (i >= ROWS.length - 1) {{ clearInterval(timer); timer = null; $("play").textContent = "play"; }} else show(i + 1); }}, 200);
}};
document.addEventListener("keydown", e => {{ if (e.key === "ArrowRight") show(i + 1); if (e.key === "ArrowLeft") show(i - 1); }});
$("img").onload = () => {{ cv.style.width = $("img").width + "px"; cv.style.height = $("img").height + "px"; }};
show(0);
</script>
"""


def build(gdir):
    rows = [json.loads(l) for l in open(os.path.join(gdir, "turns.jsonl"))]
    out = []
    for r in rows:
        s = r["state"]
        frame = next((f for f in os.listdir(gdir) if f.endswith(".jpg") and abs(float(f[:-4]) - r["t"]) < 0.02), None)
        units = [{"kind": u["kind"], "x": u["px"][0], "y": u["px"][1], "hp": u["hp_frac"]} for u in r["world"]["units"]]
        g = s.get("screen_pos")
        out.append({
            "t": r["t"], "file": frame or "", "units": units, "garen": g,
            "data": {"hp": f'{s.get("hp")}/{s.get("hp_max")}', "level": s.get("level"), "cs": s.get("cs"), "ad": s.get("ad"), "as": s.get("as"),
                     "ms": s.get("ms"), "armor": s.get("armor"), "items": s.get("items"), "dead": s.get("dead"),
                     "spells": {k: [v.get("rank"), "ready" if v.get("ready") else v.get("ready_in_s")] for k, v in s.get("spells", {}).items()},
                     "events": [e["kind"] for e in r.get("events", [])],
                     "units": {k: sum(1 for u in units if u["kind"] == k) for k in ("ally_minion", "enemy_minion", "ally_champion", "enemy_champion")}},
        })
    out = [r for r in out if r["file"]]
    title = os.path.basename(os.path.normpath(gdir))
    with open(os.path.join(gdir, "viewer.html"), "w", encoding="utf-8") as f:
        f.write(HTML.format(title="elite game " + title, last=len(out) - 1, rows=json.dumps(out)))
    print(os.path.join(gdir, "viewer.html"), len(out), "frames")


if __name__ == "__main__":
    build(sys.argv[1])
