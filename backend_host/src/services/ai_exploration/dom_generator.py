#!/usr/bin/env python3
"""
LLM-based TV-UI DOM generator (GPT-5.5, no preprocessing hints).

Single source of truth for "screenshot -> DOM" used by:
  - the /generateDom host route (live screenshot-save + Reset-DOM button)
  - the DB backfill script (backfill_dom.py)
  - the HTML report script (llm_dom_report.py)

Config was validated empirically (see docs): GPT-5.5 at reasoning_effort=medium with
NO Omni/focus-detector hints resolved every focus-bearing example_tv screen, at lower
cost/latency than the deterministic hint pipeline. We intentionally call OpenAI directly
(not the generic Anthropic-shaped provider abstraction) because the GPT-5 family needs
reasoning_effort + max_completion_tokens + no temperature + json_object — wiring that
through the shared path would risk every other vision caller.

Env overrides (all optional):
  OPENAI_API_KEY   (required)
  DOM_MODEL        default "gpt-5.5"
  DOM_EFFORT       default "medium"  (minimal|low|medium|high)
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw

# Bump when the prompt/shape changes so backfill can detect stale rows.
# v2: + screen_type and per-element ok_action (the auto-builder's exploration
#     classifications — parity with the sub-agent DOM job schema in
#     scripts/auto_build_mcp_live.py so generate_dom can replace the manual handoff).
DOM_SCHEMA_VERSION = 2
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_EFFORT = "medium"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

PROMPT = """Analyze this TV app screenshot.

Return only interactive/focusable UI elements for TV remote control.
Ignore decorative images, hero artwork, plain titles, descriptions, metadata, subtitles, timestamps, long sentences, and non-clickable text.

