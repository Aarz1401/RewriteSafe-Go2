"""Bounded, zero-cost regression suite. Original M3/M4 artifacts remain unchanged."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from agent.loop import run
from analysis.metrics import summarize
from experiments.run import episode
from robot.sim_backend import SimBackend
from tasks.loader import load, names


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("results/revision-2026-11-04"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    sources = [
        p
        for folder in ("robot", "sim", "tasks", "verifier", "agent", "experiments", "analysis")
        for p in Path(folder).glob("*")
        if p.suffix in (".py", ".yaml")
    ]
    (args.out / "sources.json").write_text(
        json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, indent=2)
    )
    summary = {}
    with (args.out / "episodes.jsonl").open("w") as file:
        for task in ("cluttered_corridor", "past_tower"):
            for split, seeds in [
                ("regression", range(100, 120)),
                ("fresh_validation", range(200, 220)),
            ]:
                for controller in ("naive", "careful"):
                    rows = []
                    for seed in seeds:
                        row = episode(task, seed, controller)
                        row["split"] = split
                        file.write(json.dumps(row) + "\n")
                        file.flush()
                        rows.append(row)
                    metrics = summarize(rows)
                    metrics["toppling_rate"] = sum(
                        max(r["tilt"].values(), default=0) > math.pi / 6 for r in rows
                    ) / len(rows)
                    summary[f"{task}/{split}/{controller}"] = metrics
                    print(
                        task,
                        split,
                        controller,
                        metrics["success"],
                        metrics["safe"],
                        metrics["toppling_rate"],
                        flush=True,
                    )
    idle = []
    for seed in range(200, 220):
        api = SimBackend(load("past_tower", seed))
        api.sleep(10)
        idle.append(
            dict(
                seed=seed,
                max_tilt=max(api.verifier.tilt.values()),
                safe=api.verifier.finish(api.snapshot())["safe"],
            )
        )
        api.close()
    (args.out / "idle_tower.json").write_text(json.dumps(idle, indent=2))
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    for task in names():
        run(args.out / "mock" / task, task=task, mock=True, train_seeds=(0,), heldout_seeds=(200,))


if __name__ == "__main__":
    main()
