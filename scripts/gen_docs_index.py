#!/usr/bin/env python3
"""
Single source of truth for the agent-docs index.

Per-doc YAML frontmatter (title / summary / tags / keywords) is the ONLY thing
humans edit. This script derives everything else from it:

  1. Injects frontmatter into agent docs that lack it (idempotent — never
     clobbers existing frontmatter; skips the 2 frontend-shipped ai/ docs).
  2. Regenerates each topic folder's README.md table.
  3. Emits docs/agent/INDEX.md   — markdown routing table for the query-docs
     skill (read_doc only accepts .md) and any agent.
  4. Emits docs/agent/INDEX.json — machine manifest (adds size_kb, updated
     git date, and an H2 outline per doc for section-targeted reading).

Conventions the index enforces:
  - tags containing `artifact` = point-in-time report → kept out of the
    routing tables (INDEX.md), flagged in the folder README, still present
    in INDEX.json with "artifact": true.
  - docs > 25 KB get a ⚠ size marker in INDEX.md: grep or target a section
    instead of reading the whole file.

Usage:
    python3 scripts/gen_docs_index.py                     # regenerate
    python3 scripts/gen_docs_index.py --regen-frontmatter # re-derive all frontmatter
    python3 scripts/gen_docs_index.py --check             # CI: exit 1 if outputs are stale
"""
import os, re, json, glob, sys, subprocess
from collections import Counter

FORCE = "--regen-frontmatter" in sys.argv
CHECK = "--check" in sys.argv

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS = os.path.join(REPO, "docs")
AGENT = os.path.join(DOCS, "agent")
BIG_KB = 25  # ⚠ threshold: above this, tell agents to grep/target sections

TOPIC = {
    "navigation": ("Navigation & UserInterface",
        "Navigation trees, the UserInterface data model, named variants, and the AI-learned UI knowledge base."),
    "validation": ("Validation & Testing",
        "Validating interfaces, diagnosing validation failures, fixing locator/verification drift, and the hidden test contracts."),
    "devices": ("Devices & Capture",
        "Driving physical devices (IR / BLE / ADB / Playwright), AV capture & streaming, screenshots, and image verification."),
    "execution": ("Execution & KPIs",
        "Running scripts and campaigns, scheduled runs, runner hosts, and end-to-end KPI measurement."),
    "infra": ("Infrastructure & Ops",
        "Deployment, CI/CD, host Linux services, Grafana, database, CPU partitioning, and VM topology."),
    "platform": ("Platform & Admin",
        "Cross-cutting concerns — organisations, users & permissions, workspaces, server auth, UI/UX, and AVQ."),
    "ai": ("AI Agent System",
        "The AI agent architecture — skills, memory, tool caching & auto-generation, Socket.IO, observability, and benchmarking."),
    "testgen": ("AI Test Generation",
        "AI-driven generation of deterministic test cases (graph_json) that run with zero AI tokens at runtime — pipeline phases, per-platform guides, and the roadmap."),
    "release": ("Release & Shipping",
        "Cutting a release/version tag, anonymizing client identifiers before anything goes public, and packaging offline customer update bundles."),
}

# docs/agent/ is excluded wholesale from the public frontend build (see
# frontend/scripts/copy-docs.sh) — nothing here ships to the public site, so there's
# no longer a "these 2 files get shipped raw" special case to carve out.
SKIP_FRONTMATTER = set()

STOP = {"the","a","an","and","or","of","to","for","in","on","with","how","via",
        "docs","agent","md","guide","reference","index","vpt","virtualpytest"}

stale = []  # --check findings


def rel(p):
    return os.path.relpath(p, DOCS)


def emit(relpath, content):
    """Write a generated file — or, in --check mode, diff against disk."""
    full = os.path.join(DOCS, relpath)
    if CHECK:
        on_disk = open(full, encoding="utf-8").read() if os.path.exists(full) else None
        if on_disk != content:
            stale.append(relpath)
        return
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w", encoding="utf-8").write(content)


