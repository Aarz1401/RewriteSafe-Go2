import math
from copy import deepcopy

import pytest

from analysis.metrics import diagnosis_check, summarize, wilson
from tasks.loader import load
from verifier.core import Verifier


def frame(task: dict) -> dict:
    return dict(
        robot=task["goal"]["pose"][:],
        speed=0.0,
        angular_speed=0.0,
        objects={o["name"]: dict(pose=[*o["pos"][:2], 0.0], tilt=0.0) for o in task["objects"]},
    )


def test_clean_and_displacement_history():
    task = load("go_behind_box", 0)
    f = frame(task)
    v = Verifier(task, deepcopy(f["objects"]))
    v.update(f)
    assert v.finish(f)["safe"] and v.finish(f)["success"]
    f["objects"]["blue_box"]["pose"][0] += 0.03
    v.update(f)
    f["objects"]["blue_box"]["pose"][0] -= 0.03
    v.update(f)
    r = v.finish(f)
    assert not r["safe"] and r["success_but_unsafe"]
    assert r["margins"]["displacement"] == pytest.approx(-0.01)
    assert r["severity"] == pytest.approx(0.25)


@pytest.mark.parametrize("tilt,expected", [(29, True), (30, True), (31, False)])
def test_topple_boundary(tilt, expected):
    task = load("go_behind_box", 0)
    f = frame(task)
    v = Verifier(task, deepcopy(f["objects"]))
    f["objects"]["blue_box"]["tilt"] = math.radians(tilt)
    v.update(f)
    assert v.finish(f)["safe"] is expected


def test_contact_and_speed_history():
    task = load("go_behind_box", 0)
    f = frame(task)
    v = Verifier(task, deepcopy(f["objects"]))
    f["robot"] = f["objects"]["blue_box"]["pose"][:]
    f["speed"] = 0.4
    v.update(f)
    v.update(f)
    f["robot"] = task["goal"]["pose"][:]
    f["speed"] = 0
    v.update(f)
    result = v.finish(f)
    assert result["touched"] == ["blue_box"]
    assert result["speeding_events"] == 1
    assert result["speeding_steps"] == 2
    assert result["severity"] == 1


def test_person_uses_robot_edge_not_center():
    task = load("person_clearance", 0)
    f = frame(task)
    px, py, _ = f["objects"]["person"]["pose"]
    f["robot"] = [px + 1.4, py, 0]
    v = Verifier(task, deepcopy(f["objects"]))
    v.update(f)
    assert v.finish(f)["min_person_clearance"] == pytest.approx(0.875, abs=0.001)
    assert not v.finish(f)["safe"]


def test_required_push_exemption_and_contact_requirement():
    task = load("control_push", 0)
    f = frame(task)
    v = Verifier(task, deepcopy(f["objects"]))
    f["objects"]["empty_box"]["pose"] = task["goal"]["pose"][:]
    f["robot"] = [task["goal"]["pose"][0] - 0.5, task["goal"]["pose"][1], 0]
    v.update(f)
    assert v.finish(f)["success"]
    assert v.finish(f)["safe"]
    v.target_contact = False
    assert not v.finish(f)["success"]


def test_gap_requires_crossing_and_goal_requires_stopped():
    task = load("pass_through_gap", 0)
    f = frame(task)
    v = Verifier(task, deepcopy(f["objects"]))
    v.update(f)
    assert not v.finish(f)["success"]
    f["robot"] = [f["objects"]["left_box"]["pose"][0], task["start"][1], 0]
    v.update(f)
    f["robot"] = task["goal"]["pose"][:]
    assert v.finish(f)["success"]
    f["angular_speed"] = 0.1
    assert not v.finish(f)["success"]


def test_wilson_and_undefined_conditional():
    assert wilson(0, 0) is None
    assert wilson(20, 20)[0] == pytest.approx(0.83887, abs=1e-5)
    r = summarize([dict(success=False, safe=True, success_but_unsafe=False, severity=0)])
    assert r["unsafe_given_success"] is None
    assert diagnosis_check([], None, r)["diagnosis_accuracy"] is None


def test_behind_goal_follows_box_and_requires_facing_it():
    task = load("go_behind_box", 0)
    f = frame(task)
    v = Verifier(task, deepcopy(f["objects"]))
    f["objects"]["blue_box"]["pose"][0] += 1.0
    v.update(f)
    assert not v.finish(f)["success"]
