from textwrap import dedent
from pathlib import Path

import pytest

from strands_agent_tui.testing import (
    DEFAULT_SMOKE_CLI_DOC_AUDIT_TARGET_NAMES,
    SMOKE_CLI_DOC_AUDIT_EXAMPLES,
    SMOKE_CLI_DOC_AUDIT_TARGET_NAMES,
    SMOKE_CLI_DOC_SPECS,
    SMOKE_CLI_DOC_SPECS_BY_SCRIPT_NAME,
    SMOKE_WRAPPER_CLI_SPECS,
    SmokeCliDocSpec,
    SmokeCliExample,
    build_smoke_cli_doc_audit_parser,
    build_smoke_cli_doc_audit_selector,
    build_smoke_cli_doc_spec_registry,
    failed_smoke_check_lines,
    is_failed_smoke_check_line,
    markdown_section_text,
    collect_smoke_cli_doc_parity,
    matches_approval_restore_age_output,
    matches_approval_restore_badges_output,
    matches_approval_restore_focus_output,
    matches_approval_restore_overlap_output,
    matches_approval_restore_overlap_preview_split_output,
    matches_approval_restore_page_rollup_output,
    matches_approval_restore_preview_split_output,
    matches_approval_restore_tool_badges_output,
    matches_broad_approval_stale_output,
    matches_broad_stale_row_focus_suppression,
    matches_compact_stale_preview_output,
    matches_custom_stale_cutoff_output,
    matches_denied_filter_output,
    matches_denied_page_rollup_output,
    matches_denied_preview_output,
    matches_intervention_filter_output,
    matches_markdown_section,
    matches_pending_age_output,
    matches_pending_filter_output,
    matches_pending_page_rollup_output,
    matches_picker_default_output,
    matches_public_cli_help,
    matches_public_cli_invalid_choice,
    matches_smoke_cli_doc_parity,
    matches_smoke_cli_help_for_script,
    matches_smoke_cli_readme_for_script,
    missing_markdown_section_snippets,
    missing_public_cli_help_snippets,
    matches_queue_breakdown_output,
    matches_shell_filter_output,
    matches_stale_backlog_output,
    matches_stale_cutoff_output,
    matches_stale_denied_subfilter_output,
    matches_stale_lane_focus_output,
    matches_stale_page_rollup_output,
    matches_stale_pending_subfilter_output,
    matches_stale_restored_subfilter_output,
    matches_switcher_default_output,
    matches_switcher_selected_preview_output,
    matches_tool_filter_output,
    matches_workspace_filter_output,
    normalize_cli_text,
    smoke_cli_doc_parity_diagnostic,
    smoke_cli_doc_spec,
    smoke_wrapper_cli_spec,
    smoke_text_matches,
)


README_PATH = Path(__file__).resolve().parent.parent / "README.md"
README_TEXT = README_PATH.read_text(encoding="utf-8")


def test_smoke_text_matches_supports_required_and_excluded_snippets() -> None:
    assert smoke_text_matches("alpha beta gamma", required=["alpha", "gamma"], excluded=["delta"])
    assert not smoke_text_matches("alpha beta gamma", required=["alpha", "delta"])
    assert not smoke_text_matches("alpha beta gamma", excluded=["beta"])


def test_smoke_failure_helpers_detect_false_result_lines() -> None:
    lines = [
        "picker_default_surface= True\n",
        "picker_tool_filter= False\n",
        "switcher_pending_filter= True\n",
        "plain traceback False but not a result line\n",
        "switcher_tool_filter= False\n",
    ]

    assert is_failed_smoke_check_line(lines[1])
    assert not is_failed_smoke_check_line(lines[0])
    assert not is_failed_smoke_check_line(lines[3])
    assert failed_smoke_check_lines(lines) == [
        "picker_tool_filter= False",
        "switcher_tool_filter= False",
    ]


