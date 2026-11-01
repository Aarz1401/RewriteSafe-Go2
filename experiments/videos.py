"""Replay the first unsafe success per baseline/task, separate from measurement runs."""

import argparse
import json
from pathlib import Path

from experiments.run import episode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=Path("outputs/videos"))
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    selected = {}
    for line in args.source.read_text().splitlines():
        row = json.loads(line)
        if row["success_but_unsafe"]:
            selected.setdefault((row["task"], row["controller"]), row)
    args.out.mkdir(parents=True, exist_ok=True)
    for (task, controller), row in list(selected.items())[: args.limit]:
        result = episode(task, row["seed"], controller, args.out / f"{task}_{controller}.mp4")
        assert result["success_but_unsafe"], "Replay mismatch"
        (args.out / f"{task}_{controller}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(task, controller, "seed", row["seed"], "unsafe success replay verified", flush=True)


if __name__ == "__main__":
    main()
