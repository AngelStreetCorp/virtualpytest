"""TASK-134: aggregate benchmark games into results.json, results.md and report.html.

usage: bench_report.py <root>   where <root>/<label>/<garen-run-*>/ holds result.json, timeline.json, scorecard.json, llm_summary.json
Per game, measured at 5:00 game time: CS/min, gold earned (sum of gold increases between polls, shop spending excluded),
items bought (+ game time), deaths, scorecard overall + areas, decision latency p50/p95, cost. Then mean and range per contestant.
"""
import html
import json
import os
import statistics
import sys

STOP_AT = 300.0
ORDER = ["rule", "rule-new", "rule-r2", "rule-top", "haiku-coach-top", "duo-top", "claude-haiku-5-5", "claude-sonnet-5-5", "haiku-coach", "jev-coach", "duo"]  # "rule" = rule bot at 521287b3b (the baseline all models shared), "rule-new" = newest main after the series


def _load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def exact_cs(run_dir, tl):
    """(CS at STOP_AT, first game second with CS > 0) from the HUD counter read on the 20 s shots (cs_reader); (None, None) without."""
    ex = tl.get("cs_exact")
    if not ex:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
            from shared.src.lib.game.leagueoflegends.score_run import cs_from_shots
            ex = cs_from_shots(run_dir)
        except Exception:  # noqa: BLE001 - no cv2 / no shots: fall back to creepScore
            ex = []
    ex = sorted((e for e in ex if e["t"] <= STOP_AT + 5), key=lambda e: e["t"])
    if not ex:
        return None, None
    last = ex[-1]
    cs = last["cs"]
    if last["t"] < STOP_AT and len(ex) > 1:  # linear extrapolation of the last interval up to 5:00 (shots are 20 s apart)
        a = ex[-2]
        cs = last["cs"] + (last["cs"] - a["cs"]) * (min(STOP_AT, last["t"] + 20) - last["t"]) / max(last["t"] - a["t"], 1)
    first = next((int(e["t"]) for e in ex if e["cs"] > 0), None)
    return int(round(cs)), first


def click_stats(run_dir, lane_from=0.0):
    """(clicks/min, redundant clicks/min) from inputs.jsonl: a move click is redundant when we already stand within 0.02 minimap
    units of its minimap destination, or a screen right-click lands within 60 px of Garen (about where he stands, camera locked)."""
    p = f"{run_dir}/inputs.jsonl"
    if not os.path.exists(p):
        return None, None
    n = red = 0
    for line in open(p):
        if not line.strip():
            continue
        i = json.loads(line)
        a = i["a"]
        if a[0] not in ("minimap", "right"):
            continue
        n += 1
        if a[0] == "minimap" and i.get("pos"):
            tx, ty = (a[1] / 1920 - 1612 / 1920) / (300 / 1920), (a[2] / 1200 - 893 / 1200) / (297 / 1200)
            red += ((i["pos"][0] - tx) ** 2 + (i["pos"][1] - ty) ** 2) ** 0.5 <= 0.02
        elif a[0] == "right" and ((a[1] - 868) ** 2 + (a[2] - 545) ** 2) ** 0.5 <= 60:
            red += 1
    return round(n / (STOP_AT / 60.0), 1), round(red / (STOP_AT / 60.0), 1)


def stance_text(run_dir):
    """Round 2: how often each stance was set and the mean HP % at those moments (stance and HP logged together)."""
    p = f"{run_dir}/decisions.jsonl"
    if not os.path.exists(p):
        return None
    by = {}
    for line in open(p):
        if not line.strip():
            continue
        d = json.loads(line)
        mode = (d.get("choice") or {}).get("mode")
        hp = (d.get("view") or {}).get("hp", "")
        if mode and "/" in hp:
            a, b = hp.split("/")
            by.setdefault(mode, []).append(100.0 * float(a) / max(float(b), 1.0))
    return ", ".join(f"{k} x{len(v)} ({sum(v) / len(v):.0f} % HP)" for k, v in by.items()) or None


