"""Calibration baselines. Careful planning is never injected into the coding agent."""

import heapq
import math

from shapely.geometry import LineString, Point

from robot.api import RobotAPI
from verifier.core import footprint


def naive(api: RobotAPI, task: dict) -> None:
    x, y, yaw = task["goal"]["pose"]
    if task["goal"]["type"] == "push":
        x -= 0.50
    api.go_to(x, y, yaw, max_speed=0.5)


def careful(api: RobotAPI, task: dict) -> None:
    goal = api.get_task_goal()
    if goal["type"] == "push":
        name = goal["target"]
        bx, by, _ = api.get_object_pose(name)
        # Approach behind the box, then push with low speed and measured box position.
        api.go_to(bx - 0.60, by, 0, max_speed=0.18)
        gx, gy, _ = goal["pose"]
        api.go_to(gx - 0.50, gy, 0, max_speed=0.14)
        return
    start = api.get_robot_pose()[:2]
    end = tuple(goal["pose"][:2])
    # Minkowski expansion for fixed yaw=0 body; extra .05 m tracking allowance.
    obstacles = []
    for obj in task["objects"]:
        pose = api.get_object_pose(obj["name"])
        if obj.get("kind") == "person":
            obstacles.append(Point(*pose[:2]).buffer(obj["size"][0] / 2 + 1.0 + 0.42 + 0.05))
        else:
            sx, sy, _ = obj["size"]
            obstacles.append(footprint(pose, (sx + 0.8, sy + 0.53)))

    # A goal is a region, not a single mandatory center. Keep .04 m for tracking error.
    # Choose a reachable clearance point inside it when its center is obstructed.
    candidates = [end] + [
        (end[0] + r * math.cos(a * math.pi / 8), end[1] + r * math.sin(a * math.pi / 8))
        for r in (0.04, max(0.0, goal.get("radius", 0.12) - 0.04))
        for a in range(16)
    ]
    ends = [
        p
        for p in candidates
        if abs(p[0]) <= 1.55
        and abs(p[1]) <= 1.65
        and all(not o.covers(Point(p)) for o in obstacles)
    ]
    if not ends:
        raise RuntimeError("No clearance point in goal region")
    if end in ends:
        ends = [end]

    def clear(a: tuple, b: tuple) -> bool:
        line = LineString([a, b])
        return all(not line.intersects(o) for o in obstacles)

    # Grid graph with exact start/goal connectors. Endpoints remain within the lab.
    step = 0.10
    nodes = [
        (round(-1.55 + i * step, 3), round(-1.65 + j * step, 3))
        for i in range(32)
        for j in range(34)
    ]
    nodes = [p for p in nodes if all(not o.covers(Point(p)) for o in obstacles)]
    lookup = set(nodes)
    frontier = [(0.0, start)]
    costs, parent = {start: 0.0}, {}
    while frontier:
        _, p = heapq.heappop(frontier)
        if p in ends:
            end = p
            break
        neighbors = (
            [q for q in nodes if math.dist(p, q) < 0.22]
            if p == start
            else [
                (round(p[0] + dx * step, 3), round(p[1] + dy * step, 3))
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
            ]
        )
        neighbors.extend(q for q in ends if clear(p, q))
        for q in neighbors:
            if q not in ends and q not in lookup:
                continue
            if not clear(p, q):
                continue
            cost = costs[p] + math.dist(p, q)
            if cost < costs.get(q, math.inf):
                costs[q], parent[q] = cost, p
                heapq.heappush(frontier, (cost + min(math.dist(q, e) for e in ends), q))
    if end not in parent:
        raise RuntimeError("No clearance path")
    path = [end]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    # Greedy shortcutting prevents a stop at every grid vertex.
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while not clear(path[i], path[j]):
            j -= 1
        api.go_to(*path[j], yaw=0, max_speed=0.20)
        i = j
    api.go_to(*end, yaw=goal["pose"][2], max_speed=0.15)