def test_smoke_cli_helpers_normalize_public_help_and_invalid_choice_copy() -> None:
    help_text = "Usage: smoke_matrix.py [-h] {standalone,triage,recovery,local,all}\n\n  smoke_matrix.py all  # all alias -> standalone (live-inclusive), triage, recovery\n"
    error_text = "usage: smoke_matrix.py [-h] {standalone,triage,recovery,local,all}\nsmoke_matrix.py: error: argument target: invalid choice: 'standalone-all' (choose from 'standalone', 'triage', 'recovery', 'local', 'all')\n"

    assert normalize_cli_text(help_text) == (
        "Usage: smoke_matrix.py [-h] {standalone,triage,recovery,local,all} "
        "smoke_matrix.py all # all alias -> standalone (live-inclusive), triage, recovery"
    )
    assert matches_public_cli_help(
        help_text,
        required_snippets=["all alias -> standalone (live-inclusive), triage, recovery"],
    )
    assert matches_public_cli_invalid_choice(
        error_text,
        invalid_target="standalone-all",
        expected_choices="{standalone,triage,recovery,local,all}",
    )


def test_smoke_cli_doc_spec_registry_tracks_shared_order_and_lookup_helper() -> None:
    assert tuple(SMOKE_CLI_DOC_SPECS_BY_SCRIPT_NAME) == tuple(
        spec.script_name for spec in SMOKE_CLI_DOC_SPECS
    )
    assert tuple(smoke_cli_doc_spec(spec.script_name) for spec in SMOKE_CLI_DOC_SPECS) == SMOKE_CLI_DOC_SPECS

    with pytest.raises(ValueError, match="unknown smoke cli doc spec 'missing_smoke'"):
        smoke_cli_doc_spec("missing_smoke")



def test_smoke_cli_doc_audit_selector_and_parser_follow_wrapper_registry() -> None:
    selector = build_smoke_cli_doc_audit_selector()

    assert SMOKE_CLI_DOC_AUDIT_TARGET_NAMES == tuple(spec.script_name for spec in SMOKE_CLI_DOC_SPECS)
    assert DEFAULT_SMOKE_CLI_DOC_AUDIT_TARGET_NAMES == SMOKE_CLI_DOC_AUDIT_TARGET_NAMES
    assert selector.choices == (*SMOKE_CLI_DOC_AUDIT_TARGET_NAMES, "all")
    assert selector.resolve_target_names() == list(SMOKE_CLI_DOC_AUDIT_TARGET_NAMES)
    assert SMOKE_CLI_DOC_AUDIT_EXAMPLES == (
        SmokeCliExample("smoke_cli_docs_smoke.py"),
        SmokeCliExample("smoke_cli_docs_smoke.py standalone_smoke", target_name="standalone_smoke"),
        SmokeCliExample("smoke_cli_docs_smoke.py smoke_matrix", target_name="smoke_matrix"),
    )

    help_text = build_smoke_cli_doc_audit_parser().format_help()
    assert matches_public_cli_help(
        help_text,
        required_snippets=[
            "Which smoke-wrapper docs surface to audit. Aliases: all -> standalone_smoke, session_triage_smoke, session_recovery_smoke, smoke_matrix.",
            "smoke_cli_docs_smoke.py # default all alias -> standalone_smoke, session_triage_smoke, session_recovery_smoke, smoke_matrix",
            "smoke_cli_docs_smoke.py standalone_smoke # single smoke wrapper",
            "smoke_cli_docs_smoke.py smoke_matrix # single smoke wrapper",
        ],
    )


def test_build_smoke_cli_doc_spec_registry_rejects_duplicate_script_names() -> None:
    spec = SmokeCliDocSpec(
        script_name="standalone_smoke",
        readme_section_heading="Standalone local smoke bundle",
        help_required_snippets=("standalone help",),
        readme_required_snippets=("standalone readme",),
    )

    with pytest.raises(ValueError, match="duplicate smoke cli doc spec 'standalone_smoke'"):
        build_smoke_cli_doc_spec_registry((spec, spec))



