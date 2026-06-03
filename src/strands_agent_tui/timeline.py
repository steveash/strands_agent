from __future__ import annotations

from collections.abc import Sequence

from strands_agent_tui.runtime import RuntimeEvent

EVENT_FILTER_MODES = frozenset({"all", "runtime", "tool", "failure", "persistence", "intervention"})
TIMELINE_KEYS_LINE = (
    "Keys: F1 all, F2 runtime, F3 tool, F4 failure, F5 persistence, F12 intervention, "
    "Ctrl+T detail, Ctrl+R raw"
)


def filter_events(events: Sequence[RuntimeEvent], event_filter: str) -> list[RuntimeEvent]:
    if event_filter == "all":
        return list(events)
    return [event for event in events if event.category == event_filter]


def render_event_timeline(
    events: Sequence[RuntimeEvent],
    *,
    event_filter: str = "all",
    max_events: int = 12,
    show_details: bool = True,
    show_data: bool = True,
) -> str:
    if not events:
        return (
            "Event Timeline\n\n"
            "No events yet.\n"
            "Tool calls, runtime milestones, and failures will appear here."
        )

    filtered = filter_events(events, event_filter)
    lines = [
        "Event Timeline",
        f"Filter: {event_filter} ({len(filtered)}/{len(events)} events)",
        f"View: detail {'on' if show_details else 'off'} | raw {'on' if show_data else 'off'}",
        TIMELINE_KEYS_LINE,
        "",
    ]
    visible = filtered[-max_events:]
    start_index = max(len(filtered) - len(visible) + 1, 1)
    for index, event in enumerate(visible, start=start_index):
        timestamp = event.timestamp[11:19] if event.timestamp else "--:--:--"
        lines.append(f"{index}. [{timestamp}] ({event.category}) kind={event.kind} | {event.title}")
        summary = summarize_event(event)
        if summary:
            lines.append(f"   summary: {summary}")
        if show_details:
            lines.append(f"   {event.detail}")
        if show_data and event.data:
            compact_data = ", ".join(f"{key}={value!r}" for key, value in sorted(event.data.items()))
            lines.append(f"   data: {compact_data}")
    return "\n".join(lines)


def summarize_event(event: RuntimeEvent) -> str:
    if event.kind.startswith("tool_"):
        return _summarize_tool_event(event)

    approval_summary = _summarize_approval_event(event)
    if approval_summary:
        return approval_summary

    if event.category == "persistence":
        return _summarize_persistence_event(event)
    return _summarize_runtime_event(event)


def _summarize_approval_event(event: RuntimeEvent) -> str:
    data = event.data
    status = _text(data.get("approval_status")) or _approval_status_from_kind(event.kind)
    if status not in {"pending", "approved", "denied", "blocked"}:
        return ""

    family = _text(data.get("approval_tool_family"))
    source = _text(data.get("approval_source"))
    queue_total = _int_value(data.get("approval_queue_total"))
    queue_position = _int_value(data.get("approval_queue_position")) or 1
    if queue_total is None:
        pending_count = _int_value(data.get("pending_count"))
        remaining_pending_count = _int_value(data.get("remaining_pending_count"))
        if pending_count is not None:
            queue_total = max(pending_count, 1)
        elif remaining_pending_count is not None:
            queue_total = max(remaining_pending_count, 0) + 1
    target_preview = _text(data.get("approval_target_preview"))
    command = _text(data.get("command"))
    relative_path = _text(data.get("relative_path"))
    next_pending_tool = _text(data.get("next_pending_tool"))
    age_summary = _text(data.get("approval_age_summary"))
    restored = bool(data.get("approval_restored", False))
    resumed = bool(data.get("resumed_from_approval", False))
    stage = _text(data.get("steering_stage"))

    if not target_preview:
        if command:
            target_preview = f"cmd {command}"
        elif relative_path:
            target_preview = f"path {relative_path}"

    if event.kind == "approval_follow_up_prepared":
        return _summarize_approval_follow_up_event(
            family=family,
            source=source,
            queue_total=queue_total,
            queue_position=queue_position,
            target_preview=target_preview,
            next_pending_tool=next_pending_tool,
            age_summary=age_summary,
            restored=restored,
            resumed=resumed,
            follow_up_mode=_text(data.get("follow_up_mode")),
            tool_result_preview=_text(data.get("tool_result_preview")),
        )

    head = f"approval {status}"
    if family:
        head += f" {family}"
    if source:
        head += f" via {source}"

    bits = [head]
    if queue_total is not None:
        bits.append(f"queue {queue_position}/{queue_total}")
    if target_preview:
        bits.append(target_preview)
    if next_pending_tool:
        bits.append(f"next {next_pending_tool}")
    if age_summary:
        bits.append(f"age {age_summary}")
    if restored:
        bits.append("restored")
    if resumed:
        bits.append("resumed")
    if stage and stage not in {"requested", status}:
        bits.append(f"stage {stage}")
    return " | ".join(bits)


