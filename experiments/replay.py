"""Replay a saved controller in simulation only."""

import argparse
import json
from pathlib import Path

from agent.runner import run_program

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("program", type=Path)
    parser.add_argument("--task", default="go_behind_box")
    parser.add_argument("--seed", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(run_program(args.program.read_text(), args.task, args.seed), indent=2))