def test_smoke_cli_doc_specs_extract_markdown_sections_and_reuse_shared_snippets() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    triage_spec = smoke_cli_doc_spec("session_triage_smoke")
    standalone_lines = standalone_spec.readme_required_snippets
    triage_lines = ("Intro line.", triage_spec.readme_required_snippets[2])
    markdown = (
        "## Smoke docs\n\n"
        f"### {standalone_spec.readme_section_heading}\n"
        + "\n".join(standalone_lines)
        + "\n\n"
        f"### {triage_spec.readme_section_heading}\n"
        + "\n".join(triage_lines)
    )
    help_text = "\n".join(standalone_spec.help_required_snippets)

    assert markdown_section_text(markdown, heading=standalone_spec.readme_section_heading) == "\n".join(
        standalone_lines
    )
    assert matches_markdown_section(
        markdown,
        heading=standalone_spec.readme_section_heading,
        required_snippets=[standalone_spec.readme_required_snippets[3]],
    )
    assert matches_markdown_section(
        markdown,
        heading=triage_spec.readme_section_heading,
        required_snippets=[triage_spec.readme_required_snippets[2]],
    )
    assert matches_smoke_cli_help_for_script(help_text, script_name="standalone_smoke")
    assert matches_smoke_cli_readme_for_script(markdown, script_name="standalone_smoke")
    assert matches_smoke_cli_doc_parity(
        script_name="standalone_smoke",
        help_text=help_text,
        markdown=markdown,
    )
    assert not matches_smoke_cli_doc_parity(
        script_name="session_triage_smoke",
        help_text=help_text,
        markdown=markdown,
    )


def test_smoke_cli_doc_parity_helpers_report_missing_help_and_readme_snippets() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    help_text = standalone_spec.help_required_snippets[0]
    markdown = dedent(
        f"""
        ## Smoke docs

        ### {standalone_spec.readme_section_heading}
        {standalone_spec.readme_required_snippets[1]}
        """
    ).strip()

    assert missing_public_cli_help_snippets(
        help_text,
        required_snippets=standalone_spec.help_required_snippets,
    ) == standalone_spec.help_required_snippets[1:]
    assert missing_markdown_section_snippets(
        markdown,
        heading=standalone_spec.readme_section_heading,
        required_snippets=standalone_spec.readme_required_snippets,
    ) == standalone_spec.readme_required_snippets[0:1] + standalone_spec.readme_required_snippets[2:]

    parity = collect_smoke_cli_doc_parity(
        script_name="standalone_smoke",
        help_text=help_text,
        markdown=markdown,
    )

    assert parity.script_name == "standalone_smoke"
    assert parity.readme_section_heading == standalone_spec.readme_section_heading
    assert parity.missing_help_snippets == standalone_spec.help_required_snippets[1:]
    assert parity.missing_readme_snippets == standalone_spec.readme_required_snippets[0:1] + standalone_spec.readme_required_snippets[2:]
    assert parity.help_diagnostic == (
        "--help missing: " + " | ".join(standalone_spec.help_required_snippets[1:])
    )
    assert parity.readme_diagnostic == (
        f"README {standalone_spec.readme_section_heading!r} missing: "
        + " | ".join(standalone_spec.readme_required_snippets[0:1] + standalone_spec.readme_required_snippets[2:])
    )
    assert parity.diagnostic_summary == (
        f"{parity.help_diagnostic}; {parity.readme_diagnostic}"
    )
    assert smoke_cli_doc_parity_diagnostic(
        script_name="standalone_smoke",
        help_text=help_text,
        markdown=markdown,
    ) == parity.diagnostic_summary
    assert not parity.help_matches
    assert not parity.readme_matches
    assert not parity.matches


