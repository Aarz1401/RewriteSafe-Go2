import math

import numpy as np
import pytest

from agent.prompts import mock_reply, task_prompt
from agent.runner import validate
from analysis.calibrate import fit_tracking
from experiments.run import episode
from robot.sim_backend import SimBackend, SimConfig
from tasks.goals import resolve_goal
from tasks.loader import load, names


@pytest.mark.parametrize("seed", [101, 102, 105])
def test_corridor_goal_region_regression(seed):
    result = episode("cluttered_corridor", seed, "careful")
    assert result["success"] and result["safe"] and result["error"] is None


@pytest.mark.parametrize("task", names())
def test_public_goal_and_prompt_for_every_task(task):
    api = SimBackend(load(task, 301))
    goal = api.get_task_goal()
    assert len(goal["pose"]) == 3 and all(math.isfinite(v) for v in goal["pose"])
    goal["pose"][0] = 999
    assert api.get_task_goal()["pose"][0] != 999
    assert "seed" not in api.get_task_goal()
    assert "pose" not in task_prompt(task)["goal"]
    for iteration in (0, 1):
        assert not validate(mock_reply(task, iteration)["program"])
    api.close()


def test_behind_goal_updates_when_box_moves():
    task = load("go_behind_box", 0)
    initial = {"blue_box": {"pose": [0, 0, 0]}}
    before = resolve_goal(task, initial, initial)
    after = resolve_goal(task, initial, {"blue_box": {"pose": [0.4, 0.2, 0]}})
    assert np.subtract(after["pose"][:2], before["pose"][:2]) == pytest.approx([0.4, 0.2])


def test_tower_is_stable_without_contact_and_topples_when_hit():
    api = SimBackend(load("past_tower", 0))
    api.sleep(10)
    assert max(api.verifier.tilt.values()) < math.radians(5)
    api.close()
    result = episode("past_tower", 0, "naive")
    assert result["physics_contacts"]
    assert max(result["tilt"].values()) > math.pi / 6
    careful = episode("past_tower", 0, "careful")
    assert careful["success"] and careful["safe"]


def test_calibration_recovers_synthetic_tracking_parameters():
    commands = np.tile(np.repeat([0.0, 0.4, 0.0, -0.3, 0.0], 100), 2)
    velocities = np.zeros(len(commands))
    for i in range(len(commands) - 1):
        command = commands[i - 6] if i >= 6 else 0.0
        velocities[i + 1] = velocities[i] + 0.01 * np.clip(
            (command - velocities[i]) / 0.08, -0.8, 0.8
        )
    rows = [
        dict(t=i * 0.01, command_vx=float(c), measured_vx=float(v))
        for i, (c, v) in enumerate(zip(commands, velocities))
    ]
    result = fit_tracking(rows)
    assert result["latency"] == 0.06
    assert result["acceleration"] == 0.8 and result["tracking_tau"] == 0.08
    assert result["rmse"] < 1e-10
    rows[3]["t"] += 0.005
    with pytest.raises(ValueError, match="100 Hz"):
        fit_tracking(rows)


@pytest.mark.parametrize("kwargs", [{"latency": -1}, {"noise": float("nan")}, {"tracking_tau": 0}])
def test_invalid_dynamics_config(kwargs):
    with pytest.raises(ValueError):
        SimConfig(**kwargs)


def test_latency_has_no_extra_control_step():
    api = SimBackend(load("dock_at_rack", 0), SimConfig(latency=0.02, noise=0))
    api.set_velocity(0.2, 0, 0)
    api.sleep(0.02)
    assert api.snapshot()["speed"] == 0
    api.sleep(0.01)
    assert api.snapshot()["speed"] > 0
    api.close()
