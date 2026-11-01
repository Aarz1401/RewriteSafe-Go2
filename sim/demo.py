"""M1 smoke test: scripted drive to the dock goal, headless, frames saved to disk.

uv run python -m sim.demo                    # outputs/m1.png + outputs/m1.mp4
uv run mjpython -m sim.demo --viewer         # optional interactive viewer (macOS)
"""

import argparse
from pathlib import Path

import imageio.v2 as imageio

from robot.sim_backend import SimBackend
from tasks.loader import load


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("outputs/m1.png"))
    args = parser.parse_args()
    api = SimBackend(load("dock_at_rack", args.seed), video=not args.viewer)
    goal = api.task["goal"]["pose"]
    if args.viewer:
        import mujoco.viewer

        with mujoco.viewer.launch_passive(api._model, api._data) as viewer:
            api.go_to(*goal, max_speed=0.2)
            viewer.sync()
            input("Press Enter to close the viewer.")
    else:
        api.go_to(*goal, max_speed=0.2)
    result = api.verifier.finish(api.snapshot())
    assert result["success"] and result["safe"], result
    args.out.parent.mkdir(parents=True, exist_ok=True)
    imageio.imwrite(args.out, api._image())
    if api.frames:
        imageio.mimsave(args.out.with_suffix(".mp4"), api.frames, fps=10)
    api.close()
    print(
        f"M1: seed {args.seed}, goal reached and stopped (dock gap {result['dock_gap']:.3f} m, "
        f"safe={result['safe']}), {len(api.frames)} frames; saved {args.out}"
    )


if __name__ == "__main__":
    main()