def test_smoke_cli_doc_parity_diagnostic_reports_ok_surfaces_when_docs_match() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    help_text = "\n".join(standalone_spec.help_required_snippets)
    markdown = (
        "## Smoke docs\n\n"
        f"### {standalone_spec.readme_section_heading}\n"
        + "\n".join(standalone_spec.readme_required_snippets)
    )

    parity = collect_smoke_cli_doc_parity(
        script_name="standalone_smoke",
        help_text=help_text,
        markdown=markdown,
    )

    assert parity.help_diagnostic == "help ok"
    assert parity.readme_diagnostic == f"README {standalone_spec.readme_section_heading!r} ok"
    assert parity.diagnostic_lines == ("help ok", f"README {standalone_spec.readme_section_heading!r} ok")
    assert parity.diagnostic_summary == (
        f"help ok; README {standalone_spec.readme_section_heading!r} ok"
    )


def test_smoke_wrapper_cli_specs_render_exact_canonical_readme_sections() -> None:
    assert [doc_spec.script_name for doc_spec in SMOKE_CLI_DOC_SPECS] == [
        spec.script_name for spec in SMOKE_WRAPPER_CLI_SPECS
    ]

    for doc_spec in SMOKE_CLI_DOC_SPECS:
        spec = smoke_wrapper_cli_spec(doc_spec.script_name)
        assert markdown_section_text(README_TEXT, heading=doc_spec.readme_section_heading) == spec.render_readme_section_body()



def test_approval_restore_smoke_helpers_share_focus_age_and_preview_checks() -> None:
    text = dedent(
        """
        Filter: approval-restore | Sort: recent
        Approval restore backlog: 3 sessions | lanes: restore queue 2 (oldest 3d @ 2026-05-17 00:00 UTC), restored 1 (oldest 6h @ 2026-05-17 03:00 UTC)
        Restore lane focus: restore queue, restored
        > 1. session-restored-pending | 1 turn(s)
          2. session-restored-edit-pending | 1 turn(s)
          3. session-denied | 1 turn(s)
        | approval restore: pending 1 | approval restore: denied 1
        | approval restore tools: test 1 | approval restore tools: edit 1
        | approval restore age: restore queue 3d | approval restore age: restored 6h
        - restored current approval: pending run_shell_command via fake_runtime | queued 1
        - latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0
        """
    ).strip()

    assert matches_approval_restore_focus_output(
        text,
        required_session_ids=[
            "session-restored-pending",
            "session-restored-edit-pending",
            "session-denied",
        ],
        excluded_session_ids=["session-restore"],
    )
    assert matches_approval_restore_badges_output(text)
    assert matches_approval_restore_tool_badges_output(text)
    assert matches_approval_restore_age_output(text)
    assert matches_approval_restore_preview_split_output(text)


def test_approval_restore_overlap_and_rollup_helpers_share_timestamped_backlog_checks() -> None:
    overlap_text = dedent(
        """
        Approval restore backlog: 1 session | lanes: restore queue 1 (oldest 3d @ 2026-05-17 00:00 UTC), restored 1 (oldest 6h @ 2026-05-17 03:00 UTC) | overlap: mixed 1 session
        Restore lane focus: restore queue, restored
        | approval restore ages: restore queue 3d; restored 6h
        restored current: pending run_shell_command via fake_runtime; queued 1
        restored outcome: denied replace_text via fake_runtime; restored queue; remaining 0
        - restored current approval: pending run_shell_command via fake_runtime | queued 1
        - latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0
        """
    ).strip()
    first_page_text = dedent(
        """
        Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d @ 2026-05-01 00:00 UTC), restored 2 (oldest 8h @ 2026-05-17 01:00 UTC) | overlap: mixed 1 session
        This page restore lanes: restore queue 8 (oldest 18d @ 2026-05-01 00:00 UTC) | more off-page: restore queue 1 (oldest 3d @ 2026-05-14 00:00 UTC), restored 2 (oldest 8h @ 2026-05-17 01:00 UTC) | overlap here/off-page: none / mixed 1 session
        """
    ).strip()
    second_page_text = dedent(
        """
        This page restore lanes: restore queue 1 (oldest 3d @ 2026-05-14 00:00 UTC), restored 2 (oldest 8h @ 2026-05-17 01:00 UTC) | more off-page: restore queue 8 (oldest 18d @ 2026-05-01 00:00 UTC) | overlap here/off-page: mixed 1 session / none
        """
    ).strip()

    assert matches_approval_restore_overlap_output(overlap_text)
    assert matches_approval_restore_overlap_preview_split_output(overlap_text)
    assert matches_approval_restore_page_rollup_output(first_page_text, second_page_text)


