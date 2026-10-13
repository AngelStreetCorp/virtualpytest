"""normalize_argv / unknown_args_message / find_unknown_flags: aliases rewritten, unknown flags named."""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from shared.src.lib.executors.cli_arg_utils import normalize_argv, unknown_args_message, split_unknown_args  # noqa: E402
from backend_server.src.mcp.tools.script_tools import find_unknown_flags  # noqa: E402


def test_userinterface_name_is_rewritten_with_a_warning():
    argv, warnings = normalize_argv(['--userinterface_name', 'youtube-web', '--node', 'video_player'])
    assert argv == ['--userinterface', 'youtube-web', '--node', 'video_player']
    assert warnings == ["'--userinterface_name' is deprecated, using '--userinterface'"]


def test_equals_form_keeps_its_value():
    argv, _ = normalize_argv(['--userinterface_name=youtube-web'])
    assert argv == ['--userinterface=youtube-web']


def test_canonical_flags_pass_through_untouched():
    argv, warnings = normalize_argv(['--userinterface', 'x', '--device', 'host'])
    assert argv == ['--userinterface', 'x', '--device', 'host'] and warnings == []


def test_unknown_args_message_lists_valid_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument('--userinterface'); parser.add_argument('--node'); parser.add_argument('--device')
    msg = unknown_args_message('goto', ['--nod', 'x'], parser)
    assert msg.startswith('Unknown argument(s) for goto: --nod x.')
    assert '--device, --node, --userinterface' in msg


def test_find_unknown_flags_accepts_script_and_framework_flags():
    assert find_unknown_flags('--userinterface a --node b --device host', ['userinterface', 'node']) == []
    assert find_unknown_flags('--userinterface_name a --node b', ['userinterface', 'node']) == ['--userinterface_name']
    assert find_unknown_flags('--max_iteration=3', ['max_iteration']) == []


def test_launcher_flags_are_tolerated_and_the_rest_rejected():
    tolerated, rejected = split_unknown_args(['--host', 'host-clone-1', '--variant', 'base', '--nod', 'x'])
    assert tolerated == ['--host', 'host-clone-1', '--variant', 'base']
    assert rejected == ['--nod', 'x']


def test_launcher_flag_with_equals_form_takes_no_extra_token():
    tolerated, rejected = split_unknown_args(['--host=host-clone-1', '--bogus'])
    assert tolerated == ['--host=host-clone-1'] and rejected == ['--bogus']
