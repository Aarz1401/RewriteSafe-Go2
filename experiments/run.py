import argparse
import json
from pathlib import Path

import imageio.v2 as imageio

from experiments.controllers import careful, naive
from robot.sim_backend import SimBackend
from tasks.loader import HELDOUT_SEEDS, TRAIN_SEEDS, load, names


def episode(task_name: str, seed: int, controller: str, video: Path | None = None) -> dict:
    task = load(task_name, seed)
    api = SimBackend(task, video=video is not None)
    error = None
    try:
        {"naive": naive, "careful": careful}[controller](api, task)
    except (RuntimeError, ValueError, TimeoutError) as exc:
        error = str(exc)
    result = api.verifier.finish(api.snapshot())
    result.update(
        task=task_name,
        seed=seed,
        controller=controller,
        condition=controller,
        iteration=0,
        error=error,
        exploit_attempts=0,
        seconds=api.snapshot()["time"],
    )
    if error:
        result["success"] = result["success_but_unsafe"] = False
    if video:
        video.parent.mkdir(parents=True, exist_ok=True)
        imageio.imwrite(video.with_suffix(".png"), api._image())
        if api.frames:
            imageio.mimsave(video, api.frames, fps=10)
    api.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["train", "heldout"], default="heldout")
    parser.add_argument("--out", type=Path, default=Path("results/m3.jsonl"))
    parser.add_argument("--task", choices=names())
    parser.add_argument("--videos", action="store_true")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for task in [args.task] if args.task else names():
            for controller in ("naive", "careful"):
                rows = []
                for seed in TRAIN_SEEDS if args.split == "train" else HELDOUT_SEEDS:
                    result = episode(task, seed, controller)
                    result["split"] = args.split
                    f.write(json.dumps(result, allow_nan=False) + "\n")
                    f.flush()
                    rows.append(result)
                print(
                    task,
                    controller,
                    "success",
                    sum(r["success"] for r in rows),
                    "safe",
                    sum(r["safe"] for r in rows),
                    "/",
                    len(rows),
                    flush=True,
                )
                if args.videos:
                    selected = next((r for r in rows if r["success_but_unsafe"]), None)
                    if selected:
                        episode(
                            task,
                            selected["seed"],
                            controller,
                            Path(f"outputs/videos/{task}_{controller}.mp4"),
                        )


if __name__ == "__main__":
    main()
