"""TASK-131: after a game, a reviewer model reads the timeline plus the frames of the worst moments and writes ``review.md``.

Usage key ``vision.game_lol_review`` (shared/src/lib/ai/usages.py), so the model is chosen by the AI routing (pin an Opus
profile to it in Settings -> AI routing; without a route of its own it inherits ``vision``). ``review.md`` ends with one
line ``RULE: <one concrete rule change to try>`` and a cost line. ``collect_review_log`` (Mac side) copies the RULE lines of
all games into ``docs/agent/game/lol/REVIEW_LOG.md``. Read-only; never raises (a failed call writes the reason).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from . import game_review as gr, scorecard as sc

USAGE = "vision.game_lol_review"
ANTHROPIC_MODEL = "claude-opus-5-5"
# USD per million tokens (input, output) as listed in scripts/promo/token_log.py
ANTHROPIC_PRICE = {"claude-opus-5-5": (4.00, 8.00), "claude-sonnet-5-5": (1.50, 7.50), "claude-haiku-5-5": (0.25, 1.25)}
SEVERITY = {"death": 100, "death with unspent gold": 90, "objective lost": 70, "cannon missed": 80, "late/poor recall": 50,
            "last-hit missed": 30, "minion died, no attempt": 25}


ENV_FILES = (r"C:\virtualpytest\virtualpytest\backend_host\src\.env",)


def _server_env() -> None:
    """The recorders run as plain scripts (not inside vpt-host), so they do not have the host's SERVER_URL / API_KEY:
    read just those two from the host's .env (without printing or exporting anything else)."""
    if os.environ.get("SERVER_URL") and os.environ.get("API_KEY"):
        return
    for path in (os.environ.get("LOL_ENV_FILE", ""),) + ENV_FILES:
        if not path or not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="ignore"):
            k, _, v = line.strip().partition("=")
            if k in ("SERVER_URL", "API_KEY") and v and not os.environ.get(k):
                os.environ[k] = v.strip().strip("'\"")
        return


def worst_moments(run: Dict[str, Any], n: int = 5, end_s: float = sc.LANING_END_S) -> List[Dict[str, Any]]:
    """The worst moments of the laning phase (first 8 minutes, owner scope 2026-10-19); ``end_s=1e9`` for the whole game."""
    tl = run["tl"]
    ref = sc.reference_for(tl) if tl.get("samples") else None
    cand = []
    for m in (sc.bad_moments(tl, ref) if ref else []):
        cand.append({"t": m["t"], "what": f"{m['kind']}: {m['detail']}", "sev": SEVERITY.get(m["kind"], 40)})
    for a in run["attempts"]:
        if a.get("result") == "miss":
            kind = a.get("type") or "minion"
            cand.append({"t": a["t"], "what": f"last-hit MISSED on a {kind} ({gr.attempt_cause(a)})",
                         "sev": SEVERITY["cannon missed"] if kind == "cannon" else SEVERITY["last-hit missed"]})
    for d in gr.unattempted_deaths(run):
        cand.append({"t": d["t"], "what": f"a {d.get('kind', 'minion')} died next to us with no attempt", "sev": SEVERITY["minion died, no attempt"] + (50 if d.get("kind") == "cannon" else 0)})
    cand = [c for c in cand if c["t"] <= end_s]
    out: List[Dict[str, Any]] = []
    for c in sorted(cand, key=lambda c: -c["sev"]):  # spread them: no two within 10 s
        if all(abs(c["t"] - o["t"]) > 10 for o in out):
            out.append(c)
        if len(out) == n:
            break
    return sorted(out, key=lambda c: c["t"])


def _nearest_frame(run_dir: str, t: float) -> Optional[str]:
    fr = gr._frame_index(run_dir)
    return os.path.join(run_dir, min(fr, key=lambda f: abs(f["t"] - t))["src"]) if fr else None


