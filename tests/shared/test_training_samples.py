"""training_samples capture helper (TASK-27 step 2).

Pure: the DB module and the training storage client are replaced by in-memory
fakes. The fake insert refuses any team that has not opted in, so no test can
write a sample row for a team without training_data_opt_in.

Run: pytest tests/shared/test_training_samples.py -v
"""
import os
import sys
from collections import Counter

import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.ai import training_samples as ts  # noqa: E402
from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402
from shared.src.lib.utils import cloudflare_utils  # noqa: E402

TEAM = "11111111-1111-1111-1111-111111111111"
OTHER_TEAM = "22222222-2222-2222-2222-222222222222"
TRAINING_ENVS = ("TRAINING_DATA_ENABLED", "MINIO_TRAINING_ENDPOINT", "MINIO_TRAINING_ACCESS_KEY",
                 "MINIO_TRAINING_SECRET_KEY", "MINIO_TRAINING_BUCKET", "R2_TRAINING_BUCKET",
                 "CLOUDFLARE_R2_ENDPOINT", "CLOUDFLARE_R2_ACCESS_KEY_ID", "CLOUDFLARE_R2_SECRET_ACCESS_KEY")
DB_FUNCS = ("insert_sample", "get_group", "get_sample", "update_label", "team_opted_in",
            "get_labelled_hashes", "set_label_conflict")


class FakeDB:
    def __init__(self, opted_in=(TEAM,)):
        self.rows = {}
        self.opted_in = set(opted_in)
        self.calls = []

    def insert_sample(self, row):
        self.calls.append("insert_sample")
        assert row["team_id"] in self.opted_in, "sample row written for a team without opt-in"
        self.rows[row["id"]] = dict(row)
        return row["id"]

    def get_group(self, team_id, family, device_model, node_id, focus_label):
        self.calls.append("get_group")
        key = (team_id, family, device_model, node_id, focus_label)
        return [(r["id"], r["dhash"], r.get("ground_truth"), bool(r.get("is_failure")))
                for r in self.rows.values()
                if (r["team_id"], r["family"], r["device_model"], r.get("node_id"), r.get("focus_label")) == key]

    def get_sample(self, sample_id, team_id):
        self.calls.append("get_sample")
        r = self.rows.get(sample_id)
        return dict(r) if r and r["team_id"] == team_id else None

    def update_label(self, sample_id, team_id, ground_truth, label_source, is_failure, label_conflict):
        self.calls.append("update_label")
        r = self.rows.get(sample_id)
        if not r or r["team_id"] != team_id:
            return False
        r.update(ground_truth=ground_truth, label_source=label_source,
                 is_failure=is_failure, label_conflict=label_conflict)
        return True

    def team_opted_in(self, team_id):
        self.calls.append("team_opted_in")
        return team_id in self.opted_in

    def get_labelled_hashes(self, team_id, family, device_model, limit=2000):
        self.calls.append("get_labelled_hashes")
        rows = [r for r in reversed(list(self.rows.values()))   # newest first
                if (r["team_id"], r["family"], r["device_model"]) == (team_id, family, device_model)
                and r.get("ground_truth") is not None]
        return [(r["id"], r["dhash"], r["ground_truth"]) for r in rows][:limit]

    def set_label_conflict(self, team_id, sample_ids, value=True):
        self.calls.append("set_label_conflict")
        n = 0
        for sid in sample_ids:
            r = self.rows.get(sid)
            if r and r["team_id"] == team_id:
                r["label_conflict"] = value
                n += 1
        return n


class FakeStorage:
    def __init__(self, fail=False):
        self.objects = {}
        self.fail = fail

    def upload_bytes(self, data, remote_path, content_type="image/jpeg"):
        if self.fail:
            raise RuntimeError("storage down")
        self.objects[remote_path] = data

    def delete_file(self, remote_path):
        self.objects.pop(remote_path, None)
        return True


def _install_db(monkeypatch, fake):
    for name in DB_FUNCS:
        monkeypatch.setattr(samples_db, name, getattr(fake, name))
    return fake


