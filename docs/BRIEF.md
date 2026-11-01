# RewriteSafe-Go2: session scope

Research question: does iterative controller rewriting trade mobile-robot safety for task
success, and does explicit safety feedback change that tradeoff? Evaluate controller
versions on fixed held-out layouts, separately from training feedback. Check whether
claimed fixes agree with held-out metric direction; investigate sim-to-real ranking later.

Implement M0–M4 only: repository/environment; planar physical MuJoCo surrogate/API;
pose-based verifier with tests; eight YAML tasks with naive/careful calibration baselines
on 20 held-out seeds each; two-iteration C2 loop on go_behind_box.

**2026-11-01 user clarification:** M4 uses the mock agent backend end-to-end. Test the
Anthropic backend with a patched SDK client and no network calls. Read a real key only
from `ANTHROPIC_API_KEY`, fail clearly if missing when selecting Anthropic, and provide
`.env.example` containing `ANTHROPIC_API_KEY=`. No paid API calls in this session.

Future real backend is a stub only. No hardware communication and no full experiments.
Full implementation decisions, limitations, milestone explanations and evidence are in
DESIGN_LOG.md. This file summarizes the brief and its clarification; it is not an earlier
file that existed in the initially empty workspace.
