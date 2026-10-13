"""Start Pairing passes the caller (§6.7.32) and the configured address (§6.7.33) to start.sh.

No adapter, no sudo: _run_script is replaced and the background thread runs inline.
"""
import importlib

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def ctl(monkeypatch):
    mod = importlib.import_module('backend_host.src.controllers.remote.bluetooth')
    c = object.__new__(mod.BluetoothRemoteController)
    c.device_type = 'bluetooth'
    c.adapter_hci = 'hci9'
    c.ble_mac = None
    c._pair_error = None
    c._pairing_in_progress = False
    c._script_running = False
    c._clear_pairing_lock = lambda: None
    c.runs = []
    c._run_script = lambda name, extra_env=None: (c.runs.append((name, extra_env)), (True, ''))[1]

    class InlineThread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(mod.threading, 'Thread', InlineThread)
    return c


def test_caller_is_passed_to_start_sh(ctl):
    r = ctl.execute_command('start_pairing', {'caller': 'user=a@b ip=10.0.0.1'})
    assert r['success'] is True
    assert ctl.runs == [('start.sh', {'VPT_PAIRING_CALLER': 'user=a@b ip=10.0.0.1'})]


def test_missing_caller_is_logged_as_unknown(ctl):
    ctl.execute_command('start_pairing', {})
    assert ctl.runs == [('start.sh', {'VPT_PAIRING_CALLER': 'unknown'})]


def test_configured_mac_is_passed_to_start_sh(ctl):
    # DEVICEn_BLE_MAC (§6.7.33): start.sh pairs on this address instead of picking one.
    ctl.ble_mac = '20:21:41:00:1F:11'
    ctl.execute_command('start_pairing', {'caller': 'c'})
    assert ctl.runs[0][1]['ADAPTER_MAC'] == '20:21:41:00:1F:11'


def test_no_configured_mac_leaves_start_sh_to_choose(ctl):
    ctl.ble_mac = None
    ctl.execute_command('start_pairing', {})
    assert 'ADAPTER_MAC' not in ctl.runs[0][1]


def test_start_sh_error_line_is_reported_in_status(ctl):
    # The panel stops waiting and shows why (e.g. advertising refused, exit 3).
    out = '== Reapplying ==\nERROR: LE Set Advertise Enable failed (HCI status 0x0C).\nAdapter hci9 ...'
    ctl._run_script = lambda name, extra_env=None: (False, out)
    ctl.execute_command('start_pairing', {})
    assert ctl._pair_error == 'ERROR: LE Set Advertise Enable failed (HCI status 0x0C).'


def test_logs_tab_shows_last_script_run_without_xtrace(ctl, tmp_path, monkeypatch):
    mod = importlib.import_module('backend_host.src.controllers.remote.bluetooth')
    log = tmp_path / 'ble-start-hci9.log'
    log.write_text('===== start.sh begin old =====\nold run\n'
                   '===== start.sh begin new =====\n+ btmgmt power off\n== Stopping ==\nPaired: 1\n')
    real = mod.os.path.getmtime
    monkeypatch.setattr(mod.os.path, 'getmtime',
                        lambda p: real(str(log)) if p.endswith('ble-start-hci9.log') else (_ for _ in ()).throw(OSError()))
    real_open = open
    monkeypatch.setattr('builtins.open', lambda p, *a, **k: real_open(str(log) if str(p).endswith('ble-start-hci9.log') else p, *a, **k))
    text = ctl._last_script_run()
    assert 'begin new' in text and '== Stopping ==' in text and 'Paired: 1' in text
    assert 'old run' not in text and '+ btmgmt' not in text
