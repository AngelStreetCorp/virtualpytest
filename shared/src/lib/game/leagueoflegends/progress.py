"""TASK-131: the bot's progress over its versions, from every recorded game (one static HTML page, no server).

``collect`` scores each run folder under the deliverables root with the CURRENT scorer (exact CS from the shots, health,
overall), so old and new games are comparable; ``build_page`` writes ``index.html``: per metric a line over the bot
versions (mean, min-max band, every game as a dot, target lines) and, as their own series, the benchmark contestants.
Colours are theme tokens (light and dark); categorical order follows the dataviz reference palette.
"""

from __future__ import annotations

import glob
import html
import json
import os
import statistics
from typing import Any, Dict, List, Optional, Tuple

from . import live_recorder, score_run, scorecard as sc

BOT_ROOTS = {"lol-garen-bot": None, "lol-garen-bot-v0": "v0"}  # folder -> fixed version (None: the group's name prefix)
BENCH_ROOT = "lol-model-benchmark"
CONTESTANTS = {"haiku": "Haiku 5.5", "sonnet": "Sonnet 5.5", "rule": "Rule bot", "rulen": "Rule bot (new)"}
METRICS = [  # key, title, unit, higher-is-better, target lines [(value, label)]; all over the evaluation window 1:00-8:00 (owner scope 2026-10-19)
    ("cs8", "CS at 8:00", "CS", True, [(64.0, "8/min = 64"), (80.0, "10/min = 80")]),
    ("cs_per_min", "CS per minute (1:00-8:00)", "CS/min", True, [(8.0, "target 8"), (10.0, "elite 10")]),
    ("lasthit_rate", "Last-hit rate (1:00-8:00)", "", True, [(0.8, "target 0.8")]),
    ("dmg_per_min", "Damage taken per minute (1:00-8:00)", "HP/min", False, [(25.0, "good <= 25")]),
    ("overall", "Scorecard overall (laning)", "/100", True, []),
]


def run_metrics(run_dir: str) -> Optional[Dict[str, Any]]:
    try:
        tl = live_recorder.load_timeline(os.path.join(run_dir, "timeline.json"))
    except (OSError, ValueError):
        return None
    ss = tl.get("samples") or []
    if len(ss) < 5 or ss[-1]["t"] < 180:
        return None
    tl["meta"].setdefault("champion", "Garen")
    if (tl["meta"].get("assigned_position") or "NONE").upper() == "NONE":
        tl["meta"]["assigned_position"] = "top"
    tl["cs_exact"] = tl.get("cs_exact") or score_run.cs_from_shots(run_dir)
    attempts: List[Dict[str, Any]] = []
    try:
        attempts = json.load(open(os.path.join(run_dir, "lasthit", "attempts.json"), encoding="utf-8")).get("attempts", [])
    except (OSError, ValueError):
        pass
    try:
        card = sc.laning_scorecard(tl, None, attempts or None)
    except Exception:  # noqa: BLE001
        return None
    hl = card["headlines"]
    h8 = hl.get("8:00")
    h = h8 or hl.get("5:00") or {}
    w = min(ss[-1]["t"], sc.LANING_END_S)
    wt = sc.window_timeline(tl, sc.LANING_END_S)
    cs_w = sc.cs_at(wt, w) - sc.cs_at(wt, sc.EVAL_START_S)
    return {"run": os.path.basename(run_dir), "when": tl["meta"].get("recorded_at", ""), "minutes": round(ss[-1]["t"] / 60, 1),
            "cs8": h8["cs"] if h8 else None, "cs_per_min": round(cs_w / ((w - sc.EVAL_START_S) / 60), 2),
            "lasthit_rate": h.get("lasthit_rate"), "dmg_per_min": (card["areas"]["health"]["numbers"] or {}).get("damage_taken_per_min"),
            "overall": card["overall"], "full_overall": card["full_game"]["overall"]}


