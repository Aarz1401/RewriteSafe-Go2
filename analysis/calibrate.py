"""Offline straight-line tracking identification. Never connects to a robot."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def fit_tracking(rows: list[dict]) -> dict:
    samples = np.array([[r["t"], r["command_vx"], r["measured_vx"]] for r in rows], dtype=float)
    if len(samples) < 100 or not np.isfinite(samples).all():
        raise ValueError("Need at least 100 finite samples")
    if not np.allclose(np.diff(samples[:, 0]), 0.01, atol=1e-6):
        raise ValueError("Use uniformly sampled 100 Hz tracks (seconds and m/s)")
    commands, observed = samples[:, 1], samples[:, 2]
    if np.ptp(commands) < 0.1 or np.count_nonzero(np.diff(commands)) < 3:
        raise ValueError("Need multiple command transitions with at least .1 m/s range")
    best = None
    for delay in range(16):
        delayed = np.r_[np.zeros(delay), commands][: len(commands) - 1]
        for acceleration in (0.4, 0.6, 0.8, 1.0, 1.2, 1.5):
            for tau in (0.04, 0.06, 0.08, 0.10, 0.12, 0.16):
                predicted = observed[:-1] + 0.01 * np.clip(
                    (delayed - observed[:-1]) / tau, -acceleration, acceleration
                )
                residual = observed[1:] - predicted
                mse = float(np.mean(residual**2))
                if best is None or mse < best["mse"]:
                    best = dict(
                        mse=mse,
                        latency=delay * 0.01,
                        acceleration=acceleration,
                        tracking_tau=tau,
                        residual_velocity_std=float(np.std(residual)),
                    )
    best["rmse"] = best.pop("mse") ** 0.5
    best["samples"] = len(rows)
    best["limitations"] = (
        "Coarse-grid straight-line fit; assumes zero initial command, fixed yaw, "
        "no contacts, and known speed cap. Residuals mix tracking and measurement "
        "noise; do not substitute them directly for SimConfig.noise. Validate "
        "on a separate track before accepting parameters. No hardware data bundled."
    )
    return best


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tracks", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = fit_tracking([json.loads(s) for s in args.tracks.read_text().splitlines()])
    result["track_sha256"] = hashlib.sha256(args.tracks.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
