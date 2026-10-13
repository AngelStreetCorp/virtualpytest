"""Remote profiles (TASK-76): shared/src/lib/config/remote_profiles.py.

Pure functions — no host, no DB.

Run: pytest tests/shared/test_remote_profiles.py -v
"""
import os
import sys

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.config.remote_profiles import (  # noqa: E402
    available_keys,
    build_groups,
    device_key_capabilities,
    group_mismatches,
    invalidate_key_cache,
    profile_remote_type,
    remote_conf,
    remote_profile,
    shared_key_intersection,
)


@pytest.mark.parametrize("implementation,conf,expected", [
    ("ir_remote", "stb", "ir:stb"),
    ("ir_remote", None, "ir:unknown"),
    ("bluetooth_remote", "arris", "ble:arris"),
    ("android_tv", None, "adb_tv"),
    ("android_mobile", None, "adb_mobile"),
    ("vega", None, "vega"),
    ("appium", None, "appium"),
])
def test_remote_profile(implementation, conf, expected):
    assert remote_profile(implementation, conf) == expected


@pytest.mark.parametrize("profile,remote_type", [
    ("ir:stb", "ir_remote"),
    ("ble:arris", "bluetooth_remote"),
    ("adb_tv", "android_tv"),
    ("adb_mobile", "android_mobile"),
    ("vega", "vega"),
])
def test_profile_remote_type(profile, remote_type):
    assert profile_remote_type(profile) == remote_type


def test_remote_conf_reads_ir_then_ble():
    class Ir:
        ir_type = "fire_tv"

    class Ble:
        ble_type = "arris"

    class Adb:
        pass

    assert remote_conf(Ir()) == "fire_tv"
    assert remote_conf(Ble()) == "arris"
    assert remote_conf(Adb()) is None


def _dev(host, dev_id, model, profiles):
    return {"host_name": host, "device_id": dev_id, "device_name": f"{host}-{dev_id}",
            "device_model": model, "remote_profiles": profiles}


STB_IR_1 = _dev("pi1", "device1", "stb", ["ir:stb"])
STB_IR_2 = _dev("pi2", "device1", "stb", ["ir:stb"])
STB_BLE = _dev("pi1", "device2", "stb", ["ble:arris"])
FIRE_ADB_IR = _dev("pi3", "device1", "fire_tv_fireos", ["adb_tv", "ir:fire_tv"])
FIRE_ADB = _dev("pi4", "device1", "fire_tv_fireos", ["adb_tv"])
FIRE_VEGA = _dev("pi4", "device2", "fire_tv_vega", ["vega"])


def test_ir_and_ble_stb_never_group():
    groups = build_groups([STB_IR_1, STB_IR_2, STB_BLE])
    assert [(g["device_model"], g["remote_profile"], len(g["devices"])) for g in groups] == [("stb", "ir:stb", 2)]


def test_multi_remote_device_joins_on_shared_profile():
    groups = build_groups([FIRE_ADB_IR, FIRE_ADB, FIRE_VEGA])
    assert len(groups) == 1
    assert groups[0]["remote_profile"] == "adb_tv"
    assert groups[0]["remote_type"] == "android_tv"
    assert {d["host_name"] for d in groups[0]["devices"]} == {"pi3", "pi4"}


def test_group_mismatches_names_each_reason():
    bad = group_mismatches([STB_IR_1, STB_BLE, FIRE_ADB], "stb", "ir:stb")
    assert [(b["host_name"], b["device_id"]) for b in bad] == [("pi1", "device2"), ("pi4", "device1")]
    assert "no ir:stb remote" in bad[0]["reason"]
    assert "model fire_tv_fireos" in bad[1]["reason"]


def test_no_profiles_means_no_group():
    assert build_groups([_dev("a", "d", "stb", []), _dev("b", "d", "stb", [])]) == []


# --- TASK-80: key capability surface (available_keys, shared intersection) -------

@pytest.fixture(autouse=True)
def _clear_key_cache():
    """Each test sees a fresh cache so re-pair invalidation can be tested in isolation."""
    invalidate_key_cache()
    yield
    invalidate_key_cache()


def test_available_keys_ir_stb_reads_json():
    keys = available_keys("stb", "ir:stb")
    # 33 keys per backend_host/src/controllers/remote/ir_conf/stb.json, minus _comment.
    assert "POWER" in keys
    assert "VOLUME_UP" in keys
    assert "RADIO" in keys  # IR-only in STB; the marker for the BLE/IR group
    assert "VOICE" not in keys
    assert len(keys) == 33


def test_available_keys_ble_arris_reads_json():
    keys = available_keys("stb", "ble:arris")
    assert "VOICE" in keys  # BLE-only on STB
    assert "EXIT" in keys
    assert "RADIO" not in keys
    assert "POWER" in keys
    assert len(keys) == 40


