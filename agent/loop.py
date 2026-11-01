"""The rewrite loop: agent writes a program -> it runs -> verifier scores -> feedback -> rewrite.

Per iteration of one run:
  1. the backend returns a complete program + diagnosis + claims (JSON);
  2. the program runs on the 3 training seeds (their results become the next feedback turn,
     filtered by the feedback condition C1/C2/C3) and on the 20 held-out seeds (written to
     disk only, never shown to the agent);
  3. held-out metrics and the diagnosis check (did held-out success/safety move in the
     claimed direction?) are saved next to the program version.

Many independent runs (tasks x conditions x repeats) advance in lock-step, one iteration at
a time, so each iteration can be sent as a single Message Batches request (--batch).

    uv run python -m agent.loop --backend mock --task go_behind_box --condition C2 --iterations 2
"""

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

from agent.backends import AgentBackend, AgentReply, AgentRequest, make_backend
from agent.costs import HARD_LIMIT_USD, Pricing, append_ledger
from agent.prompts import CONDITIONS, SYSTEM_PROMPT, feedback_message, task_message
from agent.runner import run_many
from analysis.metrics import diagnosis_check, summarize
from tasks.loader import HELDOUT_SEEDS, TRAIN_SEEDS, names

MAX_ITERATIONS = 8
LABELS = "ABCDEFGH"
CONFIG = Path("experiments/config.yaml")


@dataclasses.dataclass
class RunSpec:
    task: str = "go_behind_box"
    condition: str = "C2"
    safety_instruction: bool = False
    iterations: int = 2
    repeat: int = 0  # independent repeats of the same arm

    @property
    def arm(self) -> str:
        return self.condition + ("+instr" if self.safety_instruction else "")

    def validate(self) -> None:
        if self.task not in names():
            raise ValueError(f"unknown task {self.task}")
        if self.condition not in CONDITIONS:
            raise ValueError(f"unknown condition {self.condition}")
        if not 1 <= self.iterations <= MAX_ITERATIONS:
            raise ValueError(f"iterations must be 1-{MAX_ITERATIONS}")


def parse_reply(text: str) -> tuple[dict | None, str | None]:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"reply is not valid JSON: {exc}"
    if not isinstance(payload, dict) or not isinstance(payload.get("program"), str):
        return None, "reply has no 'program' string"
    claims = payload.get("claims") if isinstance(payload.get("claims"), list) else []
    payload["claims"] = [c for c in claims if isinstance(c, dict)]
    payload["diagnosis"] = str(payload.get("diagnosis", ""))
    return payload, None


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        return out.stdout.strip() or None
    except OSError:
        return None


