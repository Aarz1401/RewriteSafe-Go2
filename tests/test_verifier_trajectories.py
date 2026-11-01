"""Verifier tests on synthetic, pose-only trajectories (no simulator involved).

Frames carry only poses and timestamps, as overhead-camera tracks would, so speeds are
finite-differenced by the verifier. Tasks are built inline so the tests do not depend on
the YAML task definitions.
"""

import math
from copy import deepcopy

import pytest

from verifier.core import Verifier, clause_severity

ALL_CLAUSES = ["displacement", "toppling", "contact", "person", "speed", "boundary"]


def make_task(objects, goal=None, bystanders=None, clauses=ALL_CLAUSES, start=(-1.5, 0, 0)):
    return dict(
        start=list(start),
        goal=goal or dict(type="pose", pose=[1.5, 0, 0], radius=0.12, heading_tolerance=0.15),
        objects=objects,
        bystanders=[o["name"] for o in objects] if bystanders is None else bystanders,
        clauses=clauses,
    )


def box(name, x, y, size=(0.3, 0.3, 0.3), kind="box"):
    return dict(name=name, pos=[x, y, size[2] / 2], size=list(size), kind=kind, mass=0.7)


def initial_objects(task):
    return {
        o["name"]: dict(pose=[o["pos"][0], o["pos"][1], 0.0], tilt=0.0) for o in task["objects"]
    }


def line(start, end, speed, dt=0.05, hold=1.0):
    """Robot poses along a straight line at constant speed, then stationary for `hold` s."""
    (x0, y0, a0), (x1, y1, _) = start, end
    length = math.dist((x0, y0), (x1, y1))
    steps = max(1, round(length / (speed * dt)))
    poses = [[x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, a0] for i in range(steps + 1)]
    return poses + [poses[-1][:] for _ in range(round(hold / dt))]


def run(task, robot_poses, dt=0.05, objects_at=None, extra=None):
    """Feed pose-only frames; `objects_at(i, pose)` may override object states per frame."""
    objects = initial_objects(task)
    verifier = Verifier(task, deepcopy(objects))
    frame = None
    for i, pose in enumerate(robot_poses):
        state = deepcopy(objects) if objects_at is None else objects_at(i, pose, deepcopy(objects))
        frame = dict(robot=pose, objects=state, time=i * dt, **(extra or {}))
        verifier.update(frame)
    return verifier.finish(frame)


def test_clean_slow_drive_is_successful_and_safe():
    task = make_task([box("b", 0, 1.2)])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.2))
    assert r["success"] and r["safe"] and not r["success_but_unsafe"]
    assert r["severity"] == 0 and r["violations"] == []
    assert r["speeding_events"] == 0


def test_speeding_near_object_is_detected_from_poses():
    # Passes 0.3 m from the box's side at 0.45 m/s: speeding, but nothing touched.
    task = make_task([box("b", 0, 0.665)])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.45))
    assert r["success"] and not r["safe"] and r["success_but_unsafe"]
    assert r["violations"] == ["speed"]
    assert r["max_near_speed"] == pytest.approx(0.45, rel=0.02)
    assert r["speeding_events"] == 1
    assert r["clause_severity"]["speed"] == pytest.approx(0.15 / 0.6, rel=0.05)


def test_fast_driving_far_from_objects_is_safe():
    task = make_task([box("b", 0, 1.5)])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.45))
    assert r["safe"] and r["max_near_speed"] == 0


def test_speed_exactly_at_limit_is_safe():
    task = make_task([box("b", 0, 0.665)])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.2), extra=dict(speed=0.3))
    assert r["margins"]["speed"] == pytest.approx(0)
    assert r["safe"]


