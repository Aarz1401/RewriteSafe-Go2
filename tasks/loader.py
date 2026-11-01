"""Seeded task layouts from the YAML task definitions.

YAML schema (all lengths in metres, angles in radians, lab = 4 x 4 m centred at origin):

    name, instruction            instruction may use {goal_x} {goal_y} {goal_yaw} {goal_deg}
    start: [x, y, yaw]           start_randomization: [dx, dy, dyaw] (uniform +/-)
    groups: {name: [dx, dy]}     one shared random offset per group (towers, box pairs)
    objects:                     name, kind (box|cone|person), pos [x, y, z], size [sx, sy, sz],
                                 mass, dynamic (default true), rgba, group,
                                 randomization: [dx, dy]
    goal:                        type: pose | behind | dock | gap | push
                                 pose: [x, y, yaw] (absolute), or relative_to: object with
                                 offset: [dx, dy] (world frame), or for `behind`: anchor + offset
                                 randomization: [dx, dy], yaw_choices: [...], radius,
                                 heading_tolerance, target (push)
    bystanders: [names]          objects whose displacement/tilt is checked
    clauses: [names]             active safety clauses (see verifier/core.py)
    min_separation, start_clearance   layout validity margins (separation applies
                                 between movable objects; 0.1 m against static ones)

Each seed draws a layout with its own RNG stream; invalid layouts (overlapping objects,
objects outside the lab, an object on the start or goal footprint) are redrawn
deterministically. The drawn layout is stored in the task dict and logged per episode.
"""

import math
import zlib
from copy import deepcopy
from pathlib import Path

import numpy as np
import yaml
from shapely.geometry import Polygon

from verifier.core import LAB_HALF_SIZE, PERSON_CLEARANCE, ROBOT_FOOTPRINT, footprint

ROOT = Path(__file__).parent
TRAIN_SEEDS = (0, 1, 2)
HELDOUT_SEEDS = tuple(range(100, 120))
# Extra seeds for developing the hand-written baselines; disjoint from both sets above.
DEV_SEEDS = tuple(range(1000, 1020))
MAX_DRAWS = 200

assert not set(TRAIN_SEEDS) & set(HELDOUT_SEEDS)
assert not set(DEV_SEEDS) & (set(TRAIN_SEEDS) | set(HELDOUT_SEEDS))


def names() -> list[str]:
    return sorted(p.stem for p in ROOT.glob("*.yaml"))


def spec(name: str) -> dict:
    return yaml.safe_load((ROOT / f"{name}.yaml").read_text())


def _uniform(rng: np.random.Generator, half: list | None, n: int) -> np.ndarray:
    half = np.zeros(n) if half is None else np.asarray(half, dtype=float)
    return rng.uniform(-half, half) if half.any() else np.zeros(n)


def _draw(base: dict, rng: np.random.Generator) -> dict:
    task = deepcopy(base)
    task["start"] = [
        float(v) for v in np.add(base["start"], _uniform(rng, base.get("start_randomization"), 3))
    ]
    offsets = {g: _uniform(rng, half, 2) for g, half in (base.get("groups") or {}).items()}
    for obj in task["objects"]:
        shift = offsets.get(obj.get("group"), np.zeros(2)) + _uniform(
            rng, obj.get("randomization"), 2
        )
        obj["pos"] = [float(obj["pos"][0] + shift[0]), float(obj["pos"][1] + shift[1]),
                      float(obj["pos"][2])]  # fmt: skip
    goal = task["goal"]
    positions = {o["name"]: o["pos"] for o in task["objects"]}
    if goal["type"] == "behind":
        bx, by = positions[goal["anchor"]][:2]
        dx, dy = bx - task["start"][0], by - task["start"][1]
        norm = math.hypot(dx, dy)
        offset = goal.get("offset", 0.85)
        x, y = bx + offset * dx / norm, by + offset * dy / norm
        yaw = math.atan2(by - y, bx - x)
    else:
        if "relative_to" in goal:
            ax, ay = positions[goal["relative_to"]][:2]
            x, y = ax + goal["offset"][0], ay + goal["offset"][1]
            yaw = goal["offset"][2] if len(goal["offset"]) > 2 else 0.0
        else:
            x, y, yaw = goal["pose"]
            if goal.get("group"):
                x, y = np.add([x, y], offsets[goal["group"]])
        x, y = np.add([x, y], _uniform(rng, goal.get("randomization"), 2))
        if goal.get("yaw_choices"):
            yaw = float(rng.choice(goal["yaw_choices"]))
    goal["pose"] = [float(x), float(y), float(yaw)]
    return task


def _shape(obj: dict):
    return footprint([*obj["pos"][:2], 0.0], obj["size"], obj.get("kind", "box"))


def problems(task: dict) -> list[str]:
    """Reasons a drawn layout is invalid (empty list = valid)."""
    out = []
    h = LAB_HALF_SIZE - 0.02
    lab = Polygon([(-h, -h), (h, -h), (h, h), (-h, h)])
    robot_start = footprint(task["start"], ROBOT_FOOTPRINT)
    goal = task["goal"]
    shapes = {o["name"]: _shape(o) for o in task["objects"]}
    if not lab.covers(robot_start):
        out.append("start outside lab")
    if goal["type"] == "push":
        target = next(o for o in task["objects"] if o["name"] == goal["target"])
        goal_shape = footprint(goal["pose"], target["size"])
    else:
        goal_shape = footprint(goal["pose"], ROBOT_FOOTPRINT)
    if not lab.covers(goal_shape):
        out.append("goal outside lab")
    separation = task.get("min_separation", 0.15)
    clearance = task.get("start_clearance", 0.3)
    objects = task["objects"]
    for i, obj in enumerate(objects):
        shape = shapes[obj["name"]]
        if obj.get("dynamic", True) and not lab.covers(shape):
            out.append(f"{obj['name']} outside lab")
        if shape.distance(robot_start) < clearance:
            out.append(f"{obj['name']} too close to start")
        if obj["name"] != goal.get("target") and shape.distance(goal_shape) < 0.05:
            out.append(f"{obj['name']} blocks goal")
        if obj.get("kind") == "person":
            # The task must be completable safely: start and goal respect the clearance.
            for label, robot in (("start", robot_start), ("goal", goal_shape)):
                if shape.distance(robot) < PERSON_CLEARANCE + 0.1:
                    out.append(f"{label} too close to {obj['name']}")
        for other in objects[i + 1 :]:
            same_group = obj.get("group") and obj.get("group") == other.get("group")
            both_dynamic = obj.get("dynamic", True) and other.get("dynamic", True)
            needed = separation if both_dynamic else 0.1
            if not same_group and shape.distance(shapes[other["name"]]) < needed:
                out.append(f"{obj['name']} overlaps {other['name']}")
    return out


def load(name: str, seed: int) -> dict:
    base = spec(name)
    rng = np.random.default_rng([seed, zlib.crc32(name.encode())])
    for draw in range(MAX_DRAWS):
        task = _draw(base, rng)
        if not problems(task):
            break
    else:
        raise RuntimeError(f"{name}: no valid layout for seed {seed} in {MAX_DRAWS} draws")
    gx, gy, gyaw = task["goal"]["pose"]
    task["instruction"] = (
        base["instruction"]
        .format(goal_x=gx, goal_y=gy, goal_yaw=gyaw, goal_deg=math.degrees(gyaw))
        .strip()
    )
    task["seed"] = seed
    task["layout"] = dict(
        seed=seed,
        draws=draw + 1,
        start=task["start"],
        goal=task["goal"]["pose"],
        objects={o["name"]: o["pos"] for o in task["objects"]},
    )
    return task
