"""Render a contact sheet of seeded layouts (initial scene, goal marker) for inspection.

uv run python -m experiments.layouts --seeds 0 1 2 --out outputs/layouts.png
"""

import argparse
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image

from robot.sim_backend import SimBackend
from tasks.loader import load, names


def sheet(seeds: list[int], size: int = 240) -> np.ndarray:
    rows = []
    for name in names():
        tiles = []
        for seed in seeds:
            api = SimBackend(load(name, seed))
            image = api._image()
            api.close()
            tile = np.asarray(Image.fromarray(image).resize((size, size), Image.LANCZOS))
            tiles.append(np.pad(tile, ((2, 2), (2, 2), (0, 0))))
        rows.append(np.concatenate(tiles, axis=1))
    return np.concatenate(rows, axis=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--out", type=Path, default=Path("outputs/layouts.png"))
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    imageio.imwrite(args.out, sheet(args.seeds))
    print("rows:", ", ".join(names()), "| columns: seeds", args.seeds, "->", args.out)


if __name__ == "__main__":
    main()
