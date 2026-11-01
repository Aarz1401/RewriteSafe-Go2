"""Placeholder for the lab Go2-W backend. Deliberately cannot talk to hardware (M0-M4).

Planned implementation (later phase, see docs/BRIEF.md):
- motion: `unitree_sdk2py.go2.sport.sport_client.SportClient.Move(vx, vy, vyaw)` velocity
  commands, clipped to `speed_cap` (0.3 m/s) inside this class before sending, plus
  `StopMove()` for `stop()`;
- poses: an overhead camera tracking AprilTags on the robot and on every object, giving
  the same pose frames the verifier consumes in simulation (robot pose, object pose + tilt);
- safety: an operator holds the remote as an e-stop; this class never disables it.
"""

from robot.api import Pose


class RealBackend:
    speed_cap: float = 0.3

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "RealBackend is a stub: no robot communication before the hardware phase"
        )

    def get_robot_pose(self) -> Pose:
        raise NotImplementedError

    def get_object_pose(self, name: str) -> Pose:
        raise NotImplementedError

    def get_object_size(self, name: str) -> tuple[float, float, float]:
        raise NotImplementedError

    def list_objects(self) -> list[str]:
        raise NotImplementedError

    def set_velocity(self, vx: float, vy: float, wz: float) -> None:
        raise NotImplementedError

    def drive_for(self, vx: float, vy: float, wz: float, seconds: float) -> None:
        raise NotImplementedError

    def go_to(self, x: float, y: float, yaw: float | None = None, max_speed: float = 0.3) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        raise NotImplementedError

    def get_top_down_image(self) -> list:
        raise NotImplementedError
