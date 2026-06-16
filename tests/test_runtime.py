import json
from pathlib import Path

import pytest

from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import (
    AgentResponse,
    ApprovalRequest,
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
    assert result.events[4].data["approval_status"] == "pending"
    assert result.events[4].data["approval_source"] == "fake_runtime"
    assert result.events[4].data["approval_tool_family"] == "edit"
    assert result.events[4].data["approval_queue_position"] == 1
    assert result.events[4].data["approval_queue_total"] == 2
    assert result.events[4].data["approval_queue_after_current"] == 1
    assert result.events[4].data["approval_queue_has_more"] is True
    assert result.events[4].data["next_pending_tool"] == "replace_text"
    assert result.events[4].data["approval_target_kind"] == "path"
    assert result.events[4].data["approval_target_preview"] == "path notes.txt"
    assert result.events[4].data["approval_age_summary"]
    assert result.events[4].data["steering_stage"] == "requested"
    assert result.events[4].data["pending_count"] == 2
    assert "Approval required before continuing" in result.text


def test_fake_runtime_returns_pending_approval_for_shell_command_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("run pytest in the terminal")

    assert [event.kind for event in result.events] == [
        "prompt_received",
        "steering_decision",
        "steering_confirmation_required",
        "response_completed",
    ]
    assert result.pending_approval is not None
    assert result.pending_approval.tool_name == "run_shell_command"
    assert result.pending_approval.args["command"] == "pytest -q"
    assert result.events[2].data["approval_tool_family"] == "test"
    assert result.events[2].data["shell_command_family"] == "pytest"
    assert result.events[2].data["approval_target_kind"] == "command"
    assert result.events[2].data["approval_target_preview"] == "cmd pytest -q"
    assert result.events[2].data["approval_queue_total"] == 1
    assert result.events[2].data["approval_queue_after_current"] == 0
    assert result.events[2].data["approval_queue_has_more"] is False
    assert result.events[2].data["steering_stage"] == "requested"


def test_fake_runtime_allows_read_only_shell_inspection_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("check git status in the terminal")

    assert [event.kind for event in result.events] == [
        "prompt_received",
        "steering_decision",
        "tool_started",
        "tool_finished",
        "response_completed",
    ]
    assert result.pending_approval is None
    assert result.events[2].title == "run_shell_command"
    assert result.events[2].data["command"] == "git status --short"
    assert result.events[2].data["shell_policy"] == "inspect"
    assert result.events[3].data["shell_command_family"] == "git_status"
    assert result.events[3].data["exit_code"] == 0
    assert result.events[3].data["result_preview"] == "git status --short -> simulated clean output"


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
        "approval_follow_up_prepared",
        "steering_confirmation_required",
        "response_completed",
    ]
    assert approved.pending_approval is not None
    assert approved.pending_approval.tool_name == "replace_text"
    assert approved.events[0].data["approval_status"] == "approved"
    assert approved.events[0].data["approval_queue_total"] == 2
    assert approved.events[0].data["approval_queue_after_current"] == 1
    assert approved.events[0].data["approval_queue_has_more"] is True
    assert approved.events[0].data["next_pending_tool"] == "replace_text"
    assert approved.events[0].data["steering_stage"] == "approved"
    assert approved.events[1].data["approval_id"] == approval.request_id
    assert approved.events[1].data["resumed_from_approval"] is True
    assert approved.events[2].data["remaining_pending_count"] == 1
    assert approved.events[3].data["follow_up_mode"] == "approved_tool_result"
    assert approved.events[3].data["agent_continuation"] is True
    assert approved.events[3].data["tool_result_preview"] == "Simulated overwrite of notes.txt."
    assert approved.events[3].data["approval_target_kind"] == "path"
    assert approved.events[3].data["approval_target_preview"] == "path notes.txt"
    assert approved.events[3].data["approval_queue_total"] == 2
    assert approved.events[3].data["approval_queue_after_current"] == 1
    assert approved.events[3].data["next_pending_tool"] == "replace_text"
    assert approved.events[3].data["steering_stage"] == "continued"
    assert approved.events[4].data["approval_id"] == approved.pending_approval.request_id
    assert approved.events[4].data["approval_status"] == "pending"
    assert approved.events[4].data["approval_queue_total"] == 1
    assert approved.events[4].data["approval_queue_after_current"] == 0
    assert approved.events[4].data["steering_stage"] == "requested"
    assert "Approved write_file" in approved.text


