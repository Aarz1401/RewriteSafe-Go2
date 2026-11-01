import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis.metrics import summarize


def report(source: Path, out: Path) -> dict:
    groups = defaultdict(list)
    for line in source.read_text().splitlines():
        row = json.loads(line)
        if row.get("split", "heldout") == "heldout":
            groups[(row["task"], row["condition"], row["iteration"])].append(row)
    summary = {"/".join(map(str, k)): summarize(v) for k, v in groups.items()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    lines = [
        "| Task | Controller | Success | Safe | Success unsafe | Mean severity |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for (task, condition, iteration), rows in groups.items():
        s = summarize(rows)
        lines.append(
            f"| {task} | {condition} | {s['success']:.0%} | {s['safe']:.0%} | {s['success_but_unsafe']:.0%} | {s['mean_severity']:.3f} |"
        )
    (out / "table.md").write_text("\n".join(lines) + "\n")
    for task in sorted({k[0] for k in groups}):
        fig, axes = plt.subplots(1, 3, figsize=(11, 3.4))
        for condition in sorted({k[1] for k in groups if k[0] == task}):
            keys = sorted(k for k in groups if k[:2] == (task, condition))
            for ax, metric in zip(axes, ("success", "safe", "success_but_unsafe")):
                vals = [summarize(groups[k]) for k in keys]
                xs, ys = [k[2] for k in keys], [v[metric] for v in vals]
                ax.errorbar(
                    xs,
                    ys,
                    yerr=[
                        [v[metric] - v[metric + "_ci95"][0] for v in vals],
                        [v[metric + "_ci95"][1] - v[metric] for v in vals],
                    ],
                    fmt="o-",
                    capsize=4,
                    label=condition,
                )
                ax.fill_between(
                    xs,
                    [v[metric + "_ci95"][0] for v in vals],
                    [v[metric + "_ci95"][1] for v in vals],
                    alpha=0.18,
                )
                ax.set(title=metric, ylim=(-0.05, 1.05), xlabel="Rewrite iteration")
        axes[0].legend()
        fig.suptitle(task + " (Wilson 95% intervals)")
        fig.tight_layout()
        fig.savefig(out / f"{task}.png", dpi=140)
        plt.close(fig)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=Path("results/m3"))
    args = parser.parse_args()
    report(args.source, args.out)
