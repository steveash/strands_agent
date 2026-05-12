from __future__ import annotations

from collections.abc import Callable, Sequence


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
) -> str:
    lane_labels = render_lane_label_list(lanes) or "none"
    line = f"{label}: {lane_labels}"
    if cutoff:
        line += f" | cutoff: {cutoff}"
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
