from strands_agent_tui.runtime import FakeStrandsRuntime


def main() -> None:
    runtime = FakeStrandsRuntime()

    first = runtime.run("overwrite the notes file and replace all stale values")
    print("initial text=", first.text)
    print("initial pending=", first.pending_approval.summary() if first.pending_approval else "none")
    print("initial events=", [event.kind for event in first.events])
    pending_event = next((event for event in first.events if event.kind == "steering_confirmation_required"), None)
    print(
        "initial approval schema=",
        pending_event is not None
        and pending_event.data.get("approval_status") == "pending"
        and pending_event.data.get("approval_source") == "fake_runtime"
        and pending_event.data.get("pending_count") == 2,
    )

    if first.pending_approval is None:
        return

    approved = runtime.resolve_pending_approval(first.pending_approval.request_id, approve=True)
    print("after approve text=", approved.text)
    print("next pending=", approved.pending_approval.summary() if approved.pending_approval else "none")
    print("after approve events=", [event.kind for event in approved.events])
    approved_tool_event = next((event for event in approved.events if event.kind == "tool_finished"), None)
    print(
        "approved execution schema=",
        approved_tool_event is not None
        and approved_tool_event.data.get("approval_status") == "approved"
        and approved_tool_event.data.get("resumed_from_approval") is True
        and approved_tool_event.data.get("remaining_pending_count") == 1,
    )

    if approved.pending_approval is None:
        return

    denied = runtime.resolve_pending_approval(approved.pending_approval.request_id, approve=False)
    print("after deny text=", denied.text)
    print("final pending=", denied.pending_approval.summary() if denied.pending_approval else "none")
    print("after deny events=", [event.kind for event in denied.events])
    denied_event = next((event for event in denied.events if event.kind == "steering_denied"), None)
    print(
        "denied schema=",
        denied_event is not None
        and denied_event.data.get("approval_status") == "denied"
        and denied_event.data.get("remaining_pending_count") == 0,
    )


if __name__ == "__main__":
    main()
