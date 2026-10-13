"""
The game report (TASK-33 phase 4d): the game video with every decision overlaid on it, time-synced.

One page serves both views:
- **one run** (`build_html`): a single self-contained file, video embedded (base64), uploaded with the
  run's reports;
- **the whole game** (`build_series`, served by `series.py`): every run kept in the private game folder,
  played back to back like the stream's TS segments, with one timeline for the whole game. Each
  segment's video and events are fetched only when it plays, so 40 h of play stays a light page.

Each event (runner.log) is placed at `t - video_start` seconds into its segment. The page shows, for the
event active at the current time: the choice on the video, and beside it the state, the options with
their facts, the prompt sent and the answer, tokens, cost and latency.
"""

import base64
import html
import json
from typing import Dict, List, Optional

from ...utils.report_theme import report_theme_head

KIND_LABEL = {
    "battle_choice": "Battle", "battle_end": "Battle end", "strategy": "Strategy", "milestone": "Milestone", "defeat": "Defeat",
    "heal_start": "Heal", "healed": "Healed", "heal_choice": "Heal or push", "move_learn_choice": "Move to forget",
    "shop_start": "Shopping", "bought": "Bought balls", "shop_failed": "Shopping failed", "caught": "Caught", "catch_failed": "Not caught",
    "train_start": "Training", "trained": "Trained", "train_stalled": "Training stalled",
    "gym_leader": "Gym leader", "warp_unusable": "Door", "lost": "No route", "explore": "Explore", "blocked_by": "In the way",
    "blocker_wall": "Wall (beaten trainer)", "story_done": "Story done",
    "hm_taught": "Move taught", "hm_failed": "Move not taught", "cut_tree": "Tree cut", "cut_failed": "Cut failed",
    "trash_can": "Trash can", "exit_blocked": "Map exit blocked", "struggle": "Struggle (no PP)",
    "milestone_done": "Milestone done", "dead_end": "Dead end (back out)", "poster_switch": "Poster switch", "lift_floor": "Elevator floor", "flute_used": "Poké Flute",
}


def _tokens(e: Dict) -> Dict[str, int]:
    u = e.get("usage") or {}
    return {"in": int(u.get("input_tokens") or u.get("prompt_tokens") or 0),
            "out": int(u.get("output_tokens") or u.get("completion_tokens") or 0)}


def totals(events: List[Dict]) -> Dict:
    t_in = sum(_tokens(e)["in"] for e in events)
    t_out = sum(_tokens(e)["out"] for e in events)
    cost = sum(float(e.get("cost") or 0) for e in events)
    ai = [e for e in events if e.get("prompt") or e.get("instructions")]
    return {"tokens_in": t_in, "tokens_out": t_out, "cost": round(cost, 6), "ai_calls": len(ai),
            "battle_decisions": sum(1 for e in events if e["kind"] == "battle_choice")}


def segment(events: List[Dict], src: str, video_start: float, video_end: Optional[float], summary: Dict,
            offset: float = 0.0, events_url: str = "", name: str = "") -> Dict:
    """One played segment: its video, where it starts on the game's timeline, and its event marks.
    The events themselves are inlined (one run) or fetched from `events_url` (the whole game)."""
    shown = [e for e in events if e["kind"] in KIND_LABEL]
    dur = (video_end - video_start) if video_end and video_end > video_start else \
        max([float(summary.get("duration_s") or 0)] + [e["t"] - video_start + 1 for e in shown] + [1.0])
    at = lambda e: round(min(dur, max(0.0, float(e["t"]) - video_start)), 2)
    seg = {"src": src, "name": name, "video_start": video_start, "dur": round(dur, 2), "offset": round(offset, 2),
           "summary": summary, "marks": [[at(e), e["kind"]] for e in shown]}
    if events_url:
        seg["events_url"] = events_url
    else:
        seg["events"] = [{k: v for k, v in e.items() if k != "known"} for e in shown]
    return seg


