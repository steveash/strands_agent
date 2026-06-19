import json
from textwrap import dedent
from pathlib import Path

import pytest

import strands_agent_tui.testing as testing_api
import strands_agent_tui.testing.smoke_cli_assertions as smoke_cli_assertions
import strands_agent_tui.testing.smoke_cli_doc_artifacts as smoke_cli_doc_artifacts
from strands_agent_tui.testing import (
    DEFAULT_SMOKE_CLI_DOC_AUDIT_TARGET_NAMES,
    SMOKE_CLI_DOC_AUDIT_EXAMPLES,
    SMOKE_CLI_DOC_AUDIT_TARGET_NAMES,
    SMOKE_CLI_DOC_FIX_EXAMPLES,
    SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME,
    SMOKE_CLI_DOC_PARSER_HELP_EXPECTED_SNIPPETS_BY_SCRIPT_NAME,
    SMOKE_CLI_DOC_PARSER_SPECS,
    SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME,
    SMOKE_CLI_DOC_SPECS,
    SMOKE_CLI_DOC_SPECS_BY_SCRIPT_NAME,
    SMOKE_WRAPPER_CLI_SPECS,
    SmokeCliDocSpec,
    SmokeCliDocParserSpec,
    SmokeCliExample,
    build_smoke_cli_doc_audit_parser,
    build_smoke_cli_doc_audit_selector,
    build_smoke_cli_doc_fix_examples,
    build_smoke_cli_doc_fix_parser,
    build_smoke_cli_doc_invalid_choice_expected_choices_registry,
    build_smoke_cli_doc_parser_spec_registry,
    build_smoke_cli_doc_render_examples,
    build_smoke_cli_doc_render_parser,
    build_smoke_cli_doc_spec_registry,
    describe_smoke_cli_example,
    failed_smoke_check_lines,
    is_failed_smoke_check_line,
    markdown_section_text,
    collect_smoke_cli_doc_parity,
    collect_smoke_cli_readme_diffs,
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
    intervention_mix_smoke_results,
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
    format_smoke_cli_alias_help,
    format_smoke_cli_alias_lines,
    matches_queue_breakdown_output,
    repair_smoke_cli_readme_sections,
    replace_markdown_section,
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
    render_smoke_cli_readme_section,
    render_smoke_cli_readme_sections,
    smoke_cli_doc_parity_diagnostic,
    smoke_cli_doc_parser_spec,
    smoke_cli_doc_spec,
    smoke_cli_readme_diff_lines,
    smoke_wrapper_cli_spec,
    smoke_text_matches,
)
from strands_agent_tui.testing.smoke_contract_registries import (
    STANDALONE_MALFORMED_CONTRACT_ALIAS_README_DESCRIPTION,
    STANDALONE_MALFORMED_CONTRACT_ALIAS_TARGET_NAME,
    STANDALONE_MALFORMED_CONTRACT_FAILURE_CHECK_NAMES,
    STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES,
    STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS,
    STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS_BY_NAME,
    STANDALONE_MALFORMED_DETAIL_TARGET_NAME,
    STANDALONE_MALFORMED_RESULT_TARGET_NAME,
    StandaloneMalformedContractTargetSpec,
    standalone_malformed_contract_failure_check_name,
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


def test_package_testing_api_exports_standalone_malformed_contract_registry() -> None:
    exported_names = {
        "STANDALONE_MALFORMED_CONTRACT_ALIAS_README_DESCRIPTION",
        "STANDALONE_MALFORMED_CONTRACT_ALIAS_TARGET_NAME",
        "STANDALONE_MALFORMED_CONTRACT_FAILURE_CHECK_NAMES",
        "STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES",
        "STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS",
        "STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS_BY_NAME",
        "STANDALONE_MALFORMED_DETAIL_TARGET_NAME",
        "STANDALONE_MALFORMED_RESULT_TARGET_NAME",
        "StandaloneMalformedContractTargetSpec",
        "standalone_malformed_contract_failure_check_name",
    }

    assert exported_names <= set(testing_api.__all__)
    assert testing_api.STANDALONE_MALFORMED_CONTRACT_ALIAS_README_DESCRIPTION == (
        STANDALONE_MALFORMED_CONTRACT_ALIAS_README_DESCRIPTION
    )
    assert (
        testing_api.STANDALONE_MALFORMED_CONTRACT_ALIAS_TARGET_NAME
        == STANDALONE_MALFORMED_CONTRACT_ALIAS_TARGET_NAME
    )
    assert (
        testing_api.STANDALONE_MALFORMED_CONTRACT_FAILURE_CHECK_NAMES
        == STANDALONE_MALFORMED_CONTRACT_FAILURE_CHECK_NAMES
    )
    assert (
        testing_api.STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES
        == STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES
    )
    assert (
        testing_api.STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS
        == STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS
    )
    assert (
        testing_api.STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS_BY_NAME
        == STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS_BY_NAME
    )
    assert testing_api.STANDALONE_MALFORMED_DETAIL_TARGET_NAME == STANDALONE_MALFORMED_DETAIL_TARGET_NAME
    assert testing_api.STANDALONE_MALFORMED_RESULT_TARGET_NAME == STANDALONE_MALFORMED_RESULT_TARGET_NAME
    assert testing_api.StandaloneMalformedContractTargetSpec is StandaloneMalformedContractTargetSpec
    assert (
        testing_api.standalone_malformed_contract_failure_check_name
        is standalone_malformed_contract_failure_check_name
    )

    assert tuple(testing_api.STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS_BY_NAME) == (
        STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES
    )
    assert all(
        isinstance(spec, testing_api.StandaloneMalformedContractTargetSpec)
        for spec in testing_api.STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS
    )
    assert {
        target_name: testing_api.standalone_malformed_contract_failure_check_name(target_name)
        for target_name in testing_api.STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES
    } == testing_api.STANDALONE_MALFORMED_CONTRACT_FAILURE_CHECK_NAMES


def test_package_testing_api_exports_smoke_cli_doc_parser_registry(tmp_path: Path) -> None:
    exported_names = {
        "SMOKE_CLI_DOC_ARTIFACTS_DEFAULT_TARGET_NAME",
        "SMOKE_CLI_DOC_ARTIFACTS_EXAMPLES",
        "SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME",
        "SMOKE_CLI_DOC_ARTIFACTS_TARGET_SELECTOR",
        "SMOKE_CLI_DOC_AUDIT_EXAMPLES",
        "SMOKE_CLI_DOC_AUDIT_SCRIPT_NAME",
        "SMOKE_CLI_DOC_FIX_EXAMPLES",
        "SMOKE_CLI_DOC_FIX_SCRIPT_NAME",
        "SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME",
        "SMOKE_CLI_DOC_PARSER_HELP_EXPECTED_SNIPPETS_BY_SCRIPT_NAME",
        "SMOKE_CLI_DOC_PARSER_SPECS",
        "SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME",
        "SMOKE_CLI_DOC_RENDER_EXAMPLES",
        "SMOKE_CLI_DOC_RENDER_SCRIPT_NAME",
        "SmokeCliDocParserSpec",
        "build_smoke_cli_doc_artifacts_examples",
        "build_smoke_cli_doc_artifacts_parser",
        "build_smoke_cli_doc_artifacts_selector",
        "build_smoke_cli_doc_audit_examples",
        "build_smoke_cli_doc_audit_parser",
        "build_smoke_cli_doc_audit_selector",
        "build_smoke_cli_doc_fix_examples",
        "build_smoke_cli_doc_fix_parser",
        "build_smoke_cli_doc_invalid_choice_expected_choices_registry",
        "build_smoke_cli_doc_parser_spec_registry",
        "build_smoke_cli_doc_render_examples",
        "build_smoke_cli_doc_render_parser",
    }

    assert exported_names <= set(testing_api.__all__)
    for name in exported_names:
        assert getattr(testing_api, name) is getattr(smoke_cli_assertions, name)

    assert tuple(testing_api.SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME) == tuple(
        spec.script_name for spec in testing_api.SMOKE_CLI_DOC_PARSER_SPECS
    )
    assert all(
        isinstance(spec, testing_api.SmokeCliDocParserSpec)
        for spec in testing_api.SMOKE_CLI_DOC_PARSER_SPECS
    )
    assert testing_api.SMOKE_CLI_DOC_PARSER_HELP_EXPECTED_SNIPPETS_BY_SCRIPT_NAME == {
        spec.script_name: spec.help_required_snippets()
        for spec in testing_api.SMOKE_CLI_DOC_PARSER_SPECS
    }
    assert testing_api.SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME == {
        spec.script_name: spec.invalid_choice_expected_choices()
        for spec in testing_api.SMOKE_CLI_DOC_PARSER_SPECS
    }
    assert (
        testing_api.SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME[
            testing_api.SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME
        ]
        .build_parser(readme_path=tmp_path / "README.md")
        .parse_args([])
        .readme_path
        == tmp_path / "README.md"
    )


def test_package_testing_api_exports_smoke_cli_doc_artifact_payload_helpers(tmp_path: Path) -> None:
    exported_names = {
        "build_smoke_cli_doc_drift_report_payload",
        "build_smoke_cli_doc_render_manifest_payload",
        "build_smoke_cli_doc_repair_report_payload",
        "build_smoke_cli_doc_section_payloads",
        "diff_bundle_sha256",
        "diff_stats",
        "format_diff_output",
        "load_review_matrix_summary",
        "normalize_text_output",
        "output_path_from_prefixed_lines",
        "rendered_bundle_sha256",
        "rendered_summary",
        "resolve_checkout_path",
        "resolve_review_artifact_paths",
        "sha256_text",
        "write_text_output",
    }

    assert exported_names <= set(testing_api.__all__)
    for name in exported_names:
        assert getattr(testing_api, name) is getattr(smoke_cli_doc_artifacts, name)

    rendered_sections = (("standalone_smoke", "## Standalone\n\nSmoke docs\n"),)
    diff_sections = (
        (
            "standalone_smoke",
            (
                "--- README.md",
                "+++ rendered/standalone_smoke.md",
                "@@ -1 +1 @@",
                "-old",
                "+new",
            ),
        ),
    )
    output_path = tmp_path / "rendered" / "standalone_smoke.md"
    manifest_path = tmp_path / "manifest.json"
    diff_path = tmp_path / "docs.patch"

    section_payloads = testing_api.build_smoke_cli_doc_section_payloads(
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        written_paths=(output_path,),
    )
    assert section_payloads == smoke_cli_doc_artifacts.build_smoke_cli_doc_section_payloads(
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        written_paths=(output_path,),
    )
    assert section_payloads[0]["output_path"] == str(output_path)
    assert section_payloads[0]["diff_stats"] == {
        "added_line_count": 1,
        "hunk_count": 1,
        "line_count": 5,
        "removed_line_count": 1,
    }

    manifest_payload = testing_api.build_smoke_cli_doc_render_manifest_payload(
        body_only=False,
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        rendered_sections=rendered_sections,
        written_paths=(output_path,),
        readme_path=tmp_path / "README.md",
        output_dir=tmp_path / "rendered",
        manifest_output=manifest_path,
        diff_output=diff_path,
        diff_sections=diff_sections,
    )
    assert manifest_payload == smoke_cli_doc_artifacts.build_smoke_cli_doc_render_manifest_payload(
        body_only=False,
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        rendered_sections=rendered_sections,
        written_paths=(output_path,),
        readme_path=tmp_path / "README.md",
        output_dir=tmp_path / "rendered",
        manifest_output=manifest_path,
        diff_output=diff_path,
        diff_sections=diff_sections,
    )
    assert manifest_payload["sections"] == section_payloads
    assert manifest_payload["diff_bundle_sha256"] == testing_api.diff_bundle_sha256(diff_sections)
    assert manifest_payload["rendered_bundle_sha256"] == testing_api.rendered_bundle_sha256(
        rendered_sections
    )
    assert manifest_payload["up_to_date"] is False

    report_payload = testing_api.build_smoke_cli_doc_drift_report_payload(
        readme_path=tmp_path / "README.md",
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        include_diff_lines=False,
        check=True,
    )
    repair_payload = testing_api.build_smoke_cli_doc_repair_report_payload(
        readme_path=tmp_path / "README.md",
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        repaired_script_names=("standalone_smoke",),
        original_markdown="old",
        repaired_markdown="new",
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        stdout=False,
    )
    assert report_payload["sections"][0]["diff_sha256"] == testing_api.sha256_text(
        "\n".join(diff_sections[0][1])
    )
    assert "diff_lines" not in report_payload["sections"][0]
    assert repair_payload["changed"] is True
    assert report_payload["rerun_hint"] == testing_api.smoke_cli_docs_parity_rerun_hint()
    assert repair_payload["rerun_hint"] == testing_api.smoke_cli_docs_parity_rerun_hint()
    assert repair_payload["wrote_readme"] is True


def test_package_testing_api_smoke_cli_doc_diff_output_and_hash_helpers_use_filesystem(
    tmp_path: Path,
) -> None:
    diff_sections = (
        (
            "standalone_smoke",
            (
                "--- README.md",
                "+++ rendered/standalone_smoke.md",
                "@@ -1,2 +1,2 @@",
                " unchanged",
                "-old standalone",
                "+new standalone",
            ),
        ),
        (
            "smoke_matrix",
            (
                "--- README.md",
                "+++ rendered/smoke_matrix.md",
                "@@ -4 +4 @@",
                "-old matrix",
                "+new matrix",
            ),
        ),
    )
    rendered_sections = (
        ("standalone_smoke", "## Standalone\n\nSmoke docs\n"),
        ("smoke_matrix", "## Smoke Matrix\n\nMatrix docs\n"),
    )
    diff_output_path = tmp_path / "review" / "smoke-cli-docs.patch"

    formatted_diff = testing_api.format_diff_output(diff_sections)
    assert formatted_diff == smoke_cli_doc_artifacts.format_diff_output(diff_sections)
    assert formatted_diff.startswith("### standalone_smoke\n--- README.md\n+++ rendered/")
    assert "\n\n### smoke_matrix\n--- README.md\n+++ rendered/smoke_matrix.md\n" in formatted_diff
    assert not formatted_diff.endswith("\n")

    testing_api.write_text_output(diff_output_path, formatted_diff)
    persisted_diff = diff_output_path.read_text(encoding="utf-8")
    assert persisted_diff == formatted_diff + "\n"
    assert testing_api.diff_bundle_sha256(diff_sections) == testing_api.sha256_text(persisted_diff)
    assert testing_api.diff_bundle_sha256(()) is None

    expected_rendered_bundle = "\n\n".join(
        f"### {script_name}\n{text}" for script_name, text in rendered_sections
    )
    assert testing_api.rendered_bundle_sha256(rendered_sections) == testing_api.sha256_text(
        expected_rendered_bundle
    )
    assert testing_api.rendered_bundle_sha256(()) is None
    assert testing_api.normalize_text_output("") == ""


def test_package_testing_api_smoke_cli_doc_artifact_hashes_match_persisted_diff_output(
    tmp_path: Path,
) -> None:
    readme_path = tmp_path / "README.md"
    output_dir = tmp_path / "rendered"
    manifest_path = tmp_path / "review" / "smoke-cli-docs-preview.json"
    diff_output_path = tmp_path / "review" / "smoke-cli-docs.patch"
    rendered_output_path = output_dir / "standalone_smoke.md"
    rendered_sections = (
        ("standalone_smoke", "## Standalone\n\nSmoke docs\n"),
    )
    diff_sections = (
        (
            "standalone_smoke",
            (
                "--- expected",
                "+++ README",
                "@@ -1,2 +1,2 @@",
                "-old standalone",
                "+new standalone",
            ),
        ),
    )

    testing_api.write_text_output(
        rendered_output_path,
        rendered_sections[0][1],
    )
    testing_api.write_text_output(
        diff_output_path,
        testing_api.format_diff_output(diff_sections),
    )
    persisted_diff_sha256 = testing_api.sha256_text(
        diff_output_path.read_text(encoding="utf-8")
    )

    manifest_payload = testing_api.build_smoke_cli_doc_render_manifest_payload(
        body_only=False,
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        rendered_sections=rendered_sections,
        written_paths=(rendered_output_path,),
        readme_path=readme_path,
        output_dir=output_dir,
        manifest_output=manifest_path,
        diff_output=diff_output_path,
        diff_sections=diff_sections,
    )
    check_report_payload = testing_api.build_smoke_cli_doc_drift_report_payload(
        readme_path=readme_path,
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        include_diff_lines=False,
        check=True,
        render_output_dir=output_dir,
        render_manifest_path=manifest_path,
        render_diff_path=diff_output_path,
    )

    assert manifest_payload["diff_output_path"] == str(diff_output_path)
    assert manifest_payload["diff_bundle_sha256"] == persisted_diff_sha256
    assert check_report_payload["render_diff_path"] == str(diff_output_path)
    assert check_report_payload["diff_bundle_sha256"] == persisted_diff_sha256
    assert check_report_payload["sections"][0]["diff_sha256"] == testing_api.sha256_text(
        "\n".join(diff_sections[0][1])
    )
    assert "diff_lines" not in check_report_payload["sections"][0]


def test_package_testing_api_smoke_cli_doc_artifact_paths_and_summaries_use_filesystem(
    tmp_path: Path,
) -> None:
    checkout_root = tmp_path / "checkout"
    review_root = checkout_root / "artifacts" / "review"
    matrix_summary_path = review_root / "matrix-summary.json"
    rendered_output_path = review_root / "rendered" / "standalone_smoke.md"

    testing_api.write_text_output(rendered_output_path, "rendered docs")
    assert rendered_output_path.read_text(encoding="utf-8") == "rendered docs\n"
    assert testing_api.normalize_text_output("already normalized\n") == "already normalized\n"
    assert testing_api.rendered_summary("\n\nfirst summary line\nsecond line") == "first summary line"

    long_summary = "summary " + "x" * 140
    truncated_summary = testing_api.rendered_summary(long_summary)
    assert len(truncated_summary) == 120
    assert truncated_summary.startswith("summary ")
    assert truncated_summary != long_summary

    matrix_summary_payload = {
        "display_name": "docs-review",
        "target_name": "docs-review",
        "bundle_index_rerun_hint": ".venv/bin/python scripts/smoke_matrix.py review",
        "artifact_root": "artifacts/review",
        "bundle_index_path": "artifacts/review/index.json",
        "matrix_summary_path": "artifacts/review/matrix-summary.json",
        "absolute_report_path": str(tmp_path / "absolute-report.json"),
    }
    testing_api.write_text_output(matrix_summary_path, json.dumps(matrix_summary_payload))

    resolved_from_text = testing_api.output_path_from_prefixed_lines(
        f"noise\n[smoke-matrix] review matrix summary: {matrix_summary_path.relative_to(checkout_root)}\n",
        prefix="[smoke-matrix] review matrix summary: ",
        checkout_root=checkout_root,
    )
    assert resolved_from_text == matrix_summary_path
    assert (
        testing_api.output_path_from_prefixed_lines(
            "noise only",
            prefix="[smoke-matrix] review matrix summary: ",
            checkout_root=checkout_root,
        )
        is None
    )

    payload, paths = testing_api.load_review_matrix_summary(matrix_summary_path, checkout_root=checkout_root)
    assert payload == matrix_summary_payload
    assert paths == {
        "absolute_report_path": tmp_path / "absolute-report.json",
        "artifact_root": review_root,
        "bundle_index_path": review_root / "index.json",
        "matrix_summary_path": matrix_summary_path,
    }
    assert testing_api.resolve_review_artifact_paths(
        matrix_summary_payload,
        checkout_root=checkout_root,
    ) == paths
    assert testing_api.resolve_checkout_path(
        "artifacts/review/index.json",
        checkout_root=checkout_root,
    ) == review_root / "index.json"
    assert testing_api.load_review_matrix_summary(
        review_root / "missing-summary.json",
        checkout_root=checkout_root,
    ) == ({}, {})


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


def test_smoke_cli_doc_parser_specs_drive_parser_and_help_expectations(tmp_path: Path) -> None:
    assert all(isinstance(spec, SmokeCliDocParserSpec) for spec in SMOKE_CLI_DOC_PARSER_SPECS)
    assert tuple(SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME) == tuple(
        spec.script_name for spec in SMOKE_CLI_DOC_PARSER_SPECS
    )
    assert tuple(smoke_cli_doc_parser_spec(spec.script_name) for spec in SMOKE_CLI_DOC_PARSER_SPECS) == (
        SMOKE_CLI_DOC_PARSER_SPECS
    )
    assert SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME == build_smoke_cli_doc_parser_spec_registry(
        SMOKE_CLI_DOC_PARSER_SPECS
    )
    assert SMOKE_CLI_DOC_PARSER_HELP_EXPECTED_SNIPPETS_BY_SCRIPT_NAME == {
        spec.script_name: spec.help_required_snippets() for spec in SMOKE_CLI_DOC_PARSER_SPECS
    }
    assert SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME == (
        build_smoke_cli_doc_invalid_choice_expected_choices_registry(SMOKE_CLI_DOC_PARSER_SPECS)
    )
    assert SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME == {
        spec.script_name: spec.invalid_choice_expected_choices() for spec in SMOKE_CLI_DOC_PARSER_SPECS
    }

    readme_path = tmp_path / "README.md"
    parser_help_by_script_name = {
        spec.script_name: spec.build_parser(readme_path=readme_path).format_help()
        for spec in SMOKE_CLI_DOC_PARSER_SPECS
    }

    assert parser_help_by_script_name["smoke_cli_docs_smoke"] == build_smoke_cli_doc_audit_parser().format_help()
    assert parser_help_by_script_name["smoke_cli_docs_render"] == build_smoke_cli_doc_render_parser().format_help()
    assert parser_help_by_script_name["smoke_cli_docs_fix"] == build_smoke_cli_doc_fix_parser().format_help()
    assert SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME[
        "smoke_cli_docs_artifacts_smoke"
    ].build_parser(readme_path=readme_path).parse_args([]).readme_path == readme_path

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


def test_smoke_cli_doc_parser_spec_lookup_rejects_unknown_script_name() -> None:
    with pytest.raises(ValueError, match="unknown smoke cli doc parser spec 'missing_smoke'"):
        smoke_cli_doc_parser_spec("missing_smoke")


def test_package_testing_api_exports_smoke_cli_doc_parser_spec_lookup() -> None:
    assert "smoke_cli_doc_parser_spec" in testing_api.__all__
    assert testing_api.smoke_cli_doc_parser_spec is smoke_cli_doc_parser_spec
    assert testing_api.smoke_cli_doc_parser_spec("smoke_cli_docs_smoke") is (
        SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME["smoke_cli_docs_smoke"]
    )

    with pytest.raises(ValueError, match="unknown smoke cli doc parser spec 'missing_smoke'"):
        testing_api.smoke_cli_doc_parser_spec("missing_smoke")


def test_smoke_cli_doc_parser_help_examples_use_shared_description_formatter() -> None:
    spec = SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME["smoke_cli_docs_smoke"]

    expected_example_snippets = tuple(
        f"{example.command} # "
        + describe_smoke_cli_example(
            example,
            default_target_name=spec.selector.default_target_name,
            alias_target_names=spec.selector.alias_target_names,
            resolve_display_names=spec.selector.resolve_display_names,
            single_choice_description=spec.single_choice_description,
        )
        for example in spec.examples
    )

    assert spec.help_required_snippets()[1 : 1 + len(spec.examples)] == expected_example_snippets


def test_smoke_cli_doc_parser_alias_help_uses_shared_formatter() -> None:
    spec = SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME["smoke_cli_docs_smoke"]

    expected_alias_help = format_smoke_cli_alias_help(
        spec.item_help,
        alias_target_names=spec.selector.alias_target_names,
        resolve_display_names=spec.selector.resolve_display_names,
    )

    assert spec.help_required_snippets()[0] == expected_alias_help
    assert testing_api.format_smoke_cli_alias_help is format_smoke_cli_alias_help
    assert testing_api.format_smoke_cli_alias_lines(
        alias_target_names=spec.selector.alias_target_names,
        resolve_display_names=spec.selector.resolve_display_names,
    ) == ("all -> standalone_smoke, session_triage_smoke, session_recovery_smoke, smoke_matrix",)


def test_package_testing_api_smoke_cli_alias_help_formatters_cover_wrapper_specs() -> None:
    assert testing_api.format_smoke_cli_alias_help is format_smoke_cli_alias_help
    assert testing_api.format_smoke_cli_alias_lines is format_smoke_cli_alias_lines

    for spec in SMOKE_WRAPPER_CLI_SPECS:
        alias_lines = testing_api.format_smoke_cli_alias_lines(
            alias_target_names=spec.alias_target_names,
            resolve_display_names=spec.resolve_display_names,
        )
        alias_help = testing_api.format_smoke_cli_alias_help(
            spec.item_help,
            alias_target_names=spec.alias_target_names,
            resolve_display_names=spec.resolve_display_names,
        )

        assert alias_lines == spec.help_alias_lines()
        if alias_lines:
            assert alias_help == f"{spec.item_help} Aliases: " + "; ".join(alias_lines) + "."
        else:
            assert alias_help == spec.item_help


def test_smoke_cli_doc_render_parser_and_examples_follow_wrapper_registry() -> None:
    help_text = build_smoke_cli_doc_render_parser().format_help()

    assert build_smoke_cli_doc_render_examples() == (
        SmokeCliExample("smoke_cli_docs_render.py"),
        SmokeCliExample(
            "smoke_cli_docs_render.py standalone_smoke --body-only",
            target_name="standalone_smoke",
            description="single smoke wrapper body preview",
        ),
        SmokeCliExample(
            "smoke_cli_docs_render.py all --output-dir artifacts/smoke-cli-docs-preview",
            target_name="all",
            description="export all rendered smoke wrapper sections",
        ),
        SmokeCliExample(
            "smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview",
            target_name="all",
            description="export only the drifted rendered smoke wrapper sections",
        ),
        SmokeCliExample(
            "smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview --manifest-output artifacts/smoke-cli-docs-preview.json --diff-output artifacts/smoke-cli-docs-review.patch",
            target_name="all",
            description="persist drift-only review artifacts as rendered sections plus JSON manifest summaries/checksums and unified diff files",
        ),
    )
    assert matches_public_cli_help(
        help_text,
        required_snippets=[
            "Which smoke-wrapper README surface to render. Aliases: all -> standalone_smoke, session_triage_smoke, session_recovery_smoke, smoke_matrix.",
            "smoke_cli_docs_render.py # default all alias -> standalone_smoke, session_triage_smoke, session_recovery_smoke, smoke_matrix",
            "smoke_cli_docs_render.py standalone_smoke --body-only # single smoke wrapper body preview",
            "smoke_cli_docs_render.py all --output-dir artifacts/smoke-cli-docs-preview # export all rendered smoke wrapper sections",
            "smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview # export only the drifted rendered smoke wrapper sections",
            "smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview --manifest-output artifacts/smoke-cli-docs-preview.json --diff-output artifacts/smoke-cli-docs-review.patch # persist drift-only review artifacts as rendered sections plus JSON manifest summaries/checksums and unified diff files",
            "--body-only",
            "--output-dir OUTPUT_DIR",
            "--readme-path README_PATH",
            "--drift-only",
            "--manifest-output MANIFEST_OUTPUT",
            "--diff-output DIFF_OUTPUT",
        ],
    )


def test_smoke_cli_doc_fix_parser_and_examples_follow_wrapper_registry() -> None:
    help_text = build_smoke_cli_doc_fix_parser().format_help()

    assert build_smoke_cli_doc_fix_examples() == (
        SmokeCliExample("smoke_cli_docs_fix.py"),
        SmokeCliExample(
            "smoke_cli_docs_fix.py standalone_smoke --diff",
            target_name="standalone_smoke",
            description="preview a single smoke wrapper README section diff without writing it",
        ),
        SmokeCliExample(
            "smoke_cli_docs_fix.py all --check",
            target_name="all",
            description="exit non-zero when any selected smoke wrapper README section drifts",
        ),
        SmokeCliExample(
            "smoke_cli_docs_fix.py all --check --json",
            target_name="all",
            description="emit machine-readable JSON drift results with manifest-style summaries/checksums for CI without scraping prose",
        ),
        SmokeCliExample(
            "smoke_cli_docs_fix.py all --check --json-output artifacts/smoke-cli-docs-fix.json",
            target_name="all",
            description="persist the same machine-readable drift report with manifest-style summaries/checksums alongside the normal console summary",
        ),
        SmokeCliExample(
            "smoke_cli_docs_fix.py standalone_smoke",
            target_name="standalone_smoke",
            description="repair a single smoke wrapper README section in place",
        ),
        SmokeCliExample(
            "smoke_cli_docs_fix.py all --stdout",
            target_name="all",
            description="print the fully repaired README to stdout instead of writing it",
        ),
    )
    assert SMOKE_CLI_DOC_FIX_EXAMPLES == build_smoke_cli_doc_fix_examples()
    assert matches_public_cli_help(
        help_text,
        required_snippets=[
            "Which smoke-wrapper README surface to repair. Aliases: all -> standalone_smoke, session_triage_smoke, session_recovery_smoke, smoke_matrix.",
            "smoke_cli_docs_fix.py # default all alias -> standalone_smoke, session_triage_smoke, session_recovery_smoke, smoke_matrix",
            "smoke_cli_docs_fix.py standalone_smoke --diff # preview a single smoke wrapper README section diff without writing it",
            "smoke_cli_docs_fix.py all --check # exit non-zero when any selected smoke wrapper README section drifts",
            "smoke_cli_docs_fix.py all --check --json # emit machine-readable JSON drift results with manifest-style summaries/checksums for CI without scraping prose",
            "smoke_cli_docs_fix.py all --check --json-output artifacts/smoke-cli-docs-fix.json # persist the same machine-readable drift report with manifest-style summaries/checksums alongside the normal console summary",
            "smoke_cli_docs_fix.py standalone_smoke # repair a single smoke wrapper README section in place",
            "smoke_cli_docs_fix.py all --stdout # print the fully repaired README to stdout instead of writing it",
            "--readme-path README_PATH",
            "--diff",
            "--check",
            "--json",
            "--json-output JSON_OUTPUT",
            "--render-output-dir RENDER_OUTPUT_DIR",
            "--render-manifest-path RENDER_MANIFEST_PATH",
            "--render-diff-path RENDER_DIFF_PATH",
            "--stdout",
        ],
    )



def test_render_smoke_cli_readme_sections_support_full_section_and_body_views() -> None:
    assert render_smoke_cli_readme_section("standalone_smoke") == smoke_wrapper_cli_spec(
        "standalone_smoke"
    ).render_readme_section()
    assert render_smoke_cli_readme_section(
        "standalone_smoke", body_only=True
    ) == smoke_wrapper_cli_spec("standalone_smoke").render_readme_section_body()
    assert render_smoke_cli_readme_sections(requested_target_name="standalone_smoke", body_only=True) == (
        (
            "standalone_smoke",
            smoke_wrapper_cli_spec("standalone_smoke").render_readme_section_body(),
        ),
    )
    assert [
        script_name for script_name, _ in render_smoke_cli_readme_sections(requested_target_name="all")
    ] == list(DEFAULT_SMOKE_CLI_DOC_AUDIT_TARGET_NAMES)


def test_replace_markdown_section_rewrites_only_the_selected_section_body() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    triage_spec = smoke_cli_doc_spec("session_triage_smoke")
    markdown = (
        "## Smoke docs\n\n"
        f"### {standalone_spec.readme_section_heading}\n\nold standalone\n\n"
        f"### {triage_spec.readme_section_heading}\n\nkeep triage\n"
    )

    updated = replace_markdown_section(
        markdown,
        heading=standalone_spec.readme_section_heading,
        body="new standalone\n\nwith detail",
    )

    assert markdown_section_text(updated, heading=standalone_spec.readme_section_heading) == (
        "new standalone\n\nwith detail"
    )
    assert markdown_section_text(updated, heading=triage_spec.readme_section_heading) == "keep triage"


def test_repair_smoke_cli_readme_sections_updates_only_drifted_targets() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    triage_spec = smoke_cli_doc_spec("session_triage_smoke")
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )

    repaired_markdown, repaired_script_names = repair_smoke_cli_readme_sections(
        drifted_markdown,
        requested_target_name="standalone_smoke",
    )

    assert repaired_script_names == ("standalone_smoke",)
    assert (
        markdown_section_text(repaired_markdown, heading=standalone_spec.readme_section_heading)
        == smoke_wrapper_cli_spec("standalone_smoke").render_readme_section_body()
    )
    assert (
        markdown_section_text(repaired_markdown, heading=triage_spec.readme_section_heading)
        == markdown_section_text(README_TEXT, heading=triage_spec.readme_section_heading)
    )


