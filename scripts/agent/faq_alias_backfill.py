#!/usr/bin/env python3
"""TASK-152 phase 9c — alias backfill for the FAQ rows that have none.

Why this exists
---------------
Phase 9b grew the corpus from 100 curated rows to 345 live rows, but
``upsert_promoted()`` writes ``aliases: []`` — so 220 of the 345 rows can only
ever be found by an EXACT normalised-question match. A user who asks "is this
free or do i have to pay" never finds the row "Is VirtualPyTest free to use?".

The alias tier is purely lexical (stopword-filtered token overlap: >= 2 shared
content tokens AND >= 50 % of the query's content tokens), so an alias only
helps if it reuses the distinctive words a real user would type. Synonyms that
drop the key words do not match — the alias has to be a wording a user would
actually choose.

Safety rules (all enforced, none optional)
------------------------------------------
* **aliases only** — this script NEVER writes ``question_text``, ``short``,
  ``long``, ``sources`` or ``tags``, and never touches a row that already has
  aliases. It cannot overwrite an answer.
* every candidate alias must resolve back to its OWN row against the full
  corpus, otherwise it would answer somebody else's question.
* an alias may not normalise onto another row's canonical question (it would
  shadow that row).
* an alias may not make a TASK-163 use-case prompt match the FAQ tier. Those
  prompts are live-device operations that must reach the router, not a static
  docs answer — the FAQ hook short-circuits the turn before the router runs.

Usage
-----
    # 1. read the rows and produce candidate aliases (calls Haiku)
    python scripts/agent/faq_alias_backfill.py --generate --out /tmp/aliases.json
    # 2. apply them (aliases column only)
    python scripts/agent/faq_alias_backfill.py --apply --candidates /tmp/aliases.json
    # 3. coverage report
    python scripts/agent/faq_alias_backfill.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# scripts/usecase_contract.py — the contract table of the TASK-163 use cases
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from backend_server.src.agent import faqs  # noqa: E402  (pure logic, no DB)
from shared.src.lib.database import agent_faq_db  # noqa: E402
from usecase_contract import contract_rows  # noqa: E402

USECASES_MD = REPO_ROOT / "docs" / "agent" / "atlas" / "USECASES.md"

# An alias is a plausible user phrasing. Longer than this and it stops being a
# query; shorter than 2 content tokens and the alias tier can never fire
# (ALIAS_MIN_OVERLAP = 2 needs two shared content tokens).
MAX_ALIAS_WORDS = 14
MIN_ALIAS_CONTENT_TOKENS = faqs.ALIAS_MIN_OVERLAP

# The whole live corpus fits in the in-process cache for free (a 343-row cache
# measures the same 0.01 ms lookup as a 64-row one), so validation and the
# post-apply report both use the full corpus rather than the top-64.
FULL_CAP = 1024


# --------------------------------------------------------------------------- DB plumbing

def _client():
    return agent_faq_db._supabase()


def load_rows(table: str = agent_faq_db.FAQ_TABLE, *, live_only: bool = True) -> List[Dict]:
    """Every row of ``table`` in the shape ``HotFaqCache.load`` wants."""
    supabase = _client()
    q = supabase.table(table).select(
        "id,question_text,normalised_question,aliases,short,long,sources,tags,count,last_asked_at"
    )
    if live_only:
        q = q.eq("live", True)
    rows = list(q.execute().data or [])
    for r in rows:
        r["aliases"] = list(r.get("aliases") or [])
    return rows


def patch_table(table: str) -> None:
    """Point the shared DB module at another table (used for the copy test)."""
    agent_faq_db.FAQ_TABLE = table


# --------------------------------------------------------------------------- helpers

def content_tokens(text: str) -> Set[str]:
    """Stopword-filtered tokens — the unit the alias tier actually scores."""
    return faqs.alias_tokens(faqs.normalize(text))


def build_cache(rows: Sequence[Dict], cap: int = FULL_CAP):
    cache = faqs.HotFaqCache(cap)
    cache.load(rows)
    return cache


def rows_with_aliases(rows: Sequence[Dict], extra: Optional[Dict[str, List[str]]] = None) -> List[Dict]:
    """``rows`` with the candidate aliases from ``extra`` merged in (id -> aliases)."""
    out = []
    for r in rows:
        r2 = dict(r)
        if extra:
            r2["aliases"] = list(r2.get("aliases") or []) + list(extra.get(str(r2.get("id")), []) or [])
        out.append(r2)
    return out


def read_usecases(path: Path = USECASES_MD) -> List[Dict]:
    """The UC-nnn rows of the TASK-163 contract: id, prompt, expected tools.

    The contract table only: the file also holds the results tables and the
    browser-verification table, whose rows start with a UC- id too. Those are
    documentation — one of them carries a real device name, and it must not enter
    the FAQ-hijack check as if it were a live operation (scripts/usecase_contract.py).
    """
    if not path.exists():
        return []
    out: List[Dict] = []
    for row in contract_rows(path.read_text(encoding="utf-8")):
        cells = row["cells"]
        if len(cells) < 2:
            continue
        out.append({"id": row["id"], "prompt": cells[0], "tools": cells[1] if len(cells) > 1 else ""})
    return out


# --------------------------------------------------------------------------- LLM

def _anth_api_key() -> Optional[str]:
    """The Anthropic key, wherever this host keeps it.

    - ``ANTHROPIC_API_KEY`` in the environment;
    - ``~/.config/anthropic/individual.key`` (the owner's key on codebox);
    - the lab DB's secrets store (the server) — ``anthropic-individual``.

    The third one is what lets the nightly review on the server top up aliases without a
    key file on the box.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    path = Path.home() / ".config" / "anthropic" / "individual.key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    try:
        from shared.src.lib.ai.secrets_store import get_secret
        stored = get_secret("anthropic-individual")
        if stored:
            return str(stored).strip()
    except Exception:  # noqa: BLE001 - no secrets store on this host
        pass
    return None


def _call_llm(prompt: str, *, max_tokens: int = 2000) -> str:
    """One Haiku round-trip. Tightly scaffolded JSONL response."""
    import anthropic

    api_key = _anth_api_key()
    if not api_key:
        raise RuntimeError(
            "no Anthropic key: set ANTHROPIC_API_KEY, put one in "
            "~/.config/anthropic/individual.key, or store 'anthropic-individual' in the secrets store"
        )
    client = anthropic.Anthropic(api_key=api_key, timeout=120)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in (msg.content or []) if getattr(b, "type", "") == "text")


