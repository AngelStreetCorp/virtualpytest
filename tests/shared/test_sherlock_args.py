"""Script-argument facts for Sherlock (TASK-38): command line + declared args + descriptions. No network."""
from backend_server.src.agent.core import sherlock_args
from shared.src.lib.utils.script_target_rules_utils import extract_arg_descriptions_from_source

SOURCE = '''
SYSTEM = 'system'
_script_args = [
    '--url:str:google.com',
    '--dns:str:system',
    '--host:str:',
]
_arg_descriptions = {
    "url": "Hostname to resolve",
    "dns": f"DNS server to query; '{SYSTEM}' uses the host's resolver",
}
'''


def test_command_line_pairs():
    assert sherlock_args.parse_command_line("--a 1 --b=two --flag --c 'x y'") == {
        "a": "1", "b": "two", "flag": None, "c": "x y"}
    assert sherlock_args.parse_command_line("") == {}


def test_declared_args_get_value_default_and_meaning():
    out = sherlock_args.describe("--dns epg.example --host h1 --device host --extra 3", SOURCE)
    assert out == [
        {"name": "url", "value": "google.com", "default": "google.com", "used_default": True,
         "meaning": "Hostname to resolve"},
        {"name": "dns", "value": "epg.example", "default": "system", "used_default": False,
         "meaning": "DNS server to query; 'system' uses the host's resolver"},
        {"name": "extra", "value": "3"},
    ]


def test_without_source_only_the_command_line():
    assert sherlock_args.describe("--dns 8.8.8.8 --host h", "") == [{"name": "dns", "value": "8.8.8.8"}]


def test_one_fstring_description_does_not_drop_the_others():
    descs = extract_arg_descriptions_from_source(SOURCE)
    assert descs["url"] == "Hostname to resolve" and "'system'" in descs["dns"]


def test_for_record_never_raises(monkeypatch):
    def boom(path):
        raise RuntimeError("storage down")
    monkeypatch.setattr(sherlock_args, "fetch_text_from_storage", boom)
    rec = {"id": "r", "metadata": {"parameters": "--dns x", "script_source": {"path": "p"}}}
    assert sherlock_args.for_record(rec) == []
