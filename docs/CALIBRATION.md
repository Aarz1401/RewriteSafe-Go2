# Offline dynamics calibration

The simulator parameters remain uncalibrated against hardware until real measurements
are supplied. `analysis.calibrate` is a preparation tool; it does not control a robot,
read a camera, or automatically modify simulation settings.

Supply JSONL records with `t` (seconds), `command_vx` (m/s) and `measured_vx` (m/s).
Use uniformly sampled 100 Hz straight-line tracks, fixed heading, no contacts, zero
initial command, and several safe speed changes including stops. The command and
measurement clocks must be synchronized. Use commands below the configured cap, so
saturation does not masquerade as slow tracking. Irregular camera tracks require
resampling and velocity estimation before this tool; differentiation noise matters.

```bash
uv run python -m analysis.calibrate path/to/tracks.jsonl --out outputs/fit.json
```

The coarse grid estimates effective command latency (0–150 ms), acceleration limit
(0.4–1.5 m/s²) and tracking time constant (40–160 ms) by minimizing one-step velocity
prediction error. The output records sample count, RMSE, residual standard deviation
and the input SHA-256. Grid-boundary optima or large residuals are reasons to inspect
the model and measurements; they are not successful calibration evidence.

Use separate recording sessions for fitting and validation. Review predicted versus
observed motion and stopping distance on the validation recordings before accepting a
fit. Residual variance mixes tracking noise, camera noise and model error, so it must
not be copied directly into the simulator's command-noise setting.

Apply reviewed values explicitly:

```python
config = SimConfig(latency=fit['latency'], acceleration=fit['acceleration'],
                   tracking_tau=fit['tracking_tau'])
api = SimBackend(task, config=config)
```

The simulator rounds latency to its 10 ms physics step. A 20 ms setting now queues
exactly two steps; the original implementation accidentally added a third. The
`tracking_tau` setting replaces the previously hardcoded 80 ms constant. Configuration
rejects negative/nonfinite latency or noise and nonpositive/nonfinite caps, acceleration,
time constants or episode horizons.

The automated fitter test uses a synthetic track with known 60 ms latency,
0.8 m/s² acceleration and an 80 ms time constant. Recovering those values verifies the
fitting implementation, not the physical accuracy of the Go2-W surrogate. Contact
friction, rotational dynamics, lateral tracking and camera uncertainty need additional
measurements; this tool does not estimate them.