def _summarize_approval_follow_up_event(
    *,
    family: str,
    source: str,
    queue_total: int | None,
    queue_position: int,
    target_preview: str,
    next_pending_tool: str,
    age_summary: str,
    restored: bool,
    resumed: bool,
    follow_up_mode: str,
    tool_result_preview: str,
) -> str:
    head = "approval continued"
    if family:
        head += f" {family}"
    if source:
        head += f" via {source}"

    bits = [head]
    if queue_total is not None:
        bits.append(f"queue {queue_position}/{queue_total}")
    if target_preview:
        bits.append(target_preview)
    if tool_result_preview:
        bits.append(f"result {tool_result_preview}")
    if next_pending_tool:
        bits.append(f"next {next_pending_tool}")

    follow_up_label = _follow_up_mode_label(follow_up_mode)
    if follow_up_label:
        bits.append(f"continue {follow_up_label}")
    if age_summary:
        bits.append(f"age {age_summary}")
    if restored:
        bits.append("restored")
    if resumed:
        bits.append("resumed")
    return " | ".join(bits)


def _summarize_tool_event(event: RuntimeEvent) -> str:
    data = event.data
    tool_name = _text(data.get("tool_name")) or event.title
    approval_status = _text(data.get("approval_status"))
    resumed = bool(data.get("resumed_from_approval", False))

    if tool_name == "run_shell_command":
        prefix = "shell failed" if event.kind == "tool_failed" else "shell"
        policy = _text(data.get("shell_policy"))
        command = _text(data.get("command"))
        preview = _text(data.get("output_preview")) or _text(data.get("result_preview"))
        if not preview and event.kind == "tool_failed":
            preview = _text(data.get("error")) or _detail_preview(event.detail)
        elif not preview:
            preview = _detail_preview(event.detail)
        summary = " ".join(part for part in [prefix, policy, command] if part)
        if preview:
            summary += f" -> {preview}"
        return _append_tool_state_bits(summary, approval_status=approval_status, resumed=resumed)

    if event.kind == "tool_failed":
        preview = _text(data.get("error")) or _detail_preview(event.detail)
        summary = f"tool failed {tool_name}"
        if preview:
            summary += f" -> {preview}"
        return _append_tool_state_bits(summary, approval_status=approval_status, resumed=resumed)

    preview = _text(data.get("result_preview")) or _detail_preview(event.detail)
    summary = f"tool {tool_name}"
    if preview:
        summary += f" -> {preview}"
    return _append_tool_state_bits(summary, approval_status=approval_status, resumed=resumed)


def _append_tool_state_bits(summary: str, *, approval_status: str, resumed: bool) -> str:
    bits = [summary]
    if approval_status == "approved":
        bits.append("approved")
    elif approval_status in {"pending", "denied", "blocked"}:
        bits.append(approval_status)
    if resumed:
        bits.append("resumed")
    return " | ".join(bits)