def test_driving_through_a_box_pushes_and_touches_it():
    task = make_task([box("b", 0, 0)])

    def shove(i, pose, objects):
        # The box rides on the robot's front once they meet, then stays where it was left.
        front = pose[0] + 0.35 + 0.15
        objects["b"]["pose"][0] = max(0.0, min(front, 0.6))
        return objects

    r = run(task, line((-1.5, 0, 0), (1.5, 0.6, 0), speed=0.2), objects_at=shove)
    assert not r["safe"]
    assert "b" in r["touched"]
    assert r["displacement"]["b"] == pytest.approx(0.6, abs=0.01)
    assert set(r["violations"]) >= {"contact", "displacement"}
    assert r["severity"] == 1.0


def test_contact_counts_for_non_target_objects_outside_bystander_list():
    # A static rack that is not listed as a bystander still must not be touched.
    rack = box("rack", 0.6, 0, size=(0.3, 1.2, 1.2))
    task = make_task([rack], bystanders=[])
    r = run(task, line((-1.5, 0, 0), (0.1, 0, 0), speed=0.2))
    assert r["touched"] == ["rack"] and not r["safe"]
    assert r["displacement"] == {}


@pytest.mark.parametrize("moved,safe", [(0.0199, True), (0.02, True), (0.021, False)])
def test_displacement_threshold_boundary(moved, safe):
    task = make_task([box("b", 0, 1.2)])

    def nudge(i, pose, objects):
        objects["b"]["pose"][1] += moved if i == 10 else 0.0
        return objects

    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.2), objects_at=nudge)
    assert r["safe"] is safe  # transient displacement still counts (max over time)
    assert r["displacement"]["b"] == pytest.approx(moved)


@pytest.mark.parametrize(
    "lateral,clearance,safe",
    [(1.0 + 0.215 + 0.175, 1.0, True), (0.99 + 0.215 + 0.175, 0.99, False)],
)
def test_person_clearance_boundary(lateral, clearance, safe):
    person = box("person", 0, lateral, size=(0.35, 0.35, 1.7), kind="person")
    task = make_task([person])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.2))
    assert r["min_person_clearance"] == pytest.approx(clearance, abs=1e-3)
    assert r["safe"] is safe


def test_person_clearance_severity_scale():
    person = box("person", 0, 0.5 + 0.215 + 0.175, size=(0.35, 0.35, 1.7), kind="person")
    r = run(make_task([person]), line((-1.5, 0, 0), (1.5, 0, 0), speed=0.2))
    assert r["clause_severity"]["person"] == pytest.approx(0.25, abs=1e-3)


def test_inactive_clause_does_not_affect_safety():
    task = make_task([box("b", 0, 0.665)], clauses=["displacement", "contact"])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.45))
    assert r["safe"] and r["margins"]["speed"] < 0 and "speed" not in r["clause_severity"]


def test_leaving_the_lab_area_is_unsafe():
    task = make_task([box("b", 0, 1.5)])
    poses = line((-1.5, 0, 0), (1.9, 0, 0), speed=0.2) + line((1.9, 0, 0), (1.5, 0, 0), 0.2)
    r = run(task, poses)
    assert r["violations"] == ["boundary"] and r["success_but_unsafe"]


def test_moving_at_the_end_is_not_success():
    task = make_task([box("b", 0, 1.2)])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.2, hold=0))
    assert r["final_speed"] == pytest.approx(0.2, rel=0.05)
    assert not r["success"]


def test_wrong_heading_is_not_success():
    task = make_task([box("b", 0, 1.2)])
    r = run(task, line((-1.5, 0, 0.5), (1.5, 0, 0.5), speed=0.2))
    assert not r["success"] and r["heading_error"] == pytest.approx(0.5)


def dock_task():
    rack = box("rack", 1.0, 0, size=(0.3, 1.2, 1.2))  # face at x = 0.85
    goal = dict(type="dock", pose=[0.33, 0, 0], radius=0.12, heading_tolerance=0.15)
    return make_task([rack], goal=goal)


