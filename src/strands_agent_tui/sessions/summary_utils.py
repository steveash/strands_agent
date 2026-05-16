from __future__ import annotations

from collections.abc import Callable, Sequence


RECENT_SESSION_TRIAGE_JUMP_KEYS = "P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y"
RECENT_SESSION_TRIAGE_CHANGE_KEYS = "A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ]"
RECENT_SESSION_PICKER_PROMPT_KEYS = "J/K/A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ]"
RECENT_SESSION_TRIAGE_KEEP_KEYS = "P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ]"
RECENT_SESSION_PICKER_SELECTION_KEYS = "J, K, A, P, D, R, V, O, Q, X, U, T, W, E, G, H, I, Y, S, [, ], Enter, or N"
RECENT_SESSION_TRIAGE_LABELS = (
    "pending, denied, restore, restored-approval, stale-approval, stale-pending, "
    "stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, "
    "shell, shell-inspect, and shell-test triage."
)


def render_lane_label_list(lanes: Sequence[str]) -> str:
    return ", ".join(lanes)


def render_lane_focus_suffix(label: str, lanes: Sequence[str]) -> str:
    lane_labels = render_lane_label_list(lanes)
    if not lane_labels:
        return ""
    return f" | {label}: {lane_labels}"


def render_lane_focus_preview_lines(
    label: str,
    lanes: Sequence[str],
    *,
    include: bool = True,
) -> list[str]:
    lane_labels = render_lane_label_list(lanes)
    if not include or not lane_labels:
        return []
    return [f"- {label}: {lane_labels}"]


def render_filter_focus_line(
    label: str,
    lanes: Sequence[str],
    *,
    cutoff: str = "",
    oldest: str = "",
    oldest_at: str = "",
) -> str:
    lane_labels = render_lane_label_list(lanes) or "none"
    line = f"{label}: {lane_labels}"
    if cutoff:
        line += f" | cutoff: {cutoff}"
    if oldest:
        line += f" | oldest: {oldest}"
    if oldest_at:
        line += f" | oldest at: {oldest_at}"
    return line


def render_backlog_summary_line(
    label: str,
    count: int,
    *,
    lane_rollup: str = "",
    overlap_summary: str = "",
) -> str:
    session_label = "session" if count == 1 else "sessions"
    line = f"{label}: {count} {session_label}"
    if lane_rollup:
        line += f" | lanes: {lane_rollup}"
    if overlap_summary:
        line += f" | overlap: {overlap_summary}"
    return line


def render_backlog_metric_summary_line(
    label: str,
    count: int,
    metrics: Sequence[str],
) -> str:
    session_label = "session" if count == 1 else "sessions"
    parts = [f"{label}: {count} {session_label}", *(metric for metric in metrics if metric)]
    return " | ".join(parts)