def _summarize_persistence_event(event: RuntimeEvent) -> str:
    data = event.data
    if event.kind == "artifact_saved":
        session_id = _text(data.get("session_id"))
        parts = ["artifact saved"]
        if session_id:
            parts.append(f"session {session_id}")
        if "pending_approval" in data:
            parts.append(f"pending {'yes' if bool(data.get('pending_approval')) else 'no'}")
        if bool(data.get("error", False)):
            parts.append("error")
        return " | ".join(parts)

    if event.kind == "session_state_saved":
        parts = ["session state saved"]
        pending_count = _int_value(data.get("pending_count"))
        if pending_count is not None:
            parts.append(f"pending {pending_count}")
        event_filter = _text(data.get("event_filter"))
        if event_filter and event_filter != "all":
            parts.append(f"filter {event_filter}")
        detail_state = _timeline_state_label(data)
        if detail_state != "detail on | raw on":
            parts.append(detail_state)
        draft_length = _int_value(data.get("draft_prompt_length"))
        if draft_length:
            parts.append(f"draft {draft_length}c")
        return " | ".join(parts)

    if event.kind == "session_state_restored":
        parts = ["session state restored"]
        pending_count = _int_value(data.get("pending_count"))
        if pending_count is not None:
            parts.append(f"pending {pending_count}")
        tool_name = _text(data.get("tool_name"))
        if tool_name:
            parts.append(f"first {tool_name}")
        return " | ".join(parts)

    if event.kind == "session_view_restored":
        parts = ["session view restored"]
        event_filter = _text(data.get("event_filter"))
        if event_filter:
            parts.append(f"filter {event_filter}")
        detail_state = _timeline_state_label(data)
        if detail_state != "detail on | raw on":
            parts.append(detail_state)
        view = _text(data.get("view"))
        if view:
            parts.append(view)
        return " | ".join(parts)

    return ""


def _summarize_runtime_event(event: RuntimeEvent) -> str:
    data = event.data
    if event.kind == "prompt_received":
        prompt_length = _int_value(data.get("prompt_length"))
        return f"prompt {prompt_length} chars" if prompt_length is not None else ""
    if event.kind == "response_completed":
        provider = _text(data.get("provider"))
        mode = _text(data.get("mode"))
        pending_count = _int_value(data.get("pending_count"))
        head = "response"
        if provider or mode:
            runtime_label = "/".join(value for value in [provider, mode] if value)
            head = f"response {runtime_label}".strip()
        if pending_count is None:
            return head
        return f"{head} | pending {pending_count}"
    if event.kind == "approval_input_blocked":
        tool_name = _text(data.get("tool_name"))
        return f"input blocked by {tool_name}" if tool_name else "input blocked by pending approval"
    if event.kind == "session_switch_blocked":
        tool_name = _text(data.get("tool_name"))
        return f"session switch blocked by {tool_name}" if tool_name else "session switch blocked"
    if event.kind == "runtime_error":
        mode = _text(data.get("mode"))
        return f"runtime error | mode {mode}" if mode else "runtime error"
    return ""


def _approval_status_from_kind(kind: str) -> str:
    if kind == "steering_confirmation_required":
        return "pending"
    if kind == "steering_approved":
        return "approved"
    if kind == "steering_denied":
        return "denied"
    if kind == "steering_blocked":
        return "blocked"
    return ""


def _follow_up_mode_label(mode: str) -> str:
    if mode == "approved_tool_result":
        return "approved result"
    if mode == "denied_tool_request":
        return "denied request"
    return mode


def _detail_preview(detail: str, limit: int = 80) -> str:
    text = " ".join(detail.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _text(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    return text


def _timeline_state_label(data: dict[str, object]) -> str:
    detail_on = bool(data.get("show_event_details", True))
    raw_on = bool(data.get("show_event_data", True))
    return f"detail {'on' if detail_on else 'off'} | raw {'on' if raw_on else 'off'}"


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None