def test_fake_runtime_denial_resolution_clears_last_pending_request() -> None:
    runtime = FakeStrandsRuntime()
    first_response = runtime.run("overwrite the notes file")

    assert first_response.pending_approval is not None

    denied = runtime.resolve_pending_approval(first_response.pending_approval.request_id, approve=False)

    assert [event.kind for event in denied.events] == [
        "steering_denied",
        "approval_follow_up_prepared",
        "response_completed",
    ]
    assert denied.events[0].data["approval_status"] == "denied"
    assert denied.events[0].data["approval_queue_total"] == 1
    assert denied.events[0].data["approval_queue_after_current"] == 0
    assert denied.events[0].data["approval_queue_has_more"] is False
    assert denied.events[0].data["steering_stage"] == "denied"
    assert denied.events[0].data["remaining_pending_count"] == 0
    assert denied.events[1].data["follow_up_mode"] == "denied_tool_request"
    assert denied.events[1].data["agent_continuation"] is True
    assert denied.events[1].data["approval_tool_family"] == "edit"
    assert denied.events[1].data["approval_target_kind"] == "path"
    assert denied.events[1].data["approval_target_preview"] == "path notes.txt"
    assert denied.events[1].data["approval_queue_total"] == 1
    assert denied.events[1].data["approval_queue_after_current"] == 0
    assert denied.pending_approval is None
    assert "Skipped write_file" in denied.text


def test_fake_runtime_can_restore_pending_approvals_after_restart() -> None:
    first_runtime = FakeStrandsRuntime()
    first_response = first_runtime.run("overwrite the notes file and replace all stale values")

    restored_runtime = FakeStrandsRuntime()
    restored_runtime.restore_pending_approvals(first_runtime.pending_approvals())

    restored = restored_runtime.resolve_pending_approval("approval-0001", approve=True)

    assert restored.pending_approval is not None
    assert restored.pending_approval.request_id == "approval-0002"
    assert restored.events[0].data["approval_restored"] is True
    assert restored.events[1].data["approval_restored"] is True
    assert restored.events[2].data["approval_restored"] is True
    assert restored.events[3].data["approval_restored"] is True
    assert restored.pending_approval.restored_from_session is True
    assert "Approved write_file" in restored.text


def test_live_runtime_can_restore_pending_approvals_without_requeuing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class StubRuntime(StrandsSDKRuntime):
        def _build_agent(self, api_key: str, event_sink=None):
            tools = build_workspace_tools(tmp_path, event_sink=event_sink, approval_queue=self._approval_queue)
            tool_map = {tool.tool_name: tool for tool in tools}

            def agent(prompt: str) -> str:
                return f"continued: {prompt}"

            self._restored_tools = tool_map
            return agent, len(tools)

    (tmp_path / "notes.txt").write_text("old\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    runtime = StubRuntime(workspace_root=tmp_path)
    runtime.restore_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0007",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "content": "new\n", "overwrite": True},
                source="live_runtime",
                prompt="overwrite notes",
            )
        ]
    )

    result = runtime.resolve_pending_approval("approval-0007", approve=True)

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "new\n"
    assert [event.kind for event in result.events] == [
        "steering_approved",
        "tool_started",
        "tool_finished",
        "approval_follow_up_prepared",
        "response_completed",
    ]
    assert result.events[0].data["approval_status"] == "approved"
    assert result.events[0].data["approval_restored"] is True
    assert result.events[0].data["approval_queue_total"] == 1
    assert result.events[0].data["approval_queue_after_current"] == 0
    assert result.events[0].data["steering_stage"] == "approved"
    assert result.events[1].data["approval_id"] == "approval-0007"
    assert result.events[1].data["approval_restored"] is True
    assert result.events[1].data["resumed_from_approval"] is True
    assert result.events[2].data["approval_source"] == "live_runtime"
    assert result.events[2].data["approval_restored"] is True
    assert result.events[2].data["remaining_pending_count"] == 0
    assert result.events[3].data["follow_up_mode"] == "approved_tool_result"
    assert result.events[3].data["approval_restored"] is True
    assert result.events[3].data["approval_queue_total"] == 1
    assert result.events[3].data["approval_queue_after_current"] == 0
    assert result.events[3].data["approval_target_kind"] == "path"
    assert result.events[3].data["approval_target_preview"] == "path notes.txt"
    assert result.events[3].data["steering_stage"] == "continued"
    assert result.pending_approval is None
    assert "continued:" in result.text


