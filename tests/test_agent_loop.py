"""M4: prompts, feedback conditions, backends (mocked clients, no network) and the loop."""

import io
import json
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import loop
from agent.backends import AgentRequest, AnthropicBackend, MockBackend, OllamaBackend
from agent.costs import Pricing
from agent.prompts import (
    OUTPUT_SCHEMA,
    SAFETY_INSTRUCTION,
    SYSTEM_PROMPT,
    episode_feedback,
    feedback_message,
    task_message,
)
from tasks.loader import HELDOUT_SEEDS, TRAIN_SEEDS

ROW = dict(
    split="train", feedback_label="layout A", success=True, safe=False, error=None,
    stdout="hello", final_robot_pose=[1.0, 0.0, 3.1], margins={"boundary": 0.0},
    final_object_poses={"blue_box": {"pose": [0.3, 0.0, 0.0], "tilt": 0.0}},
    displacement={"blue_box": 0.3}, tilt={"blue_box": 0.0}, touched=["blue_box"],
    min_person_clearance=None, speeding_events=2, max_near_speed=0.5, seed=1,
)  # fmt: skip


# ---------------------------------------------------------------- prompts and feedback


def test_task_message_conditions_and_ablation():
    c1, c2, c3 = (task_message("go_behind_box", c) for c in ("C1", "C2", "C3"))
    assert c1 == c2 and "Success criteria" not in c2
    assert "Success criteria" in c3 and "1.0 m from any person" in c3
    assert SAFETY_INSTRUCTION not in c2
    assert SAFETY_INSTRUCTION in task_message("go_behind_box", "C2", safety_instruction=True)
    assert "goal_zone" in task_message("handoff_point", "C1")
    for text in (c1, c3, SYSTEM_PROMPT):
        assert "held-out" not in text.lower() and "heldout" not in text.lower()


def test_feedback_conditions():
    c1 = episode_feedback(ROW, "C1")
    assert c1["success"] is True and "safety_report" not in c1
    assert set(c1) == {"layout", "success", "error", "stdout", "final_robot_pose",
                       "final_object_poses"}  # fmt: skip
    assert "seed" not in json.dumps(c1)
    c2 = episode_feedback(ROW, "C2")
    report = c2["safety_report"]
    assert report["objects_moved_m"] == {"blue_box": 0.3}
    assert report["objects_touched"] == ["blue_box"] and report["speeding_events"] == 2
    assert c2["success"] is True
    c3 = episode_feedback(ROW, "C3")
    assert c3["success"] is False and c3["task_completed"] is True and "safety_report" in c3


def test_feedback_refuses_heldout_rows():
    with pytest.raises(ValueError):
        feedback_message([ROW | {"split": "heldout"}], "C2")


# ---------------------------------------------------------------- costs


def test_pricing_and_cache_accounting():
    haiku = Pricing.for_model("anthropic", "claude-haiku-5-5")
    usage = dict(input_tokens=1000, cache_creation_input_tokens=2000,
                 cache_read_input_tokens=10000, output_tokens=500)  # fmt: skip
    expected = (1000 * 0.10 + 2000 * 0.125 + 10000 * 0.01 + 500 * 0.5) / 1e6
    assert haiku.cost(usage) == pytest.approx(expected)
    assert haiku.cost(usage, batch=True) == pytest.approx(expected / 2)
    assert Pricing.for_model("mock", "anything").cost(usage) == 0
    with pytest.raises(ValueError):
        Pricing.for_model("anthropic", "some-unknown-model")


def test_budget_over_five_dollars_needs_explicit_approval(tmp_path):
    with pytest.raises(SystemExit, match="ask the user"):
        loop.main(["--backend", "mock", "--budget", "6", "--out", str(tmp_path)])


# ---------------------------------------------------------------- fake episodes


def fake_run_many(source, task, seeds, workers=None):
    return [
        dict(task=task, seed=s, success=True, safe=s % 2 == 0, success_but_unsafe=s % 2 == 1,
             severity=0.0, stdout=f"PRIVATE-{s}", error=None, final_robot_pose=[s, 0, 0],
             final_object_poses={}, exploit_attempts=0, displacement={}, tilt={})
        for s in seeds
    ]  # fmt: skip


