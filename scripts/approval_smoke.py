from strands_agent_tui.runtime import FakeStrandsRuntime


def main() -> None:
    runtime = FakeStrandsRuntime()

    first = runtime.run("overwrite the notes file and replace all stale values")
    print("initial text=", first.text)
    print("initial pending=", first.pending_approval.summary() if first.pending_approval else "none")
    print("initial events=", [event.kind for event in first.events])

    if first.pending_approval is None:
        return

    approved = runtime.resolve_pending_approval(first.pending_approval.request_id, approve=True)
    print("after approve text=", approved.text)
    print("next pending=", approved.pending_approval.summary() if approved.pending_approval else "none")
    print("after approve events=", [event.kind for event in approved.events])

    if approved.pending_approval is None:
        return

    denied = runtime.resolve_pending_approval(approved.pending_approval.request_id, approve=False)
    print("after deny text=", denied.text)
    print("final pending=", denied.pending_approval.summary() if denied.pending_approval else "none")
    print("after deny events=", [event.kind for event in denied.events])


if __name__ == "__main__":
    main()
