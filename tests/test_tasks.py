"""M3 task definitions and baselines (training seeds only; held-out seeds are for measurement)."""

import math

import pytest

from experiments.run import episode
from tasks.loader import DEV_SEEDS, HELDOUT_SEEDS, TRAIN_SEEDS, load, names, problems

TASKS = [
    "cluttered_corridor", "control_push", "dock_at_rack", "go_behind_box",
    "handoff_point", "pass_through_gap", "past_tower", "person_clearance",
]  # fmt: skip


def test_eight_tasks_and_disjoint_seed_sets():
    assert names() == TASKS
    assert not set(TRAIN_SEEDS) & set(HELDOUT_SEEDS)
    assert not set(DEV_SEEDS) & (set(TRAIN_SEEDS) | set(HELDOUT_SEEDS))


@pytest.mark.parametrize("name", TASKS)
def test_layouts_are_valid_deterministic_and_recorded(name):
    tasks = [load(name, seed) for seed in (*TRAIN_SEEDS, *HELDOUT_SEEDS)]
    for task in tasks:
        assert problems(task) == []
        assert task["layout"]["seed"] == task["seed"]
        assert task["instruction"] == tasks[0]["instruction"]  # seed-independent
    assert load(name, 101) == load(name, 101)
    # Layouts actually vary across seeds (more than the old +/-7 cm shift).
    starts = {tuple(t["start"]) for t in tasks}
    assert len(starts) == len(tasks)
    spread = max(
        max(t["layout"]["objects"][o][1] for t in tasks)
        - min(t["layout"]["objects"][o][1] for t in tasks)
        for o in tasks[0]["layout"]["objects"]
    )
    assert spread > 0.2


def test_goals_follow_their_anchor_objects():
    for seed in TRAIN_SEEDS:
        dock = load("dock_at_rack", seed)
        rack = dock["layout"]["objects"]["rack"]
        assert dock["goal"]["pose"][0] == pytest.approx(rack[0] - 0.70)
        behind = load("go_behind_box", seed)
        box = behind["layout"]["objects"]["blue_box"]
        gx, gy, gyaw = behind["goal"]["pose"]
        assert math.dist((gx, gy), box[:2]) == pytest.approx(0.85)
        assert math.cos(gyaw - math.atan2(box[1] - gy, box[0] - gx)) == pytest.approx(1)


@pytest.mark.parametrize("name", TASKS)
def test_baselines_on_a_training_seed(name):
    careful = episode(name, 0, "careful")
    assert careful["success"] and careful["safe"], careful["violations"]
    naive = episode(name, 0, "naive")
    assert not naive["safe"]
    assert naive["layout"] == careful["layout"]
