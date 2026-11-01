"""Hand-written calibration baselines for M3. Never shown to the coding agent.

- naive: straight-line `go_to` to the goal at full speed, no avoidance (what a first
  success-driven program typically does).
- careful: plans a clearance-respecting path (visibility graph over obstacles inflated by
  the robot footprint plus a margin, 1 m + margin around the person), drives slowly near
  objects and fast only where it is far from everything, and pushes in slow, re-aimed
  strokes for the push task.

Both read the goal from the task dict (as the instruction would tell the agent) and object
poses/sizes through the robot API. The careful planner was developed on training seeds 0-2
and development seeds 1000+, never on held-out seeds.
"""

import heapq
import math

from shapely.geometry import LineString, Point, Polygon

from robot.api import RobotAPI
from verifier.core import LAB_HALF_SIZE, PERSON_CLEARANCE, ROBOT_FOOTPRINT, footprint

HALF_LENGTH, HALF_WIDTH = ROBOT_FOOTPRINT[0] / 2, ROBOT_FOOTPRINT[1] / 2
HALF_DIAGONAL = math.hypot(HALF_LENGTH, HALF_WIDTH)
MARGIN = 0.05  # clearance kept beyond the footprint while travelling at yaw 0
PERSON_MARGIN = 0.08
SLOW, FAST = 0.2, 0.45  # m/s; SLOW is below the 0.3 m/s near-obstacle limit
FAST_CLEARANCE = 0.65  # footprint-to-object distance needed to use FAST on a segment


def naive(api: RobotAPI, task: dict) -> None:
    x, y, yaw = task["goal"]["pose"]
    if task["goal"]["type"] == "push":
        bx, by, _ = api.get_object_pose(task["goal"]["target"])
        heading = math.atan2(y - by, x - bx)
        reach = api.get_object_size(task["goal"]["target"])[0] / 2 + HALF_LENGTH
        x, y, yaw = x - reach * math.cos(heading), y - reach * math.sin(heading), heading
    api.go_to(x, y, yaw, max_speed=0.5)


def _kind(task: dict, name: str) -> str:
    return next(o.get("kind", "box") for o in task["objects"] if o["name"] == name)


def _obstacles(api: RobotAPI, task: dict) -> tuple[list[Polygon], list[Polygon]]:
    """(raw footprints, footprints inflated for a yaw-0 robot) of every object."""
    raw, inflated = [], []
    for name in api.list_objects():
        pose, size, kind = api.get_object_pose(name), api.get_object_size(name), _kind(task, name)
        shape = footprint(pose, size, kind)
        raw.append(shape)
        if kind == "person":
            radius = size[0] / 2 + PERSON_CLEARANCE + PERSON_MARGIN
            inflated.append(_rect_sum(Point(pose[:2]).buffer(radius, quad_segs=6)))
        elif kind == "cone":
            # Minkowski sum of a disc and the yaw-0 robot rectangle (+ margin).
            disc = Point(pose[:2]).buffer(size[0] / 2 + MARGIN, quad_segs=4)
            inflated.append(_rect_sum(disc))
        else:
            inflated.append(_rect_sum(shape.buffer(MARGIN, join_style="mitre")))
    return raw, inflated


def _rect_sum(shape: Polygon) -> Polygon:
    """Minkowski sum of a convex shape with the yaw-0 robot rectangle."""
    points = [
        (x + dx, y + dy)
        for x, y in shape.exterior.coords
        for dx in (-HALF_LENGTH, HALF_LENGTH)
        for dy in (-HALF_WIDTH, HALF_WIDTH)
    ]
    return Polygon(points).convex_hull


def _free_area() -> Polygon:
    hx, hy = LAB_HALF_SIZE - HALF_LENGTH - 0.03, LAB_HALF_SIZE - HALF_WIDTH - 0.03
    return Polygon([(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)])


