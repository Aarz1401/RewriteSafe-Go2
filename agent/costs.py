"""Token prices, cost estimates and the running cost ledger (runs/cost_ledger.csv).

Prices are USD per million tokens for the Claude API (first-party), as listed in the
Anthropic model table on 2026-10-06. Haiku 5.5's rate applies to prompts up to 100K tokens
(our prompts are far smaller). Cache writes (5-minute TTL) cost 1.25x input, cache reads
0.1x input, and the Batch API halves everything. Unknown models need explicit prices.
"""

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

PRICES = {  # model: (input, output) USD per million tokens
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
CACHE_WRITE, CACHE_READ, BATCH_DISCOUNT = 1.25, 0.10, 0.5
HARD_LIMIT_USD = 5.0  # CLAUDE.md: ask the user before spending more than this in one run
LEDGER_FIELDS = [
    "timestamp", "run_id", "task", "condition", "iteration", "backend", "model", "batch",
    "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens",
    "cost_usd", "run_cost_usd",
]  # fmt: skip


@dataclass(frozen=True)
class Pricing:
    input: float
    output: float

    @classmethod
    def for_model(
        cls, backend: str, model: str, override: tuple[float, float] | None = None
    ) -> "Pricing":
        if backend != "anthropic":
            return cls(0.0, 0.0)  # mock and local Ollama models cost nothing
        if override is not None:
            return cls(*override)
        if model not in PRICES:
            raise ValueError(f"no price for {model}; pass explicit input/output prices")
        return cls(*PRICES[model])

    def cost(self, usage: dict, batch: bool = False) -> float:
        total = (
            usage.get("input_tokens", 0) * self.input
            + usage.get("cache_creation_input_tokens", 0) * self.input * CACHE_WRITE
            + usage.get("cache_read_input_tokens", 0) * self.input * CACHE_READ
            + usage.get("output_tokens", 0) * self.output
        ) / 1e6
        return total * (BATCH_DISCOUNT if batch else 1.0)

    def upper_bound(self, input_tokens: int, max_tokens: int, batch: bool = False) -> float:
        """Worst case for one request: every input token written to cache, full output."""
        usage = {"cache_creation_input_tokens": input_tokens, "output_tokens": max_tokens}
        return self.cost(usage, batch)


def append_ledger(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LEDGER_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(
            {"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            | {k: row.get(k, "") for k in LEDGER_FIELDS if k != "timestamp"}
        )