def reply_json(program="api.stop()", claims=()):
    return json.dumps(dict(program=program, diagnosis="test", claims=list(claims)))


def fake_message(text, stop_reason="end_turn", **usage):
    usage = dict(input_tokens=100, output_tokens=40, cache_creation_input_tokens=0,
                 cache_read_input_tokens=0) | usage  # fmt: skip
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                    SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(**usage), model="claude-haiku-5-5",
                           stop_reason=stop_reason, stop_details=None)  # fmt: skip


def anthropic_client(messages):
    client = MagicMock()
    client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=1500)
    client.messages.create.side_effect = messages
    return client


# ---------------------------------------------------------------- Anthropic backend


def test_anthropic_request_uses_caching_structured_output_and_effort():
    backend = AnthropicBackend(client=MagicMock(), effort="medium")
    request = AgentRequest("r-it00", "go_behind_box", 0, SYSTEM_PROMPT,
                           [{"role": "user", "content": "task"}])  # fmt: skip
    params = backend.params(request)
    assert params["model"] == "claude-haiku-5-5"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["cache_control"] == {"type": "ephemeral"}  # auto-cache the conversation
    assert params["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
    }
    assert "thinking" not in params and "temperature" not in params


def test_anthropic_missing_key_fails_before_any_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no API request made"):
        AnthropicBackend()


def test_anthropic_loop_end_to_end_with_mocked_sdk(tmp_path):
    client = anthropic_client([
        fake_message(reply_json(), cache_creation_input_tokens=1400),
        fake_message(reply_json(claims=[{"metric": "safety", "direction": "increase",
                                         "fix": "slower"}]), cache_read_input_tokens=1400),
    ])  # fmt: skip
    with patch("agent.loop.run_many", side_effect=fake_run_many):
        runs = loop.main(["--backend", "anthropic", "--budget", "0.5", "--out", str(tmp_path)],
                         client=client)  # fmt: skip
    run = runs[0]
    assert run.status == "complete" and client.messages.create.call_count == 2
    # Held-out outputs never enter the conversation; training outputs do.
    second = client.messages.create.call_args_list[1].kwargs["messages"]
    text = json.dumps(second)
    assert all(f"PRIVATE-{s}" in text for s in TRAIN_SEEDS)
    assert not any(f"PRIVATE-{s}" in text for s in HELDOUT_SEEDS)
    # Ledger: one row per iteration with cache accounting.
    ledger = (tmp_path / "cost_ledger.csv").read_text().splitlines()
    assert len(ledger) == 3 and "cache_read_input_tokens" in ledger[0]
    first = (100 * 0.10 + 1400 * 0.125 + 40 * 0.5) / 1e6
    second_cost = (100 * 0.10 + 1400 * 0.01 + 40 * 0.5) / 1e6
    assert run.spent == pytest.approx(first + second_cost)
    metrics = json.loads((run.dir / "iter_01" / "metrics.json").read_text())
    assert metrics["claimed_specific_fix"] and metrics["checks"][0]["claim"]["metric"] == "safe"
    assert (run.dir / "iter_01" / "program.py").read_text() == "api.stop()"


def test_budget_stops_before_generation(tmp_path):
    client = anthropic_client([])
    client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=200000)
    runs = loop.main(["--backend", "anthropic", "--budget", "0.001", "--out", str(tmp_path)],
                     client=client)  # fmt: skip
    client.messages.create.assert_not_called()
    assert runs[0].status == "budget_stopped"


def test_refusal_and_unparseable_replies_are_recorded_not_fatal(tmp_path):
    client = anthropic_client([fake_message("", stop_reason="refusal"),
                               fake_message("not json")])  # fmt: skip
    with patch("agent.loop.run_many", side_effect=fake_run_many):
        runs = loop.main(["--backend", "anthropic", "--out", str(tmp_path)], client=client)
    first = json.loads((runs[0].dir / "iter_00" / "metrics.json").read_text())
    second = json.loads((runs[0].dir / "iter_01" / "metrics.json").read_text())
    assert first["reply_error"].startswith("refusal")
    assert second["reply_error"].startswith("reply is not valid JSON")
    assert runs[0].messages[-1]["content"].startswith("Your previous reply could not be used")


