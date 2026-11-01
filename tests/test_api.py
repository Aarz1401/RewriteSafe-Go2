import math

import pytest

from robot.api import API_FUNCTIONS, ProgramAPI, RobotAPI
from robot.real_backend import RealBackend
from robot.sim_backend import SimBackend, SimConfig
from tasks.loader import HELDOUT_SEEDS, TRAIN_SEEDS, load, names


def test_cap_lateral_latency_and_stop():
    task = load("go_behind_box", 0)
    task["objects"] = []
    task["bystanders"] = []
    api = SimBackend(task, SimConfig(lateral=False, noise=0))
    initial = api.get_robot_pose()
    api.set_velocity(100, 100, 0)
    api.sleep(0.04)
    assert api.get_robot_pose() == initial
    api.sleep(0.6)
    assert api.snapshot()["speed"] <= 0.5 + 1e-6
    assert api.get_robot_pose()[1] == initial[1]
    api.stop()
    assert api.snapshot()["speed"] < 0.025
    with pytest.raises(ValueError):
        api.set_velocity(math.nan, 0, 0)
    with pytest.raises(ValueError):
        api.sleep(-1)
    api.close()


def test_goal_and_determinism():
    poses = []
    for _ in range(2):
        api = SimBackend(load("go_behind_box", 0))
        api.go_to(-1.0, -0.7, 0, max_speed=0.2)
        poses.append(api.get_robot_pose())
        assert math.dist(poses[-1][:2], (-1.0, -0.7)) < 0.04
        api.close()
    assert poses[0] == poses[1]


def test_physical_push_and_tasks_load():
    assert len(names()) == 8
    assert set(TRAIN_SEEDS).isdisjoint(HELDOUT_SEEDS)
    api = SimBackend(load("control_push", 0))
    initial = api.get_object_pose("empty_box")
    api.go_to(0.35, 0, 0, max_speed=0.2)
    assert api.get_object_pose("empty_box")[0] > initial[0] + 0.1
    assert api.verifier.target_contact
    api.close()


def test_program_api_proxy_hides_backend():
    api = SimBackend(load("go_behind_box", 0))
    proxy = ProgramAPI(api)
    assert set(API_FUNCTIONS) <= set(dir(proxy))
    for hidden in ("_data", "_model", "config", "verifier", "task", "snapshot"):
        assert not hasattr(proxy, hidden)
    with pytest.raises(AttributeError):
        proxy.speed_cap = 5.0
    assert proxy.get_robot_pose() == api.get_robot_pose()
    api.close()


def test_real_backend_is_a_stub():
    assert isinstance(SimBackend(load("go_behind_box", 0)), RobotAPI)
    assert RealBackend.speed_cap == 0.3
    with pytest.raises(NotImplementedError):
        RealBackend()


def test_latency_is_exact_number_of_steps():
    task = load("go_behind_box", 0)
    task["objects"], task["bystanders"] = [], []
    api = SimBackend(task, SimConfig(latency=0.05, noise=0))
    x0 = api.get_robot_pose()[0]
    api.set_velocity(0.3, 0, 0)
    api.sleep(0.05)  # command still in the latency queue: no force applied yet
    assert api.get_robot_pose()[0] == x0
    api.sleep(0.02)
    assert api.get_robot_pose()[0] > x0
    api.close()
