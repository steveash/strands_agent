from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.testing import emit_smoke_results
from strands_agent_tui.timeline import render_event_timeline


def _summary_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith("summary:")]


def main() -> int:
    runtime = FakeStrandsRuntime()

    first = runtime.run("overwrite the notes file and replace all stale values")
    pending_event = next((event for event in first.events if event.kind == "steering_confirmation_required"), None)
    initial_timeline = render_event_timeline(first.events, event_filter="intervention")
    initial_summaries = _summary_lines(initial_timeline)
    results: list[tuple[str, object]] = [
        ("initial text", first.text),
        ("initial pending", first.pending_approval.summary() if first.pending_approval else "none"),
        ("initial events", [event.kind for event in first.events]),
        ("initial intervention summaries", initial_summaries),
        (
            "initial approval schema",
            pending_event is not None
            and pending_event.data.get("approval_status") == "pending"
            and pending_event.data.get("approval_source") == "fake_runtime"
            and pending_event.data.get("pending_count") == 2,
        ),
        (
            "initial queue schema",
            pending_event is not None
            and pending_event.data.get("approval_queue_position") == 1
            and pending_event.data.get("approval_queue_total") == 2
            and pending_event.data.get("approval_queue_after_current") == 1
            and pending_event.data.get("next_pending_tool") == "replace_text",
        ),
        (
            "initial target schema",
            pending_event is not None
            and pending_event.data.get("approval_target_kind") == "path"
            and pending_event.data.get("approval_target_preview") == "path notes.txt",
        ),
        (
            "timeline_pending_summary",
            any("approval pending edit via fake_runtime | queue 1/2 | path notes.txt | next replace_text" in line for line in initial_summaries),
        ),
    ]

    approved = None
    if first.pending_approval is not None:
        approved = runtime.resolve_pending_approval(first.pending_approval.request_id, approve=True)
        approved_tool_event = next((event for event in approved.events if event.kind == "tool_finished"), None)
        approved_follow_up_event = next(
            (event for event in approved.events if event.kind == "approval_follow_up_prepared"),
            None,
        )
        approved_timeline = render_event_timeline(approved.events, event_filter="intervention")
        approved_summaries = _summary_lines(approved_timeline)
        results.extend(
            [
                ("after approve text", approved.text),
                ("next pending", approved.pending_approval.summary() if approved.pending_approval else "none"),
                ("after approve events", [event.kind for event in approved.events]),
                ("after approve intervention summaries", approved_summaries),
                (
                    "approved execution schema",
                    approved_tool_event is not None
                    and approved_tool_event.data.get("approval_status") == "approved"
                    and approved_tool_event.data.get("resumed_from_approval") is True
                    and approved_tool_event.data.get("remaining_pending_count") == 1,
                ),
                (
                    "approved queue schema",
                    approved_follow_up_event is not None
                    and approved_follow_up_event.data.get("approval_queue_total") == 2
                    and approved_follow_up_event.data.get("approval_queue_after_current") == 1
                    and approved_follow_up_event.data.get("next_pending_tool") == "replace_text"
                    and approved_follow_up_event.data.get("approval_target_preview") == "path notes.txt",
                ),
                (
                    "timeline_approved_summary",
                    any(
                        "approval approved edit via fake_runtime | queue 1/2 | path notes.txt" in line
                        and "resumed" in line
                        for line in approved_summaries
                    )
                    and any(
                        "approval continued edit via fake_runtime | queue 1/2 | path notes.txt | result Simulated overwrite of notes.txt."
                        in line
                        and "next replace_text" in line
                        and "continue approved result" in line
                        and "resumed" in line
                        for line in approved_summaries
                    )
                    and any("approval pending edit via fake_runtime | queue 1/1 | path notes.txt" in line for line in approved_summaries),
                ),
            ]
        )
    else:
        results.extend(
            [
                ("after approve text", "skipped: missing initial pending approval"),
                ("next pending", "none"),
                ("after approve events", []),
                ("approved execution schema", False),
                ("approved queue schema", False),
            ]
        )

    if approved is not None and approved.pending_approval is not None:
        denied = runtime.resolve_pending_approval(approved.pending_approval.request_id, approve=False)
        denied_event = next((event for event in denied.events if event.kind == "steering_denied"), None)
        denied_follow_up_event = next(
            (event for event in denied.events if event.kind == "approval_follow_up_prepared"),
            None,
        )
        denied_timeline = render_event_timeline(denied.events, event_filter="intervention")
        denied_summaries = _summary_lines(denied_timeline)
        results.extend(
            [
                ("after deny text", denied.text),
                ("final pending", denied.pending_approval.summary() if denied.pending_approval else "none"),
                ("after deny events", [event.kind for event in denied.events]),
                ("after deny intervention summaries", denied_summaries),
                (
                    "denied schema",
                    denied_event is not None
                    and denied_event.data.get("approval_status") == "denied"
                    and denied_event.data.get("remaining_pending_count") == 0,
                ),
                (
                    "denied queue schema",
                    denied_follow_up_event is not None
                    and denied_follow_up_event.data.get("approval_queue_total") == 1
                    and denied_follow_up_event.data.get("approval_queue_after_current") == 0
                    and denied_follow_up_event.data.get("approval_target_preview") == "path notes.txt",
                ),
                (
                    "timeline_denied_summary",
                    any("approval denied edit via fake_runtime | queue 1/1 | path notes.txt" in line for line in denied_summaries)
                    and any(
                        "approval continued edit via fake_runtime | queue 1/1 | path notes.txt | continue denied request"
                        in line
                        for line in denied_summaries
                    ),
                ),
            ]
        )
    else:
        results.extend(
            [
                ("after deny text", "skipped: missing follow-up pending approval"),
                ("final pending", "none"),
                ("after deny events", []),
                ("denied schema", False),
                ("denied queue schema", False),
            ]
        )

    return emit_smoke_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