def git_date(relpath):
    """Last commit date (YYYY-MM-DD) of a doc; 'new' if untracked/uncommitted."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%as", "--", os.path.join("docs", relpath)],
            capture_output=True, text=True, cwd=os.path.dirname(DOCS), timeout=10,
        ).stdout.strip()
        return out or "new"
    except Exception:
        return "?"


def split_frontmatter(text):
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    raw, body = text[4:end], text[end + 5:]
    fm = {}
    for line in raw.splitlines():
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
        else:
            fm[k] = v.strip('"').strip("'")
    return fm, body


def extract_h1(body):
    infence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            infence = not infence
            continue
        if not infence and s.startswith("# "):
            return s[2:].strip()
    return None


def extract_outline(body, limit=15):
    """H2 headings — lets an agent pick a section and grep for it instead of reading whole."""
    out = []
    infence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            infence = not infence
            continue
        if not infence and s.startswith("## "):
            out.append(re.sub(r"[#*`]", "", s[3:]).strip()[:80])
            if len(out) >= limit:
                break
    return out


def extract_summary(body):
    seen_h1 = False
    para = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# ") and not seen_h1:
            seen_h1 = True
            continue
        if not seen_h1:
            continue
        if not s:
            if para:
                break
            continue
        if s.startswith("```") or s.startswith("---") or s[0] in "#>|-*":
            if para:
                break
            continue  # note: a leading `inline code` backtick is valid prose, not skipped
        para.append(s)
    text = " ".join(para)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*`]", "", text)
    m = re.search(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text).strip()[:200]


def derive_keywords(path, title, body):
    """Filename + title tokens, enriched with the doc's most frequent acronyms."""
    kws = []
    src = os.path.splitext(os.path.basename(path))[0] + " " + (title or "")
    for tok in re.split(r"[^A-Za-z0-9]+", src):
        t = tok.lower()
        if len(t) > 2 and t not in STOP and t not in kws:
            kws.append(t)
    for acro, _ in Counter(re.findall(r"\b[A-Z]{2,5}\b", body)).most_common(8):
        a = acro.lower()
        if a not in STOP and a not in kws:
            kws.append(a)
    return kws[:10]


def topic_of(relpath):
    parts = relpath.split("/")
    if relpath.startswith("agent/") and len(parts) >= 3:
        return parts[1]
    return "root"


def dump_fm(fm):
    def y(v):
        return "[" + ", ".join(v) + "]" if isinstance(v, list) else v
    lines = ["---"] + [f"{k}: {y(fm[k])}" for k in ("title", "summary", "tags", "keywords") if k in fm] + ["---"]
    return "\n".join(lines) + "\n\n"


def doc_cell(e, link):
    """Doc cell for a table row: link + size warning when the doc is heavy."""
    cell = f"[{os.path.basename(e['path'])}]({link})"
    if e["size_kb"] > BIG_KB:
        cell += f" ⚠{e['size_kb']}KB"
    return cell


# ---- collect candidates ----
# Git-ignored docs are deliberately local-only: docs/agent/infra/ and friends describe one
# private deployment and never reach the repo (the public snapshot is `git archive`, so
# untracked cannot ship). Indexing them would route every other clone — and every public
# reader — to a file they do not have. Ask git once, in bulk, rather than per file.
def _internal_paths():
    """Prefixes publish_public.sh strips from the export — tracked, but never public."""
    f = os.path.join(REPO, "scripts", "security", "internal-paths.txt")
    try:
        return [l.strip() for l in open(f, encoding="utf-8")
                if l.strip() and not l.lstrip().startswith("#")]
    except OSError:
        return []


def _ignored(paths):
    if not paths:
        return set()
    try:
        r = subprocess.run(["git", "check-ignore", "--stdin", "-z"],
                           input="\0".join(paths), capture_output=True, text=True, cwd=REPO)
    except OSError:
        return set()          # no git available: index everything, as before
    if r.returncode not in (0, 1):
        return set()          # 0 = some ignored, 1 = none ignored; anything else is an error
    return {x for x in r.stdout.split("\0") if x}

candidates = []
for p in sorted(glob.glob(os.path.join(AGENT, "**", "*.md"), recursive=True)):
    bn = os.path.basename(p)
    if bn.lower() == "readme.md" or bn == "INDEX.md":
        continue
    candidates.append(p)

_rels = [os.path.relpath(p, REPO) for p in candidates]
_skipped = _ignored(_rels)
# Same reasoning for internal-paths: those docs are tracked, so every internal clone has
# them, but the public snapshot deletes them — routing a public reader there is a dead link.
_deny = _internal_paths()
_skipped |= {r for r in _rels if any(r.startswith(d) for d in _deny)}
if _skipped:
    candidates = [p for p in candidates if os.path.relpath(p, REPO) not in _skipped]
    print(f"skipped {len(_skipped)} doc(s) not in the public snapshot (git-ignored or internal-path)")

# ---- Pass 1: inject frontmatter where missing (skipped in --check) ----
injected = 0
if not CHECK:
    for p in candidates:
        r = rel(p)
        if r in SKIP_FRONTMATTER:
            continue
        text = open(p, encoding="utf-8").read()
        fm, body = split_frontmatter(text)
        if fm is not None and not FORCE:
            continue
        h1 = extract_h1(body) or os.path.splitext(os.path.basename(p))[0]
        new_fm = {
            "title": h1,
            "summary": extract_summary(body) or h1,
            "tags": (fm or {}).get("tags") if (fm and "artifact" in (fm.get("tags") or [])) else ["agent", topic_of(r)],
            "keywords": derive_keywords(p, h1, body),
        }
        open(p, "w", encoding="utf-8").write(dump_fm(new_fm) + body)
        injected += 1
    print(f"frontmatter injected into {injected} docs (skipped {len(SKIP_FRONTMATTER)} shipped)")
else:
    for p in candidates:  # --check: a doc missing frontmatter is itself drift
        if rel(p) in SKIP_FRONTMATTER:
            continue
        if not open(p, encoding="utf-8").read().startswith("---\n"):
            stale.append(rel(p) + "  (missing frontmatter)")