def _parse_jsonl(text: str) -> List[Dict]:
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
    out: List[Dict] = []
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


ALIAS_INSTRUCTIONS = """\
You write search aliases for a documentation FAQ. Each alias is another wording a real user might type that asks for the SAME documentation, so the entry is still found when the user words it differently.

For every numbered question below, give exactly 3 aliases.

Rules:
1. An alias is a short question or keyword phrase, 2 to 12 words.
2. The matcher is LEXICAL — it counts shared words, it does not understand meaning. So an alias MUST reuse the distinctive words of its question (the product name, the file name, the command, the technical noun). Do NOT replace them with synonyms: "cost money" will not be found by a user typing "pay".
3. An alias asks for DOCUMENTATION. Never phrase an alias as an instruction to operate a device ("turn on the stb", "press home", "take control of the tv", "screenshot the box"). Those are live commands and must never be answered by the FAQ.
4. No alias may repeat its own question, and no two aliases may be the same.
5. Keep every alias about the same topic as its question.
6. Output one JSON object per line and nothing else: {{"id": "<the id you were given>", "aliases": ["...", "...", "..."]}}
7. The first character of your output must be ``[``."""


def build_prompt(batch: Sequence[Dict]) -> str:
    lines = []
    for r in batch:
        lines.append(f"- id: {r['id']}\n  question: {r['question_text']}")
    return (
        ALIAS_INSTRUCTIONS
        + "\n\n## Questions\n\n"
        + "\n".join(lines)
        + "\n\n## Output\n\n"
    )


# --------------------------------------------------------------------------- validation