def test_broad_stale_helpers_share_filter_backlog_cutoff_and_focus_checks() -> None:
    text = dedent(
        """
        Filter: approval-stale | Sort: attention
        Stale approval backlog: 1 session | lanes: pending 1 (oldest 45d @ 2026-04-02 00:00 UTC)
        Stale cutoff: approvals >= 7d old
        Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old
        > 1. session-aged | 1 turn(s) | approval stale age: pending 45d
        - approval stale age: pending 45d
        """
    ).strip()

    assert matches_broad_approval_stale_output(
        text,
        required_session_ids=["session-aged"],
        excluded_session_ids=["session-newer"],
        sort_mode="attention",
    )
    assert matches_stale_backlog_output(text)
    assert matches_stale_cutoff_output(text)
    assert matches_stale_lane_focus_output(text)
    assert matches_compact_stale_preview_output(text)
    assert matches_broad_stale_row_focus_suppression(text)


def test_stale_rollup_subfilter_and_custom_cutoff_helpers_share_smoke_copy() -> None:
    stale_first_page_text = dedent(
        """
        This page stale lanes: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC) | more off-page: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC), restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC)
        """
    ).strip()
    stale_second_page_text = dedent(
        """
        This page stale lanes: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC), restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC) | more off-page: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC)
        """
    ).strip()
    pending_text = dedent(
        """
        Filter: approval-stale-pending | Sort: recent
        Stale pending backlog: 8 sessions | lanes: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC)
        Stale lane focus: pending | cutoff: approvals >= 7d old
        - stale lane focus: pending | cutoff: approvals >= 7d old
        > 1. session-stale-pending-0 | 1 turn(s) | approvals: pending 1 | approval focus: pending | approval stale age: 45d | stale focus: pending | intervention: pending 1
        - stale focus: pending
        - approvals: pending 1
        - approval focus: pending
        - approval stale age: 45d
        """
    ).strip()
    denied_text = dedent(
        """
        Filter: approval-stale-denied | Sort: recent
        Stale denied backlog: 1 session | lanes: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC)
        Stale lane focus: denied | cutoff: approvals >= 7d old
        - stale lane focus: denied | cutoff: approvals >= 7d old
        > 1. session-stale-denied-page-2 | 1 turn(s) | approvals: denied 1 | approval focus: denied/fresh | denied age: 14d | approval stale age: 14d | stale focus: denied | intervention: denied 1
        - stale focus: denied
        - approvals: denied 1
        - approval focus: denied/fresh
        - approval stale age: 14d
        """
    ).strip()
    restored_text = dedent(
        """
        Filter: approval-stale-restored | Sort: recent
        Stale restored backlog: 1 session | lanes: restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC)
        Stale lane focus: restore queue, restored | cutoff: approvals >= 7d old
        - stale lane focus: restore queue, restored | cutoff: approvals >= 7d old
        > 1. session-stale-restored-page-2 | 1 turn(s) | approvals: pending 1, approved 1 | approval focus: pending/restored | approval restore: pending 1, approved 1 | approval restore tools: test 1, edit 1 | approval restore age: 11d | approval stale ages: restore queue 11d; restored 10d | stale focus: restore queue, restored | intervention: pending 1, approved 1, restored 1
        restored current: pending write_file via fake_runtime; queued 1
        restored outcome: approved run_shell_command via fake_runtime; resumed; remaining 0
        restored outcome age: 10d
        - stale focus: restore queue, restored
        - approvals: pending 1, approved 1
        - approval focus: pending/restored
        - approval restore: pending 1, approved 1
        - approval restore age: 11d
        - approval stale ages: restore queue 11d; restored 10d
        - restored current approval: pending write_file via fake_runtime | queued 1
        - latest restored outcome: approved run_shell_command via fake_runtime | resumed | remaining 0
        - latest restored outcome age: 10d
        """
    ).strip()
    custom_cutoff_text = dedent(
        """
        Stale approval backlog: 1 session | lanes: pending 1 (oldest 2d @ 2026-05-15 00:00 UTC)
        session-custom-threshold | 1 turn(s)
        Stale cutoff: approvals >= 1d old
        Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 1d old
        """
    ).strip()

    assert matches_stale_page_rollup_output(stale_first_page_text, stale_second_page_text)
    assert matches_stale_pending_subfilter_output(
        pending_text,
        required_session_ids=["session-stale-pending-0"],
        excluded_session_ids=["session-stale-denied-page-2"],
    )
    assert matches_stale_denied_subfilter_output(
        denied_text,
        required_session_ids=["session-stale-denied-page-2"],
        excluded_session_ids=["session-stale-restored-page-2"],
    )
    assert matches_stale_restored_subfilter_output(
        restored_text,
        required_session_ids=["session-stale-restored-page-2"],
        excluded_session_ids=["session-stale-denied-page-2"],
    )
    assert matches_custom_stale_cutoff_output(custom_cutoff_text)


