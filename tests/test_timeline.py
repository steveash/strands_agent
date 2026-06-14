from strands_agent_tui.runtime import runtime_event
from strands_agent_tui.timeline import filter_events, render_event_timeline, summarize_event


def test_render_event_timeline_shows_tool_summary_and_data() -> None:
    event = runtime_event(
        kind="tool_finished",
        title="list_files",
        detail="Returned a simulated workspace listing without touching disk.",
        data={"tool_name": "list_files", "result_preview": ".: README.md", "source": "fake_runtime"},
    )

    rendered = render_event_timeline([event])

    assert "summary: tool list_files -> .: README.md" in rendered
    assert "Returned a simulated workspace listing without touching disk." in rendered
    assert "data: result_preview='.: README.md', source='fake_runtime', tool_name='list_files'" in rendered


def test_summarize_event_compacts_intervention_queue_context() -> None:
    event = runtime_event(
        kind="steering_confirmation_required",
        title="write_file",
        detail="Overwrite request requires confirmation.",
        data={
            "approval_status": "pending",
            "approval_source": "fake_runtime",
            "approval_tool_family": "edit",
            "approval_queue_position": 1,
            "approval_queue_total": 2,
            "approval_target_preview": "path notes.txt",
            "next_pending_tool": "replace_text",
            "approval_age_summary": "3m",
        },
    )

    assert (
        summarize_event(event)
        == "approval pending edit via fake_runtime | queue 1/2 | path notes.txt | next replace_text | age 3m"
    )


def test_summarize_event_distinguishes_follow_up_preparation() -> None:
    event = runtime_event(
        kind="approval_follow_up_prepared",
        title="write_file",
        detail="Prepared the synthetic continuation prompt for the agent after resolving the approval request.",
        data={
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_tool_family": "edit",
            "approval_queue_position": 1,
            "approval_queue_total": 2,
            "approval_target_preview": "path notes.txt",
            "next_pending_tool": "replace_text",
            "follow_up_mode": "approved_tool_result",
            "tool_result_preview": "Simulated overwrite of notes.txt.",
            "resumed_from_approval": True,
        },
    )

    assert (
        summarize_event(event)
        == "approval continued edit via fake_runtime | queue 1/2 | path notes.txt | result Simulated overwrite of notes.txt. | next replace_text | continue approved result | resumed"
    )


def test_summarize_event_marks_approved_shell_tool_resumes() -> None:
    event = runtime_event(
        kind="tool_finished",
        title="run_shell_command",
        detail="Shell command completed after approval.",
        data={
            "tool_name": "run_shell_command",
            "shell_policy": "test",
            "command": "pytest -q",
            "output_preview": "2 passed",
            "approval_status": "approved",
            "resumed_from_approval": True,
        },
    )

    assert summarize_event(event) == "shell test pytest -q -> 2 passed | approved | resumed"


def test_render_event_timeline_hides_detail_and_raw_sections_when_toggled_off() -> None:
    event = runtime_event(
        kind="tool_finished",
        title="list_files",
        detail="Returned a simulated workspace listing without touching disk.",
        data={"tool_name": "list_files", "result_preview": ".: README.md", "source": "fake_runtime"},
    )

    rendered = render_event_timeline([event], show_details=False, show_data=False)

    assert "View: detail off | raw off" in rendered
    assert "summary: tool list_files -> .: README.md" in rendered
    assert "\n   Returned a simulated workspace listing without touching disk." not in rendered
    assert "data: result_preview='.: README.md'" not in rendered


def test_render_event_timeline_spotlights_single_event_in_compact_view() -> None:
    events = [
        runtime_event(
            kind="prompt_received",
            title="Prompt accepted",
            detail="Queued the operator prompt.",
            data={"prompt_length": 12},
        ),
        runtime_event(
            kind="tool_finished",
            title="list_files",
            detail="Returned a simulated workspace listing without touching disk.",
            data={"tool_name": "list_files", "result_preview": ".: README.md", "source": "fake_runtime"},
        ),
        runtime_event(
            kind="response_completed",
            title="Fake runtime response ready",
            detail="Produced a deterministic fake-runtime answer.",
            data={"provider": "fake-strands", "mode": "fake", "pending_count": 0},
        ),
    ]

    rendered = render_event_timeline(
        events,
        show_details=False,
        show_data=False,
        focused_event_index=1,
        focus_expanded=True,
    )

    assert "Focus: event 2/3 | spotlight on" in rendered
    assert ">2. [" in rendered
    assert "   Returned a simulated workspace listing without touching disk." in rendered
    assert "data: result_preview='.: README.md', source='fake_runtime', tool_name='list_files'" in rendered
    assert "Queued the operator prompt." not in rendered
    assert "Produced a deterministic fake-runtime answer." not in rendered


