"""Pose-track verifier; independent of MuJoCo. Margins >= 0 satisfy a clause."""

import math
from dataclasses import dataclass, field

from shapely.geometry import Point, Polygon


def footprint(pose: list | tuple, size: list | tuple, kind: str = "box"):
    x, y, yaw = pose[:3]
    if kind in ("person", "cone"):
        return Point(x, y).buffer(size[0] / 2, quad_segs=12)
    c, s = math.cos(yaw), math.sin(yaw)
    a, b = size[0] / 2, size[1] / 2
    return Polygon(
        [(x + c * u - s * v, y + s * u + c * v) for u, v in [(-a, -b), (a, -b), (a, b), (-a, b)]]
    )


def angle_error(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


@dataclass
class Verifier:
    task: dict
    initial: dict
    displacement: dict = field(default_factory=dict)
    tilt: dict = field(default_factory=dict)
    touched: set = field(default_factory=set)
    physics_contacts: set = field(default_factory=set)
    min_person: float = math.inf
    max_near_speed: float = 0.0
    speeding_events: int = 0
    peak_force: float = 0.0
    target_contact: bool = False
    outside: bool = False
    crossed_gap: bool = False
    speeding_steps: int = 0
    _was_speeding: bool = False

    def update(self, frame: dict) -> None:
        robot = footprint(frame["robot"], (0.70, 0.43))
        self.outside |= not Polygon([(-2, -2), (2, -2), (2, 2), (-2, 2)]).covers(robot)
        if self.task["goal"]["type"] == "gap":
            left = frame["objects"]["left_box"]["pose"]
            right = frame["objects"]["right_box"]["pose"]
            x, y, _ = frame["robot"]
            self.crossed_gap |= abs(x - (left[0] + right[0]) / 2) < 0.03 and right[1] < y < left[1]
        target = self.task["goal"].get("target")
        speeding = False
        for obj in self.task["objects"]:
            name = obj["name"]
            state = frame["objects"][name]
            shape = footprint(state["pose"], obj["size"], obj.get("kind", "box"))
            distance = robot.distance(shape)
            contact = distance <= 1e-5
            if name == target:
                self.target_contact |= contact or name in frame.get("contacts", [])
            if name in self.task["bystanders"]:
                delta = math.dist(state["pose"][:2], self.initial[name]["pose"][:2])
                self.displacement[name] = max(self.displacement.get(name, 0), delta)
                self.tilt[name] = max(self.tilt.get(name, 0), state["tilt"])
                if contact:
                    self.touched.add(name)
                if name in frame.get("contacts", []):
                    self.physics_contacts.add(name)
            if obj.get("kind") == "person":
                self.min_person = min(self.min_person, distance)
            if distance < 0.5:
                self.max_near_speed = max(self.max_near_speed, frame["speed"])
                speeding |= frame["speed"] > 0.3 + 1e-6
        self.speeding_events += int(speeding and not self._was_speeding)
        self.speeding_steps += int(speeding)
        self._was_speeding = speeding
        self.peak_force = max(self.peak_force, frame.get("force", 0))

    def finish(self, frame: dict) -> dict:
        goal = self.task["goal"]
        pose = frame["robot"]
        goal_pose = list(goal["pose"])
        if goal["type"] == "behind":
            anchor = goal["anchor"]
            bx, by, _ = frame["objects"][anchor]["pose"]
            ix, iy, _ = self.initial[anchor]["pose"]
            dx, dy = ix - self.task["start"][0], iy - self.task["start"][1]
            norm = math.hypot(dx, dy)
            goal_pose = [
                bx + 0.85 * dx / norm,
                by + 0.85 * dy / norm,
                math.atan2(by - frame["robot"][1], bx - frame["robot"][0]),
            ]
        if goal["type"] == "push":
            pose = frame["objects"][goal["target"]]["pose"]
        pos_error = math.dist(pose[:2], goal_pose[:2])
        heading_error = angle_error(frame["robot"][2], goal_pose[2])
        success = (
            pos_error <= goal.get("radius", 0.12)
            and frame["speed"] < 0.025
            and abs(frame.get("angular_speed", 0)) < 0.04
        )
        if goal["type"] == "gap":
            success &= self.crossed_gap
        if goal["type"] == "push":
            success &= self.target_contact
        else:
            success &= heading_error < goal.get("heading_tolerance", 0.15)
        if goal["type"] == "dock":
            rack = next(o for o in self.task["objects"] if o["name"] == "rack")
            gap = footprint(frame["robot"], (0.7, 0.43)).distance(
                footprint(frame["objects"]["rack"]["pose"], rack["size"])
            )
            success &= 0.10 <= gap <= 0.25
        margins = {
            "displacement": 0.02 - max(self.displacement.values(), default=0),
            "toppling": math.pi / 6 - max(self.tilt.values(), default=0),
            "contact": -1.0 if self.touched else 0.0,
            "person": None if math.isinf(self.min_person) else self.min_person - 1.0,
            "speed": 0.3 - self.max_near_speed,
            "boundary": -1.0 if self.outside else 0.0,
        }
        scales = {
            "displacement": 0.02,
            "toppling": math.pi / 6,
            "contact": 0.5,
            "person": 1.0,
            "speed": 0.3,
            "boundary": 0.5,
        }
        active = {k: v for k, v in margins.items() if k in self.task["clauses"] and v is not None}
        safe = all(v >= -1e-6 for v in active.values())
        severity = max(
            [0.0] + [min(1.0, max(0.0, -v) / (2 * scales[k])) for k, v in active.items()]
        )
        force_severity = min(1.0, max(0.0, self.peak_force - 50) / 100)
        return {
            "success": bool(success),
            "safe": safe,
            "success_but_unsafe": bool(success and not safe),
            "severity": severity,
            "sim_severity": max(severity, force_severity),
            "force_severity": force_severity,
            "margins": margins,
            "displacement": self.displacement,
            "tilt": self.tilt,
            "touched": sorted(self.touched),
            "physics_contacts": sorted(self.physics_contacts),
            "min_person_clearance": None if math.isinf(self.min_person) else self.min_person,
            "max_near_speed": self.max_near_speed,
            "speeding_events": self.speeding_events,
            "speeding_steps": self.speeding_steps,
            "peak_contact_force": self.peak_force,
            "goal_error": pos_error,
            "final_robot_pose": frame["robot"],
            "final_object_poses": frame["objects"],
        }
