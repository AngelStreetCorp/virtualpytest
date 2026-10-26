"""Atlas daily memory (TASK-172): a per-user, cross-session, written-down memory.

The Prepared FAQ (``faqs.py``) answers DOCS questions from a GLOBAL curated store: the same row for
every user, seeded from the repo's docs. This module is the other half of what an LLM-style memory
has — what *this user* asked and what *this user* got — kept **per user and per day** in a markdown
file that outlives the session.

The three properties the owner asked for, and where each one lives:

- **cross-session** — the memory is a file on disk, not a session attribute. ``session.py`` keeps
  conversations in an in-process dict that dies with the process; the memory does not.
- **user-scoped** — one directory per ``(team_id, user_id)``. No user id means no memory: a memory
  with no owner would be a global store, which is the FAQ's job, not this one's.
- **written down** — one markdown file per user per day, ``<root>/<team>/<user>/<YYYY-MM-DD>.md``,
  in the shape the owner described ("every day a memory ``.md``").

What is remembered, and what it costs
-------------------------------------
The default write is **deterministic**: the question, the tools that ran, the artefacts they
produced and the answer text. No model call, so the write costs **zero tokens** and takes the
microseconds of a file append. That is the whole reason the memory can be on by default for a user
who asks the same thing twice: remembering is free, *re-deriving* is what costs.

The retrieval is a **deterministic key match** first: the same ``normalize()`` the FAQ uses
(``faqs.normalize``) turns the question into a canonical key, and the key is looked up in the
user's memory files. A hit costs a file read (a few milliseconds). A miss costs a few milliseconds
and then falls through to the model, unchanged.

What this is NOT
----------------
- Not a summary of the conversation. The manager keeps the FULL history in the prompt
  (``manager.py``: "FULL conversation (no truncation, no summary)"); the rolling summary that used
  to be planned (``docs/agent/ai/agent_memory_strategy.md``) was never wired in.
- Not a source of truth. A memory can be stale — a device can have moved, a script can have been
  deleted, the owner can have reversed a decision. So a memory hit answers with a *recollection*,
  dated, and says so; it never claims that something happened just now.
- Not a secret store. No credentials, no customer identifiers, no transcripts: the entry holds the
  question, the tool names, the artefact ids and a truncated answer.

Switch: ``ATLAS_MEMORY=optin`` (default) | ``off`` | ``optin`` (on demand: only users with an ``.enabled``
marker, see ``set_enabled``) | ``on`` (everybody, minus users with a ``.disabled`` marker). The
markers live in the user's own directory, so a per-user switch needs no migration and no deploy.

Every public function fails soft: a memory problem must never break an Atlas turn.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# The canonical question key. Reuses the FAQ's normaliser on purpose: one normalisation rule in
# the product, one key space, and a question that hits the FAQ and a question that hits the memory
# are normalised the same way.
from . import faqs  # noqa: E402  (local import keeps the module importable on its own)

# Default root of the memory tree. ``ATLAS_MEMORY_DIR`` overrides it (the deploy sets it to a
# persistent path; a container's /tmp would lose the memory on restart). The default is OUTSIDE
# the repo: the files hold users' questions and answers, and a git checkout must never carry them
# (a stray ``git add`` would commit them, a deploy that cleans the tree would wipe them).
_DEFAULT_ROOT = Path.home() / ".virtualpytest" / "atlas_memory"

# How many days back a lookup reaches. A memory older than this is not offered: the world moves.
LOOKBACK_DAYS = 14
# How long a day file is kept on disk — 30 days at most (owner, 2026-10-25). The memory is a
# short-term working note, not an archive.
RETENTION_DAYS = 30
# The in-process index TTL. The index is a cache over the user's day files; a write invalidates it.
_INDEX_TTL_S = 60.0
# The answer is truncated before it is written. The memory is a pointer, not the transcript.
_ANSWER_MAX = 400
# The tool list is truncated for the same reason.
_TOOLS_MAX = 8
# A user id is a short opaque string. Anything longer is not a user id, it is an injection.
_MAX_ID_LEN = 128

_KEY_RE = re.compile(r"^- key:\s*(.*)$", re.MULTILINE)
_HEADING_RE = re.compile(r"^##\s+(\S+)\s*$", re.MULTILINE)


# The user ids that name nobody: the service key, open mode, auto-sign (HTTP and socket spellings)
# and the published server key resolve to the same id for everybody. A memory keyed on one of them
# would pool every caller's questions, so they get none.
SHARED_USER_IDS = frozenset({"service_api_key", "auto_sign", "auto_signed", "open_mode", "public_key"})


def _switch() -> str:
    # Default ``optin`` (owner, 2026-10-25): the memory exists only for the users who switch it on
    # from the AI agent page or Settings → AI. ``off`` removes it for everybody.
    return os.getenv("ATLAS_MEMORY", "optin").strip().lower()


def enabled() -> bool:
    """``ATLAS_MEMORY`` = ``optin`` (default) | ``off`` | ``on``. True unless it is off.

    Off by default because a memory changes what Atlas answers: a hit short-circuits the turn, so a
    stale entry can answer a question that needed a live check. ``optin`` is the on-demand mode
    (owner, 2026-10-25): the memory runs only for the users who switched it on for themselves
    (``set_enabled``), because the context mode spends prompt tokens. ``on`` is everybody.
    """
    return _switch() not in ("off", "0", "false", "no")


def opt_in_only() -> bool:
    """True in ``ATLAS_MEMORY=optin``: a user needs the ``.enabled`` marker."""
    return _switch() == "optin"


def memory_root() -> Path:
    """Where the memory tree lives."""
    return Path(os.getenv("ATLAS_MEMORY_DIR", str(_DEFAULT_ROOT))).expanduser()


def _safe_id(value: Optional[str]) -> str:
    """A filesystem-safe id. A user id goes into a path, so it is restricted to a safe alphabet."""
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))[:_MAX_ID_LEN]
    return cleaned


def user_dir(team_id: Optional[str], user_id: Optional[str]) -> Optional[Path]:
    """The directory that holds one user's memory files, or ``None`` when there is no user.

    Both ids are required. A memory is scoped to a ``(team, user)`` pair: without a team the
    same person on another team would read another team's memory, and without a user the memory
    would be global — which is the FAQ's job, not this one's.
    """
    if not team_id or not user_id or str(user_id) in SHARED_USER_IDS:
        return None
    return memory_root() / _safe_id(team_id) / _safe_id(user_id)


def enabled_for(team_id: Optional[str], user_id: Optional[str]) -> bool:
    """The env switch AND the per-user marker file.

    The per-user switch is a marker file inside the user's own directory, so it needs no
    migration, no deploy and no database write: ``.disabled`` turns the memory off for one user,
    and in ``optin`` mode ``.enabled`` is what turns it on.
    """
    if not enabled():
        return False
    directory = user_dir(team_id, user_id)
    if directory is None:
        return False
    if (directory / ".disabled").exists():
        return False
    if opt_in_only():
        return (directory / ".enabled").exists()
    return True


def question_key(text: str) -> str:
    """The canonical key of a question — the FAQ's ``normalize()``."""
    return faqs.normalize(text)


