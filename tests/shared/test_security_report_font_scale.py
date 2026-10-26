"""The security dashboard's type scale (scripts/parse-security-to-html.py -> docs/security/index.html).

The report text was requested bigger (+1 and maybe +2), the inverse of the FAQ change. These
tests pin the ladder so it stays even: every role moved up two px steps together, and the
committed index.html must still be what the generator produces.
"""
import importlib.util
import os
import re
import subprocess
import sys

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
GENERATOR = os.path.join(REPO_ROOT, "scripts", "parse-security-to-html.py")
COMMITTED_HTML = os.path.join(REPO_ROOT, "docs", "security", "index.html")

# The generator stamps a "MM-DD HH:MM" generation time into the header, so regenerating always
# differs by that one span. Blank it before comparing two generations.
TIMESTAMP_RE = re.compile(r'\d{2}-\d{2} \d{2}:\d{2}')


def _without_timestamp(html):
    return TIMESTAMP_RE.sub("<TIMESTAMP>", html)


def _load_generator():
    spec = importlib.util.spec_from_file_location("parse_security_to_html", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


@pytest.fixture(scope="module")
def committed():
    with open(COMMITTED_HTML, encoding="utf-8") as f:
        return f.read()


class TestReportFontScale:
    def test_every_role_is_bigger_than_the_original_ladder(self, gen):
        # The sizes before the +2 step, per role. A role must never fall back to or below these.
        floor = {
            "body": 12, "h1": 14, "timestamp": 10, "metricValue": 28, "metricLabel": 9,
            "summaryInfo": 10, "filterBtn": 10, "sectionArrow": 10, "sectionTitle": 11,
            "sectionCounts": 11, "jsonLink": 10, "issue": 11, "issueLoc": 10, "issueFix": 10,
        }
        assert set(gen.REPORT_FONT) == set(floor), "the scale must cover exactly these roles"
        for role, was in floor.items():
            assert gen.REPORT_FONT[role] > was, f"{role} must be bigger than {was}px"

    def test_reading_roles_stepped_two_and_tiny_captions_stay_legible(self, gen):
        # The prose roles carry the reading, so they take the full +2 step.
        for role in ("body", "issue", "sectionTitle", "sectionCounts"):
            assert gen.REPORT_FONT[role] - {"body": 12, "issue": 11, "sectionTitle": 11, "sectionCounts": 11}[role] == 2
        # Nothing lands in the sub-11px range that made the report hard to read.
        assert min(gen.REPORT_FONT.values()) >= 11

    def test_hierarchy_is_still_hierarchical(self, gen):
        f = gen.REPORT_FONT
        # Mirrors the original ordering: the section title is an uppercase 600-weight LABEL, so it
        # stays a step under body prose (it was 11px against a 12px body before this change).
        assert f["metricValue"] > f["h1"] > f["body"] > f["sectionTitle"] == f["sectionCounts"] >= f["issueLoc"]

    def test_loc_column_widened_with_its_font(self, gen):
        # .issue-loc is mono and width-locked; if the font grows without the column, paths get
        # truncated earlier than before and the bigger font buys nothing.
        assert gen.REPORT_LOC_MIN_WIDTH > 200

    def test_generated_css_uses_the_scale_and_no_stray_literal(self, committed):
        # Every font-size in the served page must come from REPORT_FONT, not a typed literal.
        sizes = {int(px) for px in re.findall(r"font-size:\s*(\d+)px", committed)}
        from_gen = set()
        for value in _load_generator().REPORT_FONT.values():
            from_gen.add(value)
        assert sizes <= from_gen, f"hand-written font sizes leaked into the CSS: {sizes - from_gen}"

    def test_committed_html_matches_a_fresh_generation(self, committed):
        # The page the server serves is docs/security/index.html, not the generator. If the
        # committed copy drifts, the live page silently shows the old size forever.
        # The generation timestamp is normalised: a fresh clock reading is not staleness.
        before = _without_timestamp(open(COMMITTED_HTML, encoding="utf-8").read())
        subprocess.run([sys.executable, GENERATOR], cwd=REPO_ROOT, check=True, capture_output=True)
        after = _without_timestamp(open(COMMITTED_HTML, encoding="utf-8").read())
        assert after == before, (
            "docs/security/index.html is stale — re-run scripts/parse-security-to-html.py and commit it"
        )