def test_repair_smoke_cli_readme_sections_returns_no_changes_when_readme_already_matches() -> None:
    repaired_markdown, repaired_script_names = repair_smoke_cli_readme_sections(
        README_TEXT,
        requested_target_name="all",
    )

    assert repaired_markdown == README_TEXT
    assert repaired_script_names == ()



def test_collect_smoke_cli_readme_diffs_returns_only_selected_drifted_targets() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    triage_spec = smoke_cli_doc_spec("session_triage_smoke")
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    drifted_markdown = replace_markdown_section(
        drifted_markdown,
        heading=triage_spec.readme_section_heading,
        body="broken triage docs",
    )

    assert collect_smoke_cli_readme_diffs(
        drifted_markdown,
        requested_target_name="standalone_smoke",
    ) == (("standalone_smoke", smoke_cli_readme_diff_lines(drifted_markdown, script_name="standalone_smoke")),)
    assert collect_smoke_cli_readme_diffs(
        drifted_markdown,
        requested_target_name="all",
    ) == (
        ("standalone_smoke", smoke_cli_readme_diff_lines(drifted_markdown, script_name="standalone_smoke")),
        ("session_triage_smoke", smoke_cli_readme_diff_lines(drifted_markdown, script_name="session_triage_smoke")),
    )
    assert collect_smoke_cli_readme_diffs(README_TEXT, requested_target_name="all") == ()