def render_page_label(total_matches: int, page_size: int, page_index: int) -> str:
    if total_matches <= 0 or page_size <= 0:
        return "0/0"
    total_pages = ((total_matches - 1) // page_size) + 1
    return f"{page_index + 1}/{total_pages}"


def render_page_window_label(
    total_matches: int,
    page_size: int,
    page_index: int,
    visible_count: int,
) -> str:
    if total_matches <= 0 or page_size <= 0 or visible_count <= 0:
        return "0 of 0"
    start = page_index * page_size + 1
    end = start + visible_count - 1
    return f"{start}-{end} of {total_matches}"


def render_recent_session_page_banner(
    *,
    filter_mode: str,
    sort_mode: str,
    total_matches: int,
    page_size: int,
    page_index: int,
    visible_count: int,
    stale_cutoff_suffix: str = "",
) -> str:
    return (
        f"Filter: {filter_mode} | Sort: {sort_mode}{stale_cutoff_suffix} | "
        f"Page: {render_page_label(total_matches, page_size, page_index)} | "
        f"Showing: {render_page_window_label(total_matches, page_size, page_index, visible_count)}"
    )


def render_page_lane_summary_line(
    label: str,
    visible_rollup: str,
    *,
    off_page_rollup: str = "",
    visible_overlap_summary: str = "",
    off_page_overlap_summary: str = "",
) -> str:
    line = f"This page {label}: {visible_rollup}"
    if off_page_rollup:
        line += f" | more off-page: {off_page_rollup}"
    if visible_overlap_summary or off_page_overlap_summary:
        line += (
            " | overlap here/off-page: "
            f"{visible_overlap_summary or 'none'} / {off_page_overlap_summary or 'none'}"
        )
    return line


def render_page_metric_summary_line(
    label: str,
    metrics: Sequence[str],
    *,
    off_page_metrics: Sequence[str] = (),
) -> str:
    visible = [metric for metric in metrics if metric]
    line = f"This page {label}: {' | '.join(visible) if visible else 'none'}"
    remaining = [metric for metric in off_page_metrics if metric]
    if remaining:
        line += f" | more off-page: {' | '.join(remaining)}"
    return line


def render_recent_session_filter_summary_block_lines(
    *,
    backlog_label: str,
    count: int,
    focus_label: str,
    focus_lanes: Sequence[str],
    lane_rollup: str = "",
    overlap_summary: str = "",
    cutoff: str = "",
    page_lane_label: str = "",
    visible_rollup: str = "",
    off_page_rollup: str = "",
    visible_overlap_summary: str = "",
    off_page_overlap_summary: str = "",
) -> list[str]:
    lines = [
        render_backlog_summary_line(
            backlog_label,
            count,
            lane_rollup=lane_rollup,
            overlap_summary=overlap_summary,
        ),
        render_filter_focus_line(
            focus_label,
            focus_lanes,
            cutoff=cutoff,
        ),
    ]
    if page_lane_label and visible_rollup:
        lines.append(
            render_page_lane_summary_line(
                page_lane_label,
                visible_rollup,
                off_page_rollup=off_page_rollup,
                visible_overlap_summary=visible_overlap_summary,
                off_page_overlap_summary=off_page_overlap_summary,
            )
        )
    return lines


def render_recent_session_metric_summary_block_lines(
    *,
    backlog_label: str,
    count: int,
    backlog_metrics: Sequence[str],
    focus_label: str,
    focus_lanes: Sequence[str],
    oldest: str = "",
    oldest_at: str = "",
    page_metric_label: str = "",
    visible_metrics: Sequence[str] = (),
    off_page_metrics: Sequence[str] = (),
) -> list[str]:
    lines = [
        render_backlog_metric_summary_line(backlog_label, count, backlog_metrics),
        render_filter_focus_line(focus_label, focus_lanes, oldest=oldest, oldest_at=oldest_at),
    ]
    if page_metric_label and any(metric for metric in visible_metrics):
        lines.append(
            render_page_metric_summary_line(
                page_metric_label,
                visible_metrics,
                off_page_metrics=off_page_metrics,
            )
        )
    return lines


def render_compact_badge_row_suffix(
    *,
    default_suffix: str,
    focused_badges: Sequence[str],
    singular_label: str,
    plural_label: str,
    singular_value_transform: Callable[[str], str] | None = None,
) -> str:
    if not focused_badges:
        return default_suffix
    if len(focused_badges) == 1:
        value = focused_badges[0]
        if singular_value_transform is not None:
            value = singular_value_transform(value)
        return f" | {singular_label}: {value}"
    return f" | {plural_label}: {'; '.join(focused_badges)}"


def render_compact_badge_preview_lines(
    *,
    default_lines: Sequence[str],
    focused_badges: Sequence[str],
    focus_lanes: Sequence[str],
    focus_label: str,
    include_focus_line: bool,
    singular_label: str,
    plural_label: str,
    singular_value_transform: Callable[[str], str] | None = None,
) -> list[str]:
    focus_lines = render_lane_focus_preview_lines(focus_label, focus_lanes, include=include_focus_line)
    if not focused_badges:
        return [*focus_lines, *default_lines]
    if len(focused_badges) == 1:
        value = focused_badges[0]
        if singular_value_transform is not None:
            value = singular_value_transform(value)
        return [*focus_lines, f"- {singular_label}: {value}"]
    return [*focus_lines, f"- {plural_label}: {'; '.join(focused_badges)}"]


def render_recent_session_filter_jump_line() -> str:
    return (
        "Try A to show all sessions, or "
        f"{RECENT_SESSION_TRIAGE_JUMP_KEYS} to jump between {RECENT_SESSION_TRIAGE_LABELS}"
    )


def render_recent_session_empty_state_lines(
    *,
    available_count: int,
    filter_mode: str,
    surface: str = "picker",
) -> list[str]:
    surface = "switcher" if surface == "switcher" else "picker"
    lines = [f"No saved sessions match the active {surface} filter."]
    session_label = "session" if available_count == 1 else "sessions"
    verb = "exists" if available_count == 1 else "exist"
    lines.append(f"{available_count} saved {session_label} still {verb} under this root.")
    if filter_mode != "all":
        lines.append(render_recent_session_filter_jump_line())
    if surface == "picker":
        lines.append(
            "Press Enter or N to start a fresh session while keeping this picker context for the next reopen."
        )
    else:
        lines.append(
            "Use N to start a fresh session, or Esc/F11 to return to the active session until a visible match exists."
        )
        lines.append("Enter switches the highlighted session once a visible row exists again.")
    return lines


def render_selected_session_preview_header_lines(
    *,
    visible_index: int,
    overall_index: int,
    total_matches: int,
    session_id: str,
    session_dir: object,
) -> list[str]:
    return [
        "Selected preview:",
        f"- slot {visible_index} on this page | overall {overall_index} of {total_matches} | session {session_id}",
        f"- artifact dir: {session_dir}",
    ]


def render_selected_preview_section_lines(*blocks: Sequence[str]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        lines.extend(line for line in block if line)
    return lines


def render_selected_session_preview_lines(
    *,
    header_lines: Sequence[str],
    status_lines: Sequence[str] = (),
    approval_lines: Sequence[str] = (),
    intervention_lines: Sequence[str] = (),
    session_lines: Sequence[str] = (),
    tool_lines: Sequence[str] = (),
    workspace_lines: Sequence[str] = (),
    shell_lines: Sequence[str] = (),
    event_lines: Sequence[str] = (),
) -> list[str]:
    return render_selected_preview_section_lines(
        header_lines,
        status_lines,
        approval_lines,
        intervention_lines,
        session_lines,
        tool_lines,
        workspace_lines,
        shell_lines,
        event_lines,
    )


def render_numbered_preview_section_lines(label: str, items: Sequence[str]) -> list[str]:
    if not items:
        return []
    return [
        f"- {label} ({len(items)}):",
        *(f"  {index}. {item}" for index, item in enumerate(items, start=1)),
    ]


def render_preview_detail_line(label: str, value: str) -> list[str]:
    if not value:
        return []
    return [f"- {label}: {value}"]


def render_row_detail_suffix(label: str, value: str) -> str:
    if not value:
        return ""
    return f" | {label}: {value}"


def render_preview_badges_line(
    label: str,
    values: Sequence[str],
    *,
    separator: str = ", ",
) -> list[str]:
    if not values:
        return []
    return render_preview_detail_line(label, separator.join(values))


def render_row_badges_suffix(
    label: str,
    values: Sequence[str],
    *,
    separator: str = ", ",
) -> str:
    if not values:
        return ""
    return render_row_detail_suffix(label, separator.join(values))


def render_recent_session_summary_line(
    *,
    index: int,
    session_id: str,
    turn_count: int,
    updated_at: str,
    suffixes: Sequence[str],
) -> str:
    rendered_suffixes = "".join(suffix for suffix in suffixes if suffix)
    return f"{index}. {session_id} | {turn_count} turn(s) | updated {updated_at}{rendered_suffixes}"


def render_recent_session_list_row(
    *,
    marker: str,
    summary_line: str,
    is_current: bool = False,
) -> str:
    current_suffix = " (current)" if is_current else ""
    return f"{marker} {summary_line}{current_suffix}"


def render_badged_preview_line(
    label: str,
    value: str,
    badges: Sequence[str],
    *,
    badge_separator: str = "/",
    badge_value_separator: str = " ",
) -> list[str]:
    badge_prefix = badge_separator.join(badges)
    if badge_prefix and value:
        rendered_value = f"{badge_prefix}{badge_value_separator}{value}"
    else:
        rendered_value = badge_prefix or value
    return render_preview_detail_line(label, rendered_value)


def render_badged_row_suffix(
    label: str,
    value: str,
    badges: Sequence[str],
    *,
    badge_separator: str = "/",
    badge_value_separator: str = " ",
) -> str:
    badge_prefix = badge_separator.join(badges)
    if badge_prefix and value:
        rendered_value = f"{badge_prefix}{badge_value_separator}{value}"
    else:
        rendered_value = badge_prefix or value
    return render_row_detail_suffix(label, rendered_value)


def render_picker_controls_line() -> str:
    return (
        "Picker controls: J/K preview, A all, P pending, D denied, R restore, V restored approvals, "
        "O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, "
        "E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, [ prev page, ] next page, "
        "N new session"
    )


def render_switcher_controls_line() -> str:
    return (
        "Keys: ↑/↓ or J/K move, PgUp/PgDn or bracket keys page, Enter switch, 1-8 quick switch, "
        "A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, "
        "X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, "
        "I inspect shell, Y shell tests, S sort, N new session, Esc/F11 cancel"
    )


def render_picker_selection_prompt() -> str:
    return (
        "Select visible session number, press Enter to reopen highlighted, N for new session, or use "
        f"{RECENT_SESSION_PICKER_PROMPT_KEYS} to triage/page: "
    )


def render_picker_invalid_selection_message(selection: str, visible_count: int) -> str:
    return (
        f"Invalid selection: {selection!r}. Choose 1-{visible_count} from the visible list, "
        "press Enter to reopen highlighted, or N for a new session."
    )


def render_picker_invalid_key_guidance(visible_count: int) -> str:
    return f"Invalid selection. Use 1-{visible_count}, {RECENT_SESSION_PICKER_SELECTION_KEYS}."


def render_picker_empty_filter_prompt() -> str:
    return (
        "No sessions match this filter. Press Enter or N for a new session, or use "
        f"{RECENT_SESSION_TRIAGE_CHANGE_KEYS} to change triage: "
    )


def render_picker_empty_filter_visible_guidance() -> str:
    return (
        "No sessions are visible with the active filter. Press A to show all sessions, or "
        f"{RECENT_SESSION_TRIAGE_KEEP_KEYS} to keep triaging; Enter or N starts a new session."
    )


def render_picker_empty_filter_adjust_guidance() -> str:
    return (
        "No sessions match the active filter. Use "
        f"{RECENT_SESSION_TRIAGE_CHANGE_KEYS} to adjust triage, or press Enter/N to start a new session."
    )