class AgentRun:
    """One conversation: a task under one feedback condition, for up to N iterations."""

    def __init__(self, spec: RunSpec, root: Path, backend: AgentBackend, run_id: str) -> None:
        spec.validate()
        self.spec, self.backend, self.run_id = spec, backend, run_id
        self.dir = root / run_id
        self.dir.mkdir(parents=True, exist_ok=False)  # never overwrite a run
        self.messages = [
            {"role": "user", "content": task_message(spec.task, spec.condition,
                                                     spec.safety_instruction)}
        ]  # fmt: skip
        self.iteration, self.spent, self.previous = 0, 0.0, None
        self.status, self.history = "running", []
        self.manifest = dict(
            run_id=run_id, task=spec.task, condition=spec.condition, arm=spec.arm,
            safety_instruction=spec.safety_instruction, repeat=spec.repeat,
            iterations=spec.iterations, backend=backend.name, model=backend.model,
            train_seeds=list(TRAIN_SEEDS), heldout_seeds=list(HELDOUT_SEEDS),
            created=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            git_commit=_git_commit(),
            system_prompt_sha256=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        )  # fmt: skip
        self._save_manifest()

    @property
    def active(self) -> bool:
        return self.status == "running"

    @property
    def custom_id(self) -> str:
        return f"{self.run_id}-it{self.iteration:02d}"

    def request(self) -> AgentRequest:
        return AgentRequest(self.custom_id, self.spec.task, self.iteration, SYSTEM_PROMPT,
                            list(self.messages))  # fmt: skip

    def stop(self, status: str) -> None:
        self.status = status
        self._save_manifest()

    def _save_manifest(self) -> None:
        self.manifest.update(status=self.status, completed_iterations=self.iteration,
                             estimated_cost_usd=round(self.spent, 6))  # fmt: skip
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=2) + "\n")

    def record(self, reply: AgentReply, pricing: Pricing, ledger: Path) -> dict:
        """Run the program from `reply`, score it, and append training feedback."""
        it_dir = self.dir / f"iter_{self.iteration:02d}"
        it_dir.mkdir()
        cost = pricing.cost(reply.usage, reply.batch)
        self.spent += cost
        append_ledger(ledger, dict(
            run_id=self.run_id, task=self.spec.task, condition=self.spec.arm,
            iteration=self.iteration, backend=self.backend.name, model=reply.model or
            self.backend.model, batch=reply.batch, cost_usd=f"{cost:.6f}",
            run_cost_usd=f"{self.spent:.6f}", **reply.usage,
        ))  # fmt: skip
        (it_dir / "request.json").write_text(json.dumps(self.messages, indent=1) + "\n")
        (it_dir / "reply.json").write_text(json.dumps(
            dataclasses.asdict(reply) | {"cost_usd": cost}, indent=1) + "\n")  # fmt: skip

        payload, parse_error = parse_reply(reply.text)
        error = reply.error or parse_error
        source = payload["program"] if payload else ""
        (it_dir / "program.py").write_text(source)
        sha = hashlib.sha256(source.encode()).hexdigest()
        rows = {}
        for split, seeds in (("train", TRAIN_SEEDS), ("heldout", HELDOUT_SEEDS)):
            rows[split] = run_many(source, self.spec.task, list(seeds))
            for i, row in enumerate(rows[split]):
                row.update(
                    run_id=self.run_id,
                    condition=self.spec.condition,
                    arm=self.spec.arm,
                    iteration=self.iteration,
                    split=split,
                    program_sha256=sha,
                    backend=self.backend.name,
                    model=reply.model or self.backend.model,
                    reply_error=error,
                    feedback_label=f"layout {LABELS[i]}" if split == "train" else None,
                )
                # fmt: skip
        with (self.dir / "episodes.jsonl").open("a") as file:
            for row in rows["train"] + rows["heldout"]:
                file.write(json.dumps(row, allow_nan=False) + "\n")

        heldout, train = summarize(rows["heldout"]), summarize(rows["train"])
        claims = [
            {**c, "metric": "safe" if c.get("metric") == "safety" else c.get("metric")}
            for c in (payload or {}).get("claims", [])
        ]
        check = diagnosis_check(claims, self.previous, heldout)
        metrics = dict(
            iteration=self.iteration, reply_error=error, program_sha256=sha,
            exploit_attempt=bool(rows["train"][0].get("exploit_attempts")),
            diagnosis=(payload or {}).get("diagnosis"), claims=(payload or {}).get("claims", []),
            claimed_specific_fix=any(str(c.get("fix", "")).strip() for c in claims),
            heldout=heldout, train=train, cost_usd=cost, **check,
        )  # fmt: skip
        (it_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, allow_nan=False) + "\n")
        self.history.append(metrics)
        self.previous = heldout

        # Only training episodes cross into the conversation.
        feedback = feedback_message(rows["train"], self.spec.condition)
        if error:
            feedback = f"Your previous reply could not be used: {error}\n\n" + feedback
        self.messages += [
            {"role": "assistant", "content": reply.text or "{}"},
            {"role": "user", "content": feedback},
        ]
        self.iteration += 1
        if self.iteration >= self.spec.iterations:
            self.status = "complete"
        self._save_manifest()
        return metrics


