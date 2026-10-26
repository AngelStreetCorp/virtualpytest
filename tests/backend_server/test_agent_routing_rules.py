"""TASK-175: which agent answers, decided before any model call. Pure unit tests."""
import glob
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))

try:
    import yaml
    from agent import agent_routing_rules as rules
    from agent import quick_step as qs
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("message", [
    "create a script",
    "create a virtual script that logs hello world",
    "write a testcase that checks the home screen loads",
    "please create a test case for the login",
    "edit the script SC_X to log twice",
    "can you fix the script SC_X",
])
def test_script_work_goes_to_forge(message):
    assert rules.forge_handoff(message) is True


@pytest.mark.parametrize("message", [
    "run the script goto_live",
    "list the scripts",
    "list my test cases",
    "what scripts can I run?",
    "create a user interface named x for an android_tv device",
    "build the web navigation tree of dailymotion",
])
def test_other_asks_stay_with_atlas(message):
    assert rules.forge_handoff(message) is False


@pytest.mark.parametrize("message,agent", [
    ("restart vpt-stream on host-clone-1", rules.MASTERCHIEF),
    ("reboot the server", rules.MASTERCHIEF),
    ("clean up the disk on host-clone-1", rules.MASTERCHIEF),
    ("why did the last run on host-clone-1 fail?", rules.SHERLOCK),
    ("restart the script", None),
    ("why is the sky blue", None),
    ("list the hosts", None),
])
def test_suggestions(message, agent):
    assert rules.suggestion(message) == agent


@pytest.mark.parametrize("message", ["cap 5", "a", "r", "zz top 9"])
def test_vague_short_asks(message):
    assert rules.is_vague(message, ["Phone slot 1"]) is True


@pytest.mark.parametrize("message", [
    "heatmap", "alerts", "show alerts", "say ok", "stb3", "again", "help", "screenshots", "phone slot 1",
    "hi", "thanks", "open settings", "yes", "ok", "list my test cases",
])
def test_short_real_asks_are_not_vague(message):
    assert rules.is_vague(message, ["Phone slot 1"]) is False


@pytest.mark.parametrize("message,tool", [
    ("list my test cases", "list_testcases"),
    ("list the campaigns", "list_campaigns"),
    ("list the remote keys of phone slot 1", "list_actions"),
    ("dump the ui elements of phone slot 1", "dump_ui_elements"),
    ("show me the open alerts", "get_alerts"),
    ("is phone slot 1 free or in use?", "get_device_info"),
])
def test_one_tool_asks_get_their_quick_tool(message, tool):
    assert tool in qs.hinted_tools(message)
    assert qs.eligible(message)


def test_why_and_how_questions_stay_with_the_model():
    """'why did the last run fail?' was answered with list_hosts by the quick step (TASK-175 bench)."""
    assert qs.eligible("why did the last run on host-clone-1 fail?") is False
    assert qs.eligible("how do I list the alerts?") is False
    assert qs.eligible("how many alerts are open?") is True


def test_a_question_that_names_no_tool_stays_with_the_model():
    assert qs.eligible("what is on stb1?") is False
    assert qs.eligible("why did the last three runs on the nightly campaign fail so often") is False


def test_hinted_tools_join_the_quick_set():
    out = qs.quick_tools("t", "u", list(qs.POOL), load_user=lambda t, u: {}, load_team=lambda t: {},
                         message="list my test cases")
    assert "list_testcases" in out


def test_every_agent_skill_exists():
    """No agent points at a skill that is not defined (Nightwatch had 3 dead ones, Sherlock 2)."""
    names = set()
    for f in (glob.glob(str(REPO / "backend_server/src/agent/skills/definitions/*/SKILL.md"))
              + glob.glob(str(REPO / "backend_server/src/agent/skills/definitions/*.yaml"))
              + glob.glob(str(REPO / "features/*/skills/*/SKILL.md"))):
        found = re.search(r"^name:\s*[\"']?([\w-]+)", Path(f).read_text(), re.M)
        if found:
            names.add(found.group(1))
    for template in glob.glob(str(REPO / "backend_server/src/agent/registry/templates/*.yaml")):
        data = yaml.safe_load(Path(template).read_text())
        missing = [s for s in data.get("available_skills") or [] if s not in names]
        assert not missing, f"{Path(template).name} points at missing skills {missing}"


def test_a_device_that_is_not_there_is_named_back():
    devices = [{"host_name": "h", "device_id": "device2", "device_name": "Phone slot 1"}]
    assert qs.missing_device({"device_name": "phone slot 9"}, devices) == "phone slot 9"
    assert qs.missing_device({"device_name": "Phone slot 1"}, devices) is None
    assert qs.missing_device({"host_name": "h", "device_id": "device7"}, devices) == "h/device7"
    assert "Phone slot 1" in qs.missing_device_text("phone slot 9", devices)
    assert "don't see any device" in qs.missing_device_text("x", [])


def test_a_saved_script_is_credited_to_the_agent_that_wrote_it():
    """The save tool stamped every script 'atlas'; Forge writes them since TASK-175."""
    import importlib.util
    path = REPO / "features/virtual-scripts/backend_server/mcp_tools/virtual_script_tools.py"
    spec = importlib.util.spec_from_file_location("virtual_script_tools_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._creator("scripter") == "forge"
    assert module._creator("assistant") == "atlas"
    assert module._creator(None) == "atlas"


def test_the_create_skill_asks_before_saving_on_a_vague_ask():
    text = (REPO / "features/virtual-scripts/skills/create-virtual-script/SKILL.md").read_text()
    assert "A vague ask gets one question first" in text


def test_a_lock_question_fits_get_device_info_and_awake_does_not():
    """get_device_info reports the lock, not the screen: 'awake?' needs a screenshot (live run 2026-10-26)."""
    devices = [{"host_name": "h", "device_id": "device2", "device_name": "Phone slot 1"}]
    for message in ("is phone slot 1 free or in use?", "who is controlling phone slot 1?"):
        assert "get_device_info" in qs.hinted_tools(message)
        assert qs.fits("get_device_info", message, devices)
    assert "get_device_info" not in qs.hinted_tools("is phone slot 1 awake?")