def test_render_event_timeline_includes_latest_shortcut_in_key_legend() -> None:
    event = runtime_event(
        kind="response_completed",
        title="Fake runtime response ready",
        detail="Produced a deterministic fake-runtime answer.",
        data={"provider": "fake-strands", "mode": "fake", "pending_count": 0},
    )

    rendered = render_event_timeline([event], show_details=False, show_data=False)

    assert "Focus: latest" in rendered
    assert "Ctrl+L latest" in rendered


def test_render_event_timeline_preserves_empty_state() -> None:
    rendered = render_event_timeline([], event_filter="intervention")

    assert rendered == (
        "Event Timeline\n\n"
        "No events yet.\n"
        "Tool calls, runtime milestones, and failures will appear here."
    )


def test_filter_events_uses_event_categories() -> None:
    events = [
        runtime_event("prompt_received", "Prompt accepted", "hi", data={"prompt_length": 2}),
        runtime_event("tool_started", "list_files", "starting", data={"tool_name": "list_files"}),
        runtime_event("tool_failed", "run_shell_command", "failed", data={"tool_name": "run_shell_command"}),
        runtime_event("artifact_saved", "Session artifact saved", "saved", data={"session_id": "session-1"}),
        runtime_event(
            "steering_confirmation_required",
            "write_file",
            "confirm",
            data={"approval_status": "pending", "approval_source": "fake_runtime"},
        ),
    ]

    assert [event.kind for event in filter_events(events, "runtime")] == ["prompt_received"]
    assert [event.kind for event in filter_events(events, "tool")] == ["tool_started"]
    assert [event.kind for event in filter_events(events, "failure")] == ["tool_failed"]
    assert [event.kind for event in filter_events(events, "persistence")] == ["artifact_saved"]
    assert [event.kind for event in filter_events(events, "intervention")] == ["steering_confirmation_required"]


def test_summarize_event_compacts_runtime_response_metadata() -> None:
    event = runtime_event(
        kind="response_completed",
        title="Fake runtime response ready",
        detail="Produced a deterministic fake-runtime answer.",
        data={"provider": "fake-strands", "mode": "fake", "pending_count": 0},
    )

    assert summarize_event(event) == "response fake-strands/fake | pending 0"


def test_summarize_event_compacts_persistence_state() -> None:
    artifact_event = runtime_event(
        kind="artifact_saved",
        title="Session artifact saved",
        detail="Persisted the turn artifact.",
        data={"session_id": "session-1", "pending_approval": False},
    )
    state_event = runtime_event(
        kind="session_state_saved",
        title="Session state saved",
        detail="Persisted the current event filter and draft prompt.",
        data={"pending_count": 0, "event_filter": "runtime", "draft_prompt_length": 14},
    )
    toggled_state_event = runtime_event(
        kind="session_view_restored",
        title="Session view restored",
        detail="Restored the saved timeline state.",
        data={"event_filter": "tool", "show_event_details": False, "show_event_data": False, "view": "replay 3/4"},
    )

    assert summarize_event(artifact_event) == "artifact saved | session session-1 | pending no"
    assert summarize_event(state_event) == "session state saved | pending 0 | filter runtime | draft 14c"
    assert summarize_event(toggled_state_event) == "session view restored | filter tool | detail off | raw off | replay 3/4"


def test_summarize_event_compacts_timeline_focus_restore_state() -> None:
    state_event = runtime_event(
        kind="session_state_saved",
        title="Pending approvals saved",
        detail="Persisted pending approvals plus restart-safe view state.",
        data={
            "pending_count": 1,
            "event_filter": "tool",
            "show_event_details": False,
            "show_event_data": False,
            "event_focus_position": 2,
            "event_focus_event_count": 5,
            "event_focus_expanded": True,
        },
    )
    restored_event = runtime_event(
        kind="session_view_restored",
        title="Session view restored",
        detail="Restored saved timeline state.",
        data={
            "event_filter": "tool",
            "show_event_details": False,
            "show_event_data": False,
            "event_focus_position": 2,
            "event_focus_event_count": 5,
            "event_focus_expanded": True,
            "view": "replay 3/4",
        },
    )

    assert summarize_event(state_event) == (
        "session state saved | pending 1 | filter tool | detail off | raw off | event 2/5 spotlight"
    )
    assert summarize_event(restored_event) == (
        "session view restored | filter tool | detail off | raw off | event 2/5 spotlight | replay 3/4"
    )
