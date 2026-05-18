from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.testing import emit_smoke_results


def main() -> int:
    runtime = FakeStrandsRuntime()

    first = runtime.run("overwrite the notes file and replace all stale values")
    pending_event = next((event for event in first.events if event.kind == "steering_confirmation_required"), None)
    results: list[tuple[str, object]] = [
        ("initial text", first.text),
        ("initial pending", first.pending_approval.summary() if first.pending_approval else "none"),
        ("initial events", [event.kind for event in first.events]),
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
    ]

    approved = None
    if first.pending_approval is not None:
        approved = runtime.resolve_pending_approval(first.pending_approval.request_id, approve=True)
        approved_tool_event = next((event for event in approved.events if event.kind == "tool_finished"), None)
        approved_follow_up_event = next(
            (event for event in approved.events if event.kind == "approval_follow_up_prepared"),
            None,
        )
        results.extend(
            [
                ("after approve text", approved.text),
                ("next pending", approved.pending_approval.summary() if approved.pending_approval else "none"),
                ("after approve events", [event.kind for event in approved.events]),
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
                    and approved_follow_up_event.data.get("next_pending_tool") == "replace_text",
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
        results.extend(
            [
                ("after deny text", denied.text),
                ("final pending", denied.pending_approval.summary() if denied.pending_approval else "none"),
                ("after deny events", [event.kind for event in denied.events]),
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
                    and denied_follow_up_event.data.get("approval_queue_after_current") == 0,
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