def test_build_smoke_cli_doc_spec_registry_rejects_duplicate_script_names() -> None:
    spec = SmokeCliDocSpec(
        script_name="standalone_smoke",
        readme_section_heading="Standalone local smoke bundle",
        help_required_snippets=("standalone help",),
        readme_required_snippets=("standalone readme",),
    )

    with pytest.raises(ValueError, match="duplicate smoke cli doc spec 'standalone_smoke'"):
        build_smoke_cli_doc_spec_registry((spec, spec))


def test_build_smoke_cli_doc_parser_spec_registry_rejects_duplicate_script_names() -> None:
    spec = SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME["smoke_cli_docs_smoke"]

    with pytest.raises(ValueError, match="duplicate smoke cli doc parser spec 'smoke_cli_docs_smoke'"):
        build_smoke_cli_doc_parser_spec_registry((spec, spec))


def test_build_smoke_cli_doc_invalid_choice_registry_rejects_duplicate_script_names() -> None:
    spec = SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME["smoke_cli_docs_smoke"]

    with pytest.raises(
        ValueError,
        match="duplicate smoke cli doc invalid-choice registry entry 'smoke_cli_docs_smoke'",
    ):
        build_smoke_cli_doc_invalid_choice_expected_choices_registry((spec, spec))



