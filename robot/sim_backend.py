import math
from collections import deque
from dataclasses import dataclass

import mujoco
import numpy as np

from sim.scene import build
from tasks.goals import resolve_goal
from verifier.core import Verifier


@dataclass(frozen=True)
class SimConfig:
    speed_cap: float = 0.5
    lateral: bool = True
    acceleration: float = 0.8
    latency: float = 0.06
    noise: float = 0.003
    tracking_tau: float = 0.08
    max_seconds: float = 90.0

    def __post_init__(self) -> None:
        for name in ("speed_cap", "acceleration", "tracking_tau", "max_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("latency", "noise"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")


class SimBackend:
    def __init__(self, task: dict, config: SimConfig | None = None, video: bool = False) -> None:
        self.task, self.config = task, config or SimConfig()
        self._model = build(task)
        self._data = mujoco.MjData(self._model)
        self._data.qpos[:3] = task["start"]
        self._rng = np.random.default_rng(task["seed"])
        self._command = np.zeros(3)
        self._queue = deque([np.zeros(3) for _ in range(round(self.config.latency / 0.01))])
        self._renderer = None
        self.frames: list = []
        self.video = video
        # Settle stacked bodies before recording initial references.
        for _ in range(100):
            mujoco.mj_step(self._model, self._data)
        self._data.time = 0
        mujoco.mj_forward(self._model, self._data)
        self.verifier = Verifier(task, self.snapshot()["objects"])
        self.verifier.update(self.snapshot())

    def get_robot_pose(self) -> tuple[float, float, float]:
        return tuple(float(v) for v in self._data.qpos[:3])

    def get_task_goal(self) -> dict:
        return resolve_goal(self.task, self.verifier.initial, self.snapshot()["objects"])

    def get_object_pose(self, name: str) -> tuple[float, float, float]:
        body = self._data.body(name)
        mat = body.xmat.reshape(3, 3)
        return float(body.xpos[0]), float(body.xpos[1]), math.atan2(mat[1, 0], mat[0, 0])

    def get_object_size(self, name: str) -> tuple[float, float, float]:
        return tuple(next(o["size"] for o in self.task["objects"] if o["name"] == name))

    def list_objects(self) -> list[str]:
        return [o["name"] for o in self.task["objects"]]

    def set_velocity(self, vx: float, vy: float, wz: float) -> None:
        command = np.array([vx, vy if self.config.lateral else 0, wz], dtype=float)
        if not np.isfinite(command).all():
            raise ValueError("Nonfinite command")
        norm = np.linalg.norm(command[:2])
        command[:2] *= min(1, self.config.speed_cap / max(norm, 1e-9))
        command[2] = np.clip(command[2], -1.2, 1.2)
        self._command = command

    def sleep(self, seconds: float) -> None:
        if not math.isfinite(seconds) or not 0 <= seconds <= self.config.max_seconds:
            raise ValueError("Invalid duration")
        for _ in range(math.ceil(seconds / 0.01)):
            self._step()

    def _step(self) -> None:
        if self._data.time >= self.config.max_seconds:
            raise TimeoutError("Simulation horizon exceeded")
        self._queue.append(self._command.copy())
        cmd = self._queue.popleft()
        yaw = self.get_robot_pose()[2]
        c, s = math.cos(yaw), math.sin(yaw)
        desired = np.array([c * cmd[0] - s * cmd[1], s * cmd[0] + c * cmd[1], cmd[2]])
        if np.linalg.norm(cmd) > 0:
            desired[:2] += self._rng.normal(0, self.config.noise, 2)
        desired[:2] *= min(1, self.config.speed_cap / max(np.linalg.norm(desired[:2]), 1e-9))
        accel = (desired[:2] - self._data.qvel[:2]) / self.config.tracking_tau
        accel *= min(1, self.config.acceleration / max(np.linalg.norm(accel), 1e-9))
        self._data.qfrc_applied[:2] = 18 * accel
        self._data.qfrc_applied[2] = np.clip((desired[2] - self._data.qvel[2]) * 8, -4, 4)
        mujoco.mj_step(self._model, self._data)
        self.verifier.update(self.snapshot())
        if self.video and round(self._data.time * 100) % 10 == 0:
            self.frames.append(self._image())

    def drive_for(self, vx: float, vy: float, wz: float, seconds: float) -> None:
        self.set_velocity(vx, vy, wz)
        self.sleep(seconds)
        self.stop()

    def stop(self) -> None:
        self.set_velocity(0, 0, 0)
        self.sleep(0.8)

    def go_to(self, x: float, y: float, yaw: float | None = None, max_speed: float = 0.5) -> None:
        if not all(math.isfinite(v) for v in [x, y, max_speed]) or max_speed <= 0:
            raise ValueError("Invalid goal")
        for _ in range(3500):
            px, py, a = self.get_robot_pose()
            dx, dy = x - px, y - py
            distance = math.hypot(dx, dy)
            target_yaw = (
                math.atan2(dy, dx)
                if distance > 0.03 and not self.config.lateral
                else a
                if yaw is None
                else yaw
            )
            da = (target_yaw - a + math.pi) % (2 * math.pi) - math.pi
            if distance < 0.025 and abs(da) < 0.04:
                break
            speed = min(max_speed, distance * 1.5)
            vx = speed * (math.cos(a) * dx + math.sin(a) * dy) / max(distance, 1e-9)
            vy = speed * (-math.sin(a) * dx + math.cos(a) * dy) / max(distance, 1e-9)
            if not self.config.lateral and abs(da) > 0.2:
                vx = 0
            self.set_velocity(vx, vy, 2 * da)
            self.sleep(0.02)
        else:
            raise TimeoutError("go_to did not converge")
        self.stop()

    def snapshot(self) -> dict:
        objects = {}
        for name in self.list_objects():
            mat = self._data.body(name).xmat.reshape(3, 3)
            objects[name] = {
                "pose": list(self.get_object_pose(name)),
                "tilt": math.acos(float(np.clip(mat[2, 2], -1, 1))),
            }
        contacts, peak = set(), 0.0
        robot_id = self._model.geom("robot").id
        for i in range(self._data.ncon):
            contact = self._data.contact[i]
            if robot_id in (contact.geom1, contact.geom2):
                other = contact.geom2 if contact.geom1 == robot_id else contact.geom1
                name = self._model.geom(other).name
                if name != "floor":
                    contacts.add(name)
                    force = np.zeros(6)
                    mujoco.mj_contactForce(self._model, self._data, i, force)
                    peak = max(peak, float(np.linalg.norm(force[:3])))
        return {
            "robot": list(self.get_robot_pose()),
            "objects": objects,
            "speed": float(np.linalg.norm(self._data.qvel[:2])),
            "angular_speed": float(self._data.qvel[2]),
            "contacts": sorted(contacts),
            "force": peak,
            "time": float(self._data.time),
        }

    def _image(self) -> np.ndarray:
        if self._renderer is None:
            self._renderer = mujoco.Renderer(self._model, 640, 640)
        self._renderer.update_scene(self._data, camera="top")
        return self._renderer.render().copy()

    def get_top_down_image(self) -> list:
        return self._image().tolist()

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
