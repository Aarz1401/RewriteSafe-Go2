"""Pluggable agent backends: Anthropic (Claude API), Ollama (local) and a mock.

Every backend turns an AgentRequest (system prompt + conversation) into an AgentReply (the
raw JSON text the agent produced plus token usage). `complete_many` lets the runner send
one iteration of many independent runs together; for Anthropic with batch=True it becomes
a single Message Batches API request (50% price, asynchronous).
"""

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

from agent.prompts import OUTPUT_SCHEMA

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class AgentRequest:
    custom_id: str  # unique per run and iteration, e.g. "<run_id>-it03"
    task: str
    iteration: int
    system: str
    messages: list[dict]  # [{"role": "user"|"assistant", "content": str}, ...]


@dataclass
class AgentReply:
    text: str  # the agent's JSON reply ("" when nothing usable came back)
    usage: dict = field(default_factory=dict)
    model: str = ""
    stop_reason: str = ""
    error: str | None = None
    batch: bool = False


class AgentBackend(Protocol):
    name: str
    model: str

    def complete_many(self, requests: list[AgentRequest], batch: bool = False) -> dict: ...


def _usage(raw) -> dict:
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
            "cache_read_input_tokens")  # fmt: skip
    return {k: int(getattr(raw, k, 0) or 0) for k in keys}


class MockBackend:
    """Returns pre-written programs and diagnoses from agent/fixtures/<task>.yaml.

    Used for tests and for exercising the whole loop without spending money. Iterations
    beyond the end of the fixture list repeat the last entry.
    """

    name = "mock"

    def __init__(self, model: str = "mock", fixtures: Path = FIXTURES) -> None:
        self.model = model
        self.fixtures = fixtures

    def reply(self, request: AgentRequest) -> AgentReply:
        path = self.fixtures / f"{request.task}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"no mock fixture for task {request.task}: {path}")
        versions = yaml.safe_load(path.read_text())["versions"]
        version = versions[min(request.iteration, len(versions) - 1)]
        payload = {k: version[k] for k in ("program", "diagnosis", "claims")}
        usage = dict.fromkeys(
            ["input_tokens", "output_tokens", "cache_creation_input_tokens",
             "cache_read_input_tokens"], 0
        )  # fmt: skip
        return AgentReply(json.dumps(payload), usage, self.model, "end_turn")

    def complete_many(self, requests: list[AgentRequest], batch: bool = False) -> dict:
        return {r.custom_id: self.reply(r) for r in requests}


class AnthropicBackend:
    """Claude via the official Python SDK.

    - JSON replies are constrained by structured outputs (output_config.format).
    - Prompt caching: an explicit breakpoint after the system prompt plus top-level automatic
      caching of the growing conversation, so each iteration re-reads the earlier turns from
      cache. Verify with usage.cache_read_input_tokens.
    - Refusals are recorded, not retried on another model: a server-side fallback would
      silently change which model wrote the program, confounding the experiment.
    """

    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        max_tokens: int = 16000,
        effort: str = "medium",
        client=None,
        poll_seconds: float = 30.0,
    ) -> None:
        self.model, self.max_tokens, self.effort = model, max_tokens, effort
        self.poll_seconds = poll_seconds
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set; no API request made")
            import anthropic

            client = anthropic.Anthropic(timeout=600.0)
        self.client = client

    def params(self, request: AgentRequest) -> dict:
        return dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],  # fmt: skip
            messages=request.messages,
            cache_control={"type": "ephemeral"},
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        )

    def count_input_tokens(self, request: AgentRequest) -> int:
        params = self.params(request)
        params.pop("max_tokens")
        return self.client.messages.count_tokens(**params).input_tokens

    def _reply(self, message, batch: bool = False) -> AgentReply:
        text = next((b.text for b in message.content if b.type == "text"), "")
        error = None
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            error = f"refusal ({getattr(details, 'category', None)})"
            text = ""
        elif message.stop_reason == "max_tokens":
            error = "reply truncated at max_tokens"
        return AgentReply(text, _usage(message.usage), message.model, message.stop_reason,
                          error, batch)  # fmt: skip

    def complete_many(self, requests: list[AgentRequest], batch: bool = False) -> dict:
        if not batch:
            return {
                r.custom_id: self._reply(self.client.messages.create(**self.params(r)))
                for r in requests
            }
        created = self.client.messages.batches.create(
            requests=[{"custom_id": r.custom_id, "params": self.params(r)} for r in requests]
        )
        while True:
            status = self.client.messages.batches.retrieve(created.id)
            if status.processing_status == "ended":
                break
            time.sleep(self.poll_seconds)
        replies = {}
        for result in self.client.messages.batches.results(created.id):  # any order
            if result.result.type == "succeeded":
                replies[result.custom_id] = self._reply(result.result.message, batch=True)
            else:
                replies[result.custom_id] = AgentReply(
                    "", {}, self.model, "", f"batch request {result.result.type}", True
                )
        for r in requests:
            replies.setdefault(r.custom_id, AgentReply("", {}, self.model, "", "missing", True))
        return replies


class OllamaBackend:
    """A free local model through Ollama's /api/chat endpoint (stdlib HTTP, no extra deps)."""

    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5-coder:14b",
        host: str | None = None,
        seed: int = 0,
        num_ctx: int = 32768,
        timeout: float = 900.0,
    ) -> None:
        self.model, self.seed, self.num_ctx, self.timeout = model, seed, num_ctx, timeout
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host

    def body(self, request: AgentRequest) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": request.system}, *request.messages],
            "stream": False,
            "format": OUTPUT_SCHEMA,
            "options": {"seed": self.seed, "num_ctx": self.num_ctx},
        }

    def complete(self, request: AgentRequest) -> AgentReply:
        data = json.dumps(self.body(request)).encode()
        http = urllib.request.Request(
            f"{self.host}/api/chat", data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(http, timeout=self.timeout) as response:
            result = json.loads(response.read())
        usage = {
            "input_tokens": int(result.get("prompt_eval_count", 0)),
            "output_tokens": int(result.get("eval_count", 0)),
        }
        text = result.get("message", {}).get("content", "")
        return AgentReply(text, usage, result.get("model", self.model),
                          result.get("done_reason", ""))  # fmt: skip

    def complete_many(self, requests: list[AgentRequest], batch: bool = False) -> dict:
        return {r.custom_id: self.complete(r) for r in requests}


def make_backend(config: dict, client=None) -> AgentBackend:
    """Build the backend named in config["backend"] (mock | anthropic | ollama)."""
    kind = config.get("backend", "mock")
    if kind == "mock":
        return MockBackend()
    if kind == "anthropic":
        options = config.get("anthropic", {})
        return AnthropicBackend(
            model=config.get("model", "claude-haiku-5-5"),
            max_tokens=options.get("max_tokens", 16000),
            effort=options.get("effort", "medium"),
            client=client,
            poll_seconds=options.get("batch_poll_seconds", 30.0),
        )
    if kind == "ollama":
        options = config.get("ollama", {})
        return OllamaBackend(
            model=config.get("model", "qwen2.5-coder:14b"),
            host=options.get("host"),
            seed=options.get("seed", 0),
            num_ctx=options.get("num_ctx", 32768),
        )
    raise ValueError(f"unknown agent backend {kind!r}")