def test_smoke_cli_doc_specs_extract_markdown_sections_and_reuse_shared_snippets() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    triage_spec = smoke_cli_doc_spec("session_triage_smoke")
    standalone_body = smoke_wrapper_cli_spec("standalone_smoke").render_readme_section_body()
    triage_body = smoke_wrapper_cli_spec("session_triage_smoke").render_readme_section_body()
    markdown = (
        "## Smoke docs\n\n"
        f"### {standalone_spec.readme_section_heading}\n\n"
        f"{standalone_body}\n\n"
        f"### {triage_spec.readme_section_heading}\n\n"
        f"{triage_body}"
    )
    help_text = "\n".join(standalone_spec.help_required_snippets)

    assert markdown_section_text(markdown, heading=standalone_spec.readme_section_heading) == standalone_body
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
    assert parity.readme_diagnostic.startswith(
        f"README {standalone_spec.readme_section_heading!r} missing: "
        + " | ".join(standalone_spec.readme_required_snippets[0:1] + standalone_spec.readme_required_snippets[2:])
        + "; diff: --- expected | +++ README | @@"
    )
    assert parity.readme_diff_lines[0:2] == ("--- expected", "+++ README")
    assert parity.readme_diff_lines[2].startswith("@@ ")
    assert parity.diagnostic_summary == f"{parity.help_diagnostic}; {parity.readme_diagnostic}"
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
        f"### {standalone_spec.readme_section_heading}\n\n"
        f"{smoke_wrapper_cli_spec('standalone_smoke').render_readme_section_body()}"
    )

    parity = collect_smoke_cli_doc_parity(
        script_name="standalone_smoke",
        help_text=help_text,
        markdown=markdown,
    )

    assert parity.help_diagnostic == "help ok"
    assert parity.readme_diagnostic == f"README {standalone_spec.readme_section_heading!r} ok"
    assert parity.readme_diff_summary == "none"
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