def test_live_runtime_can_restore_shell_pending_approval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class StubRuntime(StrandsSDKRuntime):
        def _build_agent(self, api_key: str, event_sink=None):
            tools = build_workspace_tools(tmp_path, event_sink=event_sink, approval_queue=self._approval_queue)

            def agent(prompt: str) -> str:
                return f"continued: {prompt}"

            self._restored_tools = {tool.tool_name: tool for tool in tools}
            return agent, len(tools)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    runtime = StubRuntime(workspace_root=tmp_path)
    runtime.restore_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0003",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pwd", "relative_path": ".", "timeout_seconds": 5},
                source="live_runtime",
                prompt="run pwd",
            )
        ]
    )

    result = runtime.resolve_pending_approval("approval-0003", approve=True)

    assert [event.kind for event in result.events] == [
        "steering_approved",
        "tool_started",
        "tool_finished",
        "approval_follow_up_prepared",
        "response_completed",
    ]
    assert result.pending_approval is None
    assert "continued:" in result.text
    assert result.events[1].data["approval_id"] == "approval-0003"
    assert result.events[1].data["args"]["command"] == "pwd"
    assert result.events[1].data["approval_restored"] is True
    assert result.events[1].data["resumed_from_approval"] is True
    assert result.events[2].title == "run_shell_command"
    assert result.events[2].data["approval_status"] == "approved"
    assert result.events[2].data["approval_restored"] is True
    assert result.events[3].data["approval_tool_family"] == "shell"
    assert result.events[3].data["approval_queue_total"] == 1
    assert result.events[3].data["approval_queue_after_current"] == 0
    assert result.events[3].data["approval_target_kind"] == "command"
    assert result.events[3].data["approval_target_preview"] == "cmd pwd"
    assert result.events[3].data["follow_up_mode"] == "approved_tool_result"


def test_live_runtime_can_restore_pending_approvals_and_deny_without_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class StubRuntime(StrandsSDKRuntime):
        def _build_agent(self, api_key: str, event_sink=None):
            tools = build_workspace_tools(tmp_path, event_sink=event_sink, approval_queue=self._approval_queue)

            def agent(prompt: str) -> str:
                return f"continued: {prompt}"

            self._restored_tools = {tool.tool_name: tool for tool in tools}
            return agent, len(tools)

    (tmp_path / "notes.txt").write_text("old\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    runtime = StubRuntime(workspace_root=tmp_path)
    runtime.restore_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0008",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "content": "new\n", "overwrite": True},
                source="live_runtime",
                prompt="overwrite notes",
            )
        ]
    )

    result = runtime.resolve_pending_approval("approval-0008", approve=False)

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "old\n"
    assert [event.kind for event in result.events] == [
        "steering_denied",
        "approval_follow_up_prepared",
        "response_completed",
    ]
    assert result.events[0].data["approval_status"] == "denied"
    assert result.events[0].data["approval_source"] == "live_runtime"
    assert result.events[0].data["approval_restored"] is True
    assert result.events[0].data["approval_queue_total"] == 1
    assert result.events[0].data["approval_queue_after_current"] == 0
    assert result.events[0].data["remaining_pending_count"] == 0
    assert result.events[0].data["resumed_from_approval"] is False
    assert result.events[1].data["follow_up_mode"] == "denied_tool_request"
    assert result.events[1].data["approval_restored"] is True
    assert result.events[1].data["approval_queue_total"] == 1
    assert result.events[1].data["approval_queue_after_current"] == 0
    assert result.events[1].data["approval_target_kind"] == "path"
    assert result.events[1].data["approval_target_preview"] == "path notes.txt"
    assert result.pending_approval is None
    assert "continued:" in result.text


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
    assert events[0].data["approval_status"] == "pending"
    assert events[0].data["approval_source"] == "live_runtime"
    assert events[0].data["approval_tool_family"] == "edit"
    assert events[0].data["steering_stage"] == "requested"


def test_build_workspace_tools_queues_shell_command_confirmation(tmp_path: Path) -> None:
    events = []
    approvals = _ApprovalQueue()
    tools = {
        tool.tool_name: tool
        for tool in build_workspace_tools(
            tmp_path,
            event_sink=events.append,
            approval_queue=approvals,
            prompt_provider=lambda: "run pwd",
        )
    }

    rendered = tools["run_shell_command"](command="pytest -q")

    assert rendered.startswith("Approval required for run_shell_command.")
    assert approvals.current() is not None
    assert approvals.current().tool_name == "run_shell_command"
    assert [event.kind for event in events] == ["steering_confirmation_required"]
    assert events[0].data["command"] == "pytest -q"
    assert events[0].data["shell_policy"] == "test"
    assert events[0].data["approval_status"] == "pending"
    assert events[0].data["approval_tool_family"] == "test"
    assert events[0].data["shell_command_family"] == "pytest"
    assert events[0].data["steering_stage"] == "requested"


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


