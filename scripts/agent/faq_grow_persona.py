#!/usr/bin/env python3
"""faq_grow_persona.py — generate candidate FAQ entries for one (persona, area) pair.

Phase 9b of TASK-152. Reads the docs in the area, asks a tightly scaffolded LLM prompt to
generate ``max_rows`` candidate questions the persona would actually ask, and writes one
JSONL per pair. Output rows are ``proposed=true`` candidates; the daily review pass flips
them to ``live=true`` once they pass.

The LLM call here is the only model expense in 9b. With the script's prompt capping the
generation to ~2k input + 4k output per call, a ``max_rows=100`` pair fits in one LLM call.

Usage
-----
    scripts/agent/faq_grow_persona.py --persona tester --area tv --output /tmp/x.jsonl [--max-rows 100]

Output: JSONL with rows of
    { "id": "tv-001", "topic": "tv", "question": "...", "short": "...",
      "long": "...", "sources": ["docs/agent/devices/INFRARED.md"], "tags": ["tester", "tv"] }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- persona prompts

PERSONAS: Dict[str, str] = {
    "tester":       "You are a hands-on QA tester. You run scripts, watch HLS streams, click IR/AV keys, and explain a customer-side observation in one sentence. You ask 'how do I' and 'why does it fail on my STB'.",
    "developer":    "You are a backend/frontend developer fixing issues in the repo. You ask about APIs, MCP tools, table columns, and infra calls. You want a code-shaped answer.",
    "marketing":    "You are writing customer-facing material. You ask about pricing, packaging, the public-ask flow, and 'what is this product for'. You want an external-safe answer.",
    "manager":      "You are a product manager. You ask about timelines, what's blocking, who can fix what, license implications, and how Atlas reports KPIs.",
    "support":      "You are a support engineer reading BUG-NNN logs and customer bug tickets. You ask 'how do I reproduce' and 'where is the version pin'.",
    "security":     "You are the security/compliance reviewer. You ask about RLS, the leak gate, sudoers, .env shape, audit logs, and where secrets are stored.",
    "ai":           "You are the AI specialist. You ask about models, routes, the prompt cache, the softcap, and how the agent loop decides between skills and tools.",
    "mobile-qa":    "You are the mobile-app QA. You pair the phone agent, drive the HD stream, validate the `mobile-app` feature flag, and watch the KPI panel.",
    "web-qa":       "You are the web-app QA. You drive the Next.js UI, take control through the auto-sign token, and exercise org/tenant flows.",
    "games-qa":     "You are the AI/game QA. You watch the bot loop, follow the screen via the navigation tree, and check the GAME_BOTS / SWITCH_GAMES coverage.",
}


# --------------------------------------------------------------------------- area doc map

AREAS: Dict[str, List[str]] = {
    "tv":          ["docs/agent/devices/INFRARED.md", "docs/agent/devices/STB_UI_OPERATOR.md",
                   "docs/agent/devices/STB_STANDBY.md", "docs/agent/devices/STREAM.md"],
    "mobile-app":  ["docs/features/mobile-app.md", "docs/agent/devices/PHONE_AGENT.md",
                   "docs/user-guide/app-languages.md"],
    "web-app":     ["docs/agent/devices/WEB_UI_ORCHTNET.md",
                   "docs/user-guide/custom-pages.md", "docs/agent/platform/DASHBOARD_CARDS.md"],
    "ai":          ["docs/agent/ai/agent.md", "docs/agent/ai/ATLAS_COMPANION.md",
                   "docs/agent/ai/ATLAS_VOICE.md", "docs/agent/ai/AI_USAGE.md",
                   "docs/agent/ai/AI_BENCHMARK.md", "docs/agent/ai/COC_LLM_BUDGET.md"],
    "games":       ["docs/agent/game/GAME_BOTS.md", "docs/agent/game/SWITCH_GAMES.md"],
    "infra":       ["docs/agent/infra/LOAD_AVERAGE.md", "docs/agent/platform/MAINTENANCE.md"],
    "leaks":       ["docs/agent/release/LEAK_GATE.md", "docs/agent/release/RELEASING.md"],
    "setup":       ["docs/get-started/install.md", "docs/get-started/docker.md",
                   "docs/agent/validation/TESTING.md", "docs/agent/platform/SERVER_AUTH.md"],
}


# --------------------------------------------------------------------------- LLM call

def _anth_api_key() -> Optional[str]:
    """Pick an Anthropic API key from the env or from ``~/.config/anthropic/individual.key``."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    path = Path.home() / ".config" / "anthropic" / "individual.key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def _call_llm(prompt: str, *, max_tokens: int = 4096) -> str:
    """Single MiniMax-M3 (default llm-call backend) round-trip. Falls back to claude-haiku if
    the anthropic SDK is unavailable. Tightly scaffolded JSON response."""
    try:
        import anthropic
    except Exception:
        # last-ditch: the cbsession parent runs this through an env shim (`llm-call` skill);
        # nothing to do here without the SDK.
        raise RuntimeError("anthropic SDK not installed on this host; spawn a cbsession worker instead")
    api_key = _anth_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY required (or ~/.config/anthropic/individual.key)")
    client = anthropic.Anthropic(api_key=api_key, timeout=120)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    out: List[str] = []
    for block in msg.content or []:
        if getattr(block, "type", "") == "text":
            out.append(block.text)
    return "".join(out)


