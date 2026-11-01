"""M1 smoke test; optional macOS viewer: uv run mjpython -m sim.demo --viewer."""

import argparse
from pathlib import Path

import imageio.v2 as imageio

from robot.sim_backend import SimBackend
from tasks.loader import load


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("outputs/m1.png"))
    args = parser.parse_args()
    api = SimBackend(load("dock_at_rack", 0))
    if args.viewer:
        import mujoco.viewer

        with mujoco.viewer.launch_passive(api._model, api._data) as viewer:
            api.go_to(*api.task["goal"]["pose"], max_speed=0.2)
            viewer.sync()
            input("Press Enter to close the viewer.")
    else:
        api.go_to(*api.task["goal"]["pose"], max_speed=0.2)
    result = api.verifier.finish(api.snapshot())
    assert result["success"], result
    args.out.parent.mkdir(parents=True, exist_ok=True)
    imageio.imwrite(args.out, api._image())
    api.close()
    print("M1: goal reached, stopped, frame saved:", args.out)


if __name__ == "__main__":
    main()