@pytest.fixture
def db(monkeypatch):
    return _install_db(monkeypatch, FakeDB())


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(cloudflare_utils, "get_training_storage", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in TRAINING_ENVS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def enabled_env(monkeypatch):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setenv("MINIO_TRAINING_ENDPOINT", "http://minio.invalid:9000")
    monkeypatch.setenv("MINIO_TRAINING_ACCESS_KEY", "k")
    monkeypatch.setenv("MINIO_TRAINING_SECRET_KEY", "s")
    monkeypatch.setenv("MINIO_TRAINING_BUCKET", "vpt-training")


def frame(seed, h=360, w=640):
    """A blocky random BGR frame; different seeds give dHashes ~128 bits apart."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, size=(h // 20, w // 20, 3), dtype=np.uint8)
    return np.kron(small, np.ones((20, 20, 1), dtype=np.uint8))


def rand_hash(seed):
    """A random 256-bit hash as 64 hex chars."""
    return np.random.default_rng(seed).bytes(32).hex()


def record(img, **kw):
    args = dict(family="screen-id", team_id=TEAM, device_model="android_tv", node_id="home")
    args.update(kw)
    return ts.record_sample(img, **args)


# --- gating ----------------------------------------------------------------------

def test_disabled_returns_none_and_touches_nothing(db, storage):
    assert ts.enabled() is False
    assert record(frame(1)) is None
    assert db.calls == [] and storage.objects == {}


def test_flag_without_bucket_is_disabled(monkeypatch, db, storage):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "1")
    assert ts.enabled() is False
    assert record(frame(1)) is None
    assert db.calls == []


@pytest.mark.parametrize("model", sorted(ts.EXCLUDED_DEVICE_MODELS))
def test_phone_device_models_are_never_recorded(enabled_env, db, storage, model):
    assert record(frame(1), family="av-fault", device_model=model, force=True) is None
    assert record(frame(2), family="screen-id", device_model=model) is None
    assert db.calls == [] and storage.objects == {}


@pytest.mark.parametrize("ui", ["game2048-web", "game2048-android-mobile", "tetris-web", "flappy-web",
                                "pokemon-blue-web"])
def test_game_showcases_are_never_recorded(enabled_env, db, storage, ui):
    assert record(frame(1), family="av-fault", userinterface=ui, force=True) is None
    assert record(frame(2), family="screen-id", userinterface=ui) is None
    assert db.calls == [] and storage.objects == {}


def test_a_tv_app_is_still_recorded(enabled_env, db, storage):
    assert record(frame(1), userinterface="stb-testop") is not None
    assert record(frame(2), userinterface="acceptance-stb4-tv-20261003-1758-stb") is not None


def test_not_opted_in_returns_none_even_if_enabled(enabled_env, db, storage):
    assert ts.enabled() is True
    assert record(frame(1), team_id=OTHER_TEAM) is None
    assert "insert_sample" not in db.calls
    assert storage.objects == {}


# --- record + dedup ---------------------------------------------------------------

def test_records_a_sample(enabled_env, db, storage):
    sid = record(frame(1), userinterface="example_tv", source_ref={"tree_id": "t", "node_id": "home"})
    assert sid
    row = db.rows[sid]
    assert row["object_key"].startswith(f"{TEAM}/screen-id/android_tv/")
    assert row["object_key"].endswith(f"/{sid}.jpg")
    assert row["object_key"] in storage.objects
    assert len(row["dhash"]) == 64
    assert row["split"] in ("train", "eval", "holdout")
    assert row["label_source"] == "none" and row["is_failure"] is False


def test_image_is_resized_to_1280_long_side(enabled_env, db, storage):
    import cv2
    sid = record(frame(3, h=1080, w=1920))
    data = storage.objects[db.rows[sid]["object_key"]]
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) == 1280


def test_near_duplicate_is_skipped(enabled_env, db, storage):
    img = frame(7)
    assert record(img)
    noise = np.random.default_rng(0).integers(-2, 3, img.shape)
    noisy = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    assert record(noisy) is None
    assert record(frame(8)) is not None          # a different frame is kept
    assert record(img, node_id="settings")       # same frame, other group: kept


def test_21st_sample_in_group_is_skipped_but_force_is_not(enabled_env, db, storage):
    for i in range(ts.GROUP_CAP):
        db.rows[f"pre-{i}"] = {"id": f"pre-{i}", "team_id": TEAM, "family": "screen-id",
                               "device_model": "android_tv", "node_id": "home", "focus_label": None,
                               "dhash": rand_hash(1000 + i), "ground_truth": None, "is_failure": False}
    assert record(frame(21)) is None
    assert record(frame(21), force=True) is not None


def test_twentieth_sample_is_kept(enabled_env, db, storage):
    for i in range(ts.GROUP_CAP - 1):
        db.rows[f"pre-{i}"] = {"id": f"pre-{i}", "team_id": TEAM, "family": "screen-id",
                               "device_model": "android_tv", "node_id": "home", "focus_label": None,
                               "dhash": rand_hash(2000 + i), "ground_truth": None, "is_failure": False}
    assert record(frame(22)) is not None


def test_force_bypasses_near_duplicate(enabled_env, db, storage):
    img = frame(9)
    assert record(img)
    assert record(img, force=True) is not None


def test_storage_exception_returns_none(enabled_env, db, monkeypatch):
    monkeypatch.setattr(cloudflare_utils, "get_training_storage", lambda: FakeStorage(fail=True))
    assert record(frame(1)) is None
    assert "insert_sample" not in db.calls


def test_db_exception_returns_none(enabled_env, db, storage, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(samples_db, "get_group", boom)
    assert record(frame(1)) is None


def test_unknown_family_is_refused(enabled_env, db, storage):
    assert record(frame(1), family="nonsense") is None
    assert "insert_sample" not in db.calls


# --- split ------------------------------------------------------------------------

def test_assign_split_is_deterministic():
    keys = ts.stable_keys(TEAM, "focus", "android_tv", "home", "Settings")
    h = rand_hash(5)
    assert ts.assign_split(keys, h) == ts.assign_split(dict(keys), h)
    assert ts.assign_split(keys, h) == ts.assign_split((TEAM, "focus", "android_tv", "home", "Settings"), h)
    # only the first 16 bits of the hash are part of the tuple
    assert ts.assign_split(keys, h) == ts.assign_split(keys, h[:4] + "0" * 60)


def test_assign_split_roughly_85_10_5():
    n = 4000
    counts = Counter(ts.assign_split(ts.stable_keys(TEAM, "screen-id", "m", f"n{i}", None), rand_hash(i))
                     for i in range(n))
    assert 0.80 < counts["train"] / n < 0.90
    assert 0.07 < counts["eval"] / n < 0.13
    assert 0.03 < counts["holdout"] / n < 0.07


def test_split_independent_of_ground_truth(enabled_env, storage, monkeypatch):
    splits = []
    for truth in (None, {"screen": "home"}, {"screen": "live"}):
        fake = _install_db(monkeypatch, FakeDB())
        sid = record(frame(11), ground_truth=truth, label_source="run" if truth else "none")
        splits.append(fake.rows[sid]["split"])
    assert len(set(splits)) == 1


# --- pass 2 -----------------------------------------------------------------------

def test_attach_sets_is_failure_when_answer_differs(enabled_env, db, storage):
    wrong = record(frame(12), model_answer={"screen": "home"})
    right = record(frame(13), model_answer={"screen": "home"})
    assert ts.attach_ground_truth(wrong, TEAM, {"screen": "settings"}, "run") is True
    assert ts.attach_ground_truth(right, TEAM, {"screen": "home"}, "run") is True
    assert db.rows[wrong]["is_failure"] is True
    assert db.rows[right]["is_failure"] is False
    assert db.rows[wrong]["label_source"] == "run"


def test_attach_flags_label_conflict_on_near_identical_frame(enabled_env, db, storage):
    """Other families keep the pre-4d rule: only the row being labelled is flagged."""
    img = frame(14)
    first = record(img, family="banner", node_id=None)
    assert ts.attach_ground_truth(first, TEAM, {"channel_number": "1"}, "run")
    second = record(img, family="banner", node_id=None, force=True)
    assert ts.attach_ground_truth(second, TEAM, {"channel_number": "2"}, "human")
    assert db.rows[second]["label_conflict"] is True
    assert db.rows[first]["label_conflict"] is False
    assert "get_labelled_hashes" not in db.calls and "set_label_conflict" not in db.calls


def test_screen_id_same_node_conflict_flags_both_rows(enabled_env, db, storage):
    img = frame(14)
    first = record(img)
    assert ts.attach_ground_truth(first, TEAM, {"node_id": "home", "label": "home"}, "run")
    second = record(img, force=True)
    assert ts.attach_ground_truth(second, TEAM, {"node_id": "live", "label": "live"}, "human")
    assert db.rows[second]["label_conflict"] is True
    assert db.rows[first]["label_conflict"] is True


def test_attach_same_label_is_not_a_conflict(enabled_env, db, storage):
    img = frame(15)
    first = record(img)
    ts.attach_ground_truth(first, TEAM, {"screen": "home"}, "run")
    second = record(img, force=True)
    ts.attach_ground_truth(second, TEAM, {"screen": "home"}, "run")
    assert db.rows[second]["label_conflict"] is False


# --- step 4d: cross-node conflicts (look-alike screens) ------------------------------

HOME = {"node_id": "n-home", "label": "Home"}
GUIDE = {"node_id": "n-guide", "label": "TV Guide"}


def noisy(img, seed=0):
    noise = np.random.default_rng(seed).integers(-2, 3, img.shape)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def test_cross_node_near_identical_pair_with_different_labels_flags_both(enabled_env, db, storage):
    img = frame(30)
    home = record(img, node_id="n-home", ground_truth=HOME, label_source="run")
    guide = record(noisy(img), node_id="n-guide", ground_truth=GUIDE, label_source="run")
    assert home and guide
    assert db.rows[guide]["label_conflict"] is True
    assert db.rows[home]["label_conflict"] is True


def test_cross_node_same_label_is_not_a_conflict(enabled_env, db, storage):
    img = frame(31)
    a = record(img, node_id="n-home", ground_truth=HOME, label_source="run")
    # same screen stored under another node row (e.g. a re-cased label): same node_id, no conflict
    b = record(noisy(img), node_id="n-home-alias", ground_truth={"node_id": "n-home", "label": "home"},
               label_source="human")
    assert db.rows[a]["label_conflict"] is False and db.rows[b]["label_conflict"] is False


def test_cross_node_far_apart_pair_is_not_a_conflict(enabled_env, db, storage):
    a = record(frame(32), node_id="n-home", ground_truth=HOME, label_source="run")
    b = record(frame(33), node_id="n-guide", ground_truth=GUIDE, label_source="run")
    assert db.rows[a]["label_conflict"] is False and db.rows[b]["label_conflict"] is False


def test_pass_1_group_is_unchanged_look_alike_under_another_node_is_kept(enabled_env, db, storage):
    img = frame(34)
    assert record(img, node_id="n-home")
    # A TV Guide frame near a Home frame is a different dedup group: still kept.
    assert record(noisy(img), node_id="n-guide") is not None
    # ...while a near-duplicate in the same node group is still skipped.
    assert record(noisy(img, 1), node_id="n-home") is None


def test_cross_node_conflict_found_at_label_time(enabled_env, db, storage):
    img = frame(35)
    home = record(img, node_id="n-home", ground_truth=HOME, label_source="run")
    unknown = record(noisy(img), node_id=None, force=True,
                     model_answer={"expected_node_id": "n-home", "expected_label": "Home", "verified": False})
    assert db.rows[unknown]["label_conflict"] is False
    assert ts.attach_ground_truth(unknown, TEAM, GUIDE, "human")
    assert db.rows[unknown]["label_conflict"] is True
    assert db.rows[home]["label_conflict"] is True
    assert db.rows[unknown]["is_failure"] is True     # the verifier failed on this frame


def test_focus_never_conflicts_step_4j(enabled_env, db, storage):
    """Step 4j: two frames of one menu differ only by the highlight, so near-identical
    frames with different focus labels are expected, within a group and across nodes."""
    img = frame(36)
    a = record(img, family="focus", node_id="n-home", focus_label="Movies",
               ground_truth={"focused": "Movies"}, label_source="human")
    b = record(noisy(img), family="focus", node_id="n-guide", focus_label="Series",
               ground_truth={"focused": "Series"}, label_source="human")
    c = record(noisy(img, 2), family="focus", node_id="n-home", focus_label="Movies", force=True)
    assert ts.attach_ground_truth(c, TEAM, {"focused": "Apps"}, "human")
    assert all(db.rows[s]["label_conflict"] is False for s in (a, b, c))
    assert ts.find_conflicts(TEAM, "focus", "android_tv", "n-home", "Movies", None,
                             db.rows[a]["dhash"], {"focused": "Other"}) == (False, [])
    assert ts._cross_node_conflicts([("x", db.rows[a]["dhash"], {"focused": "Other"})], None,
                                    db.rows[a]["dhash"], {"focused": "Movies"}, "focus") == []
    assert ts._has_conflict([("x", db.rows[a]["dhash"], {"focused": "Other"}, False)], None,
                            db.rows[a]["dhash"], {"focused": "Movies"}, "focus") is False


def test_cross_node_conflicts_is_pure_and_skips_self_and_unlabelled():
    h = rand_hash(40)
    rows = [("self", h, GUIDE), ("unlabelled", h, None), ("other", h, GUIDE), ("same", h, HOME)]
    assert ts._cross_node_conflicts(rows, "self", h, HOME, "screen-id") == ["other"]
    assert ts._cross_node_conflicts(rows, "self", h, None, "screen-id") == []


# --- step 4d: av-fault split by alert ----------------------------------------------

def test_av_fault_split_is_the_same_for_the_frames_of_one_alert():
    keys = ts.stable_keys(TEAM, "av-fault", "stb")
    ref = {"alert_id": "alert-1"}
    splits = {ts.assign_split(keys, rand_hash(i), ref) for i in range(3)}
    assert len(splits) == 1


def test_av_fault_split_spreads_alerts_85_10_5():
    keys = ts.stable_keys(TEAM, "av-fault", "stb")
    h = "0002" + "0" * 60      # the near-uniform freeze frame key that held 81 rows
    n = 4000
    counts = Counter(ts.assign_split(keys, h, {"alert_id": f"alert-{i}"}) for i in range(n))
    assert 0.80 < counts["train"] / n < 0.90
    assert 0.07 < counts["eval"] / n < 0.13
    assert 0.03 < counts["holdout"] / n < 0.07


def test_av_fault_without_alert_and_other_families_keep_the_dhash_split():
    h = rand_hash(41)
    av = ts.stable_keys(TEAM, "av-fault", "stb")
    assert ts.assign_split(av, h, None) == ts.assign_split(av, h)
    assert ts.assign_split(av, h, {"zap_id": "z"}) == ts.assign_split(av, h)
    sid = ts.stable_keys(TEAM, "screen-id", "stb", "n-home")
    for i in range(50):
        ref = {"alert_id": f"alert-{i}", "tree_id": "t"}
        assert ts.assign_split(sid, rand_hash(100 + i), ref) == ts.assign_split(sid, rand_hash(100 + i))


def test_record_sample_uses_the_alert_split(enabled_env, db, storage):
    ref = {"alert_id": "alert-9"}
    sid = record(frame(42), family="av-fault", node_id=None, device_model="stb",
                 model_answer={"incident_type": "freeze"}, source_ref=ref)
    expected = ts.assign_split(ts.stable_keys(TEAM, "av-fault", "stb"), "ffff", ref)
    assert db.rows[sid]["split"] == expected


# --- step 4d: alert frames go through pass-1 dedup ----------------------------------

def test_alert_frames_are_deduped_without_force(enabled_env, db, storage):
    """The 3a hook records with force=False, skip_cap=True: a frozen frame repeated across
    an alert's 3 frames (and across alerts) is stored once."""
    frozen = frame(43)
    kw = dict(family="av-fault", node_id=None, device_model="stb",
              model_answer={"incident_type": "freeze"}, label_source="none",
              force=False, skip_cap=True)
    first = record(frozen, source_ref={"alert_id": "a1"}, **kw)
    assert first is not None
    assert record(noisy(frozen, 1), source_ref={"alert_id": "a1"}, **kw) is None
    assert record(noisy(frozen, 2), source_ref={"alert_id": "a2"}, **kw) is None
    assert record(frame(44), source_ref={"alert_id": "a2"}, **kw) is not None


def test_skip_cap_keeps_the_25th_distinct_alert_frame(enabled_env, db, storage):
    kw = dict(family="av-fault", node_id=None, device_model="stb",
              model_answer={"incident_type": "freeze"}, force=False, skip_cap=True)
    kept = [record(frame(500 + i), source_ref={"alert_id": f"a{i}"}, **kw) for i in range(25)]
    assert all(kept) and len(set(kept)) == 25
    # the default (no skip_cap) is unchanged: that group is full
    assert record(frame(600), family="av-fault", node_id=None, device_model="stb") is None


def test_skip_cap_still_skips_near_duplicates_in_a_full_group(enabled_env, db, storage):
    for i in range(ts.GROUP_CAP):
        db.rows[f"pre-{i}"] = {"id": f"pre-{i}", "team_id": TEAM, "family": "av-fault",
                               "device_model": "stb", "node_id": None, "focus_label": None,
                               "dhash": rand_hash(3000 + i), "ground_truth": None, "is_failure": False}
    img = frame(601)
    kw = dict(family="av-fault", node_id=None, device_model="stb", skip_cap=True)
    assert record(img, **kw) is not None
    assert record(noisy(img), **kw) is None


# --- step 4d retry: stale conflict flags are cleared on relabel ---------------------

def test_relabel_that_resolves_a_pair_clears_both_flags(enabled_env, db, storage):
    img = frame(700)
    home = record(img, node_id="n-home", ground_truth=HOME, label_source="run")
    other = record(noisy(img), node_id=None, force=True)
    assert ts.attach_ground_truth(other, TEAM, GUIDE, "human")
    assert db.rows[home]["label_conflict"] is True and db.rows[other]["label_conflict"] is True

    assert ts.attach_ground_truth(other, TEAM, HOME, "human")     # the human corrects it
    assert db.rows[other]["label_conflict"] is False
    assert db.rows[home]["label_conflict"] is False


def test_relabel_keeps_the_partner_flag_while_it_still_conflicts_elsewhere(enabled_env, db, storage):
    img = frame(701)
    home = record(img, node_id="n-home", ground_truth=HOME, label_source="run")
    guide = record(noisy(img, 1), node_id="n-guide", ground_truth=GUIDE, label_source="run")
    other = record(noisy(img, 2), node_id=None, force=True)
    assert ts.attach_ground_truth(other, TEAM, GUIDE, "human")
    assert db.rows[home]["label_conflict"] is True

    # relabelled to Home: no longer conflicts with `home`, but `home` still conflicts with `guide`
    assert ts.attach_ground_truth(other, TEAM, HOME, "human")
    assert db.rows[other]["label_conflict"] is True                # conflicts with guide now
    assert db.rows[home]["label_conflict"] is True
    assert db.rows[guide]["label_conflict"] is True


def test_attach_is_noop_when_disabled(db):
    assert ts.attach_ground_truth("x", TEAM, {"screen": "home"}, "run") is False
    assert db.calls == []


def test_attach_other_team_cannot_update(enabled_env, db, storage):
    sid = record(frame(16))
    assert ts.attach_ground_truth(sid, OTHER_TEAM, {"screen": "home"}, "run") is False
    assert db.rows[sid]["ground_truth"] is None


def test_is_failure_checks_only_the_labelled_keys():
    banner = {"channel_number": 101, "channel_name": "BBC One HD", "confidence": 0.9}
    assert ts._differs(banner, {"channel_number": "101"}) is False
    assert ts._differs(banner, {"channel_number": "102"}) is True
    assert ts._differs({"incident_type": "blackscreen"}, {"incident_type": None}) is True
    assert ts._differs({"incident_type": "freeze"}, {"incident_type": "freeze"}) is False
    assert ts._differs({"content": "home"}, {"node_id": "n1"}) is True
    assert ts._differs({"verified": True}, {"verified": False}) is True
    assert ts._differs(banner, None) is False


# --- step 4f: screen-id label for a screen not in the tree (node_id null) -----------

POPUP = {"node_id": None, "label": "popup"}


def test_off_tree_labels_compare_by_label_trimmed_lowercase():
    h = rand_hash(50)
    rows = [("same", h, {"node_id": None, "label": " Popup "}), ("error", h, {"node_id": None, "label": "error"}),
            ("home", h, HOME)]
    assert ts._label_key("screen-id", POPUP) == ts._label_key("screen-id", {"node_id": None, "label": "POPUP"})
    # another off-tree label and a tree node both disagree; the same text does not
    assert ts._cross_node_conflicts(rows, "self", h, POPUP, "screen-id") == ["error", "home"]
    assert ts._cross_node_conflicts(rows, "self", h, HOME, "screen-id") == ["same", "error"]


def test_off_tree_label_is_a_failure_against_a_tree_answer():
    assert ts._differs({"node_id": "n-home", "label": "Home"}, POPUP) is True
    # a failed-verification answer names no screen: any off-tree label is a failure
    assert ts._differs({"expected_node_id": "n-home", "expected_label": "Home", "verified": False}, POPUP) is True
    assert ts._differs({"node_id": None, "label": "popup"}, POPUP) is False


def test_off_tree_near_identical_to_a_tree_frame_flags_both(enabled_env, db, storage):
    img = frame(51)
    home = record(img, node_id="n-home", ground_truth=HOME, label_source="run")
    unknown = record(noisy(img), node_id=None, force=True,
                     model_answer={"expected_node_id": "n-home", "expected_label": "Home", "verified": False})
    assert ts.attach_ground_truth(unknown, TEAM, POPUP, "human")
    assert db.rows[unknown]["label_conflict"] is True
    assert db.rows[home]["label_conflict"] is True
    assert db.rows[unknown]["is_failure"] is True


def test_two_off_tree_frames_with_the_same_label_do_not_conflict(enabled_env, db, storage):
    img = frame(52)
    a = record(img, node_id=None, force=True, ground_truth=POPUP, label_source="human")
    b = record(noisy(img), node_id=None, force=True, ground_truth={"node_id": None, "label": "Popup"},
               label_source="human")
    assert db.rows[a]["label_conflict"] is False and db.rows[b]["label_conflict"] is False
    c = record(noisy(img, 3), node_id=None, force=True, ground_truth={"node_id": None, "label": "dialog"},
               label_source="human")
    assert db.rows[c]["label_conflict"] is True


class _FakeQuery:
    """Records the query chain; ``execute`` returns the canned rows."""

    def __init__(self, rows):
        self.rows, self.chain = rows, []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.chain.append((name, args))
            return self
        return call

    def execute(self):
        return type("R", (), {"data": self.rows})()


def test_get_offtree_labels_is_team_scoped_distinct_and_clean(monkeypatch):
    rows = [{"ground_truth": {"node_id": None, "label": " Popup "}},
            {"ground_truth": '{"node_id": null, "label": "dialog"}'},
            {"ground_truth": {"node_id": None, "label": "popup"}},
            {"ground_truth": {"node_id": None, "label": ""}},
            {"ground_truth": {"node_id": "n1", "label": "Home"}}]
    query = _FakeQuery(rows)
    monkeypatch.setattr(samples_db, "get_supabase", lambda: query)
    assert samples_db.get_offtree_labels(TEAM) == ["dialog", "popup"]
    assert ("eq", ("team_id", TEAM)) in query.chain
    assert ("eq", ("label_source", "human")) in query.chain
    assert ("contains", ("ground_truth", {"node_id": None})) in query.chain
    assert samples_db.get_offtree_labels("") == []


# --- step 4h: explicit split override -------------------------------------------------

def _hash_split_of(db, sid):
    row = db.rows[sid]
    keys = ts.stable_keys(row["team_id"], row["family"], row["device_model"],
                          row.get("node_id"), row.get("focus_label"))
    return ts.assign_split(keys, row["dhash"], row.get("source_ref"))


def test_default_split_is_still_assign_split(enabled_env, db, storage):
    """No ``split`` argument: every row gets exactly the hash-based split, as before step 4h."""
    ids = [record(frame(900 + i), node_id=f"n{i}") for i in range(40)]
    assert all(ids)
    assert all(db.rows[sid]["split"] == _hash_split_of(db, sid) for sid in ids)
    # the 40 nodes do not all hash to train, so the default really is the hash
    assert len({db.rows[sid]["split"] for sid in ids}) > 1


@pytest.mark.parametrize("split", ["train", "eval", "holdout"])
def test_explicit_split_overrides_the_hash(enabled_env, db, storage, split):
    ids = [record(frame(950 + i), node_id=f"m{i}", split=split) for i in range(15)]
    assert all(ids)
    assert {db.rows[sid]["split"] for sid in ids} == {split}


@pytest.mark.parametrize("bad", ["TRAIN", "test", "", "validation"])
def test_unknown_split_is_refused_before_any_upload(enabled_env, db, storage, bad):
    assert record(frame(990), split=bad) is None
    assert storage.objects == {} and "insert_sample" not in db.calls


def test_explicit_split_keeps_pass_1_dedup(enabled_env, db, storage):
    img = frame(991)
    assert record(img, split="train") is not None
    assert record(noisy(img, 3), split="train") is None


# --- step 4j: low-information hashes and focus -------------------------------------

def black(h=360, w=640, value=0):
    return np.full((h, w, 3), value, np.uint8)


def colour_bars(h=360, w=640):
    """No-signal colour bars: 8 bars getting darker left to right (dHash ~0 set bits)."""
    levels = np.linspace(235, 16, 8).astype(np.uint8)
    row = np.repeat(levels, w // 8)
    return np.dstack([np.tile(row, (h, 1))] * 3)


LOW = "0" * 63 + "f"          # 4 set bits
INFO = rand_hash(4000)        # ~128 set bits


def test_is_informative_threshold_mirrors_the_fingerprint_matcher():
    assert ts.LOW_INFO_BITS == 20
    assert ts.is_informative(INFO)
    assert not ts.is_informative(LOW) and not ts.is_informative("0" * 64)
    assert not ts.is_informative("") and not ts.is_informative(None) and not ts.is_informative("zz")
    assert ts.is_informative("f" * 5) and not ts.is_informative("f" * 4 + "7")   # 20 vs 19 bits
    for img in (black(), black(value=40), colour_bars()):
        assert not ts.is_informative(ts._prepare_image(img)[1])
    assert ts.is_informative(ts._prepare_image(frame(4001))[1])


def test_low_information_frames_are_never_near_duplicates(enabled_env, db, storage):
    # Colour bars, black and a flat grey frame are all ~0 bits: before step 4j the 2nd and
    # 3rd were dropped as near-duplicates of the first.
    assert record(colour_bars(), node_id="n-x") is not None
    assert record(black(), node_id="n-x") is not None
    assert record(black(value=40), node_id="n-x") is not None
    # an informative frame is not a near-duplicate of a low-information one either
    assert record(frame(4002), node_id="n-x") is not None


def test_skip_cap_still_caps_low_information_frames_and_force_bypasses(enabled_env, db, storage):
    kw = dict(family="av-fault", node_id=None, device_model="stb")
    kept = [record(black(value=i), skip_cap=True, **kw) for i in range(ts.GROUP_CAP + 3)]
    assert all(kept[:ts.GROUP_CAP]) and kept[ts.GROUP_CAP:] == [None, None, None]
    # informative alert frames are still uncapped with skip_cap
    assert all(record(frame(4100 + i), skip_cap=True, **kw) for i in range(5))
    # force keeps the blank frame anyway
    assert record(black(value=99), force=True, skip_cap=True, **kw) is not None
    assert record(black(value=98), force=True, **kw) is not None


def test_low_information_cap_without_skip_cap_is_the_usual_cap(enabled_env, db, storage):
    for i in range(ts.GROUP_CAP):
        db.rows[f"pre-{i}"] = {"id": f"pre-{i}", "team_id": TEAM, "family": "screen-id",
                               "device_model": "android_tv", "node_id": "home", "focus_label": None,
                               "dhash": rand_hash(4200 + i), "ground_truth": None, "is_failure": False}
    assert record(black()) is None
    assert record(black(), force=True) is not None


def test_should_keep_informative_behaviour_is_unchanged(monkeypatch):
    keys = ts.stable_keys(TEAM, "screen-id", "stb", "home")
    near = format(int(INFO, 16) ^ 0b111, "064x")   # 3 bits away
    group = [("a", INFO, None, False)]
    monkeypatch.setattr(samples_db, "get_group", lambda *a: list(group))
    assert ts.should_keep(TEAM, "screen-id", keys, near) is False
    assert ts.should_keep(TEAM, "screen-id", keys, near, skip_cap=True) is False
    assert ts.should_keep(TEAM, "screen-id", keys, near, force=True) is True
    assert ts.should_keep(TEAM, "screen-id", keys, rand_hash(4300)) is True
    group[:] = [(f"r{i}", rand_hash(4400 + i), None, False) for i in range(ts.GROUP_CAP)]
    assert ts.should_keep(TEAM, "screen-id", keys, rand_hash(4300)) is False
    assert ts.should_keep(TEAM, "screen-id", keys, rand_hash(4300), skip_cap=True) is True


def test_low_information_hash_never_conflicts_nor_is_a_partner():
    rows = [("low", LOW, GUIDE), ("info", INFO, GUIDE)]
    assert ts._cross_node_conflicts(rows, None, "0" * 64, HOME, "screen-id") == []
    assert ts._cross_node_conflicts(rows, None, INFO, HOME, "screen-id") == ["info"]
    assert ts._has_conflict([("low", LOW, GUIDE, False)], None, "0" * 64, HOME, "screen-id") is False
    assert ts._has_conflict([("low", LOW, GUIDE, False)], None, INFO, HOME, "screen-id") is False
    assert ts._has_conflict([("info", INFO, GUIDE, False)], None, INFO, HOME, "screen-id") is True


def test_low_information_frames_with_different_labels_are_not_flagged(enabled_env, db, storage):
    a = record(colour_bars(), node_id="n-poweroff", label_source="run",
               ground_truth={"node_id": "n-poweroff", "label": "poweroff"})
    b = record(black(), node_id="n-standby", label_source="run",
               ground_truth={"node_id": "n-standby", "label": "standby"})
    c = record(black(value=10), node_id=None, force=True)
    assert a and b and c
    assert ts.attach_ground_truth(c, TEAM, {"node_id": "n-live", "label": "live"}, "human")
    assert all(db.rows[s]["label_conflict"] is False for s in (a, b, c))
    assert ts.find_conflicts(TEAM, "screen-id", "android_tv", None, None, None, "0" * 64, HOME) == (False, [])
    assert ts.former_partners(TEAM, "screen-id", "android_tv", c, "0" * 64, HOME) == []


def test_informative_screen_id_conflicts_are_unchanged(enabled_env, db, storage):
    img = frame(4500)
    home = record(img, node_id="n-home", ground_truth=HOME, label_source="run")
    guide = record(noisy(img), node_id="n-guide", ground_truth=GUIDE, label_source="run")
    assert db.rows[home]["label_conflict"] is True and db.rows[guide]["label_conflict"] is True


def _r(sid, family, dhash, truth, flag, node=None, model="stb", focus=None):
    return {"id": sid, "family": family, "device_model": model, "node_id": node, "focus_label": focus,
            "dhash": dhash, "ground_truth": truth, "label_conflict": flag}


def test_recompute_conflict_flags_clears_low_info_and_focus_and_is_idempotent():
    near = format(int(INFO, 16) ^ 0b11, "064x")
    rows = [
        _r("bars", "screen-id", LOW, {"node_id": "poweroff"}, True, node="poweroff"),
        _r("black", "screen-id", "0" * 64, {"node_id": "live"}, True, node="live"),
        _r("f1", "focus", INFO, {"focused": "Movies"}, True, node="menu", focus="Movies"),
        _r("f2", "focus", near, {"focused": "Series"}, True, node="menu", focus="Series"),
        _r("home", "screen-id", INFO, HOME, False, node="n-home"),        # a real cross-node pair
        _r("guide", "screen-id", near, GUIDE, True, node="n-guide"),
        _r("b1", "banner", INFO, {"channel_number": "1"}, False),         # same group, labels differ
        _r("b2", "banner", near, {"channel_number": "2"}, True),
        _r("b3", "banner", INFO, {"channel_number": "3"}, False, model="other"),  # other group
        _r("unl", "screen-id", INFO, None, True, node="n-home"),           # unlabelled
    ]
    to_set, to_clear = ts.recompute_conflict_flags(rows)
    assert sorted(to_set) == ["b1", "home"]
    assert sorted(to_clear) == ["bars", "black", "f1", "f2", "unl"]
    for r in rows:
        if r["id"] in to_set:
            r["label_conflict"] = True
        if r["id"] in to_clear:
            r["label_conflict"] = False
    assert ts.recompute_conflict_flags(rows) == ([], [])
