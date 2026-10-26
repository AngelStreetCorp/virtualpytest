"""The deploy script's usage block must agree with the deploy script's own code.

`update_core.sh --help` prints a usage block, and an operator reads it before touching
the fleet. Its `--skip-leased` entry used to say that a host another agent has leased is
dropped (`SKIPPED (leased by <agent>): <host>`), while the script does something else: a
leased host of this run is synced without a lease and only its `vpt-host` restart is
deferred - the script prints `SYNC ONLY (leased by <agent>): <host>` and puts the host in
`SKIPPED_HOSTS` so the deploy runner queues a catch-up deploy. Only a leased host that is
NOT part of this run (a Windows host, a secondary server) is dropped.

A usage block that lies is worse than no usage block: the operator reads `--help` and
takes a decision the script will not honour. The wording will be reworded again - the
day it is, a test that asserted one exact sentence is dead - so nothing here compares the
usage block with a hard-coded sentence. Each check holds the script's own words against
the script's own code:

- the code prints `SYNC ONLY` -> the usage block mentions `SYNC ONLY`;
- the code syncs a leased host and defers its restart -> the `--skip-leased` entry says
  so, and the drop it mentions is scoped to a host that is not part of this run;
- the code has the `DROPPED_HOSTS` path -> the `--hosts` entry says the unknown name is
  dropped with a WARNING, and does not abort the deploy on one unknown name.

Pure unit: the script is read as text. Nothing is executed, no node is contacted, no
fleet identifier appears here.
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = PROJECT_ROOT / "setup" / "proxmox" / "node" / "update_core.sh"

pytestmark = pytest.mark.unit

# The heredoc that usage() prints.
USAGE_RE = re.compile(
    r"usage\(\)\s*\{\s*\n\s*cat\s*<<'(?P<tag>[A-Za-z_][A-Za-z0-9_]*)'\n"
    r"(?P<body>.*?)\n(?P=tag)\n",
    re.S,
)

# An option documented in the usage block: the flag at the start of the line.
ENTRY_RE = re.compile(r"^[ \t]{2,}(?P<flag>--[A-Za-z0-9][A-Za-z0-9-]*)\b")

# Words that scope a statement to one case ("not part of this run", "outside this run").
# Matched on word boundaries: "another agent" is not a "not".
SCOPING_WORDS = (r"\bnot\b", r"\bexcept\b", r"\boutside\b", r"\bother than\b", r"\bbeyond\b")

# Words that scope an abort to a set of names ("only if EVERY name is unknown").
QUANTIFIERS = (r"\bonly\b", r"\bevery\b", r"\ball\b", r"\bunless\b")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _usage_block(script_text: str) -> str:
    """The text `--help` prints."""
    match = USAGE_RE.search(script_text)
    assert match, "update_core.sh has no usage() heredoc to check"
    return match.group("body")


def _usage_entries(body: str) -> dict:
    """{flag: the text that documents it} for every option in the usage block.

    An option's text is its own line plus the wrapped lines below it: the lines that
    follow it and are indented deeper than it is. The deeper indent is what separates a
    wrapped option from the next line of the usage block.

    A flag can also be mentioned in passing elsewhere in the usage block (the DOCKER_IPS
    bullet names --hosts and --skip-hosts on their way to something else). The fullest
    documentation of a flag is the one that has to agree with the code, so the longest
    entry for a flag wins.
    """
    entries = {}
    lines = body.split("\n")
    index = 0
    while index < len(lines):
        match = ENTRY_RE.match(lines[index])
        if not match:
            index += 1
            continue
        chunk = [lines[index]]
        following = index + 1
        while following < len(lines):
            candidate = lines[following]
            if not candidate.strip() or _indent(candidate) <= _indent(lines[index]):
                break
            if ENTRY_RE.match(candidate):
                break
            chunk.append(candidate)
            following += 1
        text = "\n".join(chunk)
        flag = match.group("flag")
        if flag not in entries or len(text) > len(entries[flag]):
            entries[flag] = text
        index = following
    return entries


def _clauses(text: str) -> list:
    """The entry split into the statements it makes.

    A statement ends at a ';' or at the end of a sentence - that is where the entry
    moves from one case to the next.
    """
    return [part for part in re.split(r";|(?<=\.)\s+", text) if part.strip()]


def _usage_units(body: str) -> list:
    """The usage block split into the statements it makes.

    An option's documented text is one statement: its own line plus the wrapped
    lines below it. Every other line is a statement of its own - two example lines
    are two statements.

    The unit matters: a clause split over the whole block merges the example list
    into a single clause, and then one word in one example line ('except', from
    '--skip-hosts ... everything except one host') would scope a statement in a
    different example line, and a stale line would slip through unscoped. The
    wrapped lines of an option are the one case where the lines belong together,
    and the option entry check below already reads them as one text.
    """
    units = []
    lines = body.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        chunk = [line]
        following = index + 1
        if ENTRY_RE.match(line):
            while following < len(lines):
                candidate = lines[following]
                if not candidate.strip() or _indent(candidate) <= _indent(line):
                    break
                if ENTRY_RE.match(candidate):
                    break
                chunk.append(candidate)
                following += 1
        units.append("\n".join(chunk))
        index = following
    return units


def _code(script_text: str) -> str:
    """The script without its usage block: what the script actually does."""
    return USAGE_RE.sub("", script_text)


def _facts(script_text: str) -> dict:
    """What the script does, read off its own code."""
    code = _code(script_text)
    return {
        # the script prints SYNC ONLY for a leased host of this run
        "prints_sync_only": "SYNC ONLY" in code,
        # it syncs that host's code and defers only its restart
        "syncs_and_defers": bool(re.search(r"sync_leased_host\s*\(\)", code))
        and "DEFERRED_RESTARTS" in code,
        # an unknown --hosts name is dropped instead of failing the deploy
        "drops_unknown_host": "DROPPED_HOSTS" in code and "hosts_filter_known" in code,
    }


@pytest.fixture(scope="module")
def script_text():
    if not DEPLOY_SCRIPT.exists():
        pytest.skip(f"{DEPLOY_SCRIPT} is not in this checkout")
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def usage(script_text):
    return _usage_block(script_text)


@pytest.fixture(scope="module")
def entries(usage):
    return _usage_entries(usage)


class TestThePathsTheUsageBlockIsCheckedAgainst:
    """The checks below are conditional on the code. These keep them from going vacuous."""

    def test_the_script_still_has_them(self, script_text):
        facts = _facts(script_text)
        assert facts["prints_sync_only"], (
            "the script no longer prints SYNC ONLY - the usage checks below would pass "
            "on a usage block that says nothing about it"
        )
        assert facts["syncs_and_defers"], (
            "the script no longer syncs a leased host and defers its restart - the "
            "--skip-leased usage check below would be vacuous"
        )
        assert facts["drops_unknown_host"], (
            "the script no longer has the DROPPED_HOSTS path - the --hosts usage check "
            "below would be vacuous"
        )


class TestTheWholeUsageBlock:
    """The same rule over the whole block, not only over the --skip-leased entry.

    The entry is not the only place the block talks about a leased host: the example
    list carries a one-line summary of the same flag, and that line is the one an
    operator scans. A rule that only reads the entry cannot see it, so the next
    wording that slips in slips in there too. The rule is the same one: a statement
    that drops a leased host has to say which leased host it drops.
    """

    def test_no_clause_drops_a_leased_host_without_scoping_it(self, script_text, usage):
        if not _facts(script_text)["syncs_and_defers"]:
            pytest.skip("the script no longer syncs a leased host and defers its restart")
        offenders = []
        for unit in _usage_units(usage):
            for clause in _clauses(unit):
                lowered = clause.lower()
                if "dropped" not in lowered or "leased" not in lowered:
                    continue
                if any(re.search(word, clause, re.I) for word in SCOPING_WORDS):
                    continue
                offenders.append(clause.strip())
        assert not offenders, (
            "the usage block drops a leased host without saying which one. The script "
            "drops a leased host that is NOT part of this run (a Windows host, a "
            "secondary server) and syncs the ones that are, so every statement that "
            "drops a leased host has to be scoped:\n  "
            + "\n  ".join(offenders)
        )


class TestTheSkipLeasedEntry:
    def test_the_usage_block_mentions_the_marker_the_script_prints(self, script_text, usage):
        if not _facts(script_text)["prints_sync_only"]:
            pytest.skip("the script no longer prints SYNC ONLY")
        assert "SYNC ONLY" in usage, (
            "the script prints SYNC ONLY for a leased host of this run, so the usage "
            "block has to say so - an operator reading --help is told a leased host is "
            "dropped while the script in fact syncs it and defers its restart"
        )

    def test_the_entry_describes_the_sync_and_defer_path(self, script_text, entries):
        if not _facts(script_text)["syncs_and_defers"]:
            pytest.skip("the script no longer syncs a leased host and defers its restart")
        entry = entries["--skip-leased"]
        lowered = entry.lower()
        assert "sync" in lowered, (
            "the script syncs a leased host of this run (it prints 'code is synced'), so "
            "the --skip-leased entry must not leave the operator thinking the host is "
            "dropped:\n" + entry
        )
        assert "defer" in lowered, (
            "the script defers the vpt-host restart of a leased host of this run (it "
            "prints 'restart deferred if due'), so the --skip-leased entry must say so:\n"
            + entry
        )

    def test_the_drop_it_mentions_is_scoped_to_a_host_outside_this_run(self, script_text, entries):
        if not _facts(script_text)["syncs_and_defers"]:
            pytest.skip("the script no longer syncs a leased host and defers its restart")
        entry = entries["--skip-leased"]
        drops = [clause for clause in _clauses(entry) if "dropped" in clause.lower()]
        assert drops, "the --skip-leased entry no longer mentions any dropped host"
        for clause in drops:
            assert any(re.search(word, clause, re.I) for word in SCOPING_WORDS), (
                "the --skip-leased entry drops a leased host without saying which one. "
                "The script drops a leased host that is NOT part of this run (a Windows "
                "host, a secondary server) and syncs the ones that are, so the drop has "
                "to be scoped:\n" + clause.strip()
            )


class TestTheHostsEntry:
    def test_it_drops_an_unknown_name_with_a_warning(self, script_text, entries):
        if not _facts(script_text)["drops_unknown_host"]:
            pytest.skip("the script no longer has the DROPPED_HOSTS path")
        entry = entries["--hosts"]
        assert "drop" in entry.lower(), (
            "the script drops a --hosts name it does not know, so the entry has to say "
            "so:\n" + entry
        )
        assert "warning" in entry.lower(), (
            "the script warns about a --hosts name it does not know, so the entry has to "
            "say so:\n" + entry
        )

    def test_it_does_not_abort_the_deploy_on_one_unknown_name(self, script_text, entries):
        if not _facts(script_text)["drops_unknown_host"]:
            pytest.skip("the script no longer has the DROPPED_HOSTS path")
        entry = entries["--hosts"]
        for clause in _clauses(entry):
            if "abort" not in clause.lower():
                continue
            assert any(re.search(word, clause, re.I) for word in QUANTIFIERS), (
                "the script drops a --hosts name it does not know and aborts only when "
                "EVERY name is unknown, so the entry must not read as an abort on one "
                "unknown name:\n" + clause.strip()
            )