def test_batch_iteration_maps_results_by_custom_id(tmp_path):
    client = MagicMock()
    client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
    client.messages.batches.create.return_value = SimpleNamespace(id="batch_1")
    client.messages.batches.retrieve.return_value = SimpleNamespace(processing_status="ended")

    def results(batch_id):
        requests = client.messages.batches.create.call_args.kwargs["requests"]
        out = [SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(
            type="succeeded", message=fake_message(reply_json(f"print('{r['custom_id']}')"))))
            for r in requests]  # fmt: skip
        random.Random(0).shuffle(out)  # batch results arrive in any order
        return out

    client.messages.batches.results.side_effect = results
    with patch("agent.loop.run_many", side_effect=fake_run_many):
        runs = loop.main(["--backend", "anthropic", "--condition", "C1", "C2", "C3",
                          "--iterations", "1", "--batch", "--out", str(tmp_path)],
                         client=client)  # fmt: skip
    assert client.messages.batches.create.call_count == 1  # one batch for the iteration
    assert len(client.messages.batches.create.call_args.kwargs["requests"]) == 3
    client.messages.create.assert_not_called()
    for run in runs:
        assert (run.dir / "iter_00" / "program.py").read_text() == f"print('{run.run_id}-it00')"
        assert json.loads((run.dir / "iter_00" / "reply.json").read_text())["batch"] is True


# ---------------------------------------------------------------- Ollama and mock


def test_ollama_backend_posts_schema_and_maps_usage():
    backend = OllamaBackend(model="qwen2.5-coder:14b", host="localhost:11434")
    request = AgentRequest("r-it00", "go_behind_box", 0, "SYS", [{"role": "user", "content": "t"}])
    answer = {"model": "qwen2.5-coder:14b", "message": {"content": reply_json()},
              "prompt_eval_count": 321, "eval_count": 54, "done_reason": "stop"}  # fmt: skip
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = io.BytesIO(json.dumps(answer).encode())
        reply = backend.complete_many([request])["r-it00"]
    http = urlopen.call_args.args[0]
    body = json.loads(http.data)
    assert http.full_url == "http://localhost:11434/api/chat"
    assert body["format"] == OUTPUT_SCHEMA and body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert reply.usage == {"input_tokens": 321, "output_tokens": 54}
    assert json.loads(reply.text)["program"] == "api.stop()"


def test_mock_backend_repeats_last_fixture_and_requires_one():
    mock = MockBackend()
    request = AgentRequest("x", "go_behind_box", 99, "", [])
    assert "0.45" in json.loads(mock.reply(request).text)["program"]
    with pytest.raises(FileNotFoundError):
        mock.reply(AgentRequest("x", "dock_at_rack", 0, "", []))


def test_mock_loop_on_the_simulator(tmp_path):
    """The real M4 path: mock agent, C2, 2 iterations, 3 training + 20 held-out episodes."""
    runs = loop.main(["--backend", "mock", "--out", str(tmp_path)])
    run = runs[0]
    rows = [json.loads(line) for line in (run.dir / "episodes.jsonl").read_text().splitlines()]
    assert len(rows) == 2 * 23
    assert {r["seed"] for r in rows if r["split"] == "heldout"} == set(HELDOUT_SEEDS)
    assert all(r["layout"]["seed"] == r["seed"] for r in rows)
    it0, it1 = (json.loads((run.dir / f"iter_0{i}" / "metrics.json").read_text())
                for i in (0, 1))  # fmt: skip
    assert it0["heldout"]["safe"] == 0 and it1["heldout"]["safe"] == 1
    assert it1["diagnosis_accuracy"] == 1.0
    request = (run.dir / "iter_01" / "request.json").read_text()
    heldout_stdout = [r["stdout"].strip() for r in rows if r["split"] == "heldout"]
    assert not any(s and json.dumps(s)[1:-1] in request for s in heldout_stdout)
    manifest = json.loads((run.dir / "manifest.json").read_text())
    assert manifest["status"] == "complete" and manifest["estimated_cost_usd"] == 0
    assert Path(tmp_path / "cost_ledger.csv").exists()
