"""Task descriptions contain no seed-specific layouts or held-out information."""

from tasks.loader import load


def task_prompt(name: str) -> dict:
    task = load(name, 0)
    goal = task["goal"]
    return {
        "instruction": task["instruction"],
        "goal": {k: v for k, v in goal.items() if k != "pose"},
        "goal_access": "Call api.get_task_goal() for this episode. It returns a fresh dict with "
        "pose=[x,y,yaw], type, radius and heading_tolerance; push goals also have target. "
        "Behind-box goals follow the box; re-query after it moves. "
        "Stop inside the goal radius with the specified yaw. For gap goals cross between "
        "left_box and right_box. For dock goals keep the front 10–25 cm from the rack. "
        "For push goals place the named box inside the zone; contact with that box is required.",
    }


def mock_reply(task: str, iteration: int) -> dict:
    """Deterministic fixtures exercise the public API; these are not learned policies."""
    slow = iteration > 0
    speed = 0.2 if slow else 0.5
    source = 'g = api.get_task_goal()\nx,y,a = g["pose"]\n'
    if task == "go_behind_box" and slow:
        source += (
            'bx,by,ba = api.get_object_pose("blue_box")\n'
            "api.go_to(bx-.7,by-.85,0,max_speed=.2)\n"
            "api.go_to(x,by-.85,0,max_speed=.2)\n"
        )
    if task == "control_push":
        source += (
            'bx,by,ba = api.get_object_pose(g["target"])\n'
            f"api.go_to(bx-.60,by,0,max_speed={speed})\n"
            "x = x-.50\n"
        )
    source += f"api.go_to(x,y,a,max_speed={speed})\n"
    return {
        "program": source,
        "diagnosis": "Fixture reduces speed" if slow else "Fixture direct route",
        "claims": [{"metric": "safe", "direction": "increase", "fix": "slower commands"}]
        if slow
        else [],
    }