def drive(
    runs: list[AgentRun],
    backend: AgentBackend,
    pricing: Pricing,
    budget_usd: float,
    ledger: Path,
    batch: bool = False,
    log=print,
) -> None:
    """Advance all runs one iteration at a time until they finish or the budget is reached."""
    while any(r.active for r in runs):
        active = [r for r in runs if r.active]
        requests = {r.run_id: r.request() for r in active}
        if pricing.input or pricing.output:
            # Worst-case estimate before generation: counted input tokens (all treated as
            # cache writes) plus the full max_tokens of output for every request.
            estimate = sum(
                pricing.upper_bound(backend.count_input_tokens(q), backend.max_tokens, batch)
                for q in requests.values()
            )
            spent = sum(r.spent for r in runs)
            if spent + estimate > budget_usd:
                for r in active:
                    r.stop("budget_stopped")
                log(f"budget stop: spent ${spent:.4f} + worst case ${estimate:.4f} "
                    f"> ${budget_usd:.2f}")  # fmt: skip
                break
        replies = backend.complete_many(list(requests.values()), batch=batch)
        for run in active:
            m = run.record(replies[requests[run.run_id].custom_id], pricing, ledger)
            h = m["heldout"]
            log(f"{run.run_id} it{m['iteration']}: held-out success {h['success']:.2f} "
                f"safe {h['safe']:.2f} | claims supported: {m['diagnosis_accuracy']} "
                f"| ${m['cost_usd']:.4f}")  # fmt: skip


def load_config(path: Path | None) -> dict:
    if path and path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def main(argv: list[str] | None = None, client=None) -> list[AgentRun]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--backend", choices=["mock", "anthropic", "ollama"])
    parser.add_argument("--model")
    parser.add_argument("--task", nargs="+")
    parser.add_argument("--condition", nargs="+", choices=list(CONDITIONS))
    parser.add_argument("--safety-instruction", action="store_true")
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--budget", type=float, help="USD cap for this whole invocation")
    parser.add_argument("--approved-over-5", action="store_true",
                        help="the user explicitly approved a budget above $5")  # fmt: skip
    parser.add_argument("--batch", action="store_true", help="send each iteration as a batch")
    parser.add_argument("--input-price", type=float)
    parser.add_argument("--output-price", type=float)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--name", default="", help="suffix for run ids")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    agent = dict(config.get("agent", {}))
    if args.backend:
        agent["backend"] = args.backend
    if args.model:
        agent["model"] = args.model
    elif agent.get("backend", "mock") == "mock":
        agent["model"] = "mock"
    budget = args.budget if args.budget is not None else agent.get("budget_usd", 1.0)
    if budget > HARD_LIMIT_USD and not args.approved_over_5:
        raise SystemExit(f"budget ${budget} > ${HARD_LIMIT_USD}: ask the user first "
                         "(then pass --approved-over-5)")  # fmt: skip
    backend = make_backend(agent, client=client)
    override = (args.input_price, args.output_price) if args.input_price is not None else None
    pricing = Pricing.for_model(backend.name, backend.model, override)
    root = args.out or Path(config.get("runs_dir", "runs"))
    ledger = root / "cost_ledger.csv"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    runs = []
    for task in args.task or [agent.get("task", "go_behind_box")]:
        for condition in args.condition or [agent.get("condition", "C2")]:
            for repeat in range(args.repeats):
                spec = RunSpec(
                    task,
                    condition,
                    args.safety_instruction,
                    args.iterations or agent.get("iterations", 2),
                    repeat,
                )
                run_id = f"{stamp}-{backend.name}-{task}-{spec.arm}-r{repeat}{args.name}"
                runs.append(AgentRun(spec, root, backend, run_id.replace("+", "_")))
                # fmt: skip
    drive(runs, backend, pricing, budget, ledger, batch=args.batch)
    return runs


if __name__ == "__main__":
    main()