def test_smoke_cli_doc_parity_detects_exact_readme_section_drift_without_missing_snippets() -> None:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    help_text = "\n".join(standalone_spec.help_required_snippets)
    drifted_body = smoke_wrapper_cli_spec("standalone_smoke").render_readme_section_body().replace(
        "Operator shortcuts:",
        "Shortcut notes:",
        1,
    )
    markdown = (
        "## Smoke docs\n\n"
        f"### {standalone_spec.readme_section_heading}\n\n"
        f"{drifted_body}"
    )

    parity = collect_smoke_cli_doc_parity(
        script_name="standalone_smoke",
        help_text=help_text,
        markdown=markdown,
    )

    assert parity.missing_readme_snippets == ()
    assert parity.readme_matches is False
    assert parity.matches is False
    assert parity.readme_diff_lines[0:2] == ("--- expected", "+++ README")
    assert parity.readme_diff_lines[2].startswith("@@ ")
    assert "-Operator shortcuts:" in parity.readme_diff_lines
    assert "+Shortcut notes:" in parity.readme_diff_lines
    assert parity.readme_diff_summary.startswith("--- expected | +++ README | @@ ")
    assert "diff: --- expected | +++ README | @@ " in parity.readme_diagnostic



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
        This page stale lanes: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC) | cutoff: approvals >= 7d old | more off-page: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC), restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC)
        """
    ).strip()
    stale_second_page_text = dedent(
        """
        This page stale lanes: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC), restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC) | cutoff: approvals >= 7d old | more off-page: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC)
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
        Intervention mix: requests: 7 | families: test 4, edit 3 | targets: path 3, command 4 | continuations: approved result 1
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
    assert intervention_mix_smoke_results(
        intervention_text,
        result_prefix="picker",
        surface_required_session_ids=["session-pending", "session-denied"],
        surface_excluded_session_ids=["session-plain"],
        surface_required=["intervention: pending 1"],
        require_preview=True,
        target_mix_required=["targets: path 3, command 4"],
        continuation_mix_required=["continuations: approved result 1"],
    ) == (
        ("picker_intervention_surface", True),
        ("picker_intervention_target_mix", True),
        ("picker_intervention_continuation_mix", True),
    )
    assert intervention_mix_smoke_results(
        intervention_text,
        result_prefix="switcher",
        surface_result_name="switcher_intervention_filter",
        sort_mode="attention",
        target_mix_required=["targets: path 3, command 4"],
        continuation_mix_required=["continuations: approved result 1"],
    ) == (
        ("switcher_intervention_filter", False),
        ("switcher_intervention_target_mix", False),
        ("switcher_intervention_continuation_mix", False),
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
