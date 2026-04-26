from pathlib import Path

import pytest

from strands_agent_tui.config import AppConfig
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
    assert result.events[0].kind == "input_rejected"


def test_fake_runtime_emits_deterministic_workspace_tool_events() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("list files in the workspace")

    event_kinds = [event.kind for event in result.events]

    assert event_kinds == ["prompt_received", "tool_started", "tool_finished", "response_completed"]
    assert result.events[1].title == "list_files"


def test_fake_runtime_emits_search_write_and_edit_events() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("search the repo, create a notes file, and replace stale text")

    titles = [event.title for event in result.events]

    assert titles == [
        "Prompt accepted",
        "list_files",
        "list_files",
        "search_files",
        "search_files",
        "write_file",
        "write_file",
        "replace_text",
        "replace_text",
        "Assistant response ready",
    ]


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


def test_app_config_defaults_artifacts_root_under_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRANDS_AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("STRANDS_AGENT_ARTIFACTS_ROOT", raising=False)

    from strands_agent_tui.config import load_config

    config = load_config()

    assert config.artifacts_root == str(tmp_path.resolve() / "artifacts" / "sessions")