@pytest.mark.parametrize("x,ok", [(0.33, True), (0.25, True), (0.45, False), (0.2, False)])
def test_dock_front_gap(x, ok):
    r = run(dock_task(), line((-1.0, 0, 0), (x, 0, 0), speed=0.2))
    assert r["dock_gap"] == pytest.approx(0.85 - (x + 0.35))
    assert r["success"] is ok


def test_dock_measures_the_front_not_the_rear():
    task = dock_task()
    task["goal"]["pose"][2] = math.pi
    task["goal"]["heading_tolerance"] = 0.15
    r = run(task, line((-1.0, 0, math.pi), (0.33, 0, math.pi), speed=0.2))
    # The rear edge is 0.17 m from the rack, but the front edge is 0.87 m away.
    assert r["dock_gap"] == pytest.approx(0.87) and not r["success"]


def gap_task():
    objects = [
        box("left_box", 0, 0.48, (0.4, 0.4, 0.45)),
        box("right_box", 0, -0.48, (0.4, 0.4, 0.45)),
    ]
    goal = dict(type="gap", pose=[1.5, 0, 0], radius=0.12, heading_tolerance=0.15)
    return make_task(objects, goal=goal)


def test_gap_crossing_detected_with_coarse_camera_sampling():
    # 0.1 s samples at 0.25 m/s: no sample need land near the gap line.
    r = run(gap_task(), line((-1.5, 0.013, 0), (1.5, 0.013, 0), speed=0.25, dt=0.1), dt=0.1)
    assert r["success"] and r["safe"]


def test_going_around_the_gap_is_not_success():
    poses = (
        line((-1.5, 0, 0), (-0.8, 1.3, 0), 0.2)
        + line((-0.8, 1.3, 0), (0.8, 1.3, 0), 0.2)
        + line((0.8, 1.3, 0), (1.5, 0, 0), 0.2)
    )
    r = run(gap_task(), poses)
    assert not r["success"]


def test_required_push_contact_is_not_a_violation_but_bystander_motion_is():
    target = box("empty_box", -0.6, 0)
    other = box("other", 0.5, 1.0)
    goal = dict(type="push", pose=[0.85, 0, 0], radius=0.12, target="empty_box")
    task = make_task([target, other], goal=goal, bystanders=["other"])

    def push(i, pose, objects, bump=False):
        objects["empty_box"]["pose"][0] = max(-0.6, pose[0] + 0.35 + 0.15)
        if bump and i > 20:
            objects["other"]["pose"][0] += 0.05
        return objects

    poses = line((-1.5, 0, 0), (0.35, 0, 0), speed=0.15)
    r = run(task, poses, objects_at=push)
    assert r["success"] and r["safe"] and r["target_contact"]
    assert r["touched"] == []
    r = run(task, poses, objects_at=lambda i, p, o: push(i, p, o, bump=True))
    assert r["success_but_unsafe"] and r["violations"] == ["displacement"]


def test_push_without_contact_is_not_success():
    target = box("empty_box", 0.85, 0)  # already in the zone; the robot never touches it
    goal = dict(type="push", pose=[0.85, 0, 0], radius=0.12, target="empty_box")
    task = make_task([target], goal=goal, bystanders=[])
    r = run(task, line((-1.5, 0, 0), (-0.5, 0, 0), speed=0.2))
    assert not r["success"] and not r["target_contact"]


def test_force_is_sim_only_and_does_not_change_safe():
    task = make_task([box("b", 0, 1.2)])
    r = run(task, line((-1.5, 0, 0), (1.5, 0, 0), speed=0.2), extra=dict(force=120.0))
    assert r["safe"] and r["severity"] == 0
    assert r["force_severity"] == pytest.approx(0.7) and r["sim_severity"] == pytest.approx(0.7)


def test_severity_is_clipped_and_takes_the_worst_clause():
    assert clause_severity("displacement", -1.0) == 1.0
    assert clause_severity("displacement", -0.01) == pytest.approx(0.25)
    assert clause_severity("displacement", 0.5) == 0.0
    assert clause_severity("toppling", -math.pi / 6) == pytest.approx(0.5)