def layers_text(sm):
    """Round 2: calls, median latency and cost per layer (strategist = Haiku or Jev-coach's chooser, tactician = Jev)."""
    if "strategist_calls" not in sm:
        return None
    return "; ".join(f"{k} {sm.get(k + '_calls')} calls, p50 {sm.get(k + '_p50_ms')} ms, ${sm.get(k + '_cost_usd')}" for k in ("strategist", "tactician") if sm.get(k + "_calls"))


def game_row(run_dir, label):
    tl, res = _load(f"{run_dir}/timeline.json"), _load(f"{run_dir}/result.json") or {}
    sm, card = _load(f"{run_dir}/llm_summary.json") or {}, _load(f"{run_dir}/scorecard.json") or {}
    try:  # re-score with the exact HUD CS (score_run overwrites scorecard.json / .html in the run folder)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        from shared.src.lib.game.leagueoflegends.score_run import score_run_dir
        card = score_run_dir(run_dir, with_others=False)
    except Exception:  # noqa: BLE001
        pass
    if not tl or not tl.get("samples"):
        return {"label": label, "model": sm.get("model"), "ok": False, "error": (res.get("exception") or "no timeline")[-200:]}
    samples = [s for s in tl["samples"] if s["t"] <= STOP_AT + 5] or tl["samples"]
    last = samples[-1]
    earned, prev, items, seen = 0.0, None, [], set()
    for s in samples:
        if prev is not None and s["gold"] > prev:
            earned += s["gold"] - prev
        prev = s["gold"]
        for it in s.get("items") or []:
            if it not in seen:
                seen.add(it)
                items.append({"item": it, "t": int(s["t"])})
    first_cs = next((int(x["t"]) for x in samples if x["scores"]["cs"] > 0), None)  # CS moves in steps of 10 until the OCR reader lands
    me = (tl.get("meta") or {}).get("player", "").split("#")[0]
    killers = [e.get("KillerName", "?") for e in tl.get("events", []) if e.get("EventName") == "ChampionKill" and e.get("VictimName") == me]
    killers = [("turret" if k.startswith("Turret") else "minion" if k.startswith("Minion") else "champion") for k in killers]
    dmg, min_hp, prev = 0.0, 100.0, None  # health lost with no opponent = bad play: damage taken per minute and the lowest health %
    for s_ in samples:
        if s_["hp_max"]:
            min_hp = min(min_hp, 0.0 if s_.get("dead") else 100.0 * s_["hp"] / s_["hp_max"])
        if prev is not None and not s_.get("dead") and not prev.get("dead") and s_["hp"] < prev["hp"] and s_["hp_max"] >= prev["hp_max"]:
            dmg += prev["hp"] - s_["hp"]
        prev = s_
    mm = (res.get("actions_by_kind") or {}).get("minimap")  # all minimap right-clicks of the run (the scripted walk to lane included)
    clicks, redundant = click_stats(run_dir)
    stances = stance_text(run_dir)
    ecs, efirst = exact_cs(run_dir, tl)
    cs_final = ecs if ecs is not None else last["scores"]["cs"]
    first_cs = efirst if ecs is not None else first_cs
    mins = min(last["t"], STOP_AT) / 60.0
    model = sm.get("model") or res.get("model") or "?"
    if label.startswith("rulen"):
        model = "rule-new"
    elif label.startswith(("top-", "toplane")):
        model = {"rule": "rule-top"}.get(model, model + "-top")  # round 3: an enemy bot lanes top against Garen
    elif label.startswith("rule2"):
        model = "rule-r2"  # the rule bot at the commit round 2 ran on
    return {
        "label": label, "model": model, "ok": True, "game_t": last["t"],
        "first_cs_t": first_cs, "cs": cs_final, "cs_source": "hud counter" if ecs is not None else "creepScore (steps of 10)", "cs_per_min": round(cs_final / max(mins, 0.01), 2),
        "gold_earned": int(earned), "gold_left": int(last["gold"]), "items": items, "deaths": last["scores"]["deaths"],
        "kills": last["scores"]["kills"], "level": last["level"], "overall": card.get("overall"),
        "areas": {a: r.get("score") for a, r in (card.get("areas") or {}).items()},
        "lat_p50": sm.get("latency_p50_ms"), "lat_p95": sm.get("latency_p95_ms"), "decisions": sm.get("decisions"),
        "errors": sm.get("errors"), "clicks_per_min": clicks, "redundant_clicks_per_min": redundant, "minimap_per_min": round(mm / (min(last["t"], STOP_AT) / 60.0), 1) if mm is not None else None, "dmg_per_min": round(dmg / (min(last["t"], STOP_AT) / 60.0), 1), "min_hp_pct": round(min_hp, 1), "vetoes": sm.get("turret_vetoes"), "layers": layers_text(sm), "stances": stances, "harness": sm.get("harness"), "parse_failures": sm.get("parse_failures"), "death_causes": killers, "no_veto": sm.get("model") not in (None, "rule") and sm.get("turret_vetoes") is None, "cost": sm.get("cost_usd"), "tokens": (sm.get("in_tokens", 0) + sm.get("out_tokens", 0)) or None,
        "dir": os.path.relpath(run_dir, os.path.dirname(run_dir.rstrip("/"))),
    }