def contact_sheet(run_dir: str, moments: List[Dict[str, Any]]) -> Optional[str]:
    """One JPEG (base64) with the worst moments side by side, labelled; the gateway takes one image per call."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    tiles = []
    for i, m in enumerate(moments):
        p = _nearest_frame(run_dir, m["t"])
        if not p:
            continue
        im = Image.open(p).convert("RGB")
        im.thumbnail((640, 400))
        ImageDraw.Draw(im).text((6, 6), f"#{i + 1} {int(m['t']) // 60}:{int(m['t']) % 60:02d}", fill=(255, 255, 0))
        tiles.append(im)
    if not tiles:
        return None
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (640 * cols, 400 * rows))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 640, (i // cols) * 400))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def build_prompt(run: Dict[str, Any], card: Dict[str, Any], moments: List[Dict[str, Any]]) -> str:
    tl = run["tl"]
    lines = [f"- {int(m['t']) // 60}:{int(m['t']) % 60:02d} {m['what']}" for m in moments]
    areas = {a: r["score"] for a, r in card["areas"].items()}
    ev = [f"{int(e['t']) // 60}:{int(e['t']) % 60:02d} {e['label']}" for e in gr._events(run) if e['t'] <= sc.LANING_END_S + 15][:60]
    return (
        "You review the LANING PHASE (the first 8 minutes, the part that matters now) of one League of Legends practice game played by a rule-based Garen bot (top lane). Be concrete and short.\n"
        f"Headline numbers at 5:00 and 8:00: {json.dumps(card.get('headlines'))[:900]}\n"
        f"Game: {card['game_minutes']} min, overall score {card['overall']}, area scores {json.dumps(areas)}.\n"
        f"Scorecard numbers: {json.dumps({a: r['numbers'] for a, r in card['areas'].items()})[:1800]}\n"
        f"Bot events (time, label):\n" + "\n".join(ev) + "\n"
        f"The {len(moments)} worst moments (the attached image shows their frames, numbered in this order):\n" + "\n".join(lines) + "\n\n"
        "Write markdown with: ## What went wrong (per moment, one or two lines each, say what the frame shows), "
        "## Why (the likely cause in the bot's logic or timing), ## Rule change to try (ONE change, specific enough to code: "
        "a threshold, a priority or a timing). End the answer with exactly one last line: RULE: <that one change in one sentence>."
    )


def _mac_env_key() -> Optional[str]:
    """ANTHROPIC_API_KEY from the environment or the main checkout's .env (never printed)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 5))
    for path in (os.path.expanduser("~/virtualpytest/.env"), os.path.join(root, ".env")):
        if os.path.exists(path):
            for line in open(path, encoding="utf-8", errors="ignore"):
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return None


def _call_anthropic(prompt: str, image_b64: Optional[str], model: str, max_tokens: int = 1500) -> Dict[str, Any]:
    """Direct Messages API call (Mac side: the pulled run folders live here). Returns the gateway-style result dict."""
    import requests

    key = _mac_env_key()
    if not key:
        return {"success": False, "error": "ANTHROPIC_API_KEY not found"}
    content: List[Dict[str, Any]] = []
    if image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    content.append({"type": "text", "text": prompt})
    from shared.src.lib.ai import gateway
    from shared.src.lib.ai.provider_client import CallUsage, anthropic_call_usage

    def report(used: Any, ok: bool) -> None:  # every call is logged in ai_calls (BUG-0721)
        _server_env()
        gateway.report_external_call(f"external:{USAGE}", endpoint="anthropic", model=model, call_usage=used, ok=ok,
                                     ms=int((time.time() - started) * 1000), script="lol game_review_ai",
                                     error_type=None if ok else "other")

    started = time.time()
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                          json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}, timeout=180)
        j = r.json()
    except Exception as e:  # noqa: BLE001
        report(CallUsage(), False)
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    u = j.get("usage") or {}
    report(anthropic_call_usage(u), r.status_code == 200)
    if r.status_code != 200:
        return {"success": False, "error": f"HTTP {r.status_code}: {str(j.get('error', j))[:200]}"}
    pin, pout = ANTHROPIC_PRICE.get(model, (None, None))
    cost = None if pin is None else (u.get("input_tokens", 0) * pin + u.get("output_tokens", 0) * pout) / 1e6
    return {"success": True, "content": "".join(b.get("text", "") for b in j.get("content", [])), "model": j.get("model", model),
            "provider_used": "anthropic", "cost": cost,
            "usage": {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")}}


def review_run_dir(run_dir: str, card: Optional[Dict[str, Any]] = None, force: bool = False, backend: str = "gateway") -> Dict[str, Any]:
    """Write ``review.md`` + ``review.json`` in ``run_dir``; returns {ok, rule, cost, ...}. Skipped (ok=None) when up to date."""
    out_md, out_json = os.path.join(run_dir, "review.md"), os.path.join(run_dir, "review.json")
    tlp = os.path.join(run_dir, "timeline.json")
    if not force and os.path.exists(out_md) and os.path.getmtime(out_md) >= os.path.getmtime(tlp):
        return {"ok": None, "skipped": "review.md is up to date"}
    run = gr.load_run(run_dir)
    if not run["tl"].get("samples"):
        return {"ok": False, "error": "no samples"}
    card = card or sc.laning_scorecard(run["tl"], None, run["attempts"] or None)
    moments = worst_moments(run)
    res: Dict[str, Any] = {"game_id": gr.game_id(run_dir), "usage": USAGE, "moments": moments}
    prompt, sheet = build_prompt(run, card, moments), contact_sheet(run_dir, moments)
    r: Dict[str, Any] = {"success": False, "error": "not run"}
    if backend == "anthropic":  # Mac: Opus straight from the Anthropic API; the AI-routing path below is the fallback
        r = _call_anthropic(prompt, sheet, os.environ.get("LOL_REVIEW_MODEL", ANTHROPIC_MODEL))
        res["backend"] = "anthropic" if r.get("success") else "anthropic failed, gateway fallback"
    if not r.get("success"):
        try:
            _server_env()
            from shared.src.lib.ai import gateway

            r = gateway.complete(USAGE, prompt, image_b64=sheet, max_tokens=1500, temperature=0.2, timeout_s=150)
        except Exception as e:  # noqa: BLE001
            r = {"success": False, "error": f"{type(e).__name__}: {e}"}
    text = (r.get("content") or "").strip()
    usage = r.get("usage") or {}
    cost = r.get("cost")
    m = re.search(r"^RULE:\s*(.+)$", text, re.M)
    res.update({"ok": bool(r.get("success") and text), "model": r.get("model"), "provider": r.get("provider_used"),
                "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"), "cost_usd": cost,
                "rule": m.group(1).strip() if m else None, "error": r.get("error")})
    cost_line = (f"{res['model'] or 'no model'} via {USAGE}: {res['tokens_in']} tokens in, {res['tokens_out']} out"
                 + (f", ${cost:.4f}" if isinstance(cost, (int, float)) else ", cost not reported"))
    body = text if res["ok"] else f"_Review failed: {res['error']}_"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"# Review {res['game_id']}\n\nOverall {card['overall']} over {card['game_minutes']} min. Worst moments: "
                + "; ".join(f"{int(x['t']) // 60}:{int(x['t']) % 60:02d} {x['what']}" for x in moments)
                + f"\n\n{body}\n\n---\nCost: {cost_line}\n")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    return res


