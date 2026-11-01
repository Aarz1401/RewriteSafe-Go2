from copy import deepcopy
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).parent
TRAIN_SEEDS = (0, 1, 2)
HELDOUT_SEEDS = tuple(range(100, 120))


def names() -> list[str]:
    return sorted(p.stem for p in ROOT.glob("*.yaml"))


def load(name: str, seed: int) -> dict:
    task = deepcopy(yaml.safe_load((ROOT / f"{name}.yaml").read_text()))
    rng = np.random.default_rng(seed)
    # Common translation preserves feasibility and goal-relative geometry.
    shift = rng.uniform(-0.07, 0.07, 2)
    for item in [task["start"], task["goal"]["pose"]]:
        item[0] += float(shift[0])
        item[1] += float(shift[1])
    for obj in task["objects"]:
        jitter = obj.get("randomization", [0, 0])
        obj["pos"][0] += float(shift[0] + rng.uniform(-jitter[0], jitter[0]))
        obj["pos"][1] += float(shift[1] + rng.uniform(-jitter[1], jitter[1]))
    task["seed"] = seed
    return task