def validate_candidates(
    rows: Sequence[Dict],
    candidates: Dict[str, List[str]],
    uc_prompts: Sequence[Dict],
    *,
    baseline_hijacked: Set[str],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Split the candidates into the ones that survive and the ones that do not.

    Returns ``(accepted, rejected)`` — both keyed by row id.
    """
    rejected: Dict[str, List[str]] = {}
    accepted: Dict[str, List[str]] = {}
    by_id = {str(r["id"]): r for r in rows}
    canonical_of = {str(r["id"]): faqs.normalize(r.get("question_text") or "") for r in rows}
    # normalised canonical question -> owning id, to catch an alias shadowing another row
    canonical_owner: Dict[str, str] = {}
    for r in rows:
        n = faqs.normalize(r.get("question_text") or "")
        if n and n not in canonical_owner:
            canonical_owner[n] = str(r["id"])

    # Gate 1-4: per-alias, cheap and local.
    for rid, aliases in candidates.items():
        row = by_id.get(str(rid))
        if row is None:
            rejected.setdefault(str(rid), []).append("row not in corpus")
            continue
        existing = {faqs.normalize(a) for a in (row.get("aliases") or [])}
        own_norm = canonical_of[str(rid)]
        keep: List[str] = []
        for alias in aliases:
            a = str(alias or "").strip()
            why = None
            if not a:
                why = "empty"
            elif len(a.split()) > MAX_ALIAS_WORDS:
                why = f"more than {MAX_ALIAS_WORDS} words"
            elif len(content_tokens(a)) < MIN_ALIAS_CONTENT_TOKENS:
                why = "fewer than 2 content tokens"
            else:
                an = faqs.normalize(a)
                if an == own_norm:
                    why = "identical to its own question"
                elif an in existing:
                    why = "duplicate alias"
                elif an in canonical_owner and canonical_owner[an] != str(rid):
                    why = "shadows another row's canonical question"
            if why:
                rejected.setdefault(str(rid), []).append(f"{a!r}: {why}")
            else:
                keep.append(a)
        if keep:
            accepted[str(rid)] = keep

    # Gate 5: every accepted alias must resolve back to its own row, against the
    # full corpus with all candidate aliases applied.
    merged = rows_with_aliases(rows, accepted)
    cache = build_cache(merged)
    for rid, aliases in list(accepted.items()):
        keep = []
        for alias in aliases:
            hit = cache.lookup(alias)
            if hit is None:
                rejected.setdefault(rid, []).append(f"{alias!r}: resolves to nothing (too few content tokens)")
            elif str(hit.entry.id) != str(rid):
                rejected.setdefault(rid, []).append(
                    f"{alias!r}: resolves to {hit.entry.question_text!r} instead of its own row"
                )
            else:
                keep.append(alias)
        if keep:
            accepted[rid] = keep
        else:
            accepted.pop(rid, None)

    # Gate 6: an alias may not make a TASK-163 use-case prompt hit the FAQ tier.
    # The FAQ hook answers before the router runs, so a match here would replace a
    # live-device operation with a static docs answer. A prompt the admission guard
    # hands back to the router is not the FAQ's business at all.
    for uc in uc_prompts:
        if faqs.should_decline(uc["prompt"]):
            continue
        hit = cache.lookup(uc["prompt"])
        if hit is None:
            continue
        owner = str(hit.entry.id)
        if owner in accepted:
            rejected.setdefault(owner, []).append(
                f"alias would hijack {uc['id']} ({uc['prompt']!r})"
            )
            accepted.pop(owner, None)

    # Gate 7: no re-assignment. A probe that already resolved to a row must still
    # resolve to that SAME row once the aliases are in. Adding an alias only ever adds
    # tokens to the index, so a probe can change its winner but never lose its match;
    # when it does, the new winner is the row whose new alias stole it, and that row's
    # aliases are dropped and the check repeated.
    probes: List[str] = []
    for r in rows:
        probes.append(r.get("question_text") or "")
        probes.extend(r.get("aliases") or [])
    before: Dict[str, Optional[str]] = {}
    base_cache = build_cache(rows)
    for p in probes:
        if not p:
            continue
        hit = base_cache.lookup(p)
        before[p] = str(hit.entry.id) if hit is not None else None

    changed = True
    while changed and accepted:
        changed = False
        after_cache = build_cache(rows_with_aliases(rows, accepted))
        for p, owner_before in before.items():
            if owner_before is None:
                continue  # a probe that missed before may now match; that is the point
            hit = after_cache.lookup(p)
            owner_after = str(hit.entry.id) if hit is not None else None
            if owner_after == owner_before:
                continue
            culprit = owner_after if owner_after in accepted else owner_before
            if culprit not in accepted:
                continue
            rejected.setdefault(culprit, []).append(
                f"alias would steal the query {p!r} from another row"
            )
            accepted.pop(culprit, None)
            changed = True
            break
    return accepted, rejected


def baseline_hijacks(rows: Sequence[Dict], uc_prompts: Sequence[Dict]) -> Set[str]:
    """UC ids that the FAQ tier already answers before any alias is added."""
    cache = build_cache(rows)
    out = set()
    for uc in uc_prompts:
        if cache.lookup(uc["prompt"]) is not None:
            out.add(uc["id"])
    return out


# --------------------------------------------------------------------------- modes

def broken_alias_rows(rows: Sequence[Dict]) -> List[Dict]:
    """Live rows whose existing alias set does not resolve to their own row.

    The seed loader used to write machine-made aliases ("IR what", "why are my") that carry only
    generic words. Such an alias resolves to another row or to nothing, and it squats on queries:
    a stray "Setup my" was enough to stop another row from claiming its own question. These rows
    are the ones worth regenerating.
    """
    cache = build_cache(rows)
    out: List[Dict] = []
    for r in rows:
        aliases = list(r.get("aliases") or [])
        if not aliases:
            continue
        for a in aliases:
            hit = cache.lookup(a)
            if hit is None or str(hit.entry.id) != str(r["id"]):
                out.append(r)
                break
    return out


def select_targets(rows: Sequence[Dict], mode: str) -> List[Dict]:
    """The rows to work on.

    A live operation ("Lock stb3 for me") is never a target: the FAQ tier hands it to the router,
    so an alias on it buys nothing and only adds collision surface.
    """
    pool = [r for r in rows if not faqs.should_decline(r.get("question_text") or "")]
    if mode == "broken":
        return broken_alias_rows(pool)
    return [r for r in pool if not (r.get("aliases") or [])]


def cmd_generate(args) -> int:
    patch_table(args.table)
    rows = load_rows(args.table)
    targets = select_targets(rows, args.targets)
    if args.limit:
        targets = targets[: args.limit]
    print(
        f"faq_alias_backfill: {len(targets)} target rows ({args.targets}) "
        f"out of {len(rows)} live rows"
    )
    if not targets:
        return 0

    batches = [targets[i: i + args.batch] for i in range(0, len(targets), args.batch)]
    candidates: Dict[str, List[str]] = {}
    for i, batch in enumerate(batches, 1):
        if args.dry_run:
            print(f"--- batch {i}/{len(batches)} prompt ---\n{build_prompt(batch)}\n")
            continue
        prompt = build_prompt(batch)
        raw = _call_llm(prompt)
        for obj in _parse_jsonl(raw):
            rid = str(obj.get("id") or "").strip()
            al = obj.get("aliases") or []
            if rid and isinstance(al, list):
                candidates.setdefault(rid, []).extend(str(a) for a in al)
        print(f"batch {i}/{len(batches)}: {len(candidates)} rows with candidates so far", flush=True)

    if args.dry_run:
        return 0

    uc = read_usecases(Path(args.usecases))
    base_hijack = baseline_hijacks(rows, uc)
    accepted, rejected = validate_candidates(rows, candidates, uc, baseline_hijacked=base_hijack)

    out = Path(args.out)
    out.write_text(
        json.dumps(
            {
                "accepted": accepted,
                "rejected": rejected,
                "baseline_hijacked": sorted(base_hijack),
                "table": args.table,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    n_alias = sum(len(v) for v in accepted.values())
    print(f"accepted {n_alias} aliases on {len(accepted)} rows; {len(rejected)} rows with rejections")
    print(f"written to {out}")
    return 0


def cmd_apply(args) -> int:
    patch_table(args.table)
    payload = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    accepted: Dict[str, List[str]] = payload.get("accepted") or {}
    if not accepted:
        print("faq_alias_backfill: nothing to apply")
        return 0

    supabase = _client()
    rows = {str(r["id"]): r for r in load_rows(args.table)}
    broken_ids = {str(r["id"]) for r in broken_alias_rows(list(rows.values()))}
    applied = skipped = 0
    for rid, aliases in accepted.items():
        row = rows.get(str(rid))
        if row is None:
            print(f"  skip {rid}: row not live in {args.table}")
            skipped += 1
            continue
        current = list(row.get("aliases") or [])
        if current and str(rid) not in broken_ids:
            # never overwrite a healthy alias set
            print(f"  skip {rid}: already has {len(current)} aliases")
            skipped += 1
            continue
        if current and not args.replace:
            # the row's aliases are broken, but replacing them needs the explicit flag
            print(f"  skip {rid}: has {len(current)} broken aliases (use --replace to regenerate)")
            skipped += 1
            continue
        if args.dry_run:
            verb = "replace" if current else "set"
            print(f"  would {verb} {len(aliases)} aliases on {row.get('question_text')!r}")
            applied += 1
            continue
        supabase.table(args.table).update({"aliases": aliases}).eq("id", rid).execute()
        applied += 1
        print(f"  + {len(aliases)} aliases on {row.get('question_text')!r}")
    print(f"applied to {applied} rows, skipped {skipped}")
    return 0


def cmd_topup(args) -> int:
    """Generate, validate and apply in one run — the nightly job's mode.

    Safe to run every night: it only touches rows that have no aliases (or, with ``--replace``,
    rows whose aliases are broken), every candidate is validated before it is written, and the
    write touches the ``aliases`` column only.
    """
    args.generate = True
    args.out = args.candidates
    rc = cmd_generate(args)
    if rc != 0:
        return rc
    args.apply = True
    return cmd_apply(args)


def cmd_report(args) -> int:
    patch_table(args.table)
    rows = load_rows(args.table)
    with_alias = [r for r in rows if r.get("aliases")]
    without = [r for r in rows if not r.get("aliases")]
    print(f"live rows: {len(rows)} | with aliases: {len(with_alias)} | without: {len(without)}")

    cache = build_cache(rows)
    print(f"cache size (full corpus): {cache.size()}")

    uc = read_usecases(Path(args.usecases))
    hijacked = []
    for u in uc:
        hit = cache.lookup(u["prompt"])
        if hit is not None:
            hijacked.append({"uc": u["id"], "prompt": u["prompt"], "matched": hit.entry.question_text})
    print(f"use-case prompts: {len(uc)} | answered by the FAQ tier: {len(hijacked)}")
    for h in hijacked:
        print(f"  {h['uc']}: {h['prompt']!r} -> {h['matched']!r}")

    # alias self-resolution
    bad = []
    for r in with_alias:
        for a in r["aliases"]:
            hit = cache.lookup(a)
            if hit is None or str(hit.entry.id) != str(r["id"]):
                bad.append((r["question_text"], a))
    broken_rows = broken_alias_rows(rows)
    print(f"rows whose alias set is broken: {len(broken_rows)} of {len(with_alias)} with aliases")
    print(f"aliases that do not resolve to their own row: {len(bad)}")
    for q, a in bad[:20]:
        print(f"  {q!r} <- alias {a!r}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generate", action="store_true", help="call the LLM and produce candidate aliases")
    ap.add_argument("--apply", action="store_true", help="write the accepted aliases (aliases column only)")
    ap.add_argument("--topup", action="store_true",
                    help="generate + validate + apply in one run (the nightly job's mode)")
    ap.add_argument("--report", action="store_true", help="alias coverage + use-case hijack report")
    ap.add_argument("--targets", choices=("empty", "broken"), default="empty",
                    help="rows to work on: 'empty' (no aliases) or 'broken' (aliases that do not "
                         "resolve to their own row)")
    ap.add_argument("--replace", action="store_true",
                    help="allow replacing a BROKEN alias set (a healthy set is never replaced)")
    ap.add_argument("--candidates", default="/tmp/faq_alias_candidates.json")
    ap.add_argument("--out", default="/tmp/faq_alias_candidates.json")
    ap.add_argument("--table", default=agent_faq_db.FAQ_TABLE, help="target table (a copy, for the test run)")
    ap.add_argument("--usecases", default=str(USECASES_MD))
    ap.add_argument("--batch", type=int, default=8, help="questions per LLM call")
    ap.add_argument("--limit", type=int, default=0, help="only the first N rows (debug)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.topup:
        return cmd_topup(args)
    if args.generate:
        return cmd_generate(args)
    if args.apply:
        return cmd_apply(args)
    if args.report:
        return cmd_report(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