def test_available_keys_canonical_vega_fire_tv():
    keys = available_keys("fire_tv_vega", "vega")
    assert "POWER" in keys
    assert "HOME" in keys
    assert "VOICE" in keys
    # Vega accepts the full Fire TV remote surface
    assert "KEY_0" in keys
    assert len(keys) == 34


def test_available_keys_canonical_adb_tv():
    keys = available_keys("fire_tv_fireos", "adb_tv")
    assert "POWER" in keys
    assert "HOME" in keys
    assert "KEY_9" in keys
    assert "VOICE" in keys
    assert len(keys) == 34


def test_available_keys_unknown_profile_is_empty():
    assert available_keys("anything", "nonsense:abc") == []


def test_available_keys_cached_after_first_load():
    """The loader is wrapped in lru_cache, so a second call for the same
    profile must not re-read the file. Inspect cache_info to prove it."""
    import shared.src.lib.config.remote_profiles as rp
    invalidate_key_cache()
    rp._load_ir_keys.cache_clear()
    assert rp._load_ir_keys.cache_info().misses == 0
    available_keys("stb", "ir:stb")
    after_first = rp._load_ir_keys.cache_info()
    available_keys("stb", "ir:stb")
    available_keys("stb", "ir:stb")
    after_more = rp._load_ir_keys.cache_info()
    assert after_first.misses == 1
    assert after_more.misses == 1  # the next two calls were hits
    assert after_more.hits >= 2


def test_invalidate_key_cache_drops_cache():
    """invalidate_key_cache must clear the loader cache so the next call
    re-reads the file (this is what start_pairing calls after a re-pair).

    The behavior we assert is the observable one: after invalidate, the next
    call is a fresh miss (currsize=0 just before, then the call populates it
    again). Internally lru_cache.cache_clear() also resets the misses counter,
    so we check the first post-invalidate miss is non-zero.
    """
    import shared.src.lib.config.remote_profiles as rp
    invalidate_key_cache()
    rp._load_ir_keys.cache_clear()
    available_keys("stb", "ir:stb")  # miss #1
    assert rp._load_ir_keys.cache_info().misses == 1
    invalidate_key_cache()  # drops cache AND resets the miss counter
    info_after_clear = rp._load_ir_keys.cache_info()
    assert info_after_clear.currsize == 0
    assert info_after_clear.misses == 0  # cache_clear resets the counter
    available_keys("stb", "ir:stb")  # fresh miss
    assert rp._load_ir_keys.cache_info().misses == 1  # would be 0 if invalidate didn't drop


def test_shared_key_intersection_stb_ir_and_ble():
    common = shared_key_intersection("stb", ["ir:stb", "ble:arris"])
    assert "POWER" in common
    assert "VOLUME_UP" in common
    assert "OK" in common
    assert "KEY_0" in common
    # 32 keys: 33 IR + 40 BLE, minus IR-only RADIO and BLE-only {VOICE, INFO, EXIT, NEXT, PREVIOUS, PROFILE, SELECT, TV}
    assert len(common) == 32
    assert "RADIO" not in common  # IR-only
    assert "VOICE" not in common  # BLE-only
    assert "INFO" not in common   # BLE-only


def test_shared_key_intersection_fire_tv_vega_and_adb_tv():
    common = shared_key_intersection("fire_tv", ["vega", "adb_tv"])
    # Both share the canonical Fire TV set; 34 keys.
    assert "POWER" in common
    assert "HOME" in common
    assert "VOICE" in common  # adb_tv canonical = Fire TV set; vega too
    assert len(common) == 34


def test_shared_key_intersection_empty_when_no_profiles():
    assert shared_key_intersection("stb", []) == []


def test_shared_key_intersection_with_unknown_profile_falls_back_to_known():
    # An unknown profile contributes an empty set, which is dropped from the
    # intersection. Result: the keys of the *known* members only — the safe
    # default when we can't enumerate every member's keys.
    common = shared_key_intersection("stb", ["ir:stb", "nonsense:abc"])
    assert common == available_keys("stb", "ir:stb")


def test_device_key_capabilities_stb():
    dev = _dev("pi1", "device1", "stb", ["ir:stb", "ble:arris"])
    caps = device_key_capabilities(dev)
    assert set(caps.keys()) == {"ir:stb", "ble:arris"}
    assert "POWER" in caps["ir:stb"]
    assert "VOICE" in caps["ble:arris"]
    assert "VOICE" not in caps["ir:stb"]


def test_device_key_capabilities_empty_when_no_profiles():
    assert device_key_capabilities(_dev("a", "d", "stb", [])) == {}
