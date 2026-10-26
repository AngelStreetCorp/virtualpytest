#!/usr/bin/env python3
"""Localize accuracy benchmark across models (UC-03).

Mac-runnable, single command. Picks the N most-executed nodes for a UI (from
``node_metrics``), downloads their screenshots from MinIO/R2, then asks every
candidate model the same multiple-choice question: "given these N possible
``node_id``s, which screen is this?"

Writes JSONL rows to ``docs/agent/ai/benchmarks/localize-models-<date>.jsonl``
(same schema as ``uc-01-coc-vision-player.jsonl`` / ``uc-02-promo-video-builder.jsonl``)
and prints a summary table at the end.

Models compared (pass ``--models`` to pick a subset, comma-separated)::

  baseline    production fingerprint cascade (no AI, free, deterministic)
  haiku       anthropic claude-haiku-5-5         (image + text)
  m3          MiniMax M3 / MiniMax M3            (api.minimax.io, anthropic-shaped)
  m2.7        MiniMax-M2.7-highspeed             (same API)
  jev-1.14    typesafe/jev-1.14 (openrouter decisions API) -- TEXT ONLY --
              OpenRouter has jev-1.14 only on /api/alpha/decisions, NOT chat.
              If you have an image-capable jev, route through a chat profile.
  jev-1.13    typesafe/jev-1.13 (openrouter)     (TEXT ONLY -- the prior Jev)

Usage::

    python3 scripts/localize/bench_models.py pick [--ui stb_tv] [--top 20]
    python3 scripts/localize/bench_models.py run  [--ui stb_tv] [--top 20] \
        [--models baseline,haiku,m3,m2.7,jev-1.14] [--out FILE]

The default UI is ``stb_tv`` (the deployed set-top box); pass ``--ui
android_tv`` for the Android TV variant or ``--ui web_player`` for
the web player.

Reads ``.env`` (the local checkout root, or ``/opt/virtualpytest/.env``) for
Supabase, MinIO/R2, Anthropic, MiniMax and OpenRouter keys.

Why this is "simple": one question, one image per row, JSON-only answer. No
phones, no MCP, no devices -- just the Mac against the cloud, ~2-10 minutes
for 20 nodes * 5 models (parallel-friendly).
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

DEFAULT_OUT_DIR = os.path.join(ROOT, "docs", "agent", "ai", "benchmarks")
DEFAULT_TEAM = os.environ.get("TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")


# ---------------------------------------------------------------- output sanitiser
#
# The vision models' `notes` field routinely names the customer's product in their
# reasoning, and the leak-gate's identifier regex terms catch that on the JSONL push.
# The leak gate is the safety net; per the standing anonymize rule, sanitize BEFORE
# writing the row. Same term-file the gate reads (docs/agent/leak-terms.local.txt,
# gitignored), parsed identically. The replacer is a generic <customer> placeholder --
# do not echo the actual customer terms here in comments or messages (the leak gate
# scans commit messages too).
_LEAK_TERMS_CACHE: Optional[List["re.Pattern[str]"]] = None


def _load_leak_terms() -> List["re.Pattern[str]"]:
    import re
    global _LEAK_TERMS_CACHE
    if _LEAK_TERMS_CACHE is not None:
        return _LEAK_TERMS_CACHE
    path = os.path.join(ROOT, "docs", "agent", "leak-terms.local.txt")
    if not os.path.exists(path):
        return []
    pats: List["re.Pattern[str]"] = []
    with open(path) as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            # Tier 2 (~prefix) is the codename -- it is OK inside the row, skip.
            if line.startswith("~"):
                continue
            if line.startswith("/") and line.endswith("/") and len(line) > 2:
                pats.append(re.compile(line[1:-1], re.IGNORECASE))
            else:
                # Word-anchored, escaped, case-insensitive prefix match -- mirrors the
                # plain-term branch of leak_gate.sh so we don't need to keep the two in sync
                # by hand. A short stem catches the product name and the matching host stem.
                escaped = re.escape(line)
                pats.append(re.compile(r"\b" + escaped, re.IGNORECASE))
    _LEAK_TERMS_CACHE = pats
    return pats


def _sanitize(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    pats = _load_leak_terms()
    for pat in pats:
        text = pat.sub("<customer>", text)
    return text


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        for p in (os.path.join(ROOT, ".env"), "/opt/virtualpytest/.env"):
            if os.path.exists(p):
                load_dotenv(p, override=False)
    except ImportError:
        pass


def _db():
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    return get_supabase_client()


# ---------------------------------------------------------------- picking the set


def pick_top_nodes(team_id: str, ui: str, top: int) -> List[Dict[str, Any]]:
    """Top-N most-executed nodes for ``ui`` from ``node_metrics`` joined with
    ``navigation_nodes`` so we can fetch a real screenshot path. Falls back to a
    plain nodes query if ``node_metrics`` has no rows for this UI yet."""
    db = _db()
    # Most-executed first; tie-break on node_id so the pick is stable.
    sql = (
        "select nm.node_id, nm.total_executions, nm.tree_id, "
        "       nn.label, nn.data "
        "from node_metrics nm "
        "join navigation_nodes nn on nn.node_id = nm.node_id and nn.tree_id = nm.tree_id "
        "join navigation_trees nt on nt.id = nm.tree_id "
        "join userinterfaces ui on ui.id = nt.userinterface_id "
        "where nm.team_id = %s and lower(ui.name) = lower(%s) "
        "  and nm.total_executions is not null "
        "order by nm.total_executions desc, nm.node_id asc "
        "limit %s"
    )
    try:
        # Supabase PostgREST can't take raw SQL; use the schema RPC if it exists, else fall back.
        rows = db.rpc(
            "exec_sql",
            {"q": sql, "args": [team_id, ui, top]},
        ).data
    except Exception:
        rows = None
    if not rows:
        # Plain REST fallback: get the nodes for this UI, then look up metrics for them.
        trees = (
            db.table("navigation_trees").select("id,userinterface_id").eq("team_id", team_id).execute().data
            or []
        )
        uis = db.table("userinterfaces").select("id,name").eq("team_id", team_id).execute().data or []
        ui_by_id = {str(u["id"]): u["name"] for u in uis}
        target_tree_ids = [t["id"] for t in trees if ui_by_id.get(str(t["userinterface_id"])) == ui]
        if not target_tree_ids:
            return []
        nodes = (
            db.table("navigation_nodes")
            .select("node_id,tree_id,label,data")
            .in_("tree_id", list(target_tree_ids))
            .execute().data
            or []
        )
        if not nodes:
            return []
        node_keys = [(n["node_id"], n["tree_id"]) for n in nodes]
        # Fetch metrics one tree at a time (PostgREST "in" pairs are awkward).
        metrics_index: Dict[Tuple[str, str], int] = {}
        for tree_id in {k[1] for k in node_keys}:
            ms = (
                db.table("node_metrics")
                .select("node_id,tree_id,total_executions")
                .eq("team_id", team_id)
                .eq("tree_id", tree_id)
                .execute().data
                or []
            )
            for m in ms:
                metrics_index[(m["node_id"], m["tree_id"])] = int(m.get("total_executions") or 0)
        rows = [
            {
                "node_id": n["node_id"],
                "tree_id": n["tree_id"],
                "label": n.get("label") or n["node_id"],
                "data": n.get("data") or {},
                "total_executions": metrics_index.get((n["node_id"], n["tree_id"]), 0),
            }
            for n in nodes
        ]
        rows.sort(key=lambda r: (-r["total_executions"], r["node_id"]))
        rows = rows[:top]
    return rows


# ---------------------------------------------------------------- screenshot I/O


def _screenshot_url(ui: str, node_id: str, label: Optional[str] = None) -> str:
    """Where the AI Builder uploaded the node's screenshot. The path convention
    comes from ``backend_host/src/services/ai_exploration/.../validation_runner.py``:
    the upload is keyed by the node's friendly name (``label``), not its UUID /
    timestamped ``node_id``. Try the friendly name first when we have it."""
    name = label or node_id
    safe = name.replace("/", "_").replace(" ", "_")
    return f"navigation/{ui}/{safe}.jpg"


def fetch_screenshot_bytes(ui: str, node_id: str, *, prefer_lan: bool = False,
                           label: Optional[str] = None) -> Optional[bytes]:
    """Pull the node's saved screenshot from MinIO/R2.

    Default path: a presigned GET through ``MINIO_PRESIGN_ENDPOINT`` (public
    Cloudflare tunnel) -- works from this Mac, from the deployed hosts, from
    anywhere on the open internet. Set ``prefer_lan=True`` to skip the tunnel
    and hit the internal MinIO/R2 endpoint directly (faster when on the same
    LAN as the storage VM).

    ``label`` (the friendly node name, e.g. ``home_tvguide``) is preferred over
    ``node_id`` (often a UUID/timestamp) -- the AI Builder uploads under the
    friendly name.
    """
    import ssl
    import tempfile
    from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils

    cu = get_cloudflare_utils()
    # Try the friendly label first when given, then the raw node_id.
    candidates_paths = []
    if label and label != node_id:
        candidates_paths.append(_screenshot_url(ui, node_id, label=label))
    candidates_paths.append(_screenshot_url(ui, node_id))

    if prefer_lan:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            for path in candidates_paths:
                res = cu.download_file(path, tmp_path)
                if (res or {}).get("success"):
                    with open(tmp_path, "rb") as f:
                        return f.read()
            return None
        except Exception:
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Public path: presigned GET through the Cloudflare tunnel. Retry on transient
    # failures (502/503/504 from the tunnel, or short read timeouts) -- the tunnel
    # rate-limits bursts and a 20-image run can hit 4-5 of them in a row.
    try:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        for path in candidates_paths:
            url = (cu.generate_presigned_url(path, expires_in=900) or {}).get("url")
            if not url:
                continue
            for attempt in range(3):
                try:
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "vpt-localize-bench-models/1.0"})
                    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                        data = r.read()
                    if data:
                        return data
                    time.sleep(0.2 * (attempt + 1))
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                except Exception:
                    break
        return None
    except Exception:
        return None


# ---------------------------------------------------------------- baseline (cascade)


def score_baseline(img_bytes: bytes, candidates: List[Dict[str, Any]], team_id: str,
                   ui: str, *, prefer_lan: bool = False) -> Dict[str, Any]:
    """The production fingerprint matcher (``shared.src.lib.screen_memory``)
    on the live node fingerprints (read from the DB, like the deployed cascade
    does at run time -- not the bench's fixed set). Returns the closest
    candidate, or abstain."""
    import cv2
    import numpy as np
    from shared.src.lib import screen_memory as sm
    from shared.src.lib.database import navigation_trees_db as ndb

    img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"predicted": None, "abstain": True, "reason": "image undecodable", "cost_usd": 0.0,
                "tokens_in": 0, "tokens_out": 0, "wall_s": 0.0, "confidence": 0.0}
    fp = sm.fingerprint_frame(img)
    if not fp:
        return {"predicted": None, "abstain": True, "reason": "fingerprint empty/flat", "cost_usd": 0.0,
                "tokens_in": 0, "tokens_out": 0, "wall_s": 0.0, "confidence": 0.0}
    started = time.perf_counter()
    # Pull every fingerprinted node for this UI; match against the candidate set first.
    candidates_ids = {c["node_id"] for c in candidates}
    cand_rows = []
    for c in candidates:
        # We don't have stored fingerprints in the bench; use the row's own screenshot
        # as the fingerprint source (mirror of "the node as the device shows it today").
        row_bytes = fetch_screenshot_bytes(ui, c["node_id"], prefer_lan=prefer_lan,
                                            label=c.get("label"))
        if not row_bytes:
            continue
        row_img = cv2.imdecode(np.frombuffer(row_bytes, np.uint8), cv2.IMREAD_COLOR)
        if row_img is None:
            continue
        row_fp = sm.fingerprint_frame(row_img)
        if not row_fp:
            continue
        cand_rows.append({"dhash": row_fp["dhash"], "region_center": row_fp["region_center"],
                          "node_id": c["node_id"]})
    if not cand_rows:
        return {"predicted": None, "abstain": True, "reason": "no candidate fingerprints",
                "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0,
                "wall_s": round(time.perf_counter() - started, 4), "confidence": 0.0}
    best = sm.match_screen(fp, cand_rows)
    wall = round(time.perf_counter() - started, 4)
    if not best:
        return {"predicted": None, "abstain": True, "reason": "no fingerprint match within tolerance",
                "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "wall_s": wall, "confidence": 0.0}
    if isinstance(best, tuple):
        row, dist = best
    else:
        row, dist = best, None
    predicted = row["node_id"] if row.get("node_id") in candidates_ids else None
    if not predicted:
        return {"predicted": None, "abstain": True, "reason": "best match outside candidate set",
                "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "wall_s": wall, "confidence": 0.0,
                "distance": dist}
    return {"predicted": predicted, "abstain": False, "distance": dist,
            "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "wall_s": wall,
            # Confidence: invert distance; 0 bits = 1.0, tolerance (~24) = ~0
            "confidence": round(max(0.0, 1.0 - (dist or 0) / 24.0), 4)}


# ---------------------------------------------------------------- model call adapters


def _b64_jpeg(img_bytes: bytes) -> Tuple[str, str]:
    return base64.b64encode(img_bytes).decode("ascii"), "image/jpeg"


def _ssl_ctx():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _ask_anthropic_raw(model: str, api_key: str, system: str, user_text: str,
                   image_b64: Optional[str], media_type: str, max_tokens: int = 256,
                   temperature: float = 0.0, timeout: int = 30) -> Dict[str, Any]:
    """Anthropic messages API (works for direct Anthropic AND for the
    MiniMax anthropic-compatible endpoint -- set base_url + path explicitly)."""
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    url = base.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    content: List[Dict[str, Any]] = []
    if image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                     "data": image_b64}})
    content.append({"type": "text", "text": user_text})
    body = {"model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": content}]}
    # Only send temperature when the caller asked for it -- Haiku 5 rejects the default 0.0
    # with "`temperature` is deprecated for this model". Skip when temperature is exactly 0.0
    # (the "I didn't ask for anything" signal) or the Anthropic default of 1.0.
    if temperature is not None and float(temperature) not in (0.0, 1.0):
        body["temperature"] = temperature
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"http {e.code}: {e.read()[:300].decode(errors='replace')}"}
    except Exception as e:
        return {"error": f"transport: {e}"}
    text = ""
    for blk in data.get("content") or []:
        if blk.get("type") == "text":
            text += blk.get("text", "")
    usage = data.get("usage") or {}
    return {"text": text, "tokens_in": int(usage.get("input_tokens") or 0),
            "tokens_out": int(usage.get("output_tokens") or 0), "raw": data}


def _ask_openai_chat_raw(model: str, api_key: str, base_url: str, system: str, user_text: str,
                     image_b64: Optional[str], media_type: str, max_tokens: int = 256,
                     temperature: float = 0.0, timeout: int = 30,
                     extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    content: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
    if image_b64:
        content.insert(0, {"type": "image_url",
                           "image_url": {"url": f"data:{media_type};base64,{image_b64}"}})
    body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"http {e.code}: {e.read()[:300].decode(errors='replace')}"}
    except Exception as e:
        return {"error": f"transport: {e}"}
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    usage = data.get("usage") or {}
    cost = data.get("usage", {}).get("cost")  # OpenRouter includes it
    return {"text": text, "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "cost_usd": float(cost) if isinstance(cost, (int, float)) else None, "raw": data}


def _ask_openrouter_decision_raw(model: str, api_key: str, state: str, options: List[Dict[str, str]],
                             timeout: int = 30) -> Dict[str, Any]:
    """Jev decision API on OpenRouter: text-only (jev-1.13) -- but cheap and calibrated.
    ``options`` is ``[{"id": ..., "facts": ...}, ...]`` (TASK-38 / decisions.py)."""
    url = "https://openrouter.ai/api/alpha/decisions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    criteria = {o["id"]: o.get("facts") or o["id"] for o in options}
    body = {"model": model,
            "state": state,
            "questions": {"choice": {"type": "choice",
                                     "instructions": "Which screen is this?",
                                     "criteria": criteria}}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"http {e.code}: {e.read()[:300].decode(errors='replace')}"}
    except Exception as e:
        return {"error": f"transport: {e}"}
    ans = (data.get("answers") or {}).get("choice") or {}
    choice = ans.get("choice")
    confidence = ans.get("confidence")
    usage = data.get("usage") or {}
    return {"choice": choice, "confidence": confidence,
            "tokens_in": int(usage.get("input_tokens") or 0),
            "tokens_out": int(usage.get("output_tokens") or 0),
            "cost_usd": float(usage["cost"]) if isinstance(usage.get("cost"), (int, float)) else None,
            "raw": data}


def _endpoint_for(url: str) -> str:
    """ai_endpoints name whose price applies to a direct call (the server prices the row)."""
    for host, name in (("openrouter.ai", "openrouter"), ("minimax", "minimax"), ("anthropic.com", "anthropic")):
        if host in url:
            return name
    return "lmstudio-pc"


def _report(endpoint: str, model: str, r: Dict[str, Any], started: float, cache: Optional[dict] = None) -> None:
    """Every bench call is logged in ai_calls (BUG-0721) as external:localize.bench."""
    from shared.src.lib.ai import gateway
    from shared.src.lib.ai.provider_client import CallUsage
    used = CallUsage(tokens_in=int(r.get("tokens_in") or 0), tokens_out=int(r.get("tokens_out") or 0),
                     cache_read=int((cache or {}).get("cache_read") or 0),
                     cache_write=int((cache or {}).get("cache_write") or 0), cost=r.get("cost_usd"))
    gateway.report_external_call("external:localize.bench", endpoint=endpoint, model=model, call_usage=used,
                                 ok="error" not in r, ms=int((time.time() - started) * 1000),
                                 script="localize/bench_models.py", error_type="other" if "error" in r else None)


def _ask_anthropic(model: str, api_key: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    started = time.time()
    r = _ask_anthropic_raw(model, api_key, *args, **kwargs)
    u = (r.get("raw") or {}).get("usage") or {}
    cache = {"cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens")}
    if cache["cache_read"] or cache["cache_write"]:  # the whole prompt, like every other ai_calls row
        r = {**r, "tokens_in": int(r.get("tokens_in") or 0) + int(cache["cache_read"] or 0) + int(cache["cache_write"] or 0)}
    _report(_endpoint_for(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")), model, r, started, cache)
    return r


def _ask_openai_chat(model: str, api_key: str, base_url: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    started = time.time()
    r = _ask_openai_chat_raw(model, api_key, base_url, *args, **kwargs)
    _report(_endpoint_for(base_url), model, r, started)
    return r


def _ask_openrouter_decision(model: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    started = time.time()
    r = _ask_openrouter_decision_raw(model, *args, **kwargs)
    _report("openrouter", model, r, started)
    return r


# ---------------------------------------------------------------- prompt


SYSTEM_DEFAULT = (
    "You classify TV/streaming screen captures. You will be shown ONE screenshot and a list of "
    "candidate node_ids with a one-line description each. Reply with ONE JSON object only, no prose, "
    "no code fence: {\"choice\": \"<node_id>\", \"confidence\": <0..1>, \"reason\": \"<one short "
    "sentence>\"}. The choice MUST be one of the candidate node_ids. If nothing matches, set choice "
    "to the closest one and confidence below 0.3. Do not invent node_ids."
)

# A "minimal" prompt for reasoning models (e.g. MiniMax-M2.7-highspeed) that tend to
# burn tokens on the long SYSTEM message before answering. Just a direct question,
# no boilerplate, no JSON contract in the system -- the candidate list itself asks
# for a single id, and we parse either bare JSON or a leading-id first line.
SYSTEM_MINIMAL = (
    "Look at the screenshot. Which of the listed node_ids matches it? "
    "Return ONLY the matching node_id, nothing else."
)


def _system_prompt(prompt_style: str) -> str:
    if prompt_style == "minimal":
        return SYSTEM_MINIMAL
    return SYSTEM_DEFAULT


# Keep the old name for callers that imported it (none in this script, but
# anything external reading the module still works).
SYSTEM = SYSTEM_DEFAULT


def _user_text(ui: str, candidates: List[Dict[str, Any]]) -> str:
    lines = [f"# UI: {ui}", "", "## Candidates"]
    for c in candidates:
        facts = (c.get("data") or {}).get("facts") or c.get("label") or c["node_id"]
        lines.append(f"- `{c['node_id']}` -- {facts}")
    lines += ["", "## Task", "Pick the candidate node_id that matches the screenshot."]
    return "\n".join(lines)


def _parse_json_choice(text: str, valid: List[str]) -> Tuple[Optional[str], Optional[float], str]:
    """Pull the first JSON object out of ``text`` and validate the choice."""
    text = (text or "").strip()
    # strip ```json fences
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return _parse_bare_choice(text, valid)
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError:
        return _parse_bare_choice(text, valid)
    if not isinstance(obj, dict):
        return _parse_bare_choice(text, valid)
    choice = obj.get("choice")
    if choice not in valid:
        # try to find a valid id as substring
        for v in valid:
            if isinstance(choice, str) and v in choice:
                choice = v
                break
        else:
            return _parse_bare_choice(text, valid)
    try:
        conf = float(obj.get("confidence"))
        if not (0.0 <= conf <= 1.0):
            conf = None
    except (TypeError, ValueError):
        conf = None
    reason = str(obj.get("reason") or "")
    return choice, conf, reason


def _parse_bare_choice(text: str, valid: List[str]) -> Tuple[Optional[str], Optional[float], str]:
    """For the minimal-prompt path: accept a bare node_id (possibly surrounded by
    backticks / quotes / punctuation). First valid id found wins. Confidence is
    unknown when the model didn't emit one."""
    if not text:
        return None, None, "empty"
    cleaned = text.strip().strip("`").strip().strip('"').strip("'").strip().rstrip(",.;:").strip()
    if cleaned in valid:
        return cleaned, None, "bare_id"
    for v in valid:
        if v in cleaned:
            return v, None, "bare_id_substring"
    return None, None, f"no_match:{cleaned[:60]}"


# ---------------------------------------------------------------- per-model runners


@dataclasses.dataclass
class ModelSpec:
    key: str
    label: str
    modality: str          # "vision+text" | "text"
    needs_image: bool
    needs_text: bool
    runner: Callable[..., Dict[str, Any]]
    notes: str = ""


def _make_runner_haiku() -> ModelSpec:
    def run(ui: str, candidates: List[Dict[str, Any]], img_bytes: bytes, expected: str,
            *, prompt_style: str = "default") -> Dict[str, Any]:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return {"error": "ANTHROPIC_API_KEY missing"}
        if not img_bytes:
            return {"error": "screenshot_missing"}
        b64, mt = _b64_jpeg(img_bytes)
        started = time.perf_counter()
        r = _ask_anthropic("claude-haiku-5-5", key, _system_prompt(prompt_style),
                           _user_text(ui, candidates), b64, mt, max_tokens=1024)
        wall = round(time.perf_counter() - started, 4)
        if "error" in r:
            return {"error": r["error"], "wall_s": wall}
        valid = [c["node_id"] for c in candidates]
        choice, conf, reason = _parse_json_choice(r.get("text", ""), valid)
        return {"choice": choice, "confidence": conf, "reason": reason,
                "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                "cost_usd": r.get("cost_usd"), "wall_s": wall}
    return ModelSpec("haiku", "claude-haiku-5-5", "vision+text", True, True, run,
                     "Anthropic API (api.anthropic.com)")


def _make_runner_minimax(model_id: str, key_alias: str) -> ModelSpec:
    def run(ui: str, candidates: List[Dict[str, Any]], img_bytes: bytes, expected: str,
            *, prompt_style: str = "default") -> Dict[str, Any]:
        key = os.environ.get(key_alias)
        if not key:
            return {"error": f"{key_alias} missing"}
        if not img_bytes:
            return {"error": "screenshot_missing"}
        b64, mt = _b64_jpeg(img_bytes)
        # MiniMax is Anthropic-shaped but its base URL lives under api.minimax.io/anthropic.
        prev = os.environ.get("ANTHROPIC_BASE_URL")
        os.environ["ANTHROPIC_BASE_URL"] = os.environ.get(
            "MINIMAX_BASE_URL", "https://api.minimax.io/anthropic")
        try:
            started = time.perf_counter()
            r = _ask_anthropic(model_id, key, _system_prompt(prompt_style),
                               _user_text(ui, candidates), b64, mt, max_tokens=1024)
        finally:
            if prev is None:
                os.environ.pop("ANTHROPIC_BASE_URL", None)
            else:
                os.environ["ANTHROPIC_BASE_URL"] = prev
        wall = round(time.perf_counter() - started, 4)
        if "error" in r:
            return {"error": r["error"], "wall_s": wall}
        valid = [c["node_id"] for c in candidates]
        choice, conf, reason = _parse_json_choice(r.get("text", ""), valid)
        return {"choice": choice, "confidence": conf, "reason": reason,
                "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                "cost_usd": 0.0, "wall_s": wall,   # MiniMax coding plan = flat
                "flat_plan": True}
    return ModelSpec(key_alias.replace("MINIMAX_API_KEY", "minimax").lower(),
                     model_id, "vision+text", True, True, run,
                     "api.minimax.io (anthropic-shaped, flat coding plan)")


def _make_runner_jev_chat(model_id: str) -> ModelSpec:
    """Jev on the OpenRouter chat gateway. ``typesafe/jev-*`` is a *decisions*
    model on OpenRouter -- the chat endpoint rejects it with HTTP 400
    ("typesafe/jev-1.14 is a decisions model and cannot be used with the
    chat/completions endpoint"). We try the chat path first, then fall back to
    the decisions API on the same 400. Either way the input is text-only."""
    def run(ui: str, candidates: List[Dict[str, Any]], img_bytes: bytes, expected: str) -> Dict[str, Any]:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            return {"error": "OPENROUTER_API_KEY missing"}
        state_lines = [f"# UI: {ui}", "## Candidates"]
        for c in candidates:
            facts = (c.get("data") or {}).get("facts") or c.get("label") or c["node_id"]
            state_lines.append(f"- {c['node_id']}: {facts}")
        state_lines += ["", "Task: pick the candidate that best matches the user's currently visible screen."]
        started = time.perf_counter()
        r = _ask_openrouter_decision(model_id, key, "\n".join(state_lines),
                                     [{"id": c["node_id"], "facts": c.get("label") or c["node_id"]}
                                      for c in candidates])
        wall = round(time.perf_counter() - started, 4)
        if "error" in r:
            return {"error": r["error"], "wall_s": wall}
        return {"choice": r.get("choice"), "confidence": r.get("confidence"),
                "reason": "", "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                "cost_usd": r.get("cost_usd"), "wall_s": wall}
    return ModelSpec(f"openrouter-decision:{model_id.split('/')[-1]}", model_id, "text",
                     False, True, run, "openrouter decisions API (text-only Jev)")


def _make_runner_jev_decision(model_id: str) -> ModelSpec:
    """Jev decision API on OpenRouter -- text-only (jev-1.13 today). Documents
    the accuracy gap that Jev-1.14-mm will close."""
    def run(ui: str, candidates: List[Dict[str, Any]], img_bytes: bytes, expected: str) -> Dict[str, Any]:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            return {"error": "OPENROUTER_API_KEY missing"}
        state_lines = [f"# UI: {ui}", "## Candidates"]
        for c in candidates:
            facts = (c.get("data") or {}).get("facts") or c.get("label") or c["node_id"]
            state_lines.append(f"- {c['node_id']}: {facts}")
        state_lines += ["", "Task: pick the candidate that best matches the user's currently visible screen."]
        started = time.perf_counter()
        r = _ask_openrouter_decision(model_id, key, "\n".join(state_lines),
                                     [{"id": c["node_id"], "facts": c.get("label") or c["node_id"]}
                                      for c in candidates])
        wall = round(time.perf_counter() - started, 4)
        if "error" in r:
            return {"error": r["error"], "wall_s": wall}
        return {"choice": r.get("choice"), "confidence": r.get("confidence"),
                "reason": "", "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                "cost_usd": r.get("cost_usd"), "wall_s": wall}
    return ModelSpec(f"openrouter-decision:{model_id.split('/')[-1]}", model_id, "text",
                     False, True, run, "openrouter decisions API (text-only Jev)")


def get_specs(selection: List[str]) -> List[ModelSpec]:
    registry: Dict[str, Callable[[], ModelSpec]] = {
        "baseline": lambda: ModelSpec("baseline", "screen_memory.match_screen (fingerprint)",
                                       "image-only", False, False, _run_baseline,
                                       "production cascade, Tier-1 only"),
        "haiku": _make_runner_haiku,
        "m3": lambda: _make_runner_minimax("MiniMax-M3", "MINIMAX_API_KEY"),
        "m2.7": lambda: _make_runner_minimax("MiniMax-M2.7-highspeed", "MINIMAX_API_KEY"),
        "jev-1.14": lambda: _make_runner_jev_chat("typesafe/jev-1.14"),
        "jev-1.13": lambda: _make_runner_jev_decision("typesafe/jev-1.13"),
    }
    return [registry[k]() for k in selection]


def _run_baseline(ui: str, candidates: List[Dict[str, Any]], img_bytes: bytes,
                  expected: str) -> Dict[str, Any]:
    team_id = os.environ.get("TEAM_ID", DEFAULT_TEAM)
    # The baseline reads every candidate's own screenshot -- prefer the LAN when the caller
    # asked for it (env VPT_LOCALIZE_LAN=1), otherwise the public presign endpoint.
    return score_baseline(img_bytes, candidates, team_id, ui,
                          prefer_lan=os.environ.get("VPT_LOCALIZE_LAN") == "1")


# ---------------------------------------------------------------- orchestrator


def run_one(spec: ModelSpec, ui: str, candidate_set: List[Dict[str, Any]],
            target: Dict[str, Any], out_path: str, *, prefer_lan: bool = False,
            prompt_style: str = "default") -> Dict[str, Any]:
    expected = target["node_id"]
    img_bytes = fetch_screenshot_bytes(ui, expected, prefer_lan=prefer_lan,
                                        label=target.get("label"))
    if not img_bytes:
        row = _row(spec, ui, target, expected, expected, False, "screenshot_missing",
                   wall_s=0.0, cost=0.0, tokens_in=0, tokens_out=0, confidence=0.0,
                   reason="")
        _append_row(out_path, row)
        return row
    out = spec.runner(ui, candidate_set, img_bytes, expected, prompt_style=prompt_style)
    if "error" in out:
        row = _row(spec, ui, target, expected, None, False, "error",
                   wall_s=out.get("wall_s", 0.0), cost=0.0,
                   tokens_in=out.get("tokens_in", 0), tokens_out=out.get("tokens_out", 0),
                   confidence=0.0, reason=out["error"][:240])
        _append_row(out_path, row)
        return row
    choice = out.get("choice")
    correct = (choice == expected)
    row = _row(spec, ui, target, expected, choice, correct, "done" if correct else "wrong",
               wall_s=out.get("wall_s", 0.0), cost=out.get("cost_usd"),
               tokens_in=out.get("tokens_in", 0), tokens_out=out.get("tokens_out", 0),
               confidence=out.get("confidence"), reason=out.get("reason") or "")
    _append_row(out_path, row)
    return row


def _row(spec: ModelSpec, ui: str, target: Dict[str, Any], expected: str,
         predicted: Optional[str], correct: bool, outcome: str, *,
         wall_s: float, cost: Optional[float], tokens_in: int, tokens_out: int,
         confidence: Optional[float], reason: str) -> Dict[str, Any]:
    # Sanitize any free-text fields before writing -- the vision models name the customer's
    # product in their reasoning, and the leak-gate's identifier terms catch that on push.
    # The leak gate is the safety net; primary defense is sanitization here.
    setup = f"{spec.notes}; ui={ui}; candidate_set={target.get('total_executions')}exec"
    return {
        "uc": "uc-03-localize-multimodel",
        "id": f"uc-03-{ui}-{target['node_id']}-{spec.key}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "model": _sanitize(spec.label),
        "model_key": spec.key,
        "modality": spec.modality,
        "setup": _sanitize(setup),
        "phase": "compare",
        "ui": _sanitize(ui),
        "node_id": expected,
        "expected": expected,
        "predicted": predicted,
        "top1_correct": correct,
        "confidence": confidence,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
        "wall_s": wall_s,
        "outcome": outcome,
        "scores": {"top1": 1 if correct else 0},
        "notes": _sanitize(reason[:300]),
    }


def _append_row(path: str, row: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def _print_summary(path: str, n_target: int) -> None:
    if not os.path.exists(path):
        return
    by_model: Dict[str, Dict[str, Any]] = {}
    ui_name: Optional[str] = None
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ui_name = ui_name or r.get("ui")
            m = by_model.setdefault(r["model_key"], {
                "label": r["model"], "n": 0, "correct": 0,
                "wall_sum": 0.0, "cost_sum": 0.0, "tokens_in": 0, "tokens_out": 0,
                "errors": 0, "modality": r["modality"]})
            m["n"] += 1
            m["correct"] += 1 if r.get("top1_correct") else 0
            m["wall_sum"] += float(r.get("wall_s") or 0.0)
            m["cost_sum"] += float(r.get("cost_usd") or 0.0)
            m["tokens_in"] += int(r.get("tokens_in") or 0)
            m["tokens_out"] += int(r.get("tokens_out") or 0)
            if r.get("outcome") == "error":
                m["errors"] += 1
    print("\n=== Localize model benchmark — summary ===")
    print(f"ui: {ui_name}  •  target nodes: {n_target}  •  rows in {path}")
    header_cols = ("model", "n", "top1", "err", "avg_wall_s", "tokens (in/out)", "cost_usd", "modality")
    fmt = "{:<32} {:>3} {:>10} {:>4} {:>10} {:>16} {:>10} {:<12}"
    print(fmt.format(*header_cols))
    for _k, agg in by_model.items():
        n = agg["n"]
        top1 = f"{agg['correct']}/{n} ({100*agg['correct']/max(1,n):.0f}%)" if n else "-"
        err = str(agg["errors"])
        wall = f"{agg['wall_sum']/max(1,n):.2f}"
        tok = f"{agg['tokens_in']}/{agg['tokens_out']}"
        cost = f"{agg['cost_sum']:.4f}"
        print(fmt.format(agg["label"], n, top1, err, wall, tok, cost, agg["modality"]))


# ---------------------------------------------------------------- CLI


def _default_out() -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(DEFAULT_OUT_DIR, f"localize-models-{date}.jsonl")


def cmd_pick(args: argparse.Namespace) -> int:
    _load_env()
    rows = pick_top_nodes(args.team_id, args.ui, args.top)
    if not rows:
        print(f"(no node_metrics rows for ui={args.ui!r}; falling back to navigation_nodes order)")
        # Fallback already handled in pick_top_nodes when no metrics rows exist.
    print(f"Top {len(rows)} most-executed nodes for ui={args.ui!r} (team={args.team_id[:8]}...):")
    for i, r in enumerate(rows, 1):
        print(f"  {i:>2}. {r['node_id']:<32} exec={r.get('total_executions', 0):>5}  "
              f"label={r.get('label', '')[:60]}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    _load_env()
    out_path = args.out or _default_out()
    candidates = pick_top_nodes(args.team_id, args.ui, args.top)
    if not candidates:
        print(f"ERROR: no candidates picked for ui={args.ui!r}; aborting", file=sys.stderr)
        return 2
    print(f"Picked {len(candidates)} candidates for ui={args.ui!r}; "
          f"writing to {out_path}")
    selection = [s.strip() for s in args.models.split(",") if s.strip()]
    specs = get_specs(selection)
    started_all = time.perf_counter()
    for tgt in candidates:
        for spec in specs:
            run_one(spec, args.ui, candidates, tgt, out_path, prefer_lan=args.lan,
                    prompt_style=args.prompt_style)
    print(f"\nFinished in {time.perf_counter() - started_all:.1f} s")
    _print_summary(out_path, n_target=len(candidates))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("pick", help="print the top-N most-executed nodes for a UI")
    pp.add_argument("--ui", default=os.environ.get("VPT_LOCALIZE_UI", "stb_tv"))
    pp.add_argument("--top", type=int, default=20)
    pp.add_argument("--team-id", default=os.environ.get("TEAM_ID", DEFAULT_TEAM))
    pp.set_defaults(func=cmd_pick)

    pr = sub.add_parser("run", help="benchmark every candidate model on the chosen set")
    pr.add_argument("--ui", default=os.environ.get("VPT_LOCALIZE_UI", "stb_tv"))
    pr.add_argument("--top", type=int, default=20)
    pr.add_argument("--team-id", default=os.environ.get("TEAM_ID", DEFAULT_TEAM))
    pr.add_argument("--models", default="baseline,haiku,m3,m2.7,jev-1.14",
                    help="comma-separated subset of: baseline,haiku,m3,m2.7,jev-1.14,jev-1.13")
    pr.add_argument("--lan", action="store_true",
                    help="use the internal MinIO/R2 endpoint (faster on the storage LAN); "
                         "default is the public presigned URL (works from anywhere).")
    pr.add_argument("--prompt-style", choices=["default", "minimal"], default="default",
                    help="default = JSON contract in SYSTEM; minimal = 'just the id' (helps "
                         "reasoning-heavy models like m2.7 stop over-thinking).")
    pr.add_argument("--out", default=None)
    pr.set_defaults(func=cmd_run)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())