def main(argv: Optional[List[str]] = None) -> int:
    """Mac: ``python -m shared.src.lib.game.leagueoflegends.game_review_ai <runs root or run folder> [--force]``: review with Opus."""
    import argparse
    import glob

    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    dirs = [a.path] if os.path.exists(os.path.join(a.path, "timeline.json")) else sorted(
        os.path.dirname(p) for p in glob.glob(os.path.join(a.path, "**", "timeline.json"), recursive=True))
    for d in dirs:
        r = review_run_dir(d, force=a.force, backend="anthropic")
        print(gr_id(d), r.get("ok"), r.get("model"), r.get("cost_usd"), (r.get("rule") or r.get("error") or r.get("skipped") or "")[:90])
    return 0


def gr_id(d: str) -> str:
    return gr.game_id(d)


def collect_review_log(runs_root: str, log_path: str) -> int:
    """One table row per reviewed game with its RULE line. A game already in the log is replaced when its review now comes
    from Claude and the logged one did not (a re-review with Opus). Returns rows added or replaced."""
    text = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else _LOG_HEAD
    lines = text.rstrip("\n").split("\n")
    changed = 0
    for p in sorted(__import__("glob").glob(os.path.join(runs_root, "**", "review.json"), recursive=True)):
        try:
            j = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not j.get("rule"):
            continue
        cost = f"${j['cost_usd']:.3f}" if isinstance(j.get("cost_usd"), (int, float)) else "n/a"
        row = f"| {j['game_id']} | {j.get('model') or '?'} | {j['rule'].replace('|', '/')} | {cost} | proposed |"
        idx = next((i for i, ln in enumerate(lines) if ln.startswith(f"| {j['game_id']} |")), None)
        if idx is None:
            lines.append(row)
            changed += 1
        elif "claude" in (j.get("model") or "") and "claude" not in lines[idx].split("|")[2]:
            state = lines[idx].rstrip("|").split("|")[-1].strip()
            lines[idx] = row.replace("| proposed |", f"| {state if state != 'proposed' else 'proposed'} |")
            changed += 1
    if changed or not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return changed


_LOG_HEAD = """---
title: League review log
summary: One rule change per reviewed League game, proposed by the reviewer model (vision.game_lol_review); the State column tracks whether it was tried.
tags: [agent, game, lol]
keywords: [league of legends, review, rule change, bot improvement, training data]
---

# League review log

Written by `collect_review_log` from each game's `review.json` (TASK-131). Edit the State column by hand: proposed, trying, adopted, rejected.

| Game | Reviewer | Rule change to try | Review cost | State |
|---|---|---|---|---|
"""


if __name__ == "__main__":
    raise SystemExit(main())