def _day_stamp(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def _now_stamp(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%H:%M:%SZ")


def day_path(team_id: Optional[str], user_id: Optional[str], day: Optional[str] = None) -> Optional[Path]:
    """The path of one user's memory file for one day."""
    directory = user_dir(team_id, user_id)
    if directory is None:
        return None
    return directory / f"{day or _day_stamp()}.md"


# --------------------------------------------------------------------------- the entry

@dataclass(frozen=True)
class MemoryEntry:
    """One remembered exchange."""

    question: str
    key: str
    ts: str                  # "HH:MM:SSZ" of the day the entry belongs to
    day: str                 # "YYYY-MM-DD"
    answer: str = ""
    tools: Tuple[str, ...] = ()
    artefacts: Tuple[str, ...] = ()

    def age_days(self, now: Optional[datetime] = None) -> int:
        try:
            when = datetime.strptime(self.day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return 0
        return max(0, ((now or datetime.now(timezone.utc)) - when).days)

    def render(self) -> str:
        """The answer text for a memory hit — dated, and never claiming anything happened now."""
        lines = [f'I remember this — you asked "{self.question}" on {self.day} at {self.ts}.']
        if self.tools:
            lines.append(f"What I did then: {', '.join(self.tools)}.")
        if self.artefacts:
            lines.append(f"Artefacts: {', '.join(self.artefacts)}.")
        if self.answer:
            lines.append(f"Answered then: {self.answer}")
        lines.append("This is a recollection from memory, not a fresh run — say \"again\" to run it now.")
        return "\n".join(lines)


# --------------------------------------------------------------------------- the write

_ARTEFACT_FIELDS = (
    "script_id", "virtual_script_id", "userinterface_id", "device_id", "host_name", "script_name",
    "userinterface_name", "page_id", "tree_id", "name", "id",
)
# The ids an MCP tool reports in its text answer ("created (id 3f2a…)", '"userinterface_id": "…"').
# Most tools return {"content": [{"type": "text", ...}]} with the id only in the text, so without
# this the entry of a created script or userinterface would name nothing.
_TEXT_ID_RE = re.compile(
    r'["\']?\b([a-z_]*id)\b["\']?\s*[:=( ]\s*["\']?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
    re.IGNORECASE,
)


def _artefacts_from(params: Optional[dict], result: Optional[object]) -> List[str]:
    """The ids worth remembering: what was acted on, and what came back.

    Deliberately shallow — a flat ``name=value`` list. Anything deeper would bloat the file, and
    the file is read on every turn.
    """
    found: List[str] = []
    seen = set()

    def _add(key: str, value: object) -> None:
        if value in (None, "", []):
            return
        text = str(value)
        if len(text) > 120:
            return
        token = f"{key}={text}"
        if token not in seen:
            seen.add(token)
            found.append(token)

    if isinstance(params, dict):
        for field_name in _ARTEFACT_FIELDS:
            if field_name in params:
                _add(field_name, params.get(field_name))
    if isinstance(result, dict):
        for field_name in _ARTEFACT_FIELDS:
            if field_name in result:
                _add(field_name, result.get(field_name))
        for block in result.get("content") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                for key, value in _TEXT_ID_RE.findall(block["text"])[:4]:
                    _add(key.lower(), value)
    return found[:12]


def _render_entry(question: str, key: str, ts: str, answer: str,
                  tools: Iterable[str], artefacts: Iterable[str]) -> str:
    """The markdown block of one entry. One heading, four bullet lines, no prose."""
    tool_list = [t for t in tools][:_TOOLS_MAX]
    artefact_list = list(artefacts)[:12]
    lines = [
        f"## {ts}",
        f"- question: {question.strip()[:200]}",
        f"- key: {key}",
    ]
    if tool_list:
        lines.append(f"- tools: {', '.join(tool_list)}")
    if artefact_list:
        lines.append(f"- artefacts: {', '.join(artefact_list)}")
    if answer:
        lines.append(f"- answer: {answer.strip()[:_ANSWER_MAX]}")
    return "\n".join(lines) + "\n"


def record(*, team_id: Optional[str], user_id: Optional[str], question: str, answer: str,
           tools: Optional[Iterable[str]] = None, artefacts: Optional[Iterable[str]] = None,
           now: Optional[datetime] = None) -> Optional[Path]:
    """Append one entry to today's memory file. Returns the path written, or ``None``.

    Never raises. A memory problem must not break the turn that produced it.
    """
    try:
        if not enabled_for(team_id, user_id):
            return None
        key = question_key(question)
        if not key:
            return None
        day = _day_stamp(now)
        path = day_path(team_id, user_id, day)
        if path is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = _now_stamp(now)
        block = _render_entry(question, key, stamp, answer, tools or (), artefacts or ())
        header = ""
        if not path.exists():
            header = (f"# Atlas memory — {day}\n\n"
                      f"<!-- per-user memory; the same question key recalls the last entry -->\n\n")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(header + block)
        _invalidate(team_id, user_id)
        if header:
            # A new day file is the moment to drop the ones past the retention: once a day per
            # user, on the write path, so nothing else has to schedule it.
            prune(team_id, user_id, now)
        return path
    except Exception as exc:  # noqa: BLE001 - a memory write never breaks a turn
        logger.warning("atlas memory write failed: %s", exc)
        return None


# --------------------------------------------------------------------------- the read

def _parse_entries(text: str, day: str) -> List[MemoryEntry]:
    """Parse one day file into entries.

    The format is deliberately trivial to parse: a ``## <ts>`` heading, then ``- key:``,
    ``- question:``, ``- tools:``, ``- artefacts:``, ``- answer:`` bullets.
    """
    entries: List[MemoryEntry] = []
    if not text:
        return entries
    chunks = re.split(r"^##\s+", text, flags=re.MULTILINE)
    for chunk in chunks[1:]:
        lines = chunk.splitlines()
        if not lines:
            continue
        ts = lines[0].strip().split()[0] if lines[0].strip() else ""
        key = ""
        question = ""
        answer = ""
        tools: Tuple[str, ...] = ()
        artefacts: Tuple[str, ...] = ()
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("- key:"):
                key = line[len("- key:"):].strip()
            elif line.startswith("- question:"):
                question = line[len("- question:"):].strip()
            elif line.startswith("- tools:"):
                tools = tuple(t.strip() for t in line[len("- tools:"):].split(",") if t.strip())
            elif line.startswith("- artefacts:"):
                artefacts = tuple(t.strip() for t in line[len("- artefacts:"):].split(",") if t.strip())
            elif line.startswith("- answer:"):
                answer = line[len("- answer:"):].strip()
        if key:
            entries.append(MemoryEntry(question=question or key, key=key, ts=ts, day=day,
                                       answer=answer, tools=tools, artefacts=artefacts))
    return entries


_index_lock = threading.Lock()
_index: Dict[Tuple[str, str, str], Tuple[float, Dict[str, MemoryEntry]]] = {}


def _index_key(team_id: Optional[str], user_id: Optional[str]) -> Tuple[str, str, str]:
    """The cache key. The root is part of it: the root can change (``ATLAS_MEMORY_DIR``), and a
    cache that survived the change would serve another tree's memories."""
    return (str(memory_root()), _safe_id(team_id), _safe_id(user_id))


def _invalidate(team_id: Optional[str], user_id: Optional[str]) -> None:
    with _index_lock:
        _index.pop(_index_key(team_id, user_id), None)


def _candidate_days(now: Optional[datetime] = None) -> List[str]:
    today = (now or datetime.now(timezone.utc)).date()
    return [(today - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(LOOKBACK_DAYS)]


def _load_index(team_id: Optional[str], user_id: Optional[str],
                now: Optional[datetime] = None) -> Dict[str, MemoryEntry]:
    """Every entry of the user's memory files, keyed by the question key.

    The index is a cache over the day files: it is rebuilt when it is older than the TTL, when a
    write lands, or when the files change. It is per user, so it holds one user's memories only.
    """
    cache_key = _index_key(team_id, user_id)
    now_ts = time.time()
    with _index_lock:
        cached = _index.get(cache_key)
        if cached and (now_ts - cached[0]) < _INDEX_TTL_S:
            return cached[1]

    directory = user_dir(team_id, user_id)
    if directory is None:
        return {}
    entries: Dict[str, MemoryEntry] = {}
    try:
        # Oldest day first, and within a day the later entry overwrites the earlier one, so the
        # plain assignment leaves the NEWEST write of a question in the index.
        for day in reversed(_candidate_days(now)):
            path = directory / f"{day}.md"
            if not path.exists():
                continue
            for entry in _parse_entries(path.read_text(encoding="utf-8"), day):
                entries[entry.key] = entry
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory read failed: %s", exc)
        return {}
    with _index_lock:
        _index[cache_key] = (now_ts, entries)
    return entries


def lookup(team_id: Optional[str], user_id: Optional[str], question: str,
           now: Optional[datetime] = None) -> Optional[MemoryEntry]:
    """The entry for this exact question, or ``None``.

    Exact key match only. A paraphrase is a miss: a wrong memory is worse than no memory, because
    the answer would be about something the user did not ask.
    """
    try:
        if not enabled_for(team_id, user_id):
            return None
        key = question_key(question)
        if not key:
            return None
        entries = _load_index(team_id, user_id, now)
        entry = entries.get(key)
        if entry is None:
            return None
        if entry.age_days(now) > LOOKBACK_DAYS:
            return None
        return entry
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory lookup failed: %s", exc)
        return None


def forget(team_id: Optional[str], user_id: Optional[str]) -> int:
    """Delete every memory file of one user. Returns the number of files removed.

    The owner asked for the memory to be able to be switched off; this is the same lever for one
    user, taken to its end. It touches only that user's directory.
    """
    directory = user_dir(team_id, user_id)
    if directory is None or not directory.exists():
        return 0
    removed = 0
    try:
        for path in directory.glob("*.md"):
            path.unlink()
            removed += 1
        # The memory log holds the questions too.
        log = directory / "memory.log.jsonl"
        if log.exists():
            log.unlink()
        _invalidate(team_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory forget failed: %s", exc)
    return removed


def set_enabled(team_id: Optional[str], user_id: Optional[str], enabled_: bool = True) -> bool:
    """Switch the memory on (or off) for one user, on demand.

    On writes ``.enabled`` and clears ``.disabled``; off does the reverse. In ``optin`` mode this
    is the only way a user gets a memory.
    """
    directory = user_dir(team_id, user_id)
    if directory is None:
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        on_marker, off_marker = directory / ".enabled", directory / ".disabled"
        keep, drop = (on_marker, off_marker) if enabled_ else (off_marker, on_marker)
        keep.write_text("on\n", encoding="utf-8")
        if drop.exists():
            drop.unlink()
        _invalidate(team_id, user_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory toggle failed: %s", exc)
        return False


def set_disabled(team_id: Optional[str], user_id: Optional[str], disabled: bool = True) -> bool:
    """Turn the memory off (or back on) for one user. Writes the ``.disabled`` marker."""
    directory = user_dir(team_id, user_id)
    if directory is None:
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / ".disabled"
        if disabled:
            marker.write_text("disabled by the owner\n", encoding="utf-8")
        elif marker.exists():
            marker.unlink()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory toggle failed: %s", exc)
        return False


def prune(team_id: Optional[str], user_id: Optional[str], now: Optional[datetime] = None) -> int:
    """Delete the day files older than the retention. Returns the number of files removed."""
    directory = user_dir(team_id, user_id)
    if directory is None or not directory.exists():
        return 0
    cutoff = ((now or datetime.now(timezone.utc)).date() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
    removed = 0
    try:
        for path in directory.glob("*.md"):
            if path.stem < cutoff:
                path.unlink()
                removed += 1
        if removed:
            _invalidate(team_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory prune failed: %s", exc)
    return removed


def status(team_id: Optional[str], user_id: Optional[str]) -> dict:
    """What the AI agent page and Settings → AI show for one user. Never raises."""
    info = {
        "available": False, "reason": "", "enabled": False, "switch": _switch(),
        "retention_days": RETENTION_DAYS, "lookback_days": LOOKBACK_DAYS, "days": 0, "entries": 0,
        "recalls": 0,
    }
    try:
        if not enabled():
            info["reason"] = "off"
            return info
        directory = user_dir(team_id, user_id)
        if directory is None:
            info["reason"] = "no_user"
            return info
        info["available"] = True
        info["enabled"] = enabled_for(team_id, user_id)
        if directory.exists():
            files = list(directory.glob("*.md"))
            info["days"] = len(files)
            info["entries"] = sum(len(_parse_entries(f.read_text(encoding="utf-8"), f.stem)) for f in files)
            info["recalls"] = _recall_count(directory)
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory status failed: %s", exc)
    return info


def _recall_count(directory: Path) -> int:
    """How many times this user's memory answered within the retention (from memory.log.jsonl)."""
    log = directory / "memory.log.jsonl"
    if not log.exists():
        return 0
    cutoff = time.time() - RETENTION_DAYS * 86400
    count = 0
    try:
        import json
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("source") == "memory_recall" and float(row.get("ts") or 0) >= cutoff:
                count += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory recall count failed: %s", exc)
    return count


def forget_key(team_id: Optional[str], user_id: Optional[str], key: str) -> int:
    """Drop every entry of one question key from the user's day files. Returns the entries removed."""
    directory = user_dir(team_id, user_id)
    if directory is None or not directory.exists() or not key:
        return 0
    removed = 0
    try:
        for path in directory.glob("*.md"):
            entries = _parse_entries(path.read_text(encoding="utf-8"), path.stem)
            keep = [e for e in entries if e.key != key]
            if len(keep) == len(entries):
                continue
            removed += len(entries) - len(keep)
            if not keep:
                path.unlink()
                continue
            text = (f"# Atlas memory — {path.stem}\n\n"
                    f"<!-- per-user memory; the same question key recalls the last entry -->\n\n")
            text += "".join(_render_entry(e.question, e.key, e.ts, e.answer, e.tools, e.artefacts) for e in keep)
            path.write_text(text, encoding="utf-8")
        _invalidate(team_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas memory forget_key failed: %s", exc)
    return removed
