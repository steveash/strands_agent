from pathlib import Path

import pytest

from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import (
    AgentResponse,
    FakeStrandsRuntime,
    StrandsSDKRuntime,
    _ApprovalQueue,
    build_runtime,
    build_workspace_tools,
    categorize_event_kind,
)
from strands_agent_tui.steering import build_default_policy


def test_fake_runtime_echoes_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("hello world")
    assert isinstance(result, AgentResponse)
    assert result.provider == "fake-strands"
    assert result.mode == "fake"
    assert result.text == "(fake-strands) Echo: hello world"
    assert result.pending_approval is None


def test_fake_runtime_handles_empty_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("   ")
    assert result.text == "Please enter a prompt."
    assert result.events[0].kind == "input_rejected"
    assert result.events[0].data["prompt_empty"] is True


def test_fake_runtime_emits_deterministic_workspace_tool_events() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("list files in the workspace")

    event_kinds = [event.kind for event in result.events]

    assert event_kinds == ["prompt_received", "steering_decision", "tool_started", "tool_finished", "response_completed"]
    assert result.events[1].title == "fake-policy"
    assert result.events[2].title == "list_files"


def test_fake_runtime_emits_search_write_and_edit_events() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("search the repo, create a notes file, and replace stale text")

    titles = [event.title for event in result.events]

    assert titles == [
        "Prompt accepted",
        "fake-policy",
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


def test_fake_runtime_emits_workspace_summary_events() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("summarize the repo structure")

    titles = [event.title for event in result.events]

    assert titles == [
        "Prompt accepted",
        "fake-policy",
        "list_files",
        "list_files",
        "summarize_workspace",
        "summarize_workspace",
        "Assistant response ready",
    ]


def test_fake_runtime_returns_pending_approval_for_risky_mutation_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("overwrite the notes file and replace all stale values")

    assert [event.kind for event in result.events] == [
        "prompt_received",
        "steering_decision",
        "tool_started",
        "tool_finished",
        "steering_confirmation_required",
        "response_completed",
    ]
    assert result.pending_approval is not None
    assert result.pending_approval.tool_name == "write_file"
    assert result.events[4].data["pending_count"] == 2
    assert "Approval required before continuing" in result.text


def test_fake_runtime_approval_resolution_executes_current_request_and_surfaces_next() -> None:
    runtime = FakeStrandsRuntime()
    first_response = runtime.run("overwrite the notes file and replace all stale values")

    assert first_response.pending_approval is not None
    approval = first_response.pending_approval

    approved = runtime.resolve_pending_approval(approval.request_id, approve=True)

    assert [event.kind for event in approved.events] == [
        "steering_approved",
        "tool_started",
        "tool_finished",
        "steering_confirmation_required",
        "response_completed",
    ]
    assert approved.pending_approval is not None
    assert approved.pending_approval.tool_name == "replace_text"
    assert approved.events[3].data["approval_id"] == approved.pending_approval.request_id
    assert "Approved write_file" in approved.text


def test_fake_runtime_denial_resolution_clears_last_pending_request() -> None:
    runtime = FakeStrandsRuntime()
    first_response = runtime.run("overwrite the notes file")

    assert first_response.pending_approval is not None

    denied = runtime.resolve_pending_approval(first_response.pending_approval.request_id, approve=False)

    assert [event.kind for event in denied.events] == ["steering_denied", "response_completed"]
    assert denied.pending_approval is None
    assert "Skipped write_file" in denied.text


def test_build_runtime_defaults_to_fake() -> None:
    runtime = build_runtime()
    assert isinstance(runtime, FakeStrandsRuntime)


def test_build_runtime_live_selects_strands_sdk_runtime(tmp_path: Path) -> None:
    runtime = build_runtime(mode="live", openai_model="gpt-4o-mini", workspace_root=tmp_path)
    assert isinstance(runtime, StrandsSDKRuntime)
    assert runtime.openai_model == "gpt-4o-mini"
    assert runtime.workspace_root == tmp_path.resolve()
    assert runtime.allow_overwrite is False


def test_live_runtime_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = StrandsSDKRuntime()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        runtime.run("hello")


def test_live_runtime_collects_tool_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class StubRuntime(StrandsSDKRuntime):
        def _build_agent(self, api_key: str, event_sink=None):
            tools = build_workspace_tools(tmp_path, event_sink=event_sink)
            tool_map = {tool.tool_name: tool for tool in tools}

            def agent(prompt: str) -> str:
                tool_map["read_file"](relative_path="notes.txt")
                return f"handled: {prompt}"

            return agent, len(tools)

    (tmp_path / "notes.txt").write_text("instrument me\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    runtime = StubRuntime(workspace_root=tmp_path)

    result = runtime.run("read the notes file")

    assert result.text == "handled: read the notes file"
    assert [event.kind for event in result.events] == [
        "prompt_received",
        "steering_decision",
        "tool_started",
        "tool_finished",
        "response_completed",
    ]
    assert result.events[1].title == "read_file"
    assert result.events[1].data["tool_name"] == "read_file"
    assert result.events[1].data["allowed"] is True
    assert "elapsed_ms=" in result.events[-1].detail
    assert result.metadata["model"] == "gpt-4o-mini"
    assert result.metadata["workspace_root"] == str(tmp_path.resolve())


def test_build_workspace_tools_can_queue_confirmation_instead_of_raising(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("old\n", encoding="utf-8")
    events = []
    approvals = _ApprovalQueue()
    tools = {
        tool.tool_name: tool
        for tool in build_workspace_tools(
            tmp_path,
            event_sink=events.append,
            approval_queue=approvals,
            prompt_provider=lambda: "overwrite notes",
        )
    }

    rendered = tools["write_file"](relative_path="notes.txt", content="new\n", overwrite=True)

    assert rendered.startswith("Approval required for write_file.")
    assert approvals.current() is not None
    assert approvals.current().tool_name == "write_file"
    assert [event.kind for event in events] == ["steering_confirmation_required"]
    assert events[0].data["approval_id"] == approvals.current().request_id


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


def test_app_config_loads_overwrite_policy_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRANDS_AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("STRANDS_AGENT_ALLOW_OVERWRITE", "true")

    from strands_agent_tui.config import load_config

    config = load_config()

    assert config.allow_overwrite is True


def test_event_kind_categories_cover_runtime_tool_failure_and_persistence() -> None:
    assert categorize_event_kind("prompt_received") == "runtime"
    assert categorize_event_kind("tool_started") == "tool"
    assert categorize_event_kind("tool_failed") == "failure"
    assert categorize_event_kind("runtime_error") == "failure"
    assert categorize_event_kind("artifact_saved") == "persistence"
    assert categorize_event_kind("steering_blocked") == "runtime"
    assert categorize_event_kind("steering_confirmation_required") == "runtime"


def test_build_workspace_tools_requires_confirmation_for_overwrite_by_default(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("old\n", encoding="utf-8")
    events = []
    tools = {tool.tool_name: tool for tool in build_workspace_tools(tmp_path, event_sink=events.append)}

    with pytest.raises(PermissionError, match="Confirmation required"):
        tools["write_file"](relative_path="notes.txt", content="new\n", overwrite=True)

    assert [event.kind for event in events] == ["steering_confirmation_required"]
    assert events[0].title == "write_file"
    assert events[0].data["allowed"] is False
    assert events[0].data["requires_confirmation"] is True
    assert events[0].data["disposition"] == "confirm"


def test_build_workspace_tools_allows_overwrite_when_policy_opted_in(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("old\n", encoding="utf-8")
    events = []
    tools = {
        tool.tool_name: tool
        for tool in build_workspace_tools(
            tmp_path,
            event_sink=events.append,
            steering_policy=build_default_policy(allow_overwrite=True),
        )
    }

    rendered = tools["write_file"](relative_path="notes.txt", content="new\n", overwrite=True)

    assert "Action: overwrote" in rendered
    assert [event.kind for event in events] == ["steering_decision", "tool_started", "tool_finished"]
    assert events[0].data["category"] == "allow_with_notice"


def test_build_workspace_tools_requires_confirmation_for_multi_occurrence_edit(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("alpha\nalpha\n", encoding="utf-8")
    events = []
    tools = {tool.tool_name: tool for tool in build_workspace_tools(tmp_path, event_sink=events.append)}

    with pytest.raises(PermissionError, match="Confirmation required"):
        tools["replace_text"](
            relative_path="notes.txt",
            old_text="alpha",
            new_text="beta",
            expected_occurrences=2,
        )

    assert [event.kind for event in events] == ["steering_confirmation_required"]
    assert events[0].title == "replace_text"
    assert events[0].data["expected_occurrences"] == 2
    assert events[0].data["requires_confirmation"] is True
