"""A device whose profile cannot start at boot (missing model file, broken manifest) is left out;
FrameMonitor must still start for the host's other devices. The error log quotes
dir_rescan_interval_s, which once was set after the first _assign_profile, so every such
startup crashed vpt-monitor-img for the whole host (vpt-lenovo1, counting_cars without its model)."""
import os
import sys

from tests.backend_host.test_monitor_replay import ROOT, SCRIPTS, _install_stubs


def test_profile_error_at_startup_leaves_device_out(tmp_path, monkeypatch):
    _install_stubs()
    for p in (SCRIPTS, ROOT):
        if p not in sys.path:
            sys.path.insert(0, p)
    import incident_manager
    import monitor.core as core

    class QuietIncidentManager(incident_manager.IncidentManager):
        def __init__(self, *a, **k):
            super().__init__(skip_startup_cleanup=True)

    def no_model(_folder):
        raise FileNotFoundError('coco_detect: model file not found')

    monkeypatch.setattr(core, 'IncidentManager', QuietIncidentManager)
    monkeypatch.setattr(core, 'get_device_info_from_capture_folder', no_model)
    capture_dir = tmp_path / 'stream' / 'capture4' / 'captures'
    capture_dir.mkdir(parents=True)

    fm = core.FrameMonitor([str(capture_dir)], 'test-host')

    assert fm.device_analyzers == {}
    assert list(fm._profile_errors.values()) == ['coco_detect: model file not found']