For each element return:
- index: zero-based integer in visual reading/navigation order
- id: stable snake_case id
- type: one of button, app_tile, profile_avatar, nav_item, tab, card, menu_item, settings_row, programme_cell
- label: short visible/semantic label
- text_found: exact visible text/OCR used for the element, or "" for icon-only elements
- bbox: [x, y, w, h] normalized 0..1, approximate but aligned to the visible focusable item
- focused: true/false
- confidence: 0..1
- ok_action: what pressing OK on it does — one of:
  "screen" (opens a new in-UI screen or category; navigable, BACK returns),
  "overlay" (opens an in-screen popup that keeps this screen's title),
  "external" (launches a SEPARATE app: Netflix, Disney+, YouTube, ...),
  "dynamic" (plays a content asset — a movie/show/recording tile -> a player),
  "activate" (a toggle/text-input with no navigation).
  On a content/browse screen the category tabs (Discover/Movies/Series/...) are "screen".
  Represent all visible posters/assets as AT MOST ONE generic element named "content"
  (or "asset") with ok_action="dynamic"; never use movie/show/recording titles as
  element ids or labels.

Also return:
- screen_summary
- screen_type: one of nav_row, content, overlay, app_launcher, keyboard, dialog, player, other
- focused_element_id, or null
- focus_confidence
- navigation object keyed by element id. For every element include LEFT, RIGHT, UP, DOWN, OK, BACK.

Navigation rules:
- This is a TV UI controlled by arrows and OK.
- Rows and columns determine LEFT/RIGHT/UP/DOWN.
- If a focused element is visually highlighted by a red border, white border, enlarged tile, selected underline, checkmark row, or bright pill, mark it focused.
- App tiles, profile avatars, buttons, tabs, TV guide programme cells, menu rows, settings rows, and content cards are interactive.
- Long descriptions and hero text are usually not interactive.
- Small decorative badges, ratings, clocks, channel logos inside a card, and background text are not separate interactive elements.

Return strict JSON only with this schema:
{
  "screen_summary": "...",
  "screen_type": "nav_row | content | overlay | app_launcher | keyboard | dialog | player | other",
  "focused_element_id": "id_or_null",
  "focus_confidence": 0.0,
  "focusable_elements": [
    {"index":0,"id":"...","type":"...","label":"...","text_found":"...","bbox":[0,0,0,0],"focused":false,"confidence":0.0,"ok_action":"screen"}
  ],
  "navigation": {
    "id": {"LEFT": null, "RIGHT": "id", "UP": null, "DOWN": "id", "OK": "open", "BACK": "back"}
  }
}
"""


def _image_data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _extract_json(text: str) -> dict[str, Any]:
    text = _strip_thinking(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_bboxes(parsed: dict[str, Any], image_w: int, image_h: int) -> None:
    """Coerce element bboxes to normalized [x, y, w, h] in 0..1, in place."""
    for idx, element in enumerate(parsed.get("focusable_elements", []) or []):
        element.setdefault("index", idx)
        bbox = element.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            a, b, c, d = [float(v) for v in bbox]
        except (TypeError, ValueError):
            continue
        if max(abs(a), abs(b), abs(c), abs(d)) > 2:  # absolute pixels -> normalize
            x0, y0, x1, y1 = a / image_w, b / image_h, c / image_w, d / image_h
            x, y, w, h = min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
        elif c > a and d > b and (c > 0.35 or d > 0.35):  # looks like x0,y0,x1,y1
            x, y, w, h = a, b, c - a, d - b
        else:
            x, y, w, h = a, b, c, d
        x, y = max(0, min(1, x)), max(0, min(1, y))
        w, h = max(0.001, min(1 - x, w)), max(0.001, min(1 - y, h))
        element["bbox"] = [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def generate_dom(image_path: str, *, model: str | None = None, effort: str | None = None,
                 timeout: int = 240) -> dict[str, Any]:
    """Generate a canonical TV-UI DOM for one screenshot via GPT-5.5 (no hints).

    Returns the parsed DOM dict (screen_summary, focused_element_id, focus_confidence,
    focusable_elements[], navigation{}) plus a `_dom_meta` block (model/effort/usage/
    version/elapsed). Raises on missing key or HTTP error.
    """
    # Provider fallback (2026-07-16): prefer OpenAI (gpt-5.5), fall back to
    # OpenRouter's OpenAI-compatible endpoint when no OpenAI key is configured —
    # the fleet's funded vision key is OpenRouter (see shared/src/lib/ai/config.py).
    key = os.getenv("OPENAI_API_KEY", "").strip()
    url = _OPENAI_URL
    if key:
        model = model or os.getenv("DOM_MODEL", "").strip() or DEFAULT_MODEL
    else:
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise RuntimeError("Neither OPENAI_API_KEY nor OPENROUTER_API_KEY is configured")
        url = "https://openrouter.ai/api/v1/chat/completions"
        model = model or os.getenv("DOM_MODEL", "").strip() or "qwen/qwen3-vl-235b-a22b-instruct"
    effort = (effort or os.getenv("DOM_EFFORT", "").strip() or DEFAULT_EFFORT).lower()

    path = Path(image_path)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": _image_data_url(path)}},
            ],
        }],
        "max_completion_tokens": 16000,
        "response_format": {"type": "json_object"},
    }
    # GPT-5 family: reasoning model — temperature must be default, expose effort knob.
    if url == _OPENAI_URL and effort in {"minimal", "low", "medium", "high"}:
        payload["reasoning_effort"] = effort

    started = time.time()
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    elapsed = time.time() - started
    if not resp.ok:
        raise RuntimeError(f"DOM provider {resp.status_code}: {resp.text[:800]}")
    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    parsed = _extract_json(content)
    with Image.open(path) as im:
        normalize_bboxes(parsed, *im.size)
    parsed["_dom_meta"] = {
        "v": DOM_SCHEMA_VERSION,
        "model": model,
        "effort": effort,
        "usage": body.get("usage", {}),
        "elapsed_sec": round(elapsed, 1),
    }
    return parsed


def render_dom_overlay(image_path: str, dom: dict[str, Any], out_path: str) -> str:
    """Draw the DOM boxes on the screenshot (focused = red, others = cyan) and save a
    JPEG to out_path. This is the `<stem>_dom.jpg` shown in the Edit-node DOM tab."""
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    w, h = image.size
    focus = dom.get("focused_element_id")
    for idx, element in enumerate(dom.get("focusable_elements", []) or []):
        bbox = element.get("bbox") or [0, 0, 0, 0]
        if len(bbox) != 4:
            continue
        x, y, bw, bh = bbox
        x0, y0, x1, y1 = int(x * w), int(y * h), int((x + bw) * w), int((y + bh) * h)
        focused = element.get("focused") or element.get("id") == focus
        color = (255, 50, 40) if focused else (0, 220, 255)
        draw.rectangle([x0, y0, x1, y1], outline=color, width=4 if focused else 2)
        label = f"{idx}:{element.get('id') or element.get('label') or idx}"
        draw.rectangle([x0, max(0, y0 - 16), min(w, x0 + 7 * len(label) + 6), y0], fill=(0, 0, 0))
        draw.text((x0 + 2, max(0, y0 - 15)), label, fill=color)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, quality=90)
    return out_path
