from __future__ import annotations

from strands_agent_tui.runtime import runtime_event
from strands_agent_tui.testing import emit_smoke_results
from strands_agent_tui.timeline import render_event_timeline


def build_demo_events():
    return [
        runtime_event(
            "prompt_received",
            "Prompt accepted",
            "Queued the operator prompt for the fake Strands runtime.",
            data={"prompt_length": 27},
        ),
        runtime_event(
            "response_completed",
            "Fake runtime response ready",
            "Produced a deterministic fake-runtime answer for the timeline smoke walkthrough.",
            data={"provider": "fake-strands", "mode": "fake", "pending_count": 0},
        ),
        runtime_event(
            "artifact_saved",
            "Session artifact saved",
            "Persisted the structured turn artifact after the fake runtime response completed.",
            data={"session_id": "timeline-smoke", "pending_approval": False},
        ),
        runtime_event(
            "session_state_saved",
            "Session state saved",
            "Persisted the current event filter and an in-progress draft prompt for restart-safe recovery.",
            data={"pending_count": 0, "event_filter": "runtime", "draft_prompt_length": 14},
        ),
    ]


def main() -> int:
    events = build_demo_events()
    full_timeline = render_event_timeline(events, event_filter="all")
    runtime_timeline = render_event_timeline(events, event_filter="runtime")
    persistence_timeline = render_event_timeline(events, event_filter="persistence")
    compact_timeline = render_event_timeline(events, event_filter="all", show_details=False, show_data=False)

    print("FULL TIMELINE")
    print(full_timeline)
    print("\nRUNTIME FILTER")
    print(runtime_timeline)
    print("\nPERSISTENCE FILTER")
    print(persistence_timeline)
    print("\nCOMPACT VIEW")
    print(compact_timeline)

    return emit_smoke_results(
        [
            (
                "timeline_runtime_summary",
                "summary: prompt 27 chars" in runtime_timeline
                and "summary: response fake-strands/fake | pending 0" in runtime_timeline,
            ),
            (
                "timeline_persistence_summary",
                "summary: artifact saved | session timeline-smoke | pending no" in persistence_timeline
                and "summary: session state saved | pending 0 | filter runtime | draft 14c" in persistence_timeline,
            ),
            (
                "timeline_filter_counts",
                "Filter: runtime (2/4 events)" in runtime_timeline
                and "Filter: persistence (2/4 events)" in persistence_timeline,
            ),
            (
                "timeline_compact_toggle",
                "View: detail off | raw off" in compact_timeline
                and "summary: response fake-strands/fake | pending 0" in compact_timeline
                and "Produced a deterministic fake-runtime answer" not in compact_timeline
                and "data:" not in compact_timeline,
            ),
            ("runtime_timeline_view", runtime_timeline),
            ("persistence_timeline_view", persistence_timeline),
            ("compact_timeline_view", compact_timeline),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
