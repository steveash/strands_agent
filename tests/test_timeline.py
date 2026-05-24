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
            "next_pending_tool": "replace_text",
            "approval_age_summary": "3m",
            "relative_path": "notes.txt",
        },
    )

    assert (
        summarize_event(event)
        == "approval pending edit via fake_runtime | queue 1/2 | path notes.txt | next replace_text | age 3m"
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