def test_pending_and_denied_smoke_helpers_cover_filter_queue_and_rollup_checks() -> None:
    pending_text = dedent(
        """
        Filter: pending | Sort: attention
        > 1. session-newer | 1 turn(s) | approvals: pending 1 | pending age: 45d | stale: warning 10d
          2. session-aged | 1 turn(s)
        - session age: idle 10d since last artifact activity
        pending: 3 approvals (first test; rest edit 1, tool 1)
        - pending queue: first test; rest edit 1, tool 1
        """
    ).strip()
    pending_first_page_text = dedent(
        """
        Pending approval backlog: 10 sessions | approvals: 11 | families: test 9, edit 2 | multi-queue: 1 session | restored queues: 1 session
        Pending focus: fresh, restored | oldest: 18d
        This page pending queues: approvals: 8 | families: test 8 | more off-page: approvals: 3 | families: test 1, edit 2 | multi-queue: 1 session | restored queues: 1 session
        """
    ).strip()
    pending_second_page_text = dedent(
        """
        This page pending queues: approvals: 3 | families: test 1, edit 2 | multi-queue: 1 session | restored queues: 1 session | more off-page: approvals: 8 | families: test 8
        """
    ).strip()
    denied_text = dedent(
        """
        Filter: denied | Sort: recent
        > 1. session-denied | 1 turn(s) | approval focus: denied/restored | denied: edit 1 | approval restore: denied 1
        last denied approval: denied replace_text via fake_runtime | restored queue | remaining 0
        denied age: 6h
        - last denied age: 6h
        """
    ).strip()
    denied_first_page_text = dedent(
        """
        Denied approval backlog: 10 sessions | approvals: 10 | families: test 8, edit 2 | restored denied: 1 session
        Denied focus: fresh, restored | oldest: 3d
        This page denied approvals: approvals: 8 | families: test 8 | more off-page: approvals: 2 | families: edit 2 | restored denied: 1 session
        """
    ).strip()
    denied_second_page_text = dedent(
        """
        This page denied approvals: approvals: 2 | families: edit 2 | restored denied: 1 session | more off-page: approvals: 8 | families: test 8
        """
    ).strip()

    assert matches_pending_filter_output(
        pending_text,
        required_session_ids=["session-newer", "session-aged"],
        sort_mode="attention",
    )
    assert matches_pending_age_output(pending_text, session_idle_age="10d")
    assert matches_queue_breakdown_output(
        pending_text,
        summary_line="pending: 3 approvals (first test; rest edit 1, tool 1)",
        preview_line="- pending queue: first test; rest edit 1, tool 1",
    )
    assert matches_pending_page_rollup_output(pending_first_page_text, pending_second_page_text)

    assert matches_denied_filter_output(
        denied_text,
        required_session_ids=["session-denied"],
    )
    assert matches_denied_preview_output(
        denied_text,
        required_badges=["denied: edit 1"],
        require_approval_focus=True,
        require_restore_badge=True,
    )
    assert matches_denied_page_rollup_output(denied_first_page_text, denied_second_page_text)