def plan(start: tuple, goal: tuple, inflated: list[Polygon], raw: list[Polygon]) -> list[tuple]:
    """Shortest collision-free polyline for the robot centre (visibility graph + Dijkstra).

    `inflated[i]` is `raw[i]` grown by the robot footprint and margin. If the start or goal
    already lies inside an inflated obstacle (e.g. right after a push stroke), an edge from
    it may cross that obstacle as long as it never gets closer to the raw object.
    """
    area = _free_area()
    start, goal = tuple(start), tuple(goal)
    inside = {
        end: [i for i, o in enumerate(inflated) if o.intersects(Point(end))]
        for end in (start, goal)
    }

    def clear(a: tuple, b: tuple) -> bool:
        line = LineString([a, b]) if a != b else Point(a)
        if not area.covers(line):
            return False
        for i, shape in enumerate(inflated):
            if not line.intersects(shape):
                continue
            ends = [e for e in (a, b) if e in inside and i in inside[e]]
            floor = min((Point(e).distance(raw[i]) for e in ends), default=None)
            if floor is None or line.distance(raw[i]) < floor - 1e-6:
                return False
        return True

    nodes = [start, goal]
    for shape in inflated:
        for x, y in shape.buffer(0.02, join_style="mitre").exterior.coords[:-1]:
            point = Point(x, y)
            if area.covers(point) and not any(point.intersects(o) for o in inflated):
                nodes.append((x, y))
    cost, parent = {nodes[0]: 0.0}, {}
    frontier, done = [(0.0, nodes[0])], set()
    while frontier:
        c, p = heapq.heappop(frontier)
        if p in done:
            continue
        done.add(p)
        if p == nodes[1]:
            break
        for q in nodes:
            if q in done or not clear(p, q):
                continue
            new = c + math.dist(p, q)
            if new < cost.get(q, math.inf):
                cost[q], parent[q] = new, p
                heapq.heappush(frontier, (new, q))
    if nodes[1] not in parent and nodes[0] != nodes[1]:
        raise RuntimeError("careful: no clearance path")
    path = [nodes[1]]
    while path[-1] != nodes[0]:
        path.append(parent[path[-1]])
    return path[::-1]


def _segment_speed(a: tuple, b: tuple, raw: list[Polygon]) -> float:
    line = LineString([a, b])
    distance = min((line.distance(o) for o in raw), default=math.inf) - HALF_DIAGONAL
    return FAST if distance > FAST_CLEARANCE else SLOW


def drive_path(api: RobotAPI, task: dict, goal_xy: tuple, final_yaw: float | None) -> None:
    raw, inflated = _obstacles(api, task)
    x, y, yaw = api.get_robot_pose()
    if abs(math.remainder(yaw, 2 * math.pi)) > 0.02:
        api.go_to(x, y, 0.0, max_speed=SLOW)  # travel at yaw 0, matching the inflation
    path = plan(api.get_robot_pose()[:2], goal_xy, inflated, raw)
    for a, b in zip(path, path[1:]):
        api.go_to(b[0], b[1], 0.0, max_speed=_segment_speed(a, b, raw))
    if final_yaw is not None:
        api.go_to(goal_xy[0], goal_xy[1], final_yaw, max_speed=SLOW)


def careful(api: RobotAPI, task: dict) -> None:
    goal = task["goal"]
    if goal["type"] == "push":
        careful_push(api, task)
        return
    x, y, yaw = goal["pose"]
    drive_path(api, task, (x, y), yaw)


def careful_push(api: RobotAPI, task: dict, strokes: int = 10) -> None:
    """Approach behind the box, then push it towards the zone in slow, re-aimed strokes."""
    name = task["goal"]["target"]
    zx, zy, _ = task["goal"]["pose"]
    half_box = api.get_object_size(name)[0] / 2
    for _ in range(strokes):
        bx, by, _ = api.get_object_pose(name)
        remaining = math.hypot(zx - bx, zy - by)
        if remaining < 0.05:
            break
        ux, uy = (zx - bx) / remaining, (zy - by) / remaining
        heading = math.atan2(uy, ux)
        standoff = half_box + HALF_LENGTH + 0.12
        rx, ry, ryaw = api.get_robot_pose()
        behind = (bx - standoff * ux, by - standoff * uy)
        before = (bx - (standoff + 0.25) * ux, by - (standoff + 0.25) * uy)
        # Robot centre's offset from the push line and its distance behind the box.
        lateral = abs(-(rx - bx) * uy + (ry - by) * ux)
        aligned = (
            lateral < 0.04
            and abs(math.remainder(ryaw - heading, 2 * math.pi)) < 0.06
            and (bx - rx) * ux + (by - ry) * uy > 0
        )
        if not aligned:
            # Back off, go around everything to a point behind the box, then line up.
            api.go_to(rx - 0.15 * math.cos(ryaw), ry - 0.15 * math.sin(ryaw), ryaw, max_speed=SLOW)
            drive_path(api, task, before, heading)
            api.go_to(*behind, heading, max_speed=SLOW)
        stroke = min(remaining, 0.35)
        reach = half_box + HALF_LENGTH - 0.01
        api.go_to(
            bx + stroke * ux - reach * ux, by + stroke * uy - reach * uy, heading, max_speed=0.12
        )
    rx, ry, ryaw = api.get_robot_pose()
    api.go_to(rx - 0.1 * math.cos(ryaw), ry - 0.1 * math.sin(ryaw), ryaw, max_speed=SLOW)
