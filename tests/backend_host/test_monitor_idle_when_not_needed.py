"""vpt-monitor-img / -audio / -subtitle idle when no device needs the service (BUG-0556).

The five host services (vpt-monitor-img / -audio / -subtitle / -archiver / -kpi / -avq) auto-start at
boot; they come up whether or not any device on the host needs them. The savings come in three
coordinated layers, all of which consult the same single source of truth:
`shared.src.lib.utils.monitor_profile.folders_needing_service`. A change to the contract there
must keep this test green *and* `test_monitor_services_follow_profiles.py` green.

The new "pc" profile (BEFORE this turn, before any `.env` change) is what makes the saving real on
hosts whose every device runs `pc` / `tv_lite`. See `docs/agent/devices/MONITOR_PROFILES.md` §2a.
"""
import os
import sys
import textwrap

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import shared.src.lib.utils.monitor_profile as mp  # noqa: E402


def test_profile_services_agrees_with_folders_needing_service(tmp_path, monkeypatch):
    """The two single-source-of-truth views must always agree. A profile that turns `img` on
    for the imager must be reported as needing `img` for any device whose .env selects it.

    This is the only assertion that matters at the level of the host orchestrator + per-device
    filter contract: the same answer is reachable through `folders_needing_service` (per-device
    view used by `wait_until_needed` and the in-imager filter) and
    `folders_needing_service_for_devices` (per-host view used by `_desired_state` in
    `apply_monitor_profiles`). The two answers must be the same set, always.
    """
    profile_dir = tmp_path / 'profiles'
    profile_dir.mkdir()
    # `validate_manifest_light` rejects a profile whose `services.img: true` is set without
    # an `img.analyzers` block. We give each the minimum a real profile carries.
    (profile_dir / 'pc.yaml').write_text(textwrap.dedent('''
        name: pc
        stream: lean
        services: { img: false, audio: false, subtitle: false, archiver: false, kpi: false, avq: false }
        img: { runtime: edge, analyzers: [{ type: tv_app }] }
    '''))
    (profile_dir / 'tv_app.yaml').write_text(textwrap.dedent('''
        name: tv_app
        services: { img: true, audio: true, subtitle: true, archiver: true, kpi: true, avq: true }
        img: { runtime: edge, analyzers: [{ type: tv_app }] }
    '''))
    (profile_dir / 'counting_cars.yaml').write_text(textwrap.dedent('''
        name: counting_cars
        services: { img: true, audio: false, subtitle: false, archiver: true, kpi: true, avq: false }
        img: { runtime: edge, analyzers: [{ type: coco_detect }] }
    '''))

    monkeypatch.setattr(mp, 'PROFILES_DIR', str(profile_dir))
    monkeypatch.setenv('DEVICE1_MONITOR_PROFILE', 'pc')
    monkeypatch.setenv('DEVICE2_MONITOR_PROFILE', 'tv_app')
    monkeypatch.setenv('DEVICE3_MONITOR_PROFILE', 'counting_cars')

    # The real `get_device_info_from_capture_folder` reads the capture folder on disk; in the
    # test there is no disk folder, so it would return `device_index=None` for every folder
    # and the per-device override (DEVICE1_MONITOR_PROFILE=pc) would never be read. Map each
    # capture folder to the corresponding device index so the override is consulted.
    import shared.src.lib.utils.storage_path_utils as spu
    monkeypatch.setattr(spu, 'get_device_info_from_capture_folder',
                        lambda folder: {'device_id': folder.replace('capture', 'device'),
                                        'device_index': int(folder.replace('capture', ''))})

    folders = ['capture1', 'capture2', 'capture3']

    # Per-device view: used by `wait_until_needed` and the in-imager filter.
    img_needers = mp.folders_needing_service('img', folders)
    assert sorted(img_needers) == ['capture2', 'capture3'], (
        f"folders_needing_service('img', {folders!r}) returned {img_needers!r}; "
        f"expected capture2 + capture3 (tv_app + counting_cars), not capture1 (pc)"
    )

    # Per-host view: used by `apply_monitor_profiles._desired_state`.
    profiles = {f'capture{i+1}': mp.resolve_monitor_profile(i+1) for i in range(3)}
    assert profiles == {'capture1': 'pc', 'capture2': 'tv_app', 'capture3': 'counting_cars'}

    host_view = mp.folders_needing_service_for_devices('img', profiles)
    assert sorted(host_view) == sorted(img_needers), (
        f"folders_needing_service_for_devices {host_view!r} disagrees with "
        f"folders_needing_service {img_needers!r}"
    )

    # Spot-check the other services too, on the same profiles: an `img: false` profile (`pc`)
    # must turn every other service off; an `img: true` profile (`tv_app`) must turn them on;
    # a `counting_cars` profile turns img/kpi/archiver on and audio/subtitle/avq off.
    pc_services = mp.profile_services('pc')
    assert all(pc_services[s] is False for s in mp.SERVICES), pc_services
    tv_app_services = mp.profile_services('tv_app')
    assert all(tv_app_services[s] is True for s in mp.SERVICES), tv_app_services
    cars_services = mp.profile_services('counting_cars')
    assert cars_services == {'img': True, 'audio': False, 'subtitle': False,
                              'archiver': True, 'kpi': True, 'avq': False}, cars_services


def test_pc_profile_yaml_is_lean_and_usable():
    """The new `pc.yaml` profile (this turn's commit) must declare every service off and a
    `stream: lean` mode so `run_ffmpeg.sh` skips the 24 h archive."""
    import yaml
    path = os.path.join(mp.PROFILES_DIR, 'pc.yaml')
    if not os.path.isfile(path):
        pytest.skip("pc.yaml not on disk; the pc profile commit must be checked out first")
    raw = yaml.safe_load(open(path))
    assert raw['name'] == 'pc'
    assert raw['stream'] == 'lean'
    assert raw['services'] == {s: False for s in mp.SERVICES}, raw['services']