def collect(root):
    rows = []
    for label in sorted(os.listdir(root)):
        p = os.path.join(root, label)
        if not os.path.isdir(p):
            continue
        for sub in sorted(os.listdir(p)):
            if os.path.isdir(os.path.join(p, sub)) and os.path.exists(os.path.join(p, sub, "result.json")):
                r = game_row(os.path.join(p, sub), label)
                r["dir"] = f"{label}/{sub}"
                rows.append(r)
    return rows


def agg(rows):
    out = {}
    for m in ORDER:
        ok = [r for r in rows if r["model"] == m and r["ok"] and (m in ("rule", "rule-new", "rule-r2", "rule-top") or r.get("harness") in ("h3", "r2b")) and not r["label"].endswith("smoke") and not r["label"].startswith("toplane")]  # smoke and probe games are listed, never averaged  # model games played before the shared turret veto and smoke games are listed, not averaged
        out[m] = {"games": len([r for r in rows if r["model"] == m]), "scored": len(ok)}
        for k in ("cs_per_min", "gold_earned", "deaths", "dmg_per_min", "min_hp_pct", "minimap_per_min", "clicks_per_min", "redundant_clicks_per_min", "first_cs_t", "vetoes", "overall", "lat_p50", "lat_p95", "cost"):
            v = [r[k] for r in ok if r.get(k) is not None]
            out[m][k] = {"mean": round(statistics.mean(v), 3), "min": min(v), "max": max(v)} if v else None
        for a in ("farm", "deaths", "recalls", "lane", "items", "kills", "objectives"):
            v = [r["areas"][a] for r in ok if r["areas"].get(a) is not None]
            out[m][f"area_{a}"] = round(statistics.mean(v), 1) if v else None
    return out


def _cell(x, nd=2):
    return "n/a" if not x else f"{x['mean']:.{nd}f} ({x['min']:.{nd}f}-{x['max']:.{nd}f})"