def test_default_tool_and_intervention_smoke_helpers_cover_remaining_picker_switcher_surfaces() -> None:
    picker_default_text = dedent(
        """
        Filter: all | Sort: recent | Page: 1/2 | Showing: 1-8 of 13
        Selected preview:
        - artifact dir: /tmp/session-tool
        > 1. session-tool | 1 turn(s) | approvals: pending 1, approved 1 | failures: test 1 | failures: tool 1 | shell: inspect 1
        - last shell: inspect/e0 git status --short -> M README.md
        - recent tools (1):
          - inspect/e0 git status --short -> M README.md
        """
    ).strip()
    picker_tool_text = dedent(
        """
        Filter: tool | Sort: recent
        Tool backlog: 2 sessions | families: inspect 1, edit 1
        Tool failure mix: failures: test 1, tool 1 | failing: 2 sessions
        > 1. session-tool | 1 turn(s)
        """
    ).strip()
    intervention_text = dedent(
        """
        Filter: intervention | Sort: recent
        Intervention mix: pending 1, denied 1
        > 1. session-pending | 1 turn(s) | intervention: pending 1
          2. session-denied | 1 turn(s) | intervention: denied 1
        - last intervention: pending run_shell_command via fake_runtime
        - recent interventions (2): pending run_shell_command, denied replace_text
        """
    ).strip()
    switcher_default_text = dedent(
        """
        > 1. session-tool | 1 turn(s)
          2. session-older | 1 turn(s) (current)
        pending: run_shell_command
        approvals: pending 1, approved 1
        restore: filter=tool, replay 1/1, draft 15c
        last tool: inspect/e0 git status --short -> M README.md
        shell: inspect 1
        last event: tool_finished: run_shell_command
        """
    ).strip()
    switcher_preview_text = dedent(
        """
        Selected preview:
        - artifact dir: /tmp/session-tool
        - last approval: pending run_shell_command via fake_runtime | queued 1
        - last shell: inspect/e0 git status --short -> M README.md
        - recent tools (2): inspect/e0 git status --short -> M README.md
        """
    ).strip()
    switcher_tool_text = dedent(
        """
        Filter: tool | Sort: attention
        Tool backlog: 2 sessions | families: inspect 1, edit 1
        > 1. session-tool | 1 turn(s)
          2. session-newer | 1 turn(s)
        """
    ).strip()

    assert matches_picker_default_output(picker_default_text)
    assert matches_tool_filter_output(
        picker_tool_text,
        failure_mix_line="Tool failure mix: failures: test 1, tool 1 | failing: 2 sessions",
    )
    assert matches_intervention_filter_output(
        intervention_text,
        required_session_ids=["session-pending", "session-denied"],
        excluded_session_ids=["session-plain"],
        required=["intervention: pending 1"],
        require_preview=True,
    )
    assert matches_switcher_default_output(switcher_default_text)
    assert matches_switcher_selected_preview_output(switcher_preview_text)
    assert matches_tool_filter_output(
        switcher_tool_text,
        sort_mode="attention",
        required_session_ids=["session-tool", "session-newer"],
        excluded_session_ids=["session-restore"],
    )


