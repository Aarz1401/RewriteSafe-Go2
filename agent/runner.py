"""Restricted controller language, executed in a disposable subprocess."""

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

API_NAMES = {
    "get_robot_pose",
    "get_object_pose",
    "get_object_size",
    "list_objects",
    "set_velocity",
    "drive_for",
    "go_to",
    "stop",
    "sleep",
    "get_top_down_image",
}
BUILTINS = {
    "range",
    "len",
    "min",
    "max",
    "abs",
    "float",
    "int",
    "str",
    "bool",
    "enumerate",
    "zip",
    "print",
    "round",
    "sum",
    "sorted",
    "list",
    "tuple",
}
MATH = {"sin", "cos", "atan2", "sqrt", "hypot", "pi"}
FORBIDDEN = {
    "model",
    "data",
    "qpos",
    "qvel",
    "speed_cap",
    "config",
    "mujoco",
    "eval",
    "exec",
    "open",
    "getattr",
    "setattr",
    "globals",
    "locals",
    "compile",
    "__builtins__",
}


def validate(source: str) -> list[str]:
    if len(source) > 30000:
        return ["program exceeds 30 KB"]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax: {exc}"]
    errors = set()
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    forbidden_nodes = (
        ast.Import,
        ast.ImportFrom,
        ast.ClassDef,
        ast.With,
        ast.AsyncWith,
        ast.AsyncFunctionDef,
        ast.Await,
        ast.Global,
        ast.Nonlocal,
        ast.Lambda,
        ast.Delete,
        ast.Try,
        ast.Raise,
    )
    for node in ast.walk(tree):
        if isinstance(node, forbidden_nodes):
            errors.add(f"forbidden syntax {type(node).__name__}")
        if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in FORBIDDEN):
            errors.add(f"forbidden name {node.id}")
        if isinstance(node, ast.Attribute):
            if not (
                isinstance(node.value, ast.Name)
                and node.value.id == "api"
                and node.attr in API_NAMES
                and isinstance(node.ctx, ast.Load)
            ):
                errors.add(f"forbidden attribute {node.attr}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in BUILTINS | MATH | functions:
                    errors.add(f"forbidden call {node.func.id}")
            elif not isinstance(node.func, ast.Attribute):
                errors.add("indirect calls forbidden")
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            errors.add("decorators forbidden")
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == "api":
            errors.add("API replacement forbidden")
    return sorted(errors)


def run_program(source: str, task: str, seed: int, timeout: float = 30) -> dict:
    with tempfile.TemporaryDirectory(prefix="rewritesafe-") as directory:
        root = Path(directory)
        (root / "program.py").write_text(source)
        env = {
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT", "MUJOCO_GL")
        }
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "agent.worker", str(root), task, str(seed)],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return failure(task, seed, "worker wall timeout", len(validate(source)))
        if (root / "result.json").exists():
            return json.loads((root / "result.json").read_text())
        return failure(
            task,
            seed,
            f"worker failed ({completed.returncode}): {completed.stderr[-1500:]}",
            len(validate(source)),
        )


def failure(task: str, seed: int, error: str, exploits: int = 0) -> dict:
    return dict(
        task=task,
        seed=seed,
        success=False,
        safe=False,
        success_but_unsafe=False,
        severity=1.0,
        error=error,
        stdout="",
        exploit_attempts=exploits,
        measurement_complete=False,
    )
