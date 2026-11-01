"""The robot API: the only capabilities available to controller programs.

Coordinates are world-frame metres/radians; velocities passed to `set_velocity`/`drive_for`
are body-frame (vx forward, vy left, wz counter-clockwise). Every backend enforces its own
hard speed cap; programs can request any speed but never exceed the cap.
"""

from typing import Any, Protocol, runtime_checkable

Pose = tuple[float, float, float]

# Names a controller program may call as `api.<name>(...)`. Kept here so the sandbox,
# the agent prompt and the backends all agree.
API_FUNCTIONS: tuple[str, ...] = (
    "get_robot_pose",
    "get_object_pose",
    "get_object_size",
    "list_objects",
    "set_velocity",
    "drive_for",
    "go_to",
    "stop",
    "sleep",
    "get_top_down_image",
)


@runtime_checkable
class RobotAPI(Protocol):
    def get_robot_pose(self) -> Pose: ...
    def get_object_pose(self, name: str) -> Pose: ...
    def get_object_size(self, name: str) -> tuple[float, float, float]: ...
    def list_objects(self) -> list[str]: ...
    def set_velocity(self, vx: float, vy: float, wz: float) -> None: ...
    def drive_for(self, vx: float, vy: float, wz: float, seconds: float) -> None: ...
    def go_to(
        self, x: float, y: float, yaw: float | None = None, max_speed: float = 0.5
    ) -> None: ...
    def stop(self) -> None: ...
    def sleep(self, seconds: float) -> None: ...
    def get_top_down_image(self) -> list: ...


class ProgramAPI:
    """What a controller program sees as `api`: bound API functions and nothing else.

    The backend object (with its MjModel/MjData, config, verifier and task spec) is captured
    in closures, not stored as an attribute, so `api.<anything else>` does not exist. The
    sandbox additionally rejects underscore/dunder attribute access statically.
    """

    __slots__ = API_FUNCTIONS

    def __init__(self, backend: RobotAPI) -> None:
        for name in API_FUNCTIONS:
            object.__setattr__(self, name, _wrap(getattr(backend, name)))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("the robot API is read-only")

    def __repr__(self) -> str:
        return f"<robot api: {', '.join(API_FUNCTIONS)}>"


def _wrap(method: Any) -> Any:
    def call(*args: Any, **kwargs: Any) -> Any:
        return method(*args, **kwargs)

    call.__name__ = method.__name__
    call.__doc__ = method.__doc__
    return call


def __getattr__(name: str) -> Any:
    # Backwards compatibility for `from robot.api import RealBackend`.
    if name == "RealBackend":
        from robot.real_backend import RealBackend

        return RealBackend
    raise AttributeError(name)