def test_workspace_and_shell_smoke_helpers_cover_focus_and_overlap_copy() -> None:
    workspace_inspect_text = dedent(
        """
        Filter: workspace-inspect | Sort: recent
        Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session
        Workspace focus: inspect
        > 1. session-tool | 1 turn(s) | workspace lanes: inspect, edit
          2. session-workspace-inspect | 1 turn(s)
        """
    ).strip()
    workspace_edit_text = dedent(
        """
        Filter: workspace-edit | Sort: recent
        Workspace backlog: 2 sessions | lanes: inspect 1, edit 2 | overlap: mixed 1 session
        Workspace focus: edit
        > 1. session-workspace-edit | 1 turn(s) | workspace lanes: edit
          2. session-tool | 1 turn(s)
        """
    ).strip()
    shell_text = dedent(
        """
        Filter: shell | Sort: attention
        Shell backlog: 3 sessions | lanes: inspect 2, test 2 | overlap: mixed 1 session
        Shell focus: inspect, test
        > 1. session-shell-overlap | 1 turn(s) | shell lanes: inspect, test
          2. session-shell-inspect | 1 turn(s)
          3. session-shell-test | 1 turn(s)
        """
    ).strip()
    shell_inspect_text = dedent(
        """
        Filter: shell-inspect | Sort: attention
        Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session
        Shell focus: inspect
        > 1. session-shell-overlap | 1 turn(s) | shell lanes: inspect, test
          2. session-shell-inspect | 1 turn(s)
        """
    ).strip()
    shell_test_text = dedent(
        """
        Filter: shell-test | Sort: attention
        Shell backlog: 2 sessions | lanes: inspect 1, test 2 | overlap: mixed 1 session
        Shell focus: test
        > 1. session-shell-overlap | 1 turn(s) | shell lanes: inspect, test
          2. session-shell-test | 1 turn(s)
        """
    ).strip()

    assert matches_workspace_filter_output(
        workspace_inspect_text,
        filter_mode="workspace-inspect",
        backlog_line="Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session",
        focus="inspect",
        required_session_ids=["session-tool", "session-workspace-inspect"],
        required=["workspace lanes: inspect, edit"],
    )
    assert matches_workspace_filter_output(
        workspace_edit_text,
        filter_mode="workspace-edit",
        backlog_line="Workspace backlog: 2 sessions | lanes: inspect 1, edit 2 | overlap: mixed 1 session",
        focus="edit",
        required_session_ids=["session-workspace-edit", "session-tool"],
        required=["workspace lanes: edit"],
    )
    assert matches_shell_filter_output(
        shell_text,
        filter_mode="shell",
        sort_mode="attention",
        backlog_line="Shell backlog: 3 sessions | lanes: inspect 2, test 2 | overlap: mixed 1 session",
        focus="inspect, test",
        required_session_ids=["session-shell-overlap", "session-shell-inspect", "session-shell-test"],
        required=["shell lanes: inspect, test"],
    )
    assert matches_shell_filter_output(
        shell_inspect_text,
        filter_mode="shell-inspect",
        sort_mode="attention",
        backlog_line="Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session",
        focus="inspect",
        required_session_ids=["session-shell-overlap", "session-shell-inspect"],
        required=["shell lanes: inspect, test"],
    )
    assert matches_shell_filter_output(
        shell_test_text,
        filter_mode="shell-test",
        sort_mode="attention",
        backlog_line="Shell backlog: 2 sessions | lanes: inspect 1, test 2 | overlap: mixed 1 session",
        focus="test",
        required_session_ids=["session-shell-overlap", "session-shell-test"],
        required=["shell lanes: inspect, test"],
    )
