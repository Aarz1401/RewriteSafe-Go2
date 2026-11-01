"""Pick a headless OpenGL backend before `mujoco` is imported.

MuJoCo reads MUJOCO_GL when the package is imported, and importing it with an unusable
backend (e.g. MUJOCO_GL=egl without libEGL) fails outright. On Linux we therefore probe
EGL and then OSMesa in a throwaway subprocess and export the first one that can create a
context. macOS needs nothing (CoreGraphics). The result is cached in the environment so
child processes (the program sandbox) skip the probe.
"""

import os
import subprocess
import sys
import warnings

_CHECKED = "REWRITESAFE_GL_CHECKED"
_PROBE = "import mujoco; c = mujoco.GLContext(8, 8); c.make_current(); c.free()"


def _works(backend: str) -> bool:
    env = {**os.environ, "MUJOCO_GL": backend, "PYOPENGL_PLATFORM": backend}
    try:
        done = subprocess.run(
            [sys.executable, "-c", _PROBE], env=env, capture_output=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def configure_gl() -> str | None:
    """Set MUJOCO_GL for headless rendering on Linux; return the chosen backend."""
    if not sys.platform.startswith("linux") or "mujoco" in sys.modules:
        return os.environ.get("MUJOCO_GL")
    if os.environ.get(_CHECKED):
        return os.environ.get("MUJOCO_GL") or None
    requested = os.environ.get("MUJOCO_GL", "").lower()
    candidates = [requested] if requested else []
    candidates += [b for b in ("egl", "osmesa") if b != requested]
    chosen = next((b for b in candidates if _works(b)), None)
    if chosen is None:
        # Simulation still works; only mujoco.Renderer will fail.
        os.environ.pop("MUJOCO_GL", None)
        warnings.warn("No headless GL backend (egl/osmesa) found; rendering disabled.")
    else:
        if requested and chosen != requested:
            warnings.warn(f"MUJOCO_GL={requested} unusable; falling back to {chosen}.")
        os.environ["MUJOCO_GL"] = chosen
        os.environ["PYOPENGL_PLATFORM"] = chosen
    os.environ[_CHECKED] = "1"
    return chosen
