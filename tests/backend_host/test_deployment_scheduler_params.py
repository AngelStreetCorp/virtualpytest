"""TASK-135: a script run queued behind another job kept `--userinterface=<ui>` in its parameters, and the
scheduler both dropped that token (read as a flag with no value) and put a bare <ui> first, so validation.py
stopped with "Unknown argument(s) for validation: <ui>". build_script_params is loaded alone (ast) like
test_deployment_scheduler_file_script.py does."""

import ast
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / 'backend_host/src/services/deployment_scheduler.py'


def _build():
    tree = ast.parse(_PATH.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_script_params')
    namespace = {}
    exec(compile(ast.Module([node], []), str(_PATH), 'exec'), namespace)
    return namespace['build_script_params']


DEP = {'host_name': 'host-clone-1', 'device_id': 'host'}


def test_queued_execute_keeps_its_userinterface_flag():
    params = _build()({**DEP, 'userinterface_name': 'vpttv-ch-full',
                       'parameters': '--userinterface=vpttv-ch-full --host host-clone-1 --device host'})
    assert params.startswith('--userinterface=vpttv-ch-full ')
    assert 'vpttv-ch-full' not in params.replace('--userinterface=vpttv-ch-full', '')


def test_space_form_flag_is_not_doubled_by_a_positional():
    params = _build()({**DEP, 'userinterface_name': 'ui', 'parameters': '--userinterface ui --max-iteration 3'})
    assert params == '--userinterface ui --max-iteration 3 --host host-clone-1 --device host'


def test_positional_userinterface_when_the_parameters_do_not_name_it():
    params = _build()({**DEP, 'userinterface_name': 'stb-testop', 'parameters': '--edges --max-iteration 10'})
    assert params == 'stb-testop --max-iteration 10 --host host-clone-1 --device host'


def test_empty_equals_value_is_dropped_and_spaces_stay_quoted():
    params = _build()({**DEP, 'parameters': '--node= --edge "a → b"'})
    assert params == "--edge 'a → b' --host host-clone-1 --device host"


def test_json_parameters_are_not_cli():
    assert _build()({**DEP, 'parameters': '[{"script": "x"}]'}) == '--host host-clone-1 --device host'
