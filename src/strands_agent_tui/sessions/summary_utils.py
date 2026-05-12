from __future__ import annotations

from collections.abc import Callable, Sequence


def render_lane_focus_suffix(label: str, lanes: Sequence[str]) -> str:
    if not lanes:
        return ""
    return f" | {label}: {', '.join(lanes)}"


def render_lane_focus_preview_lines(
    label: str,
    lanes: Sequence[str],
    *,
    include: bool = True,
) -> list[str]:
    if not include or not lanes:
        return []
    return [f"- {label}: {', '.join(lanes)}"]


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
