import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis.metrics import summarize

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # validated categorical order
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def baseline_chart(groups: dict, path: Path) -> None:
    """One-row comparison of single-iteration conditions (e.g. M3 baselines) across tasks."""
    tasks = sorted({k[0] for k in groups})
    conditions = sorted({k[1] for k in groups})
    metrics = [
        ("success", "Success"),
        ("safe", "Safe"),
        ("success_but_unsafe", "Success but unsafe"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(12, 0.42 * len(tasks) + 2.0), sharey=True)
    offsets = [0.16 * (i - (len(conditions) - 1) / 2) for i in range(len(conditions))]
    for ax, (metric, title) in zip(axes, metrics):
        for color, offset, condition in zip(SERIES, offsets, conditions):
            ys, xs, lo, hi = [], [], [], []
            for i, task in enumerate(tasks):
                rows = groups.get((task, condition, 0))
                if not rows:
                    continue
                s = summarize(rows)
                ys.append(i + offset)
                xs.append(s[metric])
                lo.append(s[metric] - s[metric + "_ci95"][0])
                hi.append(s[metric + "_ci95"][1] - s[metric])
            ax.errorbar(xs, ys, xerr=[lo, hi], fmt="o", ms=6, color=color, ecolor=color,
                        elinewidth=1.5, capsize=0, label=condition)  # fmt: skip
        ax.set_title(title, loc="left", color=INK, fontsize=11)
        ax.set_xlim(-0.03, 1.03)
        ax.set_xticks([0, 0.5, 1], ["0%", "50%", "100%"])
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].set_yticks(range(len(tasks)), tasks)
    axes[0].invert_yaxis()
    axes[0].legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.08), ncol=len(conditions))
    n = len(next(iter(groups.values())))
    fig.suptitle(f"Held-out episodes per task (n = {n}); whiskers are Wilson 95% intervals",
                 x=0.01, ha="left", color=MUTED, fontsize=9, y=0.025)  # fmt: skip
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, dpi=140, facecolor="#fcfcfb")
    plt.close(fig)


def report(source: Path, out: Path) -> dict:
    groups = defaultdict(list)
    for line in source.read_text().splitlines():
        row = json.loads(line)
        if row.get("split", "heldout") == "heldout":
            groups[(row["task"], row["condition"], row["iteration"])].append(row)
    summary = {"/".join(map(str, k)): summarize(v) for k, v in groups.items()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")

    def pct(s: dict, key: str) -> str:
        ci = s[key + "_ci95"]
        return "–" if s[key] is None else f"{s[key]:.0%} [{ci[0]:.0%}, {ci[1]:.0%}]"

    lines = [
        "| Task | Condition | Iter | n | Success [95% CI] | Safe [95% CI] | Success but unsafe "
        "| P(unsafe \\| success) | Mean severity | Worst displacement (m) | Min person clearance (m) "
        "| Exploits |",
        "|---|---|---:|---:|---|---|---|---|---:|---:|---:|---:|",
    ]
    for (task, condition, iteration), rows in sorted(groups.items()):
        s = summarize(rows)
        clearance = s["min_person_clearance"]
        lines.append(
            f"| {task} | {condition} | {iteration} | {s['n']} | {pct(s, 'success')} "
            f"| {pct(s, 'safe')} | {pct(s, 'success_but_unsafe')} "
            f"| {pct(s, 'unsafe_given_success')} | {s['mean_severity']:.2f} "
            f"| {s['worst_displacement']:.2f} "
            f"| {'–' if clearance is None else f'{clearance:.2f}'} | {s['exploit_attempts']} |"
        )
    (out / "table.md").write_text("\n".join(lines) + "\n")
    if all(k[2] == 0 for k in groups):
        baseline_chart(groups, out / "baselines.png")
        return summary
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
