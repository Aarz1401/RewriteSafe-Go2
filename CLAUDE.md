# Conventions
- Small modules: robot/ (API + backends), sim/, verifier/, tasks/, agent/, experiments/, analysis/.
- Use uv, Python 3.11–3.12, type hints, pytest for verifier and API.
- Fixed seeds recorded in every episode; training seeds 0–2 and held-out seeds 100–119 must never overlap.
- Every design decision/deviation gets a dated DESIGN_LOG.md entry.
- After each milestone add a 3–5 sentence plain-English explanation in DESIGN_LOG.md.
- Ask before spending more than $5 API credit in one run. Keys only via environment; never commit credentials.
- No real robot communication in M0–M4. RealBackend remains a stub.
- Do not expose model/data/qpos or configuration to generated programs.
- Never feed held-out outcomes to the agent or tune baselines on held-out seeds.
