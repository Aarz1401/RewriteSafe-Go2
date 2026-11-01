"""M3: run the naive and careful baselines on a seed split and write one JSONL row per episode.

uv run python -m experiments.run --split heldout --out results/m3/episodes.jsonl
"""

import argparse
import json
from pathlib import Path

import imageio.v2 as imageio

from experiments.controllers import careful, naive
from robot.sim_backend import SimBackend
from tasks.loader import DEV_SEEDS, HELDOUT_SEEDS, TRAIN_SEEDS, load, names

SPLITS = {"train": TRAIN_SEEDS, "dev": DEV_SEEDS, "heldout": HELDOUT_SEEDS}


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
        layout=task["layout"],
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
    parser.add_argument("--split", choices=list(SPLITS), default="heldout")
    parser.add_argument("--out", type=Path, default=Path("results/m3/episodes.jsonl"))
    parser.add_argument("--task", choices=names())
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for task in [args.task] if args.task else names():
            for controller in ("naive", "careful"):
                rows = []
                for seed in SPLITS[args.split]:
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


if __name__ == "__main__":
    main()
