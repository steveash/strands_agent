import pytest

from strands_agent_tui.config import AppConfig
from pathlib import Path

from strands_agent_tui.runtime import AgentResponse, FakeStrandsRuntime, StrandsSDKRuntime, build_runtime


def test_fake_runtime_echoes_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("hello world")
    assert isinstance(result, AgentResponse)
    assert result.provider == "fake-strands"
    assert result.mode == "fake"
    assert result.text == "(fake-strands) Echo: hello world"


def test_fake_runtime_handles_empty_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("   ")
    assert result.text == "Please enter a prompt."


def test_build_runtime_defaults_to_fake() -> None:
    runtime = build_runtime()
    assert isinstance(runtime, FakeStrandsRuntime)


def test_build_runtime_live_selects_strands_sdk_runtime(tmp_path: Path) -> None:
    runtime = build_runtime(mode="live", openai_model="gpt-4o-mini", workspace_root=tmp_path)
    assert isinstance(runtime, StrandsSDKRuntime)
    assert runtime.openai_model == "gpt-4o-mini"
    assert runtime.workspace_root == tmp_path.resolve()


def test_live_runtime_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = StrandsSDKRuntime()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        runtime.run("hello")


def test_app_config_merge_applies_non_empty_overrides() -> None:
    config = AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini", workspace_root=".")

    updated = config.merge(runtime_mode="LIVE", openai_model="gpt-4.1-mini", workspace_root="/tmp/demo")

    assert updated.runtime_mode == "live"
    assert updated.openai_model == "gpt-4.1-mini"
    assert updated.workspace_root == "/tmp/demo"


def test_app_config_merge_ignores_empty_overrides() -> None:
    config = AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini", workspace_root=".")

    updated = config.merge(runtime_mode="   ", openai_model=None, workspace_root="   ")

    assert updated == config