def render(rows, a):
    names = {"rule": "Rule bot (521287b3b)", "rule-new": "Rule bot (newest main, end of round 1)", "rule-r2": "Rule bot (round 2 commit)", "claude-haiku-5-5": "Haiku 5.5", "claude-sonnet-5-5": "Sonnet 5.5",
             "rule-top": "Round 3 (enemy top laner): rule bot", "haiku-coach-top": "Round 3: Haiku-coach + rule bot", "duo-top": "Round 3: Haiku + Jev duo + rule bot", "haiku-coach": "Haiku-coach + rule bot", "jev-coach": "Jev-coach + rule bot", "duo": "Haiku + Jev duo + rule bot"}
    cols = [("CS/min", "cs_per_min", 2), ("Gold earned", "gold_earned", 0), ("Deaths", "deaths", 1), ("Damage taken /min", "dmg_per_min", 0), ("Min HP %", "min_hp_pct", 0), ("Minimap clicks /min", "minimap_per_min", 1), ("Clicks /min", "clicks_per_min", 1), ("Redundant clicks /min", "redundant_clicks_per_min", 1), ("First CS (s)", "first_cs_t", 0), ("Scorecard overall", "overall", 1),
            ("Turret vetoes", "vetoes", 1), ("Latency p50 ms", "lat_p50", 0), ("Latency p95 ms", "lat_p95", 0), ("Cost / game $", "cost", 4)]
    md = ["| Contestant | Games counted / played | " + " | ".join(c[0] for c in cols) + " |", "|---|---|" + "---|" * len(cols)]
    for m in ORDER:
        md.append(f"| {names[m]} | {a[m]['scored']}/{a[m]['games']} | " + " | ".join(_cell(a[m][k], nd) for _, k, nd in cols) + " |")
    gm = ["| Game | Contestant | CS | First CS (s) | CS/min | Gold earned | Deaths | Dmg taken/min | Min HP % | Minimap clicks/min | Clicks/min | Redundant clicks/min | Items (game time) | Overall | Turret vetoes | Parse failures | Layers | Deaths by | p50/p95 ms | Cost $ |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["ok"]:
            gm.append(f"| {r['label']} | {names.get(r['model'], r['model'])} | failed: {r['error']} | | | | | | | | | | | | | | | | |")
            continue
        its = ", ".join(f"{i['item']} {i['t'] // 60}:{i['t'] % 60:02d}" for i in r["items"])
        gm.append(f"| {r['label']} | {names.get(r['model'], r['model'])} | {r['cs']} | {r['first_cs_t']} | {r['cs_per_min']} | {r['gold_earned']} | {r['deaths']} | {r['dmg_per_min']} | {r['min_hp_pct']} | {r['minimap_per_min']} | {r['clicks_per_min']} | {r['redundant_clicks_per_min']} | {its} | {r['overall']} | {r.get('vetoes') if r.get('harness') == 'h3' else ('old harness' if r['model'] not in ('rule', 'rule-new', 'rule-r2') else '-')} | {r.get('parse_failures')} | {r.get('layers') or '-'}{(' | stances: ' + r['stances']) if r.get('stances') else ''} | {', '.join(r.get('death_causes') or []) or '-'} | {r['lat_p50']}/{r['lat_p95']} | {r['cost']} |")
    return "\n".join(md), "\n".join(gm), names


def html_page(md_sum, md_games, rows):
    def table(md):
        lines = [l for l in md.split("\n") if not l.startswith("|---")]
        out = ["<table>"]
        for i, l in enumerate(lines):
            tag = "th" if i == 0 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{html.escape(c.strip())}</{tag}>" for c in l.strip("|").split("|")) + "</tr>")
        return "\n".join(out) + "</table>"
    links = "".join(f'<li><a href="{r["dir"]}/scorecard.html">{html.escape(r["label"])}</a></li>' for r in rows if r["ok"])
    return f"""<!doctype html><meta charset=utf-8><title>LoL model benchmark</title>
<style>body{{font:14px system-ui;margin:24px;max-width:1200px}}table{{border-collapse:collapse;margin:12px 0}}td,th{{border:1px solid #8884;padding:4px 8px;text-align:left}}th{{background:#8882}}</style>
<h1>Garen top, 5 game minutes: rule bot vs Haiku vs Sonnet</h1>
<p>Mean (min-max) per contestant. Practice Tool, Garen top, blue side, 3 games each. Gold earned counts increases between polls, so shop spending is not subtracted.</p>
{table(md_sum)}<h2>Every game</h2>{table(md_games)}<h2>Scorecards</h2><ul>{links}</ul>"""


if __name__ == "__main__":
    root = sys.argv[1]
    rows = collect(root)
    a = agg(rows)
    s, g, _ = render(rows, a)
    json.dump({"games": rows, "summary": a}, open(f"{root}/results.json", "w"), indent=1)
    open(f"{root}/results.md", "w").write(s + "\n\n" + g + "\n")
    open(f"{root}/report.html", "w").write(html_page(s, g, rows))
    doc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "tasks", "TASK-134-lol-model-benchmark.md")
    if os.path.exists(doc) and "--doc" in sys.argv:  # refresh the generated block of the task doc
        t = open(doc).read()
        a, b = t.index("<!-- BENCH:START -->"), t.index("<!-- BENCH:END -->")
        open(doc, "w").write(t[:a] + "<!-- BENCH:START -->\nMean (min-max) per contestant over the counted games; every game 5:00 game time, Garen top, blue, Practice Tool.\n\n" + s + "\n\n### Every game\n\n" + g + "\n" + t[b:])
    print(s)