def collect(root: str, cache_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(bot runs, benchmark runs); each run dict has ``series`` (version or contestant) plus the metrics."""
    cache: Dict[str, Any] = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
        except ValueError:
            cache = {}
    bots, bench = [], []
    for tlp in sorted(glob.glob(os.path.join(root, "lol-*", "**", "timeline.json"), recursive=True)):
        rd = os.path.dirname(tlp)
        rel = os.path.relpath(rd, root).split(os.sep)
        top = rel[0]
        if top in BOT_ROOTS:
            series = BOT_ROOTS[top] or rel[1].split("-")[0]
            dest = bots
        elif top == BENCH_ROOT and len(rel) >= 3:
            prefix = rel[1].split("-")[0]
            if prefix not in CONTESTANTS:
                continue
            series, dest = CONTESTANTS[prefix], bench
        else:
            continue
        key = f"v2:{rd}:{os.path.getmtime(tlp)}"  # v2: laning-window metrics
        m = cache.get(key) or run_metrics(rd)
        if m is None:
            continue
        cache[key] = m
        dest.append(dict(m, series=series))
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump(cache, open(cache_path, "w", encoding="utf-8"))
    return bots, bench


def version_order(runs: List[Dict[str, Any]]) -> List[str]:
    first: Dict[str, str] = {}
    for r in runs:
        first[r["series"]] = min(first.get(r["series"], "9"), r["when"] or "9")
    return sorted(first, key=lambda s: (first[s], s))


def stats(vals: List[float]) -> Optional[Dict[str, float]]:
    vals = [v for v in vals if v is not None]
    return {"mean": statistics.mean(vals), "min": min(vals), "max": max(vals), "n": len(vals)} if vals else None


CSS = """:root{--bg:#fcfcfb;--fg:#0b0b0b;--mut:#52514e;--grid:#e3e2dd;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#e87ba4;--s5:#6250d6;--band:rgba(42,120,214,.16)}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#1a1a19;--fg:#f0efec;--mut:#c3c2b7;--grid:#34332f;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#d55181;--s5:#9085e9;--band:rgba(57,135,229,.2)}}
:root[data-theme=dark]{--bg:#1a1a19;--fg:#f0efec;--mut:#c3c2b7;--grid:#34332f;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#d55181;--s5:#9085e9;--band:rgba(57,135,229,.2)}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}main{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}.sub{color:var(--mut);margin:0 0 12px}
.card{border:1px solid var(--grid);border-radius:8px;padding:12px;margin:12px 0}svg{width:100%;height:auto;display:block}
text{fill:var(--mut);font-size:11px}.t-fg{fill:var(--fg)}.grid{stroke:var(--grid)}.tgt{stroke:var(--mut);stroke-dasharray:4 3}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0;color:var(--mut)}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid var(--grid);padding:3px 6px;text-align:right}th:first-child,td:first-child{text-align:left}
summary{cursor:pointer;color:var(--mut);margin-top:6px}"""

BANDS = {"cs8": (64.0, 69.0, "elite 64-69 (n=6, provisional)")}  # elite band at 8:00 (TIMELINE_DATA.md, Master Garen-top games)
W, H, L, R, T, B = 920, 230, 54, 70, 14, 40


def _nice(x: float) -> float:
    """Round ``x`` up to 1, 2, 2.5, 5 or 10 times a power of ten (round axis ends)."""
    import math

    if x <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(x))
    return next(m * p for m in (1, 2, 2.5, 5, 10) if m * p >= x - 1e-12)


def _line_chart(title: str, unit: str, higher: bool, targets: List[Tuple[float, str]], order: List[str],
                by: Dict[str, List[Optional[float]]], band: Optional[Tuple[float, float, str]] = None) -> str:
    st = {v: stats(by[v]) for v in order}
    allv = [x for v in order for x in by[v] if x is not None] + [t for t, _ in targets] + ([band[1]] if band else [])
    lo, hi = min(0.0, min(allv, default=0)), _nice(max(allv, default=1))
    xs = lambda i: L + (W - L - R) * (i + 0.5) / max(1, len(order))  # noqa: E731
    ys = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)} per bot version">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        out.append(f'<line class=grid x1={L} x2={W - R} y1={ys(v):.1f} y2={ys(v):.1f} /><text x={L - 6} y={ys(v) + 4:.1f} text-anchor=end>{v:.3g}</text>')
    if band:
        out.append(f'<rect x={L} y={ys(band[1]):.1f} width={W - L - R} height={max(1.0, ys(band[0]) - ys(band[1])):.1f} fill="var(--s3)" opacity=.18><title>{html.escape(band[2])}</title></rect>'
                   f'<text x={W - R + 4} y={ys(band[1]) - 3:.1f}>{html.escape(band[2])}</text>')
    for tv, tl_ in targets:
        out.append(f'<line class=tgt x1={L} x2={W - R} y1={ys(tv):.1f} y2={ys(tv):.1f} /><text x={W - R + 4} y={ys(tv) + 4:.1f}>{html.escape(tl_)}</text>')
    pts = [(i, st[v]) for i, v in enumerate(order) if st[v]]
    if len(pts) > 1:
        top = " ".join(f"{xs(i):.1f},{ys(s['max']):.1f}" for i, s in pts)
        bot = " ".join(f"{xs(i):.1f},{ys(s['min']):.1f}" for i, s in reversed(pts))
        out.append(f'<polygon points="{top} {bot}" fill="var(--band)" />')
        out.append('<polyline fill=none stroke="var(--s1)" stroke-width=2 points="' + " ".join(f"{xs(i):.1f},{ys(s['mean']):.1f}" for i, s in pts) + '" />')
    for i, v in enumerate(order):
        for x in by[v]:
            if x is not None:
                out.append(f'<circle cx={xs(i):.1f} cy={ys(x):.1f} r=2.5 fill="var(--s1)" opacity=.45><title>{html.escape(v)}: {x:.3g} {unit}</title></circle>')
        s = st[v]
        if s:
            out.append(f'<circle cx={xs(i):.1f} cy={ys(s["mean"]):.1f} r=5 fill="var(--s1)" stroke="var(--bg)" stroke-width=2><title>{html.escape(v)}: mean {s["mean"]:.3g} {unit} (range {s["min"]:.3g}-{s["max"]:.3g}, {s["n"]} games)</title></circle>')
        out.append(f'<text x={xs(i):.1f} y={H - B + 14} text-anchor=middle class=t-fg>{html.escape(v)}</text><text x={xs(i):.1f} y={H - B + 27} text-anchor=middle>n={sum(1 for x in by[v] if x is not None)}</text>')
    out.append("</svg>")
    return "".join(out)


def _bench_chart(title: str, unit: str, targets: List[Tuple[float, str]], order: List[str], by: Dict[str, List[Optional[float]]],
                 band: Optional[Tuple[float, float, str]] = None) -> str:
    st = {v: stats(by[v]) for v in order}
    allv = [x for v in order for x in by[v] if x is not None] + [t for t, _ in targets] + ([band[1]] if band else [])
    lo, hi = min(0.0, min(allv, default=0)), _nice(max(allv, default=1))
    h = 34 * len(order) + 30
    xs = lambda v: 130 + (W - 130 - R) * (v - lo) / (hi - lo)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{html.escape(title)} per contestant">']
    if band:
        out.append(f'<rect x={xs(band[0]):.1f} y=6 width={max(1.0, xs(band[1]) - xs(band[0])):.1f} height={h - 28} fill="var(--s3)" opacity=.18><title>{html.escape(band[2])}</title></rect>'
                   f'<text x={xs(band[0]):.1f} y=14>{html.escape(band[2])}</text>')
    for tv, tl_ in targets:
        out.append(f'<line class=tgt x1={xs(tv):.1f} x2={xs(tv):.1f} y1=6 y2={h - 22} /><text x={xs(tv):.1f} y={h - 8} text-anchor=middle>{html.escape(tl_)}</text>')
    for i, v in enumerate(order):
        y, col = 22 + 34 * i, f"var(--s{2 + i % 4})"
        out.append(f'<text x=124 y={y + 4} text-anchor=end class=t-fg>{html.escape(v)}</text>')
        s = st[v]
        if not s:
            out.append(f'<text x={xs(lo) + 8:.1f} y={y + 4}>no data</text>')
        if s:
            out.append(f'<line x1={xs(s["min"]):.1f} x2={xs(s["max"]):.1f} y1={y} y2={y} stroke="{col}" stroke-width=3 opacity=.5 />')
            out.append(f'<circle cx={xs(s["mean"]):.1f} cy={y} r=6 fill="{col}" stroke="var(--bg)" stroke-width=2><title>{html.escape(v)}: mean {s["mean"]:.3g} {unit} (range {s["min"]:.3g}-{s["max"]:.3g}, {s["n"]} games)</title></circle>')
            out.append(f'<text x={xs(s["max"]) + 8:.1f} y={y + 4}>{s["mean"]:.3g} (n={s["n"]})</text>')
    out.append("</svg>")
    return "".join(out)


def _table(order: List[str], runs: List[Dict[str, Any]]) -> str:
    rows = []
    for v in order:
        rs = [r for r in runs if r["series"] == v]
        cells = []
        for key, *_ in METRICS:
            s = stats([r[key] for r in rs])
            cells.append("-" if not s else f"{s['mean']:.3g} ({s['min']:.3g}-{s['max']:.3g})")
        fo = stats([r.get("full_overall") for r in rs])
        cells.append("-" if not fo else f"{fo['mean']:.3g}")
        rows.append(f"<tr><td>{html.escape(v)}</td><td>{len(rs)}</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    head = "".join(f"<th>{m[1]}</th>" for m in METRICS) + "<th>Overall, full game (secondary)</th>"
    return f"<details><summary>Table view</summary><table><tr><th></th><th>games</th>{head}</tr>{''.join(rows)}</table></details>"


def build_page(bots: List[Dict[str, Any]], bench: List[Dict[str, Any]], out_path: str) -> str:
    border = version_order(bots)
    corder = version_order(bench)
    parts = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Bot progress</title><style>{CSS}</style><main>",
             "<h1>Garen bot progress</h1>",
             f"<p class=sub>{len(bots)} bot games over {len(border)} versions, {len(bench)} benchmark games. Every game is re-scored with the current scorer (exact CS from the HUD counter). "
             "Dot = one game, big dot = version mean, band = min-max, dashed = target. Everything is measured over the laning phase, 1:00-8:00 (the first minute is preparation) (owner scope); the full-game overall is only in the table. Games under 3 minutes are left out.</p>",
             "<h2>By bot version (oldest to newest)</h2>"]
    for key, title, unit, higher, targets in METRICS:
        by = {v: [r[key] for r in bots if r["series"] == v] for v in border}
        parts.append(f"<div class=card><b class=t-fg>{html.escape(title)}</b> <span class=sub>{'higher is better' if higher else 'lower is better'}</span>{_line_chart(title, unit, higher, targets, border, by, BANDS.get(key))}</div>")
    parts.append(_table(border, bots))
    parts.append("<h2>Benchmark contestants</h2><div class=legend>" + "".join(f"<span><i style='background:var(--s{2 + i % 4})'></i>{html.escape(c)}</span>" for i, c in enumerate(corder)) + "</div>")
    for key, title, unit, higher, targets in METRICS:
        by = {v: [r[key] for r in bench if r["series"] == v] for v in corder}
        parts.append(f"<div class=card><b class=t-fg>{html.escape(title)}</b> <span class=sub>mean and range per contestant</span>{_bench_chart(title, unit, targets, corder, by, BANDS.get(key))}</div>")
    parts.append(_table(corder, bench))
    parts.append("<p class=sub>Jev and the coaches are not in the benchmark yet; they appear here as their own series once their games are recorded.</p></main>")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return out_path


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/vpt-deliverables"))
    ap.add_argument("--out", default=os.path.expanduser("~/vpt-deliverables/lol-progress/index.html"))
    a = ap.parse_args(argv)
    bots, bench = collect(a.root, os.path.join(os.path.dirname(a.out), "cache.json"))
    print(build_page(bots, bench, a.out), len(bots), "bot games,", len(bench), "benchmark games")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