# ---- Pass 2: metadata per doc ----
entries = []
for p in candidates:
    r = rel(p)
    text = open(p, encoding="utf-8").read()
    fm, body = split_frontmatter(text)
    if fm:
        title = fm.get("title") or extract_h1(body) or r
        summary = fm.get("summary") or extract_summary(body)
        tags = fm.get("tags") if isinstance(fm.get("tags"), list) else ["agent", topic_of(r)]
        keywords = fm.get("keywords") if isinstance(fm.get("keywords"), list) else []
    else:
        title = extract_h1(body) or r
        summary = extract_summary(body)
        tags = ["agent", topic_of(r)]
        keywords = derive_keywords(p, title, body)
    entries.append({
        "path": r, "title": title, "summary": summary, "tags": tags,
        "keywords": keywords, "topic": topic_of(r),
        "size_kb": round(os.path.getsize(p) / 1024),
        "updated": git_date(r),
        "outline": extract_outline(body),
        "artifact": "artifact" in tags,
    })

# ---- regenerate topic folder READMEs ----
for topic, (title, blurb) in TOPIC.items():
    rows = [e for e in entries if e["topic"] == topic]
    if not rows:
        continue
    body = [f"# Agent Docs — {title}", "", blurb, "",
            "| Doc | What it covers |", "|---|---|"]
    for e in sorted(rows, key=lambda x: x["path"]):
        link = os.path.relpath(e["path"], f"agent/{topic}")
        if e["artifact"]:
            body.append(f"| [{os.path.basename(e['path'])}]({link}) ⚠ {e['size_kb']}KB artifact | "
                        f"Point-in-time report — do NOT read whole; open only when a human asks for it. |")
        else:
            body.append(f"| {doc_cell(e, link)} | {e['summary']} |")
    body += ["", "---", "← [Agent docs index](../README.md) · [full INDEX](../INDEX.md)", ""]
    emit(f"agent/{topic}/README.md", "\n".join(body))

# ---- INDEX.md (routing table; artifacts excluded) ----
md = ["# Agent Docs — Full Index",
      "",
      "> Generated by `scripts/gen_docs_index.py` from each doc's frontmatter. Do not edit by hand.",
      "> Route here in one hop; `search_docs(query=…)` also matches the `keywords` below.",
      f"> Docs marked ⚠ are large — grep or target a section from its outline (INDEX.json) instead of reading whole.",
      ""]
routing = [e for e in entries if not e["artifact"]]
root_rows = [e for e in routing if e["topic"] == "root"]
if root_rows:
    md += ["## Cross-cutting (agent/)", "", "| Doc | Summary | Keywords |", "|---|---|---|"]
    for e in sorted(root_rows, key=lambda x: x["path"]):
        md.append(f"| {doc_cell(e, os.path.relpath(e['path'], 'agent'))} | {e['summary']} | {', '.join(e['keywords'][:6])} |")
    md.append("")
for topic, (title, _blurb) in TOPIC.items():
    rows = [e for e in routing if e["topic"] == topic]
    if not rows:
        continue
    md += [f"## {title} (agent/{topic}/)", "", "| Doc | Summary | Keywords |", "|---|---|---|"]
    for e in sorted(rows, key=lambda x: x["path"]):
        md.append(f"| {doc_cell(e, os.path.relpath(e['path'], 'agent'))} | {e['summary']} | {', '.join(e['keywords'][:6])} |")
    md.append("")
md += ["---", "← [Agent docs index](README.md)", ""]
emit("agent/INDEX.md", "\n".join(md))

# ---- INDEX.json (machine manifest; artifacts included but flagged) ----
manifest = {
    "generated_by": "scripts/gen_docs_index.py",
    "note": "Source of truth is each doc's YAML frontmatter. Regenerate; do not hand-edit.",
    "count": len(entries),
    "docs": [{"path": f"docs/{e['path']}", "title": e["title"], "summary": e["summary"],
              "tags": e["tags"], "keywords": e["keywords"], "size_kb": e["size_kb"],
              "updated": e["updated"], "outline": e["outline"], "artifact": e["artifact"]}
             for e in sorted(entries, key=lambda x: x["path"])],
}
emit("agent/INDEX.json", json.dumps(manifest, indent=2) + "\n")

if CHECK:
    if stale:
        print("STALE — regenerate with: python3 scripts/gen_docs_index.py")
        for s in stale:
            print("  ", s)
        sys.exit(1)
    print("index up to date")
else:
    big = [e for e in entries if e["size_kb"] > BIG_KB and not e["artifact"]]
    print(f"indexed {len(entries)} docs -> agent/INDEX.md, agent/INDEX.json, {len(TOPIC)} folder READMEs")
    print(f"  {len(big)} docs >{BIG_KB}KB flagged ⚠; {sum(e['artifact'] for e in entries)} artifact(s) excluded from routing")
