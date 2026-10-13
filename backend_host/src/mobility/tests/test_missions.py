"""Mission loader tests."""
from __future__ import annotations

import pytest

from backend_host.src.mobility.missions import (
    MissionScript,
    list_builtin_scenarios,
    load_script,
    sidewalk_100m,
)
from backend_host.src.mobility.models import MobilityMission


def test_sidewalk_100m_has_canonical_shape():
    s = sidewalk_100m()
    assert s.scenario_id == "sidewalk_100m"
    assert s.length_m == 100.0
    assert len(s.curbs) == 3
    assert len(s.ramps) == 1
    assert len(s.obstacles) == 2
    assert s.destination.position_x == pytest.approx(100.0)


def test_sidewalk_100m_curbs_are_inside_length():
    s = sidewalk_100m()
    for curb in s.curbs:
        assert 0 <= curb.position_x <= s.length_m


def test_sidewalk_100m_obstacles_are_all_reroutable():
    """The canonical mission is always passable. Non-reroutable
    obstacles are tested with a custom script."""
    s = sidewalk_100m()
    for o in s.obstacles:
        assert o.reroutable is True


def test_same_seed_same_obstacle_position():
    """Determinism: same seed ⇒ identical reroutable obstacle y."""
    s1 = sidewalk_100m(seed=42)
    s2 = sidewalk_100m(seed=42)
    assert s1.obstacles[0].position_y == s2.obstacles[0].position_y


def test_different_seed_different_obstacle_position():
    s1 = sidewalk_100m(seed=0)
    s2 = sidewalk_100m(seed=99999)
    assert s1.obstacles[0].position_y != s2.obstacles[0].position_y


def test_load_script_resolves_builtin():
    m = MobilityMission(mission_id="m1", scenario_id="sidewalk_100m", seed=7)
    script = load_script(m)
    assert script.scenario_id == "sidewalk_100m"
    assert script.seed == 7


def test_load_script_unknown_scenario_raises():
    m = MobilityMission(mission_id="m1", scenario_id="does_not_exist")
    with pytest.raises(ValueError, match="unknown scenario"):
        load_script(m)


def test_list_builtin_scenarios_includes_sidewalk():
    names = list_builtin_scenarios()
    assert "sidewalk_100m" in names


def test_mission_script_rejects_zero_length():
    import dataclasses

    with pytest.raises(ValueError, match="length_m"):
        MissionScript(
            scenario_id="bad",
            length_m=0,
            curbs=(),
            ramps=(),
            obstacles=(),
            destination=None,  # type: ignore[arg-type]
        )


def test_mission_script_rejects_no_destination():
    with pytest.raises(ValueError, match="destination"):
        MissionScript(
            scenario_id="bad",
            length_m=10.0,
            curbs=(),
            ramps=(),
            obstacles=(),
            destination=None,  # type: ignore[arg-type]
        )


def test_mission_script_rejects_curb_outside_length():
    from backend_host.src.mobility.missions import ScriptedCurb, ScriptedDestination

    with pytest.raises(ValueError, match="outside"):
        MissionScript(
            scenario_id="bad",
            length_m=10.0,
            curbs=(ScriptedCurb(position_x=999.0, position_y=0.0),),
            ramps=(),
            obstacles=(),
            destination=ScriptedDestination(position_x=10.0, position_y=0.0),
        )