# --------------------------------------------------------------------------- prompt + parse

INSTRUCTIONS = """\
You read these VirtualPyTest docs and write {max_rows} short, real questions a {persona_label} would ask about the {area_label} slice. For each, give:

- ``id``: a stable identifier like "{prefix}-NNN" (zero-pad to 3 digits, 001..NNN).
- ``topic``: "{topic}".
- ``question``: the question, in plain English, 5-25 words.
- ``short``: the one-line answer the chat would send (≤ 280 chars).
- ``long``: a fuller answer (≤ 800 chars) with the cited doc path inline.
- ``sources``: list of doc paths you actually used. Quote only docs you read here.
- ``tags``: ["{persona}", "{area}"].

Rules:
1. Each ``short`` MUST be supported by at least one cited doc. Quote the file and section in ``long`` and put the path in ``sources``. No invented facts.
2. 6 of the questions should paraphrase the canonical doc headline (FAQ-style: "How does X work?" / "What's the difference between X and Y?"). 4 should be the kind of question real users send in Atlas chat: terse, sometimes bent, sometimes surprising.
3. No duplicates within the batch. Vary the question wording, the topic, and the cited doc.
4. Output one JSON object per line. No markdown fences. No commentary. No leading or trailing text. The first character of your output must be ``[``."""

def _build_prompt(persona: str, area: str, docs_text: str, max_rows: int) -> str:
    out = INSTRUCTIONS
    out = out.replace("{max_rows}", str(max_rows))
    out = out.replace("{persona_label}", persona)
    out = out.replace("{area_label}", area)
    out = out.replace("{prefix}", f"{area}")
    out = out.replace("{persona}", persona)
    out = out.replace("{area}", area)
    out = out.replace("{topic}", area)
    return out + "\n\n## Docs you have read\n\n" + docs_text + "\n\n## Output\n\n"


def _parse_jsonl(text: str) -> List[Dict]:
    """Tolerant: take the first line that looks like JSON ``[`` start and parse line-by-line."""
    out: List[Dict] = []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    if cleaned.startswith("["):
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
    for line in cleaned.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# --------------------------------------------------------------------------- entry validation

def _normalise(text: str) -> str:
    import unicodedata
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text).lower()
    no_punct = re.sub(r"[^\w\s]", " ", nfkc, flags=re.UNICODE)
    return re.sub(r"\s+", " ", no_punct).strip()[:200]


def _validate(entry: Dict, *, topic: str, persona: str, area: str, prefix: str, idx: int) -> Optional[Dict]:
    question = str(entry.get("question") or "").strip()
    short = str(entry.get("short") or "").strip()
    long = str(entry.get("long") or "").strip()
    sources = entry.get("sources") or []
    if not (question and short and long):
        return None
    if not isinstance(sources, list) or not sources:
        return None
    sources = [str(s).strip() for s in sources if str(s).strip()]
    if not sources:
        return None
    return {
        "id": str(entry.get("id") or f"{prefix}-{idx:03d}"),
        "topic": str(entry.get("topic") or topic),
        "question": question,
        "short": short[:280],
        "long": long[:800],
        "sources": sources,
        "tags": list(dict.fromkeys([str(t) for t in (entry.get("tags") or [])] + [persona, area])),
        "_normalised_question": _normalise(question),
        "proposed": True,
        "live": False,
    }


# --------------------------------------------------------------------------- main


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--persona", required=True, choices=sorted(PERSONAS))
    parser.add_argument("--area",    required=True, choices=sorted(AREAS))
    parser.add_argument("--max-rows", type=int, default=100)
    parser.add_argument("--output",  required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="build the prompt and write it to a sibling .prompt.txt; do not call the LLM")
    args = parser.parse_args(argv)

    paths = [REPO / p for p in AREAS[args.area]]
    docs_chunks: List[str] = []
    for p in paths:
        if p.exists():
            text = p.read_text(encoding="utf-8")
            docs_chunks.append(f"### {p.relative_to(REPO)}\n\n```\n{text[:6000]}\n```\n")
    docs_text = "\n\n".join(docs_chunks)
    if not docs_text:
        print(f"faq_grow_persona: no docs found in area {args.area}", file=sys.stderr)
        return 2

    prompt = _build_prompt(args.persona, args.area, docs_text, args.max_rows)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        prompt_path = out_path.with_suffix(".prompt.txt")
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"faq_grow_persona: prompt written to {prompt_path} ({len(prompt)} chars)")
        return 0

    raw = _call_llm(prompt)
    parsed = _parse_jsonl(raw)
    valid: List[Dict] = []
    seen: Dict[str, int] = {}
    for i, entry in enumerate(parsed, start=1):
        v = _validate(entry, topic=args.area, persona=args.persona, area=args.area, prefix=args.area, idx=i)
        if v is None:
            continue
        nq = v["_normalised_question"]
        if not nq or nq in seen:
            continue
        seen[nq] = 1
        valid.append(v)

    with out_path.open("w", encoding="utf-8") as h:
        for row in valid:
            h.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"faq_grow_persona: wrote {len(valid)} of {len(parsed)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
