import builtins
import contextlib
import io
import json
import math
import resource
import signal
import sys
from pathlib import Path

from agent.runner import BUILTINS, MATH, SAFE_IMPORTS, classify
from robot.api import ProgramAPI
from robot.sim_backend import SimBackend
from tasks.loader import load


def _import(name: str, globals=None, locals=None, fromlist=(), level=0):
    # Runtime twin of the static import check: only `math` can be imported.
    if level or name.split(".")[0] not in SAFE_IMPORTS:
        raise ImportError(f"import of {name} is not allowed")
    return math


class BoundedOutput(io.StringIO):
    def write(self, value: str) -> int:
        if self.tell() + len(value) > 16000:
            raise RuntimeError("stdout limit exceeded")
        return super().write(value)


def main() -> None:
    root, name, seed_text = sys.argv[1:]
    seed = int(seed_text)
    source = (Path(root) / "program.py").read_text()
    exploits, rejections = classify(source)
    errors = exploits + rejections
    task = load(name, seed)
    api = SimBackend(task)
    output = BoundedOutput()
    error = "; ".join(errors) if errors else None

    def timeout(_signum, _frame):
        raise TimeoutError("program timeout")

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(20)
    resource.setrlimit(resource.RLIMIT_CPU, (22, 23))
    # macOS rejects lowering RLIMIT_DATA on some installations. The restricted
    # runner has CPU/wall/output limits; use a container for hostile workloads.
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    if not errors:
        allowed = {n: getattr(builtins, n) for n in BUILTINS}
        allowed["__import__"] = _import
        # Programs get the API proxy only, never the backend (no MjData, config, verifier).
        scope = {"__builtins__": allowed, "api": ProgramAPI(api), "math": math}
        scope.update({n: getattr(math, n) for n in MATH})
        try:
            with contextlib.redirect_stdout(output):
                exec(compile(source, "controller.py", "exec"), scope, scope)
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
    signal.alarm(0)
    try:
        api.stop()
    except TimeoutError:
        pass
    result = api.verifier.finish(api.snapshot())
    result.update(
        task=name,
        seed=seed,
        layout=task["layout"],
        stdout=output.getvalue(),
        error=error,
        exploit_attempts=int(bool(exploits)),
        exploit_reasons=exploits,
        rejection_reasons=rejections,
        measurement_complete=True,
    )
    if error:
        result["success"] = result["success_but_unsafe"] = False
    (Path(root) / "result.json").write_text(json.dumps(result, allow_nan=False))
    api.close()


if __name__ == "__main__":
    main()
