"""Public task goal metadata, resolved for the current episode without revealing its seed."""

import math
from copy import deepcopy


def resolve_goal(task: dict, initial: dict, current: dict) -> dict:
    goal = deepcopy(task["goal"])
    if goal["type"] == "behind":
        name = goal["anchor"]
        ix, iy, _ = initial[name]["pose"]
        dx, dy = ix - task["start"][0], iy - task["start"][1]
        distance = math.hypot(dx, dy)
        bx, by, _ = current[name]["pose"]
        goal["pose"] = [bx + 0.85 * dx / distance, by + 0.85 * dy / distance, math.atan2(-dy, -dx)]
    return goal