def page(segments: List[Dict], summary: Dict, tot: Dict, title: str) -> str:
    data = json.dumps({"segments": segments, "summary": summary, "totals": tot, "labels": KIND_LABEL},
                      ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", data)


def build_html(events: List[Dict], video: Optional[bytes], video_type: str, video_start: float,
               summary: Dict, title: str = "Pokémon Blue — game report", video_end: Optional[float] = None) -> str:
    """The report of one run: a single file with the video embedded."""
    src = f"data:{video_type or 'video/webm'};base64,{base64.b64encode(video).decode()}" if video else ""
    return page([segment(events, src, video_start, video_end, summary)], summary, totals(events), title)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
""" + report_theme_head() + r"""<title>__TITLE__</title>
<style>
:root { --bg:var(--vpt-page); --card:var(--vpt-surface); --fg:var(--vpt-text); --muted:var(--vpt-text-2); --line:var(--vpt-border); --accent:var(--vpt-accent);
  --battle:var(--vpt-steel); --strategy:var(--vpt-purple); --milestone:var(--vpt-success); --defeat:var(--vpt-error); --heal:var(--vpt-warning); --other:var(--vpt-text-2); }
* { box-sizing: border-box; } body { margin:0; background:var(--bg); color:var(--fg);
  font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
header { padding:16px; } h1 { margin:0 0 6px; font-size:20px; }
.kpis { display:flex; flex-wrap:wrap; gap:8px; } .kpi { background:var(--card); border:1px solid var(--line);
  border-radius:8px; padding:6px 10px; } .kpi b { display:block; font-size:15px; } .kpi span { color:var(--muted); font-size:12px; }
main { display:grid; grid-template-columns:minmax(0,1fr) 420px; gap:16px; padding:0 16px 16px; }
@media (max-width:1000px) { main { grid-template-columns:1fr; } }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; min-width:0; }
.stage { position:relative; background:#000; border-radius:8px; overflow:hidden; }
video { width:100%; max-height:72vh; display:block; image-rendering:pixelated; aspect-ratio:160/144; background:#000; object-fit:contain; }
.over { position:absolute; left:8px; right:8px; bottom:8px; background:rgba(10,14,22,.82); color:#fff;
  border-radius:8px; padding:8px 10px; font-size:13px; pointer-events:none; }
.over .k { display:inline-block; padding:1px 7px; border-radius:10px; font-size:11px; margin-right:6px; color:#fff; }
.timeline { position:relative; height:28px; margin-top:10px; background:var(--bg); border:1px solid var(--line); border-radius:6px; cursor:pointer; }
.timeline canvas { width:100%; height:100%; display:block; }
.where { margin-top:4px; color:var(--muted); font-size:12px; display:flex; justify-content:space-between; gap:8px; }
.cursor { position:absolute; top:0; bottom:0; width:2px; background:var(--fg); opacity:.6; }
.legend { display:flex; gap:12px; flex-wrap:wrap; margin-top:6px; color:var(--muted); font-size:12px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:-1px; }
h2 { font-size:15px; margin:0 0 8px; } .muted { color:var(--muted); }
table { width:100%; border-collapse:collapse; font-size:13px; } td { padding:4px 6px; border-top:1px solid var(--line); vertical-align:top; }
tr.chosen td { background:var(--vpt-accent-tint); font-weight:600; }
details { margin-top:8px; } summary { cursor:pointer; color:var(--accent); }
pre { white-space:pre-wrap; word-break:break-word; background:var(--vpt-subtle); border:1px solid var(--line); border-radius:6px; padding:8px; font-size:12px; max-height:260px; overflow:auto; }
.list { max-height:340px; overflow:auto; margin-top:8px; } .row { padding:5px 6px; border-top:1px solid var(--line); cursor:pointer; font-size:13px; }
.row:hover, .row.on { background:var(--vpt-accent-tint); }
.tag { display:inline-block; min-width:72px; font-size:11px; font-weight:600; }
</style></head><body>
<header><h1>__TITLE__</h1><div class="kpis" id="kpis"></div></header>
<main>
  <section class="card">
    <div class="stage"><video id="v" controls muted playsinline></video><div class="over" id="over">—</div></div>
    <div class="timeline" id="tl"><canvas id="cv"></canvas><div class="cursor" id="cur"></div></div>
    <div class="where"><span id="seg"></span><span id="clock"></span></div>
    <div class="legend" id="legend"></div>
    <div class="list" id="list"></div>
  </section>
  <aside class="card" id="detail"><h2>Decision</h2><p class="muted">Play the video or click the timeline.</p></aside>
</main>
<script>
const D = __DATA__, SEG = D.segments, L = D.labels;
const TOTAL = Math.max(1, ...SEG.map(s => s.offset + s.dur));
const COLORS = {battle_choice:"--battle", move_learn_choice:"--strategy", strategy:"--strategy", milestone:"--milestone", defeat:"--defeat",
  heal_start:"--heal", healed:"--heal", train_start:"--strategy", trained:"--milestone", train_stalled:"--defeat",
  shop_start:"--heal", bought:"--heal", caught:"--milestone", catch_failed:"--defeat", shop_failed:"--defeat",
  hm_taught:"--milestone", cut_tree:"--milestone", hm_failed:"--defeat", cut_failed:"--defeat",
  milestone_done:"--milestone", poster_switch:"--milestone", lift_floor:"--milestone", flute_used:"--milestone"};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const color = k => `var(${COLORS[k] || "--other"})`;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const hms = x => { x = Math.round(x); const h = Math.floor(x / 3600), m = Math.floor(x % 3600 / 60), s = x % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0"); };
const v = document.getElementById("v"), tl = document.getElementById("tl"), cv = document.getElementById("cv"), cur = document.getElementById("cur");
const S = D.summary || {}, T = D.totals;
const kpi = (b, s) => `<div class="kpi"><b>${esc(b)}</b><span>${esc(s)}</span></div>`;
document.getElementById("kpis").innerHTML = [
  kpi(`${S.start_milestone || "?"} → ${S.end_milestone || "?"}`, "milestone"), kpi(S.badges ?? "?", "badges"),
  kpi(S.leader || "?", "party leader"), kpi(S.money ?? "?", "money"), kpi(T.battle_decisions, "battle decisions"),
  kpi(T.ai_calls, "AI calls"), kpi(`${T.tokens_in} / ${T.tokens_out}`, "tokens in / out"),
  kpi("$" + T.cost.toFixed(5), "AI cost"), kpi(hms(S.duration_s || TOTAL), "played"),
  SEG.length > 1 ? kpi(SEG.length, "runs") : ""].join("");
document.getElementById("legend").innerHTML = [["battle_choice","Battle"],["strategy","Strategy"],["milestone","Milestone"],["defeat","Defeat"],["heal_start","Heal"]]
  .map(([k,l]) => `<span><i style="background:${color(k)}"></i>${l}</span>`).join("");

// The game's timeline: every segment's marks on one canvas (thousands of marks over 40 h stay cheap).
function drawMarks() {
  const r = window.devicePixelRatio || 1, w = cv.clientWidth * r, h = cv.clientHeight * r;
  cv.width = w; cv.height = h; const g = cv.getContext("2d");
  g.fillStyle = css("--line"); SEG.forEach(s => g.fillRect(w * s.offset / TOTAL, 0, r, h));
  const draw = big => SEG.forEach(s => s.marks.forEach(([at, k]) => {
    if ((k !== "battle_choice") !== big) return;
    g.fillStyle = css(COLORS[k] || "--other");
    g.fillRect(w * (s.offset + at) / TOTAL, big ? 2 * r : 9 * r, Math.max(2, 2 * r), big ? h - 4 * r : h - 18 * r);
  }));
  draw(false); draw(true);   // battles first, the rarer kinds on top
}
function line(e) {
  if (e.kind === "battle_choice") return `${e.choice_name || e.choice} — ${e.by}${e.confidence != null ? " · conf " + Number(e.confidence).toFixed(2) : ""} · HP ${e.our_hp} vs ${e.enemy_hp}`;
  if (e.kind === "move_learn_choice") return `${e.forgotten ? "forget " + e.forgotten : "keep the moves"} for ${e.new_move} — ${e.by}${e.confidence != null ? " · conf " + Number(e.confidence).toFixed(2) : ""}`;
  if (e.kind === "heal_choice") return `${e.choice} — ${e.by}${e.confidence != null ? " · conf " + Number(e.confidence).toFixed(2) : ""}`;
  if (e.kind === "battle_end") return `${e.outcome} after ${e.turns} turn(s) (${e.battle || e.kind})`;
  if (e.kind === "strategy") return `${e.trigger}: ${e.plan || ""}`;
  if (e.kind === "milestone") return `${e.id}: ${e.goal}`;
  if (e.kind === "hm_taught") return `${e.move} taught to ${e.pokemon} (level ${e.level})`;
  if (e.kind === "cut_tree") return `${e.pokemon} cut the tree at (${e.at})`;
  if (e.kind === "trash_can") return `can (${e.at}): ${e.result}`;
  if (e.kind === "milestone_done") return `${e.id}: map ${e.map}, badges ${e.badges}, key items ${(e.bag || []).map(i => "0x" + i.toString(16)).join(" ")}`;
  if (e.kind === "lift_floor") return `elevator to floor ${e.floor}`;
  if (e.kind === "flute_used") return `Poké Flute played facing (${e.at})`;
  if (e.kind === "defeat") return `money ${e.money_before} → ${e.money_after}`;
  return Object.entries(e).filter(([k]) => !["t","at","kind","label","tok"].includes(k)).map(([k,x]) => `${k}=${typeof x === "object" ? JSON.stringify(x) : x}`).join(", ");
}
function tok(e) { const u = e.usage || {};
  return {in: +(u.input_tokens || u.prompt_tokens || 0), out: +(u.output_tokens || u.completion_tokens || 0)}; }

// The segment playing now and its events (fetched on first play when not inlined).
let si = -1, EV = [], last = -1;
async function openSeg(i) {
  if (i === si) return;
  const s = SEG[i]; let evs = s.events;
  if (!evs) { try { evs = (await (await fetch(s.events_url)).json()).events || []; } catch (err) { evs = []; } }
  si = i; last = -1;
  EV = evs.filter(e => L[e.kind]).map(e => ({...e, label: L[e.kind], tok: tok(e),
    at: Math.min(s.dur, Math.max(0, e.t - s.video_start))}));
  document.getElementById("seg").textContent = SEG.length > 1 ? `Run ${i + 1} / ${SEG.length} · ${s.name}` : "";
  document.getElementById("list").innerHTML = EV.map((e, k) =>
    `<div class="row" data-i="${k}"><span class="tag" style="color:${color(e.kind)}">${esc(e.label)}</span> <span class="muted">${hms(s.offset + e.at)}</span> ${esc(line(e))}</div>`).join("");
  document.querySelectorAll(".row").forEach(r => r.onclick = () => { v.currentTime = EV[+r.dataset.i].at + 0.05; });
  v.src = s.src;
  await new Promise(ok => v.addEventListener("loadedmetadata", ok, {once: true}));
}
async function seekGlobal(g, play) {
  let i = 0; while (i + 1 < SEG.length && SEG[i + 1].offset <= g) i++;
  const wasPlaying = play ?? !v.paused;
  await openSeg(i); v.currentTime = Math.max(0, g - SEG[i].offset);
  if (wasPlaying) v.play().catch(() => {});
}
function cost(e) { return e.cost ? "$" + Number(e.cost).toFixed(6) : "—"; }
function show(i) {
  document.querySelectorAll(".row").forEach(r => r.classList.toggle("on", +r.dataset.i === i));
  const e = EV[i], over = document.getElementById("over"), det = document.getElementById("detail");
  if (!e) { over.textContent = "—"; return; }
  const at = SEG[si].offset + e.at;
  over.innerHTML = `<span class="k" style="background:${color(e.kind)}">${esc(e.label)}</span>${esc(line(e))}` +
    ((e.tok.in || e.tok.out || e.cost) ? `<br><span style="opacity:.8">tokens ${e.tok.in} in / ${e.tok.out} out · ${cost(e)}${e.ms ? " · " + e.ms + " ms" : ""}${e.model ? " · " + esc(e.model) : ""}</span>` : "");
  let h = `<h2>${esc(e.label)} <span class="muted">@ ${hms(at)}</span></h2><p>${esc(line(e))}</p>`;
  h += `<table><tr><td>Chooser / model</td><td>${esc(e.by || e.model || e.source || "—")}</td></tr>` +
       `<tr><td>Tokens in / out</td><td>${e.tok.in} / ${e.tok.out}</td></tr><tr><td>Cost</td><td>${cost(e)}</td></tr>` +
       (e.ms ? `<tr><td>Latency</td><td>${e.ms} ms</td></tr>` : "") + `</table>`;
  if (e.state) h += `<h2 style="margin-top:12px">State</h2><p>${esc(e.state)}</p>`;
  if (e.options) h += `<h2 style="margin-top:12px">Options</h2><table>` + e.options.map(o =>
     `<tr class="${o.id === e.choice ? "chosen" : ""}"><td>${esc(o.name || o.id)}</td><td>${esc(o.facts)}` +
     (e.probabilities && e.probabilities[o.id] != null ? ` <span class="muted">(p ${Number(e.probabilities[o.id]).toFixed(2)})</span>` : "") + `</td></tr>`).join("") + `</table>`;
  if (e.lessons && e.lessons.length) h += `<h2 style="margin-top:12px">New lessons</h2><ul>` + e.lessons.map(l => `<li>${esc(l)}</li>`).join("") + `</ul>`;
  if (e.reason) h += `<p class="muted">Reason: ${esc(e.reason)}</p>`;
  if (e.prompt || e.instructions) h += `<details><summary>Prompt sent</summary><pre>${esc(e.prompt || (e.instructions + "\n\n" + (e.state || "") + "\n\n" + (e.options || []).map(o => o.id + ": " + o.facts).join("\n")))}</pre></details>`;
  if (e.answer) h += `<details><summary>Answer</summary><pre>${esc(e.answer)}</pre></details>`;
  if (!e.prompt && !e.instructions && (e.kind === "battle_choice" || e.kind === "move_learn_choice")) h += `<p class="muted">Decided by the harness heuristic (no AI call).</p>`;
  det.innerHTML = h;
}
function seek(i) { v.currentTime = EV[i].at + 0.05; show(i); }   // kept for scripted checks
v.addEventListener("timeupdate", () => {
  if (si < 0) return;
  const g = SEG[si].offset + v.currentTime;
  cur.style.left = (100 * g / TOTAL) + "%";
  document.getElementById("clock").textContent = `${hms(g)} / ${hms(TOTAL)}`;
  let i = -1; for (let k = 0; k < EV.length; k++) { if (EV[k].at <= v.currentTime + 0.05) i = k; else break; }
  if (i !== last) { last = i; show(i); }
});
v.addEventListener("ended", () => { if (si + 1 < SEG.length) seekGlobal(SEG[si + 1].offset, true); });   // play the next run
tl.onclick = ev => { const r = tl.getBoundingClientRect(); seekGlobal(TOTAL * (ev.clientX - r.left) / r.width); };
window.addEventListener("resize", drawMarks);
drawMarks(); if (SEG.length) openSeg(0).then(() => EV.length && show(0));
</script></body></html>
"""
