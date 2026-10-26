"""HTML viewer for one built dataset: scrubber over the ticks, map, entity tables, features, events, coverage, thumbnails.

The page is generated from the real tables (no server, no network). Thumbnails are one JPEG per game second, embedded
as data URIs (only when the video can be decoded with ffmpeg). Output is kept under ~15 MB by sending only the fields
the viewer shows.
"""
import base64
from collections import defaultdict
import glob
import json
import os
import shutil
import subprocess
import tempfile


def read_table(dataset_dir, name):
    path = os.path.join(dataset_dir, f"{name}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def thumbnails(video, frame0, n_seconds):
    """One JPEG per game second from frame0, as data URIs keyed by second index. {} when ffmpeg or the video is missing."""
    if not video or not os.path.exists(video) or frame0 is None or not shutil.which("ffmpeg"):
        return {}
    tmp = tempfile.mkdtemp(prefix="lol_thumbs_")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf", "fps=1,scale=256:-2", "-q:v", "6",
                        os.path.join(tmp, "%05d.jpg")], check=False)
        out = {}
        for n, path in enumerate(sorted(glob.glob(os.path.join(tmp, "*.jpg")))):
            if n >= n_seconds:
                break
            with open(path, "rb") as f:
                out[n] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build(dataset_dir, video, out_html):
    meta = json.load(open(os.path.join(dataset_dir, "meta.json"), encoding="utf-8"))
    coverage = json.load(open(os.path.join(dataset_dir, "coverage.json"), encoding="utf-8"))
    ticks = read_table(dataset_dir, "ticks")
    minions = read_table(dataset_dir, "minions")
    champs = read_table(dataset_dir, "champions")
    events = read_table(dataset_dir, "events")
    attacks = read_table(dataset_dir, "attacks")
    actions = read_table(dataset_dir, "actions")
    feats = {r["tick"]: r for r in read_table(dataset_dir, "features")}
    teams = {}
    for r in read_table(dataset_dir, "teams"):
        teams.setdefault(r["tick"], {})[r["team"]] = r

    by_tick_m, by_tick_c, by_tick_a = {}, {}, {}
    for r in minions:
        by_tick_m.setdefault(r["tick"], []).append([r["uid"], r["rel"], r.get("hp_frac"), r["px"], r["py"], r["observed"],
                                                    r["alive"], r.get("dist_to_subject_px")])
    for r in champs:
        by_tick_c.setdefault(r["tick"], []).append([r["uid"], r.get("champion"), r["side"], r["rel"], r.get("hp_frac"), r["px"], r["py"],
                                                    r["is_subject"], r.get("level"), r.get("cs"), r.get("kills"), r.get("deaths"), r.get("assists"),
                                                    r["observed"]])
    for r in actions:
        by_tick_a.setdefault(r["tick"], []).append([r["kind"], r["inferred"], r["conf"]])

    frame0 = meta.get("frame0_game_time_s")
    t0 = meta["t0"]
    rows = []
    for t in ticks:
        k = t["tick"]
        f = feats.get(k, {})
        tm = teams.get(k, {})
        rows.append({
            "k": k, "t": t["t_s"], "o": t["observed"], "lag": t["lag_ms"],
            "m": by_tick_m.get(k, []), "c": by_tick_c.get(k, []), "a": by_tick_a.get(k, []),
            "f": {c: f.get(c) for c in ("subject_hp_frac", "subject_level", "subject_cs", "subject_dead", "n_ally_minion",
                                        "n_enemy_minion", "n_enemy_minion_low", "n_enemy_champion",
                                        "nearest_enemy_minion_px", "wave_index")},
            "tm": {tid: [v["kills"], v["deaths"]] for tid, v in tm.items()},
        })
    ev_rows = [{"t": e["t_s"], "k": e["kind"], "a": e["actor_uid"], "s": e["subject_uid"], "v": e["value"], "c": e["conf"],
                "m": e["method"]} for e in sorted(events, key=lambda e: e["tick"])]
    at_rows = [{"t": a["t_s"], "tg": a["target_uid"], "k": a["kind"], "d": a["damage_frac"], "c": a["conf"]} for a in attacks]

    thumbs = thumbnails(video, frame0, int((meta["t1"] - t0) + 2)) if frame0 is not None else {}

    # three longest minion tracks, for the timeline panel (uid, [t, hp, alive, rel])
    tl = defaultdict(list)
    for r in minions:
        tl[r["uid"]].append((r["t_s"], r["hp_frac"], r["alive"], r["rel"]))
    longest = sorted(tl.items(), key=lambda kv: kv[1][-1][0] - kv[1][0][0], reverse=True)[:3]
    tracks = [{"uid": uid, "rows": [list(x) for x in sorted(v)]} for uid, v in longest]

    dps = [{"t": d["t_s"], "layer": d["layer"], "trig": d.get("trigger") or [], "chosen": d["chosen"],
            "reward": d["reward"], "window": d["window_s"], "rule": d.get("label_rule", "")}
           for d in read_table(dataset_dir, "decision_points")]

    payload = {"meta": meta, "rows": rows, "events": ev_rows, "attacks": at_rows, "coverage": coverage, "tracks": tracks, "dps": dps,
               "thumbs": {str(n): v for n, v in thumbs.items()}, "frame0": frame0, "t0": t0}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", blob).replace("__TITLE__", f"LoL dataset {meta['game_id']} ({meta['subject_champion']})")
    os.makedirs(os.path.dirname(os.path.abspath(out_html)), exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    return out_html, len(rows), len(thumbs)


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f6f4;--panel:#fff;--ink:#1c1c1a;--muted:#6b6a64;--line:#dedcd4;--ally:#2b7de0;--enemy:#d6452e;--subj:#c99700;--ok:#2f7d4a;--part:#b07a00;--miss:#a33;}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15151a;--panel:#1f1f26;--ink:#eceae4;--muted:#9a9890;--line:#33333c;--ally:#5aa2ff;--enemy:#ff7a63;--subj:#e8b630;--ok:#6cc48a;--part:#e2b04e;--miss:#ff8a8a;}}
:root[data-theme="dark"]{--bg:#15151a;--panel:#1f1f26;--ink:#eceae4;--muted:#9a9890;--line:#33333c;--ally:#5aa2ff;--enemy:#ff7a63;--subj:#e8b630;--ok:#6cc48a;--part:#e2b04e;--miss:#ff8a8a;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 system-ui,-apple-system,sans-serif}
header{padding:12px 16px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:12px;align-items:center}
header h1{font-size:15px;margin:0 8px 0 0}
button{background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 10px;cursor:pointer}
input[type=range]{width:min(60vw,640px)}
.muted{color:var(--muted)} .pill{border:1px solid var(--line);border-radius:999px;padding:1px 8px;font-size:12px}
main{display:grid;grid-template-columns:minmax(300px,1fr) minmax(320px,1fr);gap:12px;padding:12px}
@media (max-width:900px){main{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-width:0}
section h2{font-size:13px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:3px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
.scroll{max-height:300px;overflow:auto}
#map{width:100%;height:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px}
#thumb{width:100%;max-width:320px;border-radius:8px;border:1px solid var(--line)}
.st{font-weight:600} .filled{color:var(--ok)} .partial{color:var(--part)} .missing{color:var(--miss)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px} .kv b{font-weight:500;color:var(--muted)}
.note{font-size:12px;color:var(--muted)} .constant{color:var(--muted)}
</style></head><body>
<header>
  <h1>__TITLE__</h1>
  <button id="prev">&larr;</button><button id="play">Play</button><button id="next">&rarr;</button>
  <input id="s" type="range" min="0" max="0" value="0" aria-label="game time">
  <span id="pos" class="pill"></span>
  <button id="theme" title="Toggle light / dark">Theme</button>
</header>
<main>
  <section>
    <h2>Map (screen px, fixed frame; not map units)</h2>
    <svg id="map" viewBox="0 0 640 400" role="img" aria-label="units"></svg>
    <p class="note" id="mapnote"></p>
    <img id="thumb" alt="" hidden>
    <p class="note">Thumbnail: the whole video second nearest this tick (up to 0.5 s away).</p>
    <h2 style="margin-top:10px">Subject and features</h2>
    <div class="kv" id="feat"></div>
  </section>
  <section>
    <h2>Coverage (real / inferred / missing per field)</h2>
    <div id="cov"></div>
  </section>
  <section>
    <h2>Champions at this tick</h2>
    <div class="scroll"><table id="ctab"></table></div>
  </section>
  <section>
    <h2>Minions at this tick (<span id="mcount"></span>)</h2>
    <div class="scroll"><table id="mtab"></table></div>
  </section>
  <section>
    <h2>Events, last 15 s</h2>
    <div class="scroll"><table id="etab"></table></div>
  </section>
  <section>
    <h2>Attacks (not built in this build) &middot; actions (inferred)</h2>
    <div class="scroll"><table id="atab"></table></div>
    <p class="note" id="actnote"></p>
  </section>
  <section style="grid-column:1/-1">
    <h2>Minion track timelines (3 longest; bar height = HP, cursor = current tick)</h2>
    <svg id="tl" viewBox="0 0 960 150" style="width:100%;height:auto"></svg>
    <p class="note" id="tlnote"></p>
  </section>
  <section style="grid-column:1/-1">
    <h2>Decision points (event-triggered lane points, DATASET_SPEC 6)</h2>
    <p class="note" id="dpnote"></p>
    <div class="scroll"><table id="dptab"></table></div>
  </section>
</main>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const rows = D.rows, N = rows.length;
const s = $("s"); s.max = N - 1;
let i = 0, timer = null;
const esc = v => String(v ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (v, d = 2) => v == null ? "&mdash;" : (typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(d)) : esc(v));

function drawMap(r) {
  const svg = $("map"); const W = 640, H = 400;
  const pts = [];
  for (const m of r.m) if (m[3] != null) pts.push({x: m[3], y: m[4], c: m[1] === "enemy" ? "var(--enemy)" : "var(--ally)", r: 3, o: m[5]});
  for (const c of r.c) if (c[5] != null) pts.push({x: c[5], y: c[6], c: c[7] ? "var(--subj)" : (c[3] === "enemy" ? "var(--enemy)" : "var(--ally)"), r: c[7] ? 7 : 5, o: c[13]});
  // fixed frame: the capture's screen, 1920 x 1200 px (not map units)
  const x0 = 0, x1 = 1920, y0 = 0, y1 = 1200;
  const sx = v => v / 1920 * W, sy = v => v / 1200 * H;
  svg.innerHTML = pts.map(p => `<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${p.r}" fill="${p.c}" opacity="${p.o ? 1 : .45}"/>`).join("");
  $("mapnote").textContent = pts.length ? `${pts.length} units at screen px (fixed 1920 x 1200 frame), not map units. Every row is observed: no carried rows.` : "No observed units on this tick.";
}
function showThumb(r) {
  const n = Math.round(r.t - D.frame0);
  const src = D.thumbs[String(n)];
  const img = $("thumb");
  if (src) { img.src = src; img.hidden = false; } else { img.hidden = true; }
}
function render(r) {
  $("pos").textContent = `t = ${r.t.toFixed(1)} s · tick ${r.k} · ${r.o ? "observed" : "carried"} (lag ${r.lag ?? "—"} ms)`;
  const f = r.f;
  $("feat").innerHTML = [["subject HP", f.subject_hp_frac != null ? Math.round(f.subject_hp_frac * 100) + " %" : null],
    ["level", f.subject_level], ["CS", f.subject_cs], ["dead", f.subject_dead],
    ["ally minions", f.n_ally_minion], ["enemy minions", f.n_enemy_minion], ["enemy minions < 25 %", f.n_enemy_minion_low],
    ["enemy champions", f.n_enemy_champion], ["nearest enemy minion (px)", fmt(f.nearest_enemy_minion_px, 0)],
    ["wave index (30 s)", f.wave_index], ["team K / D (blue)", r.tm["100"] ? r.tm["100"].join(" / ") : null],
    ["team K / D (red)", r.tm["200"] ? r.tm["200"].join(" / ") : null]]
    .map(([k, v]) => `<b>${k}</b><span>${fmt(v)}</span>`).join("");
  $("ctab").innerHTML = "<tr><th>champion</th><th>side</th><th>HP</th><th>lvl</th><th>CS</th><th>K/D/A</th><th>obs</th></tr>" +
    r.c.map(c => `<tr><td>${c[7] ? "<b>" + esc(c[1]) + "</b>" : esc(c[1] ?? "unidentified")}</td><td>${esc(c[2])}</td><td>${c[4] != null ? Math.round(c[4]*100) + " %" : "&mdash;"}</td><td>${fmt(c[8])}</td><td>${fmt(c[9])}</td><td>${c[10] != null ? c[10] + "/" + c[11] + "/" + c[12] : "&mdash;"}</td><td>${c[13] ? "yes" : "carried"}</td></tr>`).join("");
  $("mcount").textContent = r.m.length;
  $("mtab").innerHTML = "<tr><th>uid</th><th>rel</th><th>HP %</th><th>px</th><th>py</th><th>observed</th><th>alive</th><th>dist px</th></tr>" +
    r.m.slice(0, 60).map(m => `<tr><td>${esc(m[0].split("-").slice(-1)[0])}</td><td>${esc(m[1])}</td><td>${m[2] != null ? Math.round(m[2]*100) : "&mdash;"}</td><td>${fmt(m[3],0)}</td><td>${fmt(m[4],0)}</td><td>${m[5] ? "observed" : "carried"}</td><td>${m[6] ? "yes" : "no"}</td><td>${fmt(m[7],0)}</td></tr>`).join("");
  const evs = D.events.filter(e => e.t <= r.t && e.t >= r.t - 15).slice(-40);
  $("etab").innerHTML = "<tr><th>t</th><th>kind</th><th>actor</th><th>subject</th><th>conf</th><th>method</th></tr>" +
    evs.map(e => `<tr><td>${e.t.toFixed(2)}</td><td>${esc(e.k)}</td><td>${esc(e.a)}</td><td>${esc(e.s)}</td><td>${e.c}</td><td>${esc(e.m)}</td></tr>`).join("");
  const ats = D.attacks.filter(a => a.t <= r.t && a.t >= r.t - 10).slice(-30);
  $("atab").innerHTML = "<tr><th>t</th><th>kind</th><th>target</th><th>damage (frac)</th><th>conf</th></tr>" +
    ats.map(a => `<tr><td>${a.t.toFixed(2)}</td><td>${esc(a.k)}</td><td>${esc((a.tg||"").split("-").slice(-1)[0])}</td><td>${fmt(a.d, 3)}</td><td>${a.c}</td></tr>`).join("");
  $("actnote").textContent = r.a.length ? "This tick: " + r.a.map(a => a[0] + (a[1] ? " (inferred, conf " + a[2] + ")" : " (real)")).join(", ") : "No action on this tick.";
  drawMap(r); showThumb(r); drawTracks(r.t); drawDps(r.t);
}
function show(k) {
  i = Math.max(0, Math.min(N - 1, k)); s.value = i; render(rows[i]);
}
s.oninput = e => show(+e.target.value);
$("prev").onclick = () => show(i - 1);
$("next").onclick = () => show(i + 1);
$("play").onclick = () => {
  if (timer) { clearInterval(timer); timer = null; $("play").textContent = "Play"; return; }
  $("play").textContent = "Pause";
  timer = setInterval(() => { if (i >= N - 1) { clearInterval(timer); timer = null; $("play").textContent = "Play"; } else show(i + 1); }, 250);
};
$("theme").onclick = () => {
  const root = document.documentElement; const dark = root.dataset.theme === "dark" || (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  root.dataset.theme = dark ? "light" : "dark";
};
document.addEventListener("keydown", e => { if (e.key === "ArrowRight") show(i + 1); if (e.key === "ArrowLeft") show(i - 1); });

// coverage panel: per table, the fields with status
const cov = D.coverage;
$("cov").innerHTML = Object.entries(cov).map(([tname, cols]) => {
  const vals = Object.values(cols);
  const n = vals.length, f = vals.filter(c => c.status === "filled").length, p = vals.filter(c => c.status === "partial").length, cn = vals.filter(c => c.status === "constant").length;
  const rowsList = vals.map((c, idx) => [Object.keys(cols)[idx], c]);
  return `<details><summary><b>${tname}</b> <span class="muted">${f} filled · ${p} partial · ${cn} constant · ${n - f - p - cn} missing of ${n}</span></summary>
    <table><tr><th>field</th><th>status</th><th>fill</th><th>reason</th></tr>` +
    rowsList.map(([k, c]) => `<tr><td>${esc(k)}</td><td class="st ${c.status}">${c.status}</td><td>${Math.round(c.fill*100)} %</td><td style="text-align:left;white-space:normal">${esc(c.reason || "")}</td></tr>`).join("") +
    `</table></details>`;
}).join("");

// track timelines: x = game time over the capture, one row per track, bar height = HP, colour = relation
function drawTracks(tNow) {
  const svg = $("tl"); const W = 960, rowH = 40, left = 150, t0 = D.t0, t1 = D.meta.t1;
  const X = t => left + (t - t0) / (t1 - t0) * (W - left - 10);
  let out = "";
  D.tracks.forEach((tr, i) => {
    const y = 10 + i * rowH;
    out += `<text x="4" y="${y + 22}" font-size="12" fill="var(--ink)">${esc(tr.uid.split("-").slice(-1)[0])}</text>`;
    for (const [t, hp, alive, rel] of tr.rows) {
      const h = Math.max(2, (hp ?? 0) * 28);
      out += `<rect x="${X(t).toFixed(1)}" y="${(y + 32 - h).toFixed(1)}" width="3" height="${h.toFixed(1)}" fill="${rel === "enemy" ? "var(--enemy)" : "var(--ally)"}"/>`;
      if (alive === false) out += `<circle cx="${X(t).toFixed(1)}" cy="${y + 33}" r="3" fill="var(--miss)"/>`;
    }
  });
  out += `<line x1="${X(tNow).toFixed(1)}" x2="${X(tNow).toFixed(1)}" y1="0" y2="150" stroke="var(--subj)" stroke-width="2"/>`;
  svg.innerHTML = out;
  $("tlnote").textContent = "Red bars = ally (our side relative to Garen), blue = enemy; a red dot = track ends in a death. Track ids are stable per track, not verified across frames by hand beyond one frame per track.";
}
// decision points: the list, and the one nearest the scrubber (highlighted)
function drawDps(tNow) {
  const rows = D.dps || [];
  $("dpnote").textContent = rows.length + " points (coach 5 s, tactician 3 s windows). Labels are rule-based and not yet validated; reward is per 1 s slice from the slice's own HP.";
  $("dptab").innerHTML = "<tr><th>t</th><th>layer</th><th>trigger</th><th>chosen</th><th>reward</th><th>rule</th></tr>" +
    rows.filter(d => Math.abs(d.t - tNow) <= 30).map(d => `<tr style="${Math.abs(d.t - tNow) < 0.5 ? 'font-weight:700' : ''}"><td>${d.t.toFixed(2)}</td><td>${esc(d.layer)}</td><td>${esc(d.trig.join(", "))}</td><td>${esc(d.chosen)}</td><td>${fmt(d.reward, 2)}</td><td style="text-align:left;white-space:normal">${esc(d.rule)}</td></tr>`).join("");
}
const m = D.meta;
$("feat").insertAdjacentHTML("afterend", `<p class="note">Game ${esc(m.game_id)} · subject ${esc(m.subject_champion)} (${esc(m.subject_side)}) · schema ${esc(m.schema_version)} · ${esc(m.alignment)}</p>`);
show(0);
</script>
</body></html>
"""