def test_app_config_loads_stale_approval_warning_days(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRANDS_AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("STRANDS_AGENT_STALE_APPROVAL_DAYS", "14")

    from strands_agent_tui.config import load_config

    config = load_config()

    assert config.stale_approval_warning_days == 14
    assert config.stale_approval_warning_seconds == 14 * 24 * 60 * 60


def test_app_config_loads_workspace_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "custom-artifacts"
    profile_path.write_text(
        json.dumps(
            {
                "name": "demo repo",
                "runtime": "live",
                "model": "gpt-4.1-mini",
                "workspace": str(workspace),
                "artifacts_root": str(artifacts),
                "allow_overwrite": True,
                "stale_approval_days": 3,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("STRANDS_AGENT_RUNTIME", raising=False)
    monkeypatch.delenv("STRANDS_AGENT_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("STRANDS_AGENT_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("STRANDS_AGENT_ARTIFACTS_ROOT", raising=False)
    monkeypatch.delenv("STRANDS_AGENT_ALLOW_OVERWRITE", raising=False)
    monkeypatch.delenv("STRANDS_AGENT_STALE_APPROVAL_DAYS", raising=False)

    from strands_agent_tui.config import load_config

    config = load_config(profile_path=str(profile_path))

    assert config.profile_name == "demo repo"
    assert config.profile_path == str(profile_path.resolve())
    assert config.runtime_mode == "live"
    assert config.openai_model == "gpt-4.1-mini"
    assert config.workspace_root == str(workspace)
    assert config.artifacts_root == str(artifacts)
    assert config.allow_overwrite is True
    assert config.stale_approval_warning_days == 3


def test_app_config_env_overrides_workspace_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "name": "profile defaults",
                "runtime": "fake",
                "model": "profile-model",
                "workspace": str(tmp_path / "profile-workspace"),
                "allow_overwrite": "false",
                "stale_approval_days": 3,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STRANDS_AGENT_RUNTIME", "live")
    monkeypatch.setenv("STRANDS_AGENT_OPENAI_MODEL", "env-model")
    monkeypatch.setenv("STRANDS_AGENT_WORKSPACE_ROOT", str(tmp_path / "env-workspace"))
    monkeypatch.setenv("STRANDS_AGENT_ALLOW_OVERWRITE", "true")
    monkeypatch.setenv("STRANDS_AGENT_STALE_APPROVAL_DAYS", "9")

    from strands_agent_tui.config import load_config

    config = load_config(profile_path=str(profile_path))

    assert config.profile_name == "profile defaults"
    assert config.runtime_mode == "live"
    assert config.openai_model == "env-model"
    assert config.workspace_root == str(tmp_path / "env-workspace")
    assert config.allow_overwrite is True
    assert config.stale_approval_warning_days == 9


def test_event_kind_categories_cover_runtime_tool_failure_persistence_and_intervention() -> None:
    assert categorize_event_kind("prompt_received") == "runtime"
    assert categorize_event_kind("tool_started") == "tool"
    assert categorize_event_kind("tool_failed") == "failure"
    assert categorize_event_kind("runtime_error") == "failure"
    assert categorize_event_kind("artifact_saved") == "persistence"
    assert categorize_event_kind("steering_blocked") == "intervention"
    assert categorize_event_kind("steering_confirmation_required") == "intervention"
    assert categorize_event_kind("approval_follow_up_prepared") == "intervention"


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


def test_build_workspace_tools_allows_read_only_shell_command_without_confirmation(tmp_path: Path) -> None:
    events = []
    tools = {tool.tool_name: tool for tool in build_workspace_tools(tmp_path, event_sink=events.append)}

    rendered = tools["run_shell_command"](command="pwd")

    assert "Policy level: inspect" in rendered
    assert [event.kind for event in events] == ["steering_decision", "tool_started", "tool_finished"]
    assert events[0].title == "run_shell_command"
    assert events[0].data["command"] == "pwd"
    assert events[0].data["requires_confirmation"] is False
    assert events[0].data["shell_policy"] == "inspect"
    assert events[0].data["approval_status"] == "not_needed"
    assert events[0].data["steering_stage"] == "decision"
    assert events[2].data["command"] == "pwd"
    assert events[2].data["shell_policy"] == "inspect"
    assert events[2].data["exit_code"] == 0
    assert events[2].data["result_preview"].startswith("pwd ->")


def test_build_workspace_tools_requires_confirmation_for_shell_test_command(tmp_path: Path) -> None:
    events = []
    tools = {tool.tool_name: tool for tool in build_workspace_tools(tmp_path, event_sink=events.append)}

    with pytest.raises(PermissionError, match="Confirmation required"):
        tools["run_shell_command"](command="pytest -q")

    assert [event.kind for event in events] == ["steering_confirmation_required"]
    assert events[0].title == "run_shell_command"
    assert events[0].data["command"] == "pytest -q"
    assert events[0].data["requires_confirmation"] is True
    assert events[0].data["shell_policy"] == "test"


def test_build_workspace_tools_denies_unsupported_shell_command_before_execution(tmp_path: Path) -> None:
    events = []
    tools = {tool.tool_name: tool for tool in build_workspace_tools(tmp_path, event_sink=events.append)}

    with pytest.raises(PermissionError, match="outside the narrow allowlist"):
        tools["run_shell_command"](command="rm -rf .")

    assert [event.kind for event in events] == ["steering_blocked"]
    assert events[0].data["shell_policy"] == "unsupported"
