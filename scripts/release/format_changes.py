#!/usr/bin/env python3
"""Render a release-note build section as collapsed groups for a GitHub release page.

A build section is 400 lines of dense paragraphs; nobody reads that to find out whether a
release affects them. Each bullet becomes a <details> whose summary is the title plus its bug
id and migration marker, so the section scans as a list and opens where it matters.

Extracted from delivery_note.sh so the platform release and the customer delivery note render
the same way from one implementation -- they had started to diverge the moment the platform
needed its own release body.

stdin: the raw build section(s). stdout: markdown + HTML for a release body.
"""
import re, sys

# A delivery can span several builds, each with its own Features / Bug fixes / Security
# subsections. Kept per build, the same three headings repeat and the reader has to stitch them
# together to answer "what security work is in this?". Merged into three groups instead, each a
# collapsed section over collapsed items.
GROUPS = [("features", "Features"), ("bugs", "Bug fixes"), ("security", "Security")]
buckets = {k: [] for k, _ in GROUPS}
group, cur = "features", None

def flush():
    global cur
    if not cur: return
    title, body = cur[0], cur[1].strip()
    bug = commit = task = None
    kept = []
    for seg in body.split(" · "):
        t = seg.strip()
        m = re.fullmatch(r"\[(BUG-\d+)\]\([^)]*\)", t)
        if m: bug = bug or m.group(1); continue
        if re.fullmatch(r"`[0-9a-f]{7,40}`", t) or t == "`this commit`":
            commit = commit or t.strip("`"); continue
        m = re.fullmatch(r"(TASK-\d+)", t)
        if m: task = task or m.group(1); continue
        kept.append(seg)
    body = " · ".join(kept).strip()
    badges = [b for b in (task, "🗄 migration" if "DB migration" in body else None) if b]
    head = "<b>%s</b>" % title
    if bug: head = "<b>%s</b> — %s" % (bug, title)
    if commit and commit != "this commit": head += " — <code>%s</code>" % commit
    if badges: head += " — <sub>%s</sub>" % " · ".join(badges)
    if body:
        buckets[group].extend(["<details>", "<summary>%s</summary>" % head, "", body, "", "</details>", ""])
    else:
        buckets[group].append("- %s" % head)
    cur = None

for line in sys.stdin.read().splitlines():
    if line.startswith("#"):
        flush()
        h = line.lstrip("# ").strip()
        if "security" in h.lower(): group = "security"
        elif "bug" in h.lower(): group = "bugs"
        elif "feature" in h.lower(): group = "features"
        continue
    m = re.match(r"^\s*-\s+\*\*(.+?)\*\*\s*[—-]?\s*(.*)$", line)
    if m:
        flush(); cur = [m.group(1), m.group(2)]
    elif re.match(r"^\s*-\s+\S", line):
        flush(); cur = [re.sub(r"^\s*-\s+", "", line)[:80], ""]
    elif not line.strip():
        flush()
    elif cur is not None:
        cur[1] += " " + line.strip()
flush()

out = []
for key, label in GROUPS:
    items = [x for x in buckets[key] if x.strip()]
    n = sum(1 for x in buckets[key] if x.startswith("<summary>") or x.startswith("- "))
    if not n: continue
    out += ["<details>", "<summary><h2>%s — %d</h2></summary>" % (label, n), ""]
    out += buckets[key]
    out += ["</details>", ""]
print("\n".join(out))
