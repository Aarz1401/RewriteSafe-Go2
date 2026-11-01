import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import run


def fake_episode(source: str, task: str, seed: int) -> dict:
    return dict(
        task=task,
        seed=seed,
        success=True,
        safe=True,
        success_but_unsafe=False,
        severity=0.0,
        stdout=f"PRIVATE-{seed}",
        error=None,
        final_robot_pose=[seed, 0, 0],
        final_object_poses={},
        exploit_attempts=0,
    )


def test_anthropic_sdk_mocked_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-not-a-real-key")
    sdk = MagicMock()
    sdk.messages.count_tokens.return_value = SimpleNamespace(input_tokens=100)
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(dict(program="api.stop()", diagnosis="test fixture", claims=[])),
            )
        ],
        usage=SimpleNamespace(model_dump=lambda: dict(input_tokens=100, output_tokens=30)),
    )
    sdk.messages.create.return_value = response
    with (
        patch("agent.loop.Anthropic", return_value=sdk) as client,
        patch("agent.loop.run_program", side_effect=fake_episode) as execute,
    ):
        result = run(tmp_path / "run", mock=False)
    client.assert_called_once_with(max_retries=0, timeout=90.0)
    assert sdk.messages.create.call_count == 2
    assert execute.call_count == 46
    assert result["estimated_cost"] == pytest.approx(0.00025)
    prompt = (tmp_path / "run" / "prompt_1.json").read_text()
    assert "PRIVATE-0" in prompt
    assert all(f"PRIVATE-{seed}" not in prompt for seed in range(100, 120))
    assert len((tmp_path / "run" / "episodes.jsonl").read_text().splitlines()) == 46


def test_missing_key_is_clear_and_no_sdk_call(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("agent.loop.Anthropic") as client:
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set; no API request made"):
            run(tmp_path / "run", mock=False)
        client.assert_not_called()


def test_budget_stops_before_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-not-a-real-key")
    sdk = MagicMock()
    sdk.messages.count_tokens.return_value = SimpleNamespace(input_tokens=10000)
    with patch("agent.loop.Anthropic", return_value=sdk):
        result = run(tmp_path / "run", mock=False, budget=0.0001)
    sdk.messages.create.assert_not_called()
    assert result["status"] == "budget_stopped" and result["estimated_cost"] == 0
