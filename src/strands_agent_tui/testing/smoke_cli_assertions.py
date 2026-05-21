from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SmokeCliDocSpec:
    script_name: str
    readme_section_heading: str
    help_required_snippets: tuple[str, ...]
    readme_required_snippets: tuple[str, ...]


SMOKE_CLI_DOC_SPECS = (
    SmokeCliDocSpec(
        script_name="standalone_smoke",
        readme_section_heading="Standalone local smoke bundle",
        help_required_snippets=(
            "Which standalone smoke surface to run.",
            "Alias details: local -> summary-utils, shell-tool, replay all -> summary-utils, shell-tool, replay, live",
            "default local alias -> summary-utils, shell-tool, replay",
            "standalone_smoke.py all # all alias -> summary-utils, shell-tool, replay, live",
            "standalone_smoke.py replay # single target",
        ),
        readme_required_snippets=(
            ".venv/bin/python scripts/standalone_smoke.py",
            "default `local` bundle runs `summary_utils`, `shell_tool`, and `replay` smokes together",
            "`.venv/bin/python scripts/standalone_smoke.py local` explicitly re-runs the default `local` alias (`summary_utils`, `shell_tool`, `replay`)",
            "`.venv/bin/python scripts/standalone_smoke.py all` runs the live-inclusive alias (`summary_utils`, `shell_tool`, `replay`, `live`)",
            "`.venv/bin/python scripts/standalone_smoke.py replay` runs just the replay smoke target",
        ),
    ),
    SmokeCliDocSpec(
        script_name="session_triage_smoke",
        readme_section_heading="Session triage smoke bundle",
        help_required_snippets=(
            "Which session-triage smoke surface to run.",
            "Alias details: both -> picker, switcher all -> picker, switcher",
            "default both alias -> picker, switcher",
            "session_triage_smoke.py all # all alias -> picker, switcher",
            "session_triage_smoke.py picker # single target",
        ),
        readme_required_snippets=(
            ".venv/bin/python scripts/session_triage_smoke.py",
            "default bundle runs both triage targets",
            "`.venv/bin/python scripts/session_triage_smoke.py both` explicitly re-runs the default picker+switcher alias",
            "`.venv/bin/python scripts/session_triage_smoke.py all` is an explicit alias for the same picker+switcher bundle",
            "`.venv/bin/python scripts/session_triage_smoke.py picker` runs only the launch-time picker smoke",
        ),
    ),
    SmokeCliDocSpec(
        script_name="session_recovery_smoke",
        readme_section_heading="Session recovery smoke bundle",
        help_required_snippets=(
            "Which recovery smoke surface to run.",
            "Alias details: all -> approval, approval-restart, session-state, live-restore, live-restore-denied",
            "default all alias -> approval, approval-restart, session-state, live-restore, live-restore-denied",
            "session_recovery_smoke.py live-restore # single target",
            "session_recovery_smoke.py approval # single target",
        ),
        readme_required_snippets=(
            ".venv/bin/python scripts/session_recovery_smoke.py",
            "bundle runs all recovery targets by default",
            "`.venv/bin/python scripts/session_recovery_smoke.py all` explicitly selects the full recovery bundle (`approval`, `approval-restart`, `session-state`, `live-restore`, `live-restore-denied`)",
            "`.venv/bin/python scripts/session_recovery_smoke.py live-restore` runs only the live-restore recovery target",
            "`.venv/bin/python scripts/session_recovery_smoke.py approval` runs only the approval smoke target",
        ),
    ),
    SmokeCliDocSpec(
        script_name="smoke_matrix",
        readme_section_heading="Full local smoke matrix",
        help_required_snippets=(
            "Which smoke bundle or bundle matrix to run.",
            "Bundle aliases: local -> standalone, triage, recovery all -> standalone (live-inclusive), triage, recovery",
            "default local alias -> standalone, triage, recovery",
            "The default 'local' matrix excludes the opt-in live runtime smoke target, and the 'all' alias swaps in the live-inclusive standalone bundle.",
            "smoke_matrix.py standalone # single bundle",
            "smoke_matrix.py triage # single bundle",
            "smoke_matrix.py recovery # single bundle",
            "smoke_matrix.py all # all alias -> standalone (live-inclusive), triage, recovery",
        ),
        readme_required_snippets=(
            ".venv/bin/python scripts/smoke_matrix.py",
            "default `local` matrix runs the standalone local bundle plus the session-triage and recovery bundles together",
            "`.venv/bin/python scripts/smoke_matrix.py local` explicitly re-runs the default local matrix (`standalone`, `triage`, `recovery`)",
            "`.venv/bin/python scripts/smoke_matrix.py all` swaps in the live-inclusive standalone bundle (`standalone (live-inclusive)`, `triage`, `recovery`)",
            "`.venv/bin/python scripts/smoke_matrix.py standalone` runs only the standalone local bundle",
            "`.venv/bin/python scripts/smoke_matrix.py triage` runs only the session-triage bundle",
            "`.venv/bin/python scripts/smoke_matrix.py recovery` runs only the recovery bundle",
        ),
    ),
)


def normalize_cli_text(text: str) -> str:
    return " ".join(text.split())


def markdown_section_text(markdown: str, *, heading: str) -> str:
    lines = markdown.splitlines()
    section_level: int | None = None
    start_index: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        hashes, _, title = stripped.partition(" ")
        if title == heading:
            section_level = len(hashes)
            start_index = index + 1
            break

    if section_level is None or start_index is None:
        raise ValueError(f"markdown heading not found: {heading!r}")

    collected: list[str] = []
    for line in lines[start_index:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes, _, title = stripped.partition(" ")
            if title and len(hashes) <= section_level:
                break
        collected.append(line)
    return "\n".join(collected).strip()


def matches_markdown_section(
    markdown: str,
    *,
    heading: str,
    required_snippets: Iterable[str],
) -> bool:
    normalized = normalize_cli_text(markdown_section_text(markdown, heading=heading))
    return all(snippet in normalized for snippet in required_snippets)


def matches_public_cli_invalid_choice(
    text: str,
    *,
    invalid_target: str,
    expected_choices: str,
) -> bool:
    normalized = normalize_cli_text(text)
    return f"invalid choice: '{invalid_target}'" in normalized and expected_choices in normalized


def matches_public_cli_help(
    text: str,
    *,
    required_snippets: Iterable[str],
) -> bool:
    normalized = normalize_cli_text(text)
    return all(snippet in normalized for snippet in required_snippets)
