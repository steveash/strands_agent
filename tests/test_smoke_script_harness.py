from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path

import pytest

from strands_agent_tui.testing import (
    DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS,
    SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FALSE_FAILED_LINE,
    SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_HINT_PREFIX,
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILED_LINE,
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS,
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_HINT_PREFIX,
    SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS,
    SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT,
    SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
    SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    SMOKE_MATRIX_DOCS_REVIEW_FAILED_LINE_PREFIX,
    SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS,
    SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
    SMOKE_MATRIX_DOCS_REVIEW_RUNNING_PREFIX,
    SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX,
    SMOKE_MATRIX_REVIEW_BUNDLE_RERUN_HINT_PREFIX,
    SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT,
    SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT,
    SESSION_TRIAGE_INTERVENTION_MIX_CONTRACT,
    SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX,
    SMOKE_MATRIX_REVIEW_METADATA_PREFIX,
    SMOKE_SCRIPT_CONTRACT_CASES,
    STANDALONE_DOCS_RERUN_HINT_CONTRACT,
    STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
    SmokeMatrixDocsReviewFailureDefaults,
    SmokeMatrixDocsReviewObserverSpec,
    SmokeMatrixDocsReviewSuccessDefaults,
    SmokeScriptContractCase,
    SmokeScriptRunResult,
    SmokeWrapperFailureObservation,
    assert_smoke_script_output_matches_contract,
    assert_smoke_script_results_match_contract,
    build_malformed_smoke_script_detail_results,
    build_malformed_smoke_script_result_results,
    build_review_artifact_failure_results,
    build_review_artifact_matrix_summary_assertion_results,
    build_review_artifact_observation_results,
    build_smoke_matrix_review_artifact_location_lines,
    build_smoke_matrix_review_artifact_location_messages,
    build_smoke_matrix_review_metadata_line,
    build_smoke_matrix_review_metadata_payload,
    build_smoke_matrix_docs_review_result_naming,
    build_review_artifact_success_results,
    build_script_driver_source,
    build_smoke_matrix_docs_review_observation_fixture,
    build_smoke_matrix_docs_review_observer_spec,
    build_standalone_docs_rerun_hint_results,
    collect_smoke_wrapper_failure_output,
    collect_smoke_matrix_docs_review_failure_output,
    collect_review_artifact_output,
    detail_safe_text,
    emit_smoke_results,
    find_prefixed_line_index,
    load_script_module,
    observe_loaded_review_artifact_output,
    observe_loaded_review_artifact_output_in_temp_checkout,
    observe_review_artifact_output_in_temp_checkout,
    observe_script_module_main_via_driver_review_artifact_output,
    observe_subprocess_review_artifact_output,
    run_loaded_script_module_main,
    run_loaded_script_module_main_in_temp_checkout,
    run_python_driver_in_temp_checkout,
    run_script_module_main_in_temp_checkout,
    run_script_module_main_via_driver_in_temp_checkout,
    smoke_cli_docs_parity_rerun_hint,
    smoke_contract_detail_expectation,
    smoke_matrix_docs_review_failure_summary_prefix,
    smoke_matrix_docs_review_success_summary_prefix,
)


def _write_target_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _matching_contract_output_lines(case: SmokeScriptContractCase) -> list[str]:
    return list(case.required_line_prefixes) + [
        f"{check_name}= True" for check_name in case.true_check_names
    ]


def _matching_contract_results(case: SmokeScriptContractCase) -> list[tuple[str, object]]:
    return [
        (detail_name, f"{detail_value_prefix}fixture")
        for detail_name, detail_value_prefix in (
            smoke_contract_detail_expectation(prefix) for prefix in case.required_line_prefixes
        )
    ] + [
        (check_name, True) for check_name in case.true_check_names
    ]


def _required_contract_detail_with_value_prefix(case: SmokeScriptContractCase) -> tuple[str, str]:
    return next(
        (detail_name, detail_value_prefix)
        for detail_name, detail_value_prefix in (
            smoke_contract_detail_expectation(prefix) for prefix in case.required_line_prefixes
        )
        if detail_value_prefix
    )


def test_find_prefixed_line_index_and_detail_safe_text() -> None:
    lines = ["alpha", "beta: 1", "beta: 2"]

    assert find_prefixed_line_index(lines, "beta:") == 1
    assert find_prefixed_line_index(lines, "gamma:") is None
    assert detail_safe_text("render_manifest_payload= False") == "render_manifest_payload=False"


def test_collect_review_artifact_output_tracks_metadata_and_matrix_summary(tmp_path: Path) -> None:
    checkout_root = tmp_path / "checkout"
    summary_path = checkout_root / "artifacts" / "review" / "matrix-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_payload = {
        "bundle_index_rerun_hint": "rerun docs parity",
        "display_name": "docs-review",
        "target_name": "docs-review",
        "artifact_root": "artifacts/review",
        "bundle_index_path": "artifacts/review/index.json",
        "drifted_readme_path": "artifacts/review/README-drifted.md",
        "render_output_dir": "artifacts/review/rendered",
        "render_manifest_path": "artifacts/review/render-manifest.json",
        "render_diff_path": "artifacts/review/render-review.patch",
        "fix_check_json_path": "artifacts/review/fix-check.json",
        "fix_repair_json_path": "artifacts/review/fix-repair.json",
        "fix_post_check_json_path": "artifacts/review/fix-post-check.json",
        "matrix_summary_path": "artifacts/review/matrix-summary.json",
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    metadata_payload = dict(summary_payload)

    observed = collect_review_artifact_output(
        [
            f"[smoke-matrix] review metadata: {json.dumps(metadata_payload, sort_keys=True)}",
            "[smoke-matrix] review artifacts: artifacts/review",
            "[smoke-matrix] review matrix summary: artifacts/review/matrix-summary.json",
        ],
        checkout_root=checkout_root,
        metadata_prefix="[smoke-matrix] review metadata: ",
        artifacts_prefix="[smoke-matrix] review artifacts: ",
        matrix_summary_prefix="[smoke-matrix] review matrix summary: ",
    )

    assert observed.metadata_index == 0
    assert observed.artifacts_index == 1
    assert observed.matrix_summary_index == 2
    assert observed.metadata_line_present is True
    assert observed.artifacts_line_present is True
    assert observed.matrix_summary_line_present is True
    assert observed.metadata_targets("docs-review") is True
    assert observed.metadata_artifact_root_matches("artifacts/review") is True
    assert observed.metadata_matrix_summary_matches("artifacts/review/matrix-summary.json") is True
    assert observed.metadata_bundle_index_rerun_hint_matches("rerun docs parity") is True
    assert observed.matrix_summary_artifact_exists is True
    assert observed.matrix_summary_targets("docs-review") is True
    assert observed.matrix_summary_artifact_root_matches("artifacts/review") is True
    assert observed.matrix_summary_path_matches("artifacts/review/matrix-summary.json") is True
    assert observed.matrix_summary_bundle_index_rerun_hint_matches("rerun docs parity") is True
    assert observed.matrix_summary_path_matches_metadata() is True
    assert observed.matrix_summary_line_matches_metadata_path() is True
    expected_paths = {
        "artifact_root": checkout_root / "artifacts" / "review",
        "bundle_index_path": checkout_root / "artifacts" / "review" / "index.json",
        "drifted_readme_path": checkout_root / "artifacts" / "review" / "README-drifted.md",
        "render_output_dir": checkout_root / "artifacts" / "review" / "rendered",
        "render_manifest_path": checkout_root / "artifacts" / "review" / "render-manifest.json",
        "render_diff_path": checkout_root / "artifacts" / "review" / "render-review.patch",
        "fix_check_json_path": checkout_root / "artifacts" / "review" / "fix-check.json",
        "fix_repair_json_path": checkout_root / "artifacts" / "review" / "fix-repair.json",
        "fix_post_check_json_path": checkout_root / "artifacts" / "review" / "fix-post-check.json",
        "matrix_summary_path": summary_path,
    }
    expected_path_strings = {
        "artifact_root": "artifacts/review",
        "bundle_index_path": "artifacts/review/index.json",
        "drifted_readme_path": "artifacts/review/README-drifted.md",
        "render_output_dir": "artifacts/review/rendered",
        "render_manifest_path": "artifacts/review/render-manifest.json",
        "render_diff_path": "artifacts/review/render-review.patch",
        "fix_check_json_path": "artifacts/review/fix-check.json",
        "fix_repair_json_path": "artifacts/review/fix-repair.json",
        "fix_post_check_json_path": "artifacts/review/fix-post-check.json",
        "matrix_summary_path": "artifacts/review/matrix-summary.json",
    }

    assert observed.metadata_paths == expected_paths
    assert observed.matrix_summary_paths == observed.metadata_paths
    assert observed.payload_paths_match("metadata", expected_path_strings) is True
    assert observed.payload_paths_match("matrix_summary", expected_path_strings) is True
    assert observed.resolved_paths_match("metadata", expected_paths) is True
    assert observed.resolved_paths_match("matrix_summary", expected_paths) is True

    observer_spec = SmokeMatrixDocsReviewObserverSpec(
        requested_target_name="review",
        expected_target_name="docs-review",
        expected_artifact_root="artifacts/review",
        expected_matrix_summary_path="artifacts/review/matrix-summary.json",
        expected_bundle_index_rerun_hint="rerun docs parity",
        expected_artifact_paths=expected_path_strings,
        driver_filename="run_review.py",
    )
    assert observer_spec.metadata_artifact_paths_match(observed) is True
    assert observer_spec.matrix_summary_artifact_paths_match(observed) is True
    assert observer_spec.metadata_resolved_paths_match(observed) is True
    assert observer_spec.matrix_summary_resolved_paths_match(observed) is True


def test_collect_review_artifact_output_supports_matrix_summary_without_metadata(tmp_path: Path) -> None:
    checkout_root = tmp_path / "checkout"
    summary_path = checkout_root / "artifacts" / "review" / "matrix-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "bundle_index_rerun_hint": "rerun docs parity",
                "display_name": "docs-review-all",
                "target_name": "docs-review-all",
                "artifact_root": "artifacts/review",
                "matrix_summary_path": "artifacts/review/matrix-summary.json",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    observed = collect_review_artifact_output(
        ["[smoke-matrix] review matrix summary: artifacts/review/matrix-summary.json"],
        checkout_root=checkout_root,
        matrix_summary_prefix="[smoke-matrix] review matrix summary: ",
    )

    assert observed.metadata_index is None
    assert observed.artifacts_index is None
    assert observed.metadata_line == ""
    assert observed.artifacts_line == ""
    assert observed.matrix_summary_index == 0
    assert observed.matrix_summary_line_present is True
    assert observed.matrix_summary_artifact_exists is True
    assert observed.matrix_summary_targets("docs-review-all") is True
    assert observed.matrix_summary_artifact_root_matches("artifacts/review") is True
    assert observed.matrix_summary_path_matches("artifacts/review/matrix-summary.json") is True
    assert observed.matrix_summary_bundle_index_rerun_hint_matches("rerun docs parity") is True


def test_collect_smoke_matrix_docs_review_failure_output_tracks_shared_failure_ordering(
    tmp_path: Path,
) -> None:
    checkout_root = tmp_path / "checkout"
    summary_path = checkout_root / "artifacts" / "review" / "matrix-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_payload = {
        "bundle_index_rerun_hint": "rerun docs parity",
        "display_name": "docs-review-all",
        "target_name": "docs-review-all",
        "artifact_root": "artifacts/review",
        "matrix_summary_path": "artifacts/review/matrix-summary.json",
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"[smoke-matrix] review metadata: {json.dumps(summary_payload, sort_keys=True)}",
        "[smoke-matrix] review artifacts: artifacts/review",
        "[smoke-matrix] review matrix summary: artifacts/review/matrix-summary.json",
        SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_line("rerun docs parity"),
        "[smoke-matrix] hint: live runtime guidance",
        "[smoke-matrix] hint: docs-review-only guidance",
        "[smoke-matrix] summary: 0/4 bundles passed before failure in 0.10s",
        "standalone smoke exited with status 1",
    ]
    review_output = collect_review_artifact_output(
        lines,
        checkout_root=checkout_root,
        metadata_prefix="[smoke-matrix] review metadata: ",
        artifacts_prefix="[smoke-matrix] review artifacts: ",
        matrix_summary_prefix="[smoke-matrix] review matrix summary: ",
    )

    failure_output = collect_smoke_matrix_docs_review_failure_output(
        lines,
        review_output=review_output,
        failed_line_exact="standalone smoke exited with status 1",
        bundle_rerun_hint_prefix=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.rerun_hint_prefix,
        live_runtime_hint_prefix="[smoke-matrix] hint: live runtime guidance",
        docs_review_only_hint_prefix="[smoke-matrix] hint: docs-review-only guidance",
        failure_summary_prefix="[smoke-matrix] summary: 0/4 bundles passed before failure in ",
    )

    assert failure_output.line("failed") == "standalone smoke exited with status 1"
    assert failure_output.line("metadata") == lines[0]
    assert failure_output.line("artifacts") == lines[1]
    assert failure_output.line("matrix_summary") == lines[2]
    assert failure_output.line("bundle_rerun_hint") == lines[3]
    assert failure_output.line("live_runtime_hint") == lines[4]
    assert failure_output.line("docs_review_only_hint") == lines[5]
    assert failure_output.line("failure_summary") == lines[6]
    assert failure_output.present("missing_api_key_hint") is False
    assert failure_output.appears_before("metadata", "bundle_rerun_hint") is True
    assert failure_output.appears_before("bundle_rerun_hint", "live_runtime_hint") is True
    assert failure_output.appears_before("live_runtime_hint", "docs_review_only_hint") is True
    assert failure_output.appears_before("docs_review_only_hint", "failure_summary") is True
    assert failure_output.appears_before("failed", "failure_summary") is False


def test_collect_smoke_wrapper_failure_output_tracks_shared_failure_ordering() -> None:
    lines = [
        "fix_check_summary: smoke README drift detected in 1 section(s) for README.md: standalone_smoke",
        "fix_post_check= False",
        "docs-artifacts smoke failed fast: fix_post_check= False",
        "[standalone-smoke] hint: rerun standalone_smoke.py docs-review-only",
        "[standalone-smoke] summary: 5/6 targets passed before failure in 0.10s",
    ]

    failure_output = collect_smoke_wrapper_failure_output(
        lines,
        failed_line_prefix="docs-artifacts smoke failed fast: ",
        hint_prefix="[standalone-smoke] hint: ",
        failure_summary_prefix="[standalone-smoke] summary: 5/6 targets passed before failure in ",
    )

    assert isinstance(failure_output, SmokeWrapperFailureObservation)
    assert failure_output.line("failed") == lines[2]
    assert failure_output.line("hint") == lines[3]
    assert failure_output.line("failure_summary") == lines[4]
    assert failure_output.present("failed") is True
    assert failure_output.present("hint") is True
    assert failure_output.present("failure_summary") is True
    assert failure_output.appears_before("failed", "hint") is True
    assert failure_output.appears_before("hint", "failure_summary") is True
    assert failure_output.appears_before("failed", "failure_summary") is True


def test_collect_smoke_wrapper_failure_output_validates_failed_matcher_contract() -> None:
    lines = ["docs-artifacts smoke failed fast: fix_post_check= False"]

    with pytest.raises(
        ValueError,
        match="provide exactly one failed-line matcher: failed_line_prefix or failed_line_exact",
    ):
        collect_smoke_wrapper_failure_output(
            lines,
            hint_prefix="[standalone-smoke] hint: ",
            failure_summary_prefix="[standalone-smoke] summary: ",
        )

    with pytest.raises(
        ValueError,
        match="provide exactly one failed-line matcher: failed_line_prefix or failed_line_exact",
    ):
        collect_smoke_wrapper_failure_output(
            lines,
            failed_line_prefix="docs-artifacts smoke failed fast: ",
            failed_line_exact="docs-artifacts smoke failed fast: fix_post_check= False",
            hint_prefix="[standalone-smoke] hint: ",
            failure_summary_prefix="[standalone-smoke] summary: ",
        )


def test_build_standalone_docs_rerun_hint_results_reuses_shared_contract_metadata() -> None:
    smoke_run = SmokeScriptRunResult(
        checkout_root=Path("/tmp/checkout"),
        exit_code=1,
        stdout=(
            "fix_check_summary: smoke README drift detected in 1 section(s) for README.md: standalone_smoke\n"
            "fix_post_check= False\n"
        ),
        stderr="",
        cleanup_callback=lambda: None,
    )
    failure_output = SmokeWrapperFailureObservation(
        failed_index=2,
        hint_index=3,
        failure_summary_index=4,
        failed_line="docs-artifacts smoke failed fast: fix_post_check= False",
        hint_line=(
            "[standalone-smoke] hint: standalone wrapper docs drift is easiest to isolate with "
            "`.venv/bin/python scripts/standalone_smoke.py docs-review-only`"
        ),
        failure_summary_line="[standalone-smoke] summary: 5/6 targets passed before failure in 0.10s",
    )

    output = StringIO()
    exit_code = emit_smoke_results(
        build_standalone_docs_rerun_hint_results(smoke_run, failure_output),
        stdout=output,
    )
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    for prefix in STANDALONE_DOCS_RERUN_HINT_CONTRACT.required_line_prefixes:
        assert any(line.startswith(prefix) for line in lines), prefix
    for check_name in STANDALONE_DOCS_RERUN_HINT_CONTRACT.true_check_names:
        assert f"{check_name}= True" in lines


def test_exported_smoke_script_contract_cases_cover_shared_docs_review_wrappers() -> None:
    assert STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT.script_name == "standalone_docs_rerun_hint_smoke"
    assert STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT.runner_name == "run_standalone_docs_rerun_hint_smoke"
    assert (
        STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT.required_line_prefixes
        == STANDALONE_DOCS_RERUN_HINT_CONTRACT.required_line_prefixes
    )
    assert (
        STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT.true_check_names
        == STANDALONE_DOCS_RERUN_HINT_CONTRACT.true_check_names
    )

    assert [(case.script_name, case.runner_name) for case in DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS] == [
        ("smoke_matrix_all_review_order_smoke", "run_smoke_matrix_all_review_order_smoke"),
        (
            "smoke_matrix_all_review_missing_api_key_smoke",
            "run_smoke_matrix_all_review_missing_api_key_smoke",
        ),
        ("smoke_matrix_docs_review_hint_smoke", "run_smoke_matrix_docs_review_hint_smoke"),
    ]
    for case in DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS:
        assert case.required_line_prefixes[0] == "checkout_root: "
        assert "exit_code_non_zero" in case.true_check_names
        assert "metadata_line_present" in case.true_check_names
        assert "matrix_summary_artifact_exists" in case.true_check_names


def test_exported_docs_review_failure_defaults_share_expected_prefixes() -> None:
    assert SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS == SmokeMatrixDocsReviewFailureDefaults(
        failed_line_exact=SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FALSE_FAILED_LINE,
        live_runtime_hint_prefix=SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_HINT_PREFIX,
        docs_review_only_hint_prefix=SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
        failure_summary_prefix=smoke_matrix_docs_review_failure_summary_prefix(passed_count=0),
    )
    assert SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS.collect_kwargs() == {
        "failed_line_exact": SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FALSE_FAILED_LINE,
        "live_runtime_hint_prefix": SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_HINT_PREFIX,
        "docs_review_only_hint_prefix": SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
        "failure_summary_prefix": smoke_matrix_docs_review_failure_summary_prefix(passed_count=0),
    }

    assert SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS.collect_kwargs() == {
        "failed_line_exact": SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILED_LINE,
        "bundle_rerun_hint_prefix": (
            SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS.bundle_rerun_hint_line_prefix()
        ),
        "docs_review_only_hint_prefix": SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
        "missing_api_key_hint_prefix": SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_HINT_PREFIX,
        "failure_summary_prefix": smoke_matrix_docs_review_failure_summary_prefix(passed_count=0),
    }
    assert SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS.format_bundle_rerun_hint_line(
        "rerun docs parity"
    ) == "[smoke-matrix] review bundle rerun hint: rerun docs parity"

    assert SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS.collect_kwargs() == {
        "failed_line_prefix": SMOKE_MATRIX_DOCS_REVIEW_FAILED_LINE_PREFIX,
        "bundle_rerun_hint_prefix": (
            SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS.bundle_rerun_hint_line_prefix()
        ),
        "docs_review_only_hint_prefix": SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
        "failure_summary_prefix": smoke_matrix_docs_review_failure_summary_prefix(passed_count=3),
    }
    assert SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS.stdout_running_prefix == (
        SMOKE_MATRIX_DOCS_REVIEW_RUNNING_PREFIX
    )
    assert SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS.format_bundle_rerun_hint_line(
        "rerun docs parity"
    ) is None


def test_exported_docs_review_success_defaults_share_expected_prefixes() -> None:
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS == SmokeMatrixDocsReviewSuccessDefaults(
        success_summary_prefix=smoke_matrix_docs_review_success_summary_prefix(),
        rerun_hint_prefix=SMOKE_MATRIX_REVIEW_BUNDLE_RERUN_HINT_PREFIX,
    )
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_success_summary_line(0.1) == (
        "[smoke-matrix] summary: 4/4 bundles passed in 0.10s"
    )
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.matches_success_summary_line(
        SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_success_summary_line(0.1)
    )
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_line("rerun docs parity") == (
        "[smoke-matrix] review bundle rerun hint: rerun docs parity"
    )
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_bundle_rerun_hint_line(
        "rerun docs parity"
    ) == "[smoke-matrix] review bundle rerun hint: rerun docs parity"
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_message(
        "rerun docs parity"
    ) == "review bundle rerun hint: rerun docs parity"
    assert (
        f"review_summary_line: {SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.success_summary_prefix}"
        in SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT.required_line_prefixes
    )
    assert (
        (
            "all_review_rerun_hint_line: "
            f"{SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.bundle_rerun_hint_line_prefix()}"
        )
        in SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT.required_line_prefixes
    )


def test_build_smoke_matrix_review_artifact_location_builders_share_default_docs_review_paths() -> None:
    metadata = build_smoke_matrix_review_metadata_payload(artifact_root="artifacts/review")

    assert metadata == {
        "artifact_root": "artifacts/review",
        "bundle_index_rerun_hint": smoke_cli_docs_parity_rerun_hint(),
        "bundle_index_path": "artifacts/review/index.json",
        "display_name": "docs-review",
        "drifted_readme_path": "artifacts/review/README-drifted.md",
        "fix_check_json_path": "artifacts/review/fix-check.json",
        "fix_post_check_json_path": "artifacts/review/fix-post-check.json",
        "fix_repair_json_path": "artifacts/review/fix-repair.json",
        "matrix_summary_path": "artifacts/review/matrix-summary.json",
        "render_diff_path": "artifacts/review/render-review.patch",
        "render_manifest_path": "artifacts/review/render-manifest.json",
        "render_output_dir": "artifacts/review/rendered",
        "target_name": "docs-review",
    }
    assert build_smoke_matrix_review_metadata_line(artifact_root="artifacts/review") == (
        f"{SMOKE_MATRIX_REVIEW_METADATA_PREFIX}{json.dumps(metadata, sort_keys=True)}"
    )

    messages = build_smoke_matrix_review_artifact_location_messages(
        artifact_root="artifacts/review",
        rerun_hint="rerun docs parity",
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    )

    assert messages == (
        "review artifacts: artifacts/review (index: artifacts/review/index.json)",
        "review matrix summary: artifacts/review/matrix-summary.json",
        "review bundle rerun hint: rerun docs parity",
        "review drifted README: artifacts/review/README-drifted.md",
        "review rendered sections: artifacts/review/rendered",
        "review render manifest: artifacts/review/render-manifest.json",
        "review render diff: artifacts/review/render-review.patch",
        "review fix-check JSON: artifacts/review/fix-check.json",
        "review fix-repair JSON: artifacts/review/fix-repair.json",
        "review fix-post-check JSON: artifacts/review/fix-post-check.json",
    )
    assert build_smoke_matrix_review_artifact_location_lines(
        artifact_root="artifacts/review",
        rerun_hint="rerun docs parity",
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    ) == tuple(f"[smoke-matrix] {message}" for message in messages)


def test_build_smoke_matrix_review_artifact_location_builders_honor_explicit_override_paths() -> None:
    messages = build_smoke_matrix_review_artifact_location_messages(
        artifact_root="artifacts/review",
        bundle_index_path="artifacts/review/index.json",
        drifted_readme_path="artifacts/custom/README-review.md",
        render_output_dir="artifacts/custom/rendered-sections",
        render_manifest_path="artifacts/custom/render.json",
        render_diff_path="artifacts/custom/review.patch",
        fix_check_json_path="artifacts/custom/fix-check.json",
        fix_repair_json_path="artifacts/custom/fix-repair.json",
        fix_post_check_json_path="artifacts/custom/fix-post-check.json",
        rerun_hint="hint: rerun the focused docs bundle",
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    )

    assert messages == (
        "review artifacts: artifacts/review (index: artifacts/review/index.json)",
        "review matrix summary: artifacts/review/matrix-summary.json",
        "review bundle rerun hint: hint: rerun the focused docs bundle",
        "review drifted README: artifacts/custom/README-review.md",
        "review rendered sections: artifacts/custom/rendered-sections",
        "review render manifest: artifacts/custom/render.json",
        "review render diff: artifacts/custom/review.patch",
        "review fix-check JSON: artifacts/custom/fix-check.json",
        "review fix-repair JSON: artifacts/custom/fix-repair.json",
        "review fix-post-check JSON: artifacts/custom/fix-post-check.json",
    )


def test_smoke_matrix_docs_review_failure_defaults_require_exactly_one_failed_matcher() -> None:
    with pytest.raises(ValueError, match="provide exactly one failed-line matcher"):
        SmokeMatrixDocsReviewFailureDefaults(
            failed_line_prefix="prefix",
            failed_line_exact="exact",
            failure_summary_prefix="summary: ",
        )

    with pytest.raises(ValueError, match="provide exactly one failed-line matcher"):
        SmokeMatrixDocsReviewFailureDefaults(failure_summary_prefix="summary: ")


def test_collect_smoke_matrix_docs_review_failure_output_validates_failed_matcher_contract(
    tmp_path: Path,
) -> None:
    checkout_root = tmp_path / "checkout"
    summary_path = checkout_root / "artifacts" / "review" / "matrix-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps({"target_name": "docs-review", "matrix_summary_path": "artifacts/review/matrix-summary.json"})
        + "\n",
        encoding="utf-8",
    )
    review_output = collect_review_artifact_output(
        ["[smoke-matrix] review matrix summary: artifacts/review/matrix-summary.json"],
        checkout_root=checkout_root,
        matrix_summary_prefix="[smoke-matrix] review matrix summary: ",
    )

    with pytest.raises(
        ValueError,
        match="provide exactly one failed-line matcher: failed_line_prefix or failed_line_exact",
    ):
        collect_smoke_matrix_docs_review_failure_output(
            [],
            review_output=review_output,
            failure_summary_prefix="[smoke-matrix] summary: ",
        )

    with pytest.raises(
        ValueError,
        match="provide exactly one failed-line matcher: failed_line_prefix or failed_line_exact",
    ):
        collect_smoke_matrix_docs_review_failure_output(
            [],
            review_output=review_output,
            failed_line_prefix="failed: ",
            failed_line_exact="failed",
            failure_summary_prefix="[smoke-matrix] summary: ",
        )


def test_build_smoke_matrix_docs_review_observation_fixture_builds_shared_review_setup(
    tmp_path: Path,
) -> None:
    fixture = build_smoke_matrix_docs_review_observation_fixture(
        tmp_path / "checkout",
        requested_target_name="all-review",
    )

    assert fixture.summary_path == tmp_path / "checkout" / "artifacts" / "review" / "matrix-summary.json"
    assert fixture.metadata_payload["target_name"] == "docs-review-all"
    assert fixture.review_spec.expected_target_name == "docs-review-all"
    assert fixture.review_spec.expected_artifact_root == "artifacts/review"
    assert fixture.review_spec.expected_matrix_summary_path == "artifacts/review/matrix-summary.json"
    assert fixture.review_output.matrix_summary_artifact_exists is True
    assert fixture.review_spec.metadata_artifact_paths_match(fixture.review_output) is True
    assert fixture.review_spec.matrix_summary_artifact_paths_match(fixture.review_output) is True


def test_build_smoke_matrix_docs_review_result_naming_exposes_shared_result_name_bundles() -> None:
    failure_naming = build_smoke_matrix_docs_review_result_naming(
        "all-review",
        result_prefix="",
    )
    failure_observation_names = failure_naming.observation_result_names(
        line_detail_prefix="stderr_",
    )
    failure_matrix_summary_names = failure_naming.matrix_summary_assertion_result_names()
    success_names = failure_naming.success_result_names(result_prefix="all_review")

    assert failure_observation_names.detail_names() == (
        "stderr_metadata_line",
        "stderr_artifacts_line",
        "stderr_matrix_summary_line",
    )
    assert failure_observation_names.true_check_names() == (
        "metadata_line_present",
        "artifacts_line_present",
        "matrix_summary_line_present",
        "metadata_targets_docs_review_all",
        "metadata_artifact_root_matches_all_review",
        "metadata_bundle_index_rerun_hint_matches",
        "metadata_expected_artifact_paths_match",
        "metadata_resolved_paths_match_expected",
        "matrix_summary_artifact_exists",
        "matrix_summary_targets_docs_review_all",
        "matrix_summary_artifact_root_matches_all_review",
        "matrix_summary_bundle_index_rerun_hint_matches",
        "matrix_summary_expected_artifact_paths_match",
        "matrix_summary_resolved_paths_match_expected",
    )
    assert failure_matrix_summary_names.true_check_names() == (
        "metadata_matrix_summary_matches_all_review",
        "matrix_summary_path_matches_all_review",
        "matrix_summary_path_matches_metadata",
        "matrix_summary_line_matches_metadata_path",
        "bundle_rerun_hint_line_matches_matrix_summary_hint",
    )
    selected_assertions = failure_naming.matrix_summary_assertion_selection(
        "metadata_expected_path",
        "matrix_summary_matches_metadata",
    )
    assert failure_naming.matrix_summary_assertion_result_name_kwargs(
        "metadata_expected_path",
        "matrix_summary_matches_metadata",
    ) == selected_assertions.result_name_kwargs() == {
        "metadata_expected_path_result_name": "metadata_matrix_summary_matches_all_review",
        "matrix_summary_matches_metadata_result_name": "matrix_summary_path_matches_metadata",
    }
    assert selected_assertions.contract_metadata().true_check_names == (
        "metadata_matrix_summary_matches_all_review",
        "matrix_summary_path_matches_metadata",
    )
    bundle_assertions = failure_naming.matrix_summary_assertion_bundle_selection(
        "all_review_missing_api_key_failure"
    )
    assert failure_naming.matrix_summary_assertion_result_name_bundle_kwargs(
        "all_review_missing_api_key_failure"
    ) == bundle_assertions.result_name_kwargs() == {
        "metadata_expected_path_result_name": "metadata_matrix_summary_matches_all_review",
        "matrix_summary_matches_metadata_result_name": "matrix_summary_path_matches_metadata",
        "matrix_summary_line_matches_metadata_result_name": "matrix_summary_line_matches_metadata_path",
        "bundle_rerun_hint_result_name": "bundle_rerun_hint_line_matches_matrix_summary_hint",
    }
    assert failure_matrix_summary_names.bundle_true_check_names("docs_review_hint_failure") == (
        "metadata_matrix_summary_matches_all_review",
        "matrix_summary_path_matches_all_review",
        "bundle_rerun_hint_line_matches_matrix_summary_hint",
    )
    assert success_names.matrix_summary_assertion_selection(
        "metadata_expected_path",
        "bundle_rerun_hint_matches_matrix_summary_hint",
    ).true_check_names() == (
        "all_review_metadata_matrix_summary_matches_expected_path",
        "all_review_rerun_hint_line_matches_expected_hint",
    )
    assert success_names.required_line_prefixes(
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    ) == (
        "all_review_artifact_root: ",
        f"all_review_metadata_line: {SMOKE_MATRIX_REVIEW_METADATA_PREFIX}",
        f"all_review_artifacts_line: {SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX}",
        f"all_review_matrix_summary_line: {SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX}",
        (
            "all_review_summary_line: "
            f"{SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.success_summary_prefix}"
        ),
        (
            "all_review_rerun_hint_line: "
            f"{SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.rerun_hint_prefix}"
        ),
    )
    assert success_names.summary_targets == "all_review_summary_targets_docs_review_all"
    assert success_names.summary_path_keeps_artifact_root == "all_review_summary_path_keeps_all_review_root"
    assert success_names.matrix_summary_assertion_result_names().true_check_names() == (
        "all_review_metadata_matrix_summary_matches_expected_path",
        "all_review_matrix_summary_line_matches_expected_path",
        "all_review_matrix_summary_path_matches_metadata",
        "all_review_matrix_summary_line_matches_metadata_path",
        "all_review_rerun_hint_line_matches_expected_hint",
    )
    assert success_names.true_check_names()[-3:] == (
        "all_review_summary_path_keeps_all_review_root",
        "all_review_summary_line_present",
        "all_review_rerun_hint_line_present",
    )



def test_build_review_artifact_observation_results_support_shared_review_checks(tmp_path: Path) -> None:
    fixture = build_smoke_matrix_docs_review_observation_fixture(
        tmp_path / "checkout",
        requested_target_name="all-review",
    )
    review_output = fixture.review_output
    review_spec = fixture.review_spec
    result_names = review_spec.result_naming.observation_result_names(
        result_prefix="",
        line_detail_prefix="stderr_",
    )

    result_map = dict(
        build_review_artifact_observation_results(
            review_output,
            review_spec,
            line_detail_prefix="stderr_",
        )
    )

    assert result_map[result_names.metadata_line] == review_output.metadata_line
    assert result_map[result_names.artifacts_line] == review_output.artifacts_line
    assert result_map[result_names.matrix_summary_line] == review_output.matrix_summary_line
    for check_name in result_names.true_check_names():
        assert result_map[check_name] is True



def test_build_review_artifact_failure_results_reuses_shared_review_checks(tmp_path: Path) -> None:
    fixture = build_smoke_matrix_docs_review_observation_fixture(
        tmp_path / "checkout",
        requested_target_name="all-review",
    )
    review_output = fixture.review_output
    review_spec = fixture.review_spec

    result_map = dict(
        build_review_artifact_failure_results(
            review_output,
            review_spec,
            **review_spec.failure_result_kwargs(),
        )
    )
    shared_result_map = dict(
        build_review_artifact_observation_results(
            review_output,
            review_spec,
            line_detail_prefix="stderr_",
        )
    )

    assert result_map == shared_result_map



def test_matrix_summary_assertion_result_names_bundle_contract_metadata_supports_excluding_common_checks() -> None:
    result_names = build_smoke_matrix_docs_review_result_naming(
        "all-review",
        result_prefix="",
    ).matrix_summary_assertion_result_names(result_prefix="")

    common_selection = result_names.selected_selection("metadata_expected_path")
    common_contract = common_selection.contract_metadata()
    assert common_contract.required_line_prefixes == ()
    assert common_contract.true_check_names == (result_names.metadata_expected_path,)
    assert common_selection.result_name_kwargs() == {
        "metadata_expected_path_result_name": result_names.metadata_expected_path,
    }

    bundle_selection = result_names.bundle_selection(
        "all_review_missing_api_key_failure",
        excluding_checks=("metadata_expected_path",),
    )
    bundle_contract = bundle_selection.contract_metadata()
    assert bundle_contract.required_line_prefixes == ()
    assert bundle_contract.true_check_names == (
        result_names.matrix_summary_matches_metadata,
        result_names.matrix_summary_line_matches_metadata_path,
        result_names.bundle_rerun_hint_matches_matrix_summary_hint,
    )
    assert bundle_selection.result_name_kwargs() == {
        "matrix_summary_matches_metadata_result_name": result_names.matrix_summary_matches_metadata,
        "matrix_summary_line_matches_metadata_result_name": (
            result_names.matrix_summary_line_matches_metadata_path
        ),
        "bundle_rerun_hint_result_name": result_names.bundle_rerun_hint_matches_matrix_summary_hint,
    }



def test_build_review_artifact_matrix_summary_assertion_results_support_expected_path_and_hint_checks(
    tmp_path: Path,
) -> None:
    fixture = build_smoke_matrix_docs_review_observation_fixture(
        tmp_path / "checkout",
        requested_target_name="all-review",
    )
    review_output = fixture.review_output
    review_spec = fixture.review_spec
    result_names = review_spec.result_naming.matrix_summary_assertion_result_names(result_prefix="")
    selected_assertions = review_spec.result_naming.matrix_summary_assertion_selection(
        "metadata_expected_path",
        "matrix_summary_expected_path",
        "matrix_summary_matches_metadata",
        "matrix_summary_line_matches_metadata_path",
        "bundle_rerun_hint_matches_matrix_summary_hint",
        result_prefix="",
    )

    result_map = dict(
        build_review_artifact_matrix_summary_assertion_results(
            review_output,
            review_spec,
            **selected_assertions.result_name_kwargs(),
            bundle_rerun_hint_line=(
                SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS.format_bundle_rerun_hint_line(
                    review_spec.expected_bundle_index_rerun_hint
                )
            ),
            bundle_rerun_hint_defaults=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS,
        )
    )

    assert result_map == {
        result_names.metadata_expected_path: True,
        result_names.matrix_summary_expected_path: True,
        result_names.matrix_summary_matches_metadata: True,
        result_names.matrix_summary_line_matches_metadata_path: True,
        result_names.bundle_rerun_hint_matches_matrix_summary_hint: True,
    }



def test_build_review_artifact_matrix_summary_assertion_results_rejects_missing_bundle_rerun_hint_defaults(
    tmp_path: Path,
) -> None:
    fixture = build_smoke_matrix_docs_review_observation_fixture(
        tmp_path / "checkout",
        requested_target_name="all-review",
    )

    with pytest.raises(ValueError, match="bundle_rerun_hint_line and a bundle_rerun_hint prefix/defaults"):
        build_review_artifact_matrix_summary_assertion_results(
            fixture.review_output,
            fixture.review_spec,
            bundle_rerun_hint_result_name="bundle_rerun_hint_matches_matrix_summary_hint",
        )



def test_build_review_artifact_success_results_supports_prefixed_contract_output(tmp_path: Path) -> None:
    fixture = build_smoke_matrix_docs_review_observation_fixture(
        tmp_path / "checkout",
        requested_target_name="review",
    )
    review_output = fixture.review_output
    review_spec = fixture.review_spec
    artifact_root = fixture.summary_path.parent
    result_names = review_spec.result_naming.success_result_names(result_prefix="review")

    success_summary_line = SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_success_summary_line(
        0.1
    )
    rerun_hint_line = SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_line(
        review_spec.expected_bundle_index_rerun_hint
    )
    result_map = dict(
        build_review_artifact_success_results(
            review_output,
            review_spec,
            **review_spec.success_result_kwargs(),
            success_summary_line=success_summary_line,
            rerun_hint_line=rerun_hint_line,
            success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
            exit_code=0,
            stderr_text="",
            artifacts_exist=True,
        )
    )
    shared_result_map = dict(
        build_review_artifact_observation_results(
            review_output,
            review_spec,
            result_prefix="review",
        )
    )

    for name, value in shared_result_map.items():
        assert result_map[name] == value
    assert result_map[result_names.artifact_root] == str(artifact_root)
    assert result_map[result_names.metadata_line] == review_output.metadata_line
    assert result_map[result_names.artifacts_line] == review_output.artifacts_line
    assert result_map[result_names.matrix_summary_line] == review_output.matrix_summary_line
    assert result_map[result_names.summary_line] == success_summary_line
    assert result_map[result_names.rerun_hint_line] == rerun_hint_line
    assert result_map[result_names.exit_code_zero] is True
    assert result_map[result_names.stderr_empty] is True
    for check_name in result_names.true_check_names():
        assert result_map[check_name] is True
    assert result_map[result_names.metadata_matrix_summary_matches_expected_path] is True
    assert result_map[result_names.matrix_summary_line_matches_expected_path] is True
    assert result_map[result_names.rerun_hint_line_matches_expected_hint] is True
    assert result_map[result_names.paths_loaded_from_matrix_summary] is True
    assert result_map[result_names.artifacts_exist] is True
    assert result_map[result_names.matrix_summary_path_matches_metadata] is True
    assert result_map[result_names.matrix_summary_line_matches_metadata_path] is True
    assert result_map[result_names.loaded_summary_path_matches_line] is True
    assert result_map[result_names.summary_path_keeps_artifact_root] is True
    assert result_map[result_names.summary_line_present] is True
    assert result_map[result_names.rerun_hint_line_present] is True


def test_run_script_module_main_in_temp_checkout_changes_cwd_and_unsets_env(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "temp_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path
import os


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    print(f"keep={os.environ.get('HARNESS_KEEP', '<missing>')}")
    print(f"clear={os.environ.get('HARNESS_CLEAR', '<missing>')}")
    return 3
""".strip()
        + "\n",
    )
    monkeypatch.setenv("HARNESS_KEEP", "present")
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    result = run_script_module_main_in_temp_checkout(
        script_path=script_path,
        module_name="tests.temp_target",
        argv=["all-review"],
        temp_prefix="harness-module-run-",
        unset_env_names=("HARNESS_CLEAR",),
    )
    try:
        assert result.exit_code == 3
        assert result.stderr == ""
        assert result.checkout_root.name.startswith("harness-module-run-")
        assert result.stdout_lines == [
            f"cwd_name={result.checkout_root.name}",
            "argv=['all-review']",
            "keep=present",
            "clear=<missing>",
        ]
        assert os.environ["HARNESS_KEEP"] == "present"
        assert os.environ["HARNESS_CLEAR"] == "remove-me"
    finally:
        result.cleanup()


def test_run_loaded_script_module_main_reuses_checkout_without_cleanup(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "loaded_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path
import os


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    print(f"keep={os.environ.get('HARNESS_KEEP', '<missing>')}")
    print(f"clear={os.environ.get('HARNESS_CLEAR', '<missing>')}")
    return 5
""".strip()
        + "\n",
    )
    checkout_root = tmp_path / "loaded-checkout"
    checkout_root.mkdir()
    monkeypatch.setenv("HARNESS_KEEP", "present")
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    result = run_loaded_script_module_main(
        load_script_module(script_path, "tests.loaded_target"),
        argv=["review"],
        checkout_root=checkout_root,
        unset_env_names=("HARNESS_CLEAR",),
    )

    assert result.exit_code == 5
    assert result.stderr == ""
    assert result.checkout_root == checkout_root
    assert result.stdout_lines == [
        "cwd_name=loaded-checkout",
        "argv=['review']",
        "keep=present",
        "clear=<missing>",
    ]
    result.cleanup()
    assert checkout_root.exists()
    assert os.environ["HARNESS_KEEP"] == "present"
    assert os.environ["HARNESS_CLEAR"] == "remove-me"


def test_observe_loaded_review_artifact_output_reuses_loaded_module_and_shared_checkout(tmp_path: Path) -> None:
    script_path = tmp_path / "review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    args = list(argv or [])
    target_name = args[0] if args else 'review'
    stream_name = args[1] if len(args) > 1 else 'stdout'
    stream = getattr(sys, stream_name)
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    bundle_index_path = artifact_root / 'index.json'
    bundle_index_path.write_text(json.dumps({'target_name': target_name}, sort_keys=True) + '\\n', encoding='utf-8')
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'bundle_index_path': bundle_index_path.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=stream)
    print(f"[matrix] artifacts: {artifact_root.as_posix()}", file=stream)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=stream)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.review_target")
    checkout_root = tmp_path / "shared-checkout"
    checkout_root.mkdir()

    review_run, review_output = observe_loaded_review_artifact_output(
        module,
        argv=["review"],
        checkout_root=checkout_root,
        metadata_prefix="[matrix] metadata: ",
        artifacts_prefix="[matrix] artifacts: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
    )
    all_review_run, all_review_output = observe_loaded_review_artifact_output(
        module,
        argv=["all-review"],
        checkout_root=checkout_root,
        metadata_prefix="[matrix] metadata: ",
        artifacts_prefix="[matrix] artifacts: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
    )

    assert review_run.exit_code == 0
    assert all_review_run.exit_code == 0
    assert review_run.checkout_root == checkout_root
    assert all_review_run.checkout_root == checkout_root
    assert review_output.metadata_targets("review") is True
    assert all_review_output.metadata_targets("all-review") is True
    assert review_output.matrix_summary_artifact_exists is True
    assert all_review_output.matrix_summary_artifact_exists is True
    assert review_output.matrix_summary_path_matches_metadata() is True
    assert all_review_output.matrix_summary_path_matches_metadata() is True
    assert review_output.matrix_summary_path != all_review_output.matrix_summary_path
    assert (checkout_root / "artifacts" / "review" / "matrix-summary.json").exists()
    assert (checkout_root / "artifacts" / "all-review" / "matrix-summary.json").exists()


def test_run_loaded_script_module_main_in_temp_checkout_creates_cleanup_root(tmp_path: Path) -> None:
    script_path = tmp_path / "loaded_temp_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    return 7
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.loaded_temp_target")

    result = run_loaded_script_module_main_in_temp_checkout(
        module,
        argv=["docs-review"],
        temp_prefix="loaded-temp-checkout-",
    )

    assert result.exit_code == 7
    assert result.checkout_root.name.startswith("loaded-temp-checkout-")
    assert result.stdout_lines == [
        f"cwd_name={result.checkout_root.name}",
        "argv=['docs-review']",
    ]
    assert result.checkout_root.exists()
    result.cleanup()
    assert not result.checkout_root.exists()


def test_observe_loaded_review_artifact_output_supports_stderr_stream(tmp_path: Path) -> None:
    script_path = tmp_path / "stderr_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'stderr-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.stderr_review_target")
    checkout_root = tmp_path / "stderr-checkout"
    checkout_root.mkdir()

    smoke_run, review_output = observe_loaded_review_artifact_output(
        module,
        argv=["review"],
        checkout_root=checkout_root,
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )

    assert smoke_run.exit_code == 0
    assert smoke_run.stdout == ""
    assert review_output.metadata_targets("stderr-review") is True
    assert review_output.matrix_summary_targets("stderr-review") is True
    assert review_output.matrix_summary_artifact_exists is True


def test_observe_loaded_review_artifact_output_in_temp_checkout_supports_stderr_stream(tmp_path: Path) -> None:
    script_path = tmp_path / "stderr_temp_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'stderr-temp-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.stderr_temp_review_target")

    smoke_run, review_output = observe_loaded_review_artifact_output_in_temp_checkout(
        module,
        argv=["review"],
        temp_prefix="stderr-temp-review-",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert smoke_run.exit_code == 0
        assert smoke_run.stdout == ""
        assert review_output.metadata_targets("stderr-temp-review") is True
        assert review_output.matrix_summary_targets("stderr-temp-review") is True
        assert review_output.matrix_summary_artifact_exists is True
        assert smoke_run.checkout_root.exists()
    finally:
        smoke_run.cleanup()
    assert not smoke_run.checkout_root.exists()


def test_observe_subprocess_review_artifact_output_supports_stderr_stream(tmp_path: Path) -> None:
    script_path = tmp_path / "stderr_subprocess_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'stderr-subprocess-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    driver_source = build_script_driver_source(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.stderr_subprocess_review_target",
        argv=["review"],
    )

    smoke_run, review_output = observe_subprocess_review_artifact_output(
        driver_source=driver_source,
        temp_prefix="harness-driver-review-",
        driver_filename="run_stderr_subprocess_review_target.py",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert smoke_run.exit_code == 0
        assert smoke_run.stdout == ""
        assert review_output.metadata_targets("stderr-subprocess-review") is True
        assert review_output.matrix_summary_targets("stderr-subprocess-review") is True
        assert review_output.matrix_summary_artifact_exists is True
    finally:
        smoke_run.cleanup()


def test_observe_review_artifact_output_in_temp_checkout_supports_loaded_and_subprocess_sources(
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "generic_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'generic-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.generic_review_target")

    loaded_run, loaded_output = observe_review_artifact_output_in_temp_checkout(
        module=module,
        argv=["review"],
        temp_prefix="generic-loaded-review-",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert loaded_run.exit_code == 0
        assert loaded_output.metadata_targets("generic-review") is True
        assert loaded_output.matrix_summary_targets("generic-review") is True
    finally:
        loaded_run.cleanup()

    driver_source = build_script_driver_source(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.generic_review_driver_target",
        argv=["review"],
    )
    subprocess_run, subprocess_output = observe_review_artifact_output_in_temp_checkout(
        driver_source=driver_source,
        temp_prefix="generic-subprocess-review-",
        driver_filename="run_generic_review_target.py",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert subprocess_run.exit_code == 0
        assert subprocess_output.metadata_targets("generic-review") is True
        assert subprocess_output.matrix_summary_targets("generic-review") is True
    finally:
        subprocess_run.cleanup()


def test_observe_review_artifact_output_in_temp_checkout_validates_source_contract() -> None:
    with pytest.raises(ValueError, match="provide exactly one review artifact source: module or driver_source"):
        observe_review_artifact_output_in_temp_checkout(
            temp_prefix="missing-review-source-",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )

    with pytest.raises(ValueError, match="provide exactly one review artifact source: module or driver_source"):
        observe_review_artifact_output_in_temp_checkout(
            module=object(),
            driver_source="raise SystemExit(0)\n",
            argv=["review"],
            temp_prefix="duplicate-review-source-",
            driver_filename="run_duplicate_review_source.py",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )

    with pytest.raises(ValueError, match="argv is required when observing a loaded review artifact module"):
        observe_review_artifact_output_in_temp_checkout(
            module=object(),
            temp_prefix="missing-review-argv-",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )

    with pytest.raises(ValueError, match="driver_filename is required when driver_source is provided"):
        observe_review_artifact_output_in_temp_checkout(
            driver_source="raise SystemExit(0)\n",
            temp_prefix="missing-review-driver-filename-",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )


@pytest.mark.parametrize(
    "observer",
    (
        lambda tmp_path: observe_loaded_review_artifact_output(
            object(),
            argv=["review"],
            checkout_root=tmp_path,
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_loaded_review_artifact_output_in_temp_checkout(
            object(),
            argv=["review"],
            temp_prefix="harness-invalid-temp-output-stream-",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_review_artifact_output_in_temp_checkout(
            module=object(),
            argv=["review"],
            temp_prefix="harness-invalid-generic-temp-output-stream-",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_subprocess_review_artifact_output(
            driver_source="raise SystemExit(0)\n",
            temp_prefix="harness-invalid-output-stream-",
            driver_filename="run_invalid_output_stream.py",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_review_artifact_output_in_temp_checkout(
            driver_source="raise SystemExit(0)\n",
            temp_prefix="harness-invalid-generic-driver-output-stream-",
            driver_filename="run_invalid_generic_output_stream.py",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
    ),
)
def test_review_artifact_observers_reject_invalid_output_stream(
    tmp_path: Path,
    observer,
) -> None:
    with pytest.raises(ValueError, match="output_stream must be 'stdout' or 'stderr', got 'invalid'"):
        observer(tmp_path)


def test_build_script_driver_source_and_run_python_driver_in_temp_checkout(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "driver_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path
import os

VALUE = 'script'


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    print(f"value={VALUE}")
    print(f"set={os.environ.get('HARNESS_SET', '<missing>')}")
    print(f"clear={os.environ.get('HARNESS_CLEAR', '<missing>')}")
    return 4
""".strip()
        + "\n",
    )
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    driver_source = build_script_driver_source(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.driver_target",
        argv=["docs-focused"],
        env_assignments={"HARNESS_SET": "enabled"},
        env_unsets=("HARNESS_CLEAR",),
        hook_source="module.VALUE = 'hooked'",
    )

    result = run_python_driver_in_temp_checkout(
        driver_source=driver_source,
        temp_prefix="harness-driver-run-",
        driver_filename="run_driver_target.py",
    )
    try:
        assert result.exit_code == 4
        assert result.stderr == ""
        assert result.checkout_root.name.startswith("harness-driver-run-")
        assert result.stdout_lines == [
            f"cwd_name={result.checkout_root.name}",
            "argv=['docs-focused']",
            "value=hooked",
            "set=enabled",
            "clear=<missing>",
        ]
        assert os.environ["HARNESS_CLEAR"] == "remove-me"
    finally:
        result.cleanup()



def test_run_script_module_main_via_driver_in_temp_checkout(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "driver_wrapper_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path
import os

VALUE = 'script'


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    print(f"value={VALUE}")
    print(f"set={os.environ.get('HARNESS_SET', '<missing>')}")
    print(f"clear={os.environ.get('HARNESS_CLEAR', '<missing>')}")
    return 6
""".strip()
        + "\n",
    )
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    result = run_script_module_main_via_driver_in_temp_checkout(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.driver_wrapper_target",
        argv=["docs-review-only"],
        temp_prefix="harness-driver-wrapper-run-",
        driver_filename="run_driver_wrapper_target.py",
        env_assignments={"HARNESS_SET": "enabled"},
        env_unsets=("HARNESS_CLEAR",),
        hook_source="module.VALUE = 'hooked'",
    )
    try:
        assert result.exit_code == 6
        assert result.stderr == ""
        assert result.checkout_root.name.startswith("harness-driver-wrapper-run-")
        assert result.stdout_lines == [
            f"cwd_name={result.checkout_root.name}",
            "argv=['docs-review-only']",
            "value=hooked",
            "set=enabled",
            "clear=<missing>",
        ]
        assert os.environ["HARNESS_CLEAR"] == "remove-me"
    finally:
        result.cleanup()



def test_observe_script_module_main_via_driver_review_artifact_output(tmp_path: Path) -> None:
    script_path = tmp_path / "driver_wrapper_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'driver-wrapper-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )

    smoke_run, review_output = observe_script_module_main_via_driver_review_artifact_output(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.driver_wrapper_review_target",
        argv=["review"],
        temp_prefix="harness-driver-wrapper-review-",
        driver_filename="run_driver_wrapper_review_target.py",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert smoke_run.exit_code == 0
        assert smoke_run.stdout == ""
        assert review_output.metadata_targets("driver-wrapper-review") is True
        assert review_output.matrix_summary_targets("driver-wrapper-review") is True
        assert review_output.matrix_summary_artifact_exists is True
    finally:
        smoke_run.cleanup()



def test_build_smoke_matrix_docs_review_observer_spec_uses_smoke_matrix_target_metadata() -> None:
    smoke_matrix_module = load_script_module(
        Path(__file__).resolve().parent.parent / "scripts" / "smoke_matrix.py",
        "tests.smoke_matrix_docs_review_observer_spec_target",
    )

    review_spec = build_smoke_matrix_docs_review_observer_spec(
        smoke_matrix_module,
        requested_target_name="review",
        driver_stem="smoke_matrix_docs_review_hint",
    )
    all_review_spec = build_smoke_matrix_docs_review_observer_spec(
        smoke_matrix_module,
        requested_target_name="all-review",
        driver_stem="run_smoke_matrix_all_review_missing_api_key.py",
    )

    assert review_spec.requested_target_name == "review"
    assert review_spec.expected_target_name == smoke_matrix_module.DOCS_REVIEW_TARGET_NAME
    assert review_spec.expected_artifact_root == "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review"
    assert review_spec.expected_matrix_summary_path == (
        "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/matrix-summary.json"
    )
    assert review_spec.expected_bundle_index_rerun_hint == smoke_cli_docs_parity_rerun_hint()
    assert review_spec.expected_path("artifact_root") == review_spec.expected_artifact_root
    assert review_spec.expected_path("matrix_summary_path") == review_spec.expected_matrix_summary_path
    assert review_spec.expected_path("bundle_index_path") == (
        "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/index.json"
    )
    assert review_spec.driver_filename == "run_smoke_matrix_docs_review_hint.py"
    assert review_spec.observer_kwargs() == {
        "metadata_prefix": SMOKE_MATRIX_REVIEW_METADATA_PREFIX,
        "artifacts_prefix": SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX,
        "matrix_summary_prefix": SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX,
    }
    assert review_spec.result_naming.result_prefix == "review"
    assert review_spec.result_naming.target_suffix == "docs_review"
    assert review_spec.result_naming.artifact_suffix == "review"
    assert review_spec.success_result_kwargs() == {
        "result_prefix": "review",
    }

    assert all_review_spec.requested_target_name == "all-review"
    assert all_review_spec.expected_target_name == smoke_matrix_module.DOCS_REVIEW_ALL_TARGET_NAME
    assert all_review_spec.expected_artifact_root == (
        "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
    )
    assert all_review_spec.expected_matrix_summary_path == (
        "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/matrix-summary.json"
    )
    assert all_review_spec.expected_bundle_index_rerun_hint == smoke_cli_docs_parity_rerun_hint()
    assert all_review_spec.expected_path("artifact_root") == all_review_spec.expected_artifact_root
    assert all_review_spec.expected_path("matrix_summary_path") == all_review_spec.expected_matrix_summary_path
    assert all_review_spec.driver_filename == "run_smoke_matrix_all_review_missing_api_key.py"
    assert all_review_spec.result_naming.result_prefix == "all_review"
    assert all_review_spec.result_naming.target_suffix == "docs_review_all"
    assert all_review_spec.result_naming.artifact_suffix == "all_review"
    assert all_review_spec.failure_result_kwargs() == {
        "detail_prefix": "stderr_",
        "result_prefix": "",
    }


def test_smoke_matrix_docs_review_observer_spec_resolves_expected_paths_from_checkout_root(
    tmp_path: Path,
) -> None:
    smoke_matrix_module = load_script_module(
        Path(__file__).resolve().parent.parent / "scripts" / "smoke_matrix.py",
        "tests.smoke_matrix_docs_review_observer_spec_paths",
    )

    review_spec = build_smoke_matrix_docs_review_observer_spec(
        smoke_matrix_module,
        requested_target_name="review",
        driver_stem="smoke_matrix_docs_review_hint",
    )

    resolved_paths = review_spec.resolve_expected_paths(checkout_root=tmp_path)

    assert resolved_paths["artifact_root"] == (
        tmp_path / "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review"
    )
    assert resolved_paths["matrix_summary_path"] == (
        tmp_path / "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/matrix-summary.json"
    )
    assert resolved_paths["bundle_index_path"] == (
        tmp_path / "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/index.json"
    )



def test_build_smoke_matrix_docs_review_observer_spec_rejects_non_docs_review_targets() -> None:
    smoke_matrix_module = load_script_module(
        Path(__file__).resolve().parent.parent / "scripts" / "smoke_matrix.py",
        "tests.smoke_matrix_docs_review_observer_spec_invalid_target",
    )

    with pytest.raises(
        ValueError,
        match="requested_target_name must resolve to exactly one docs-review smoke-matrix target",
    ):
        build_smoke_matrix_docs_review_observer_spec(
            smoke_matrix_module,
            requested_target_name="all",
            driver_stem="smoke_matrix_docs_review_hint",
        )


def test_exported_smoke_script_contract_cases_include_artifact_roots_contract() -> None:
    assert STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT.script_name == "standalone_docs_rerun_hint_smoke"
    assert STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT.runner_name == "run_standalone_docs_rerun_hint_smoke"
    assert [case.script_name for case in DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS] == [
        "smoke_matrix_all_review_order_smoke",
        "smoke_matrix_all_review_missing_api_key_smoke",
        "smoke_matrix_docs_review_hint_smoke",
    ]
    assert [case.runner_name for case in DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS] == [
        "run_smoke_matrix_all_review_order_smoke",
        "run_smoke_matrix_all_review_missing_api_key_smoke",
        "run_smoke_matrix_docs_review_hint_smoke",
    ]
    assert [case.script_name for case in SMOKE_SCRIPT_CONTRACT_CASES] == [
        "standalone_docs_rerun_hint_smoke",
        "smoke_matrix_all_review_order_smoke",
        "smoke_matrix_all_review_missing_api_key_smoke",
        "smoke_matrix_docs_review_hint_smoke",
        "smoke_matrix_artifact_roots_smoke",
        "session_triage_intervention_mix_smoke",
        "smoke_script_malformed_result_smoke",
        "smoke_script_malformed_detail_smoke",
    ]
    assert SMOKE_SCRIPT_CONTRACT_CASES[-4] == SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT
    assert SMOKE_SCRIPT_CONTRACT_CASES[-3] == SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT
    assert SMOKE_SCRIPT_CONTRACT_CASES[-2] == SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT
    assert SMOKE_SCRIPT_CONTRACT_CASES[-1] == SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT.script_name == "smoke_matrix_artifact_roots_smoke"
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT.runner_name == "run_smoke_matrix_artifact_roots_smoke"
    assert SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT.contract == SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT
    assert "checkout_root: " in SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT.required_line_prefixes
    assert "review_artifact_root: " in SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT.required_line_prefixes
    assert "all_review_artifact_root: " in SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT.required_line_prefixes
    assert "artifact_roots_distinct" in SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT.true_check_names
    assert "review_summary_preserved_after_all_review" in SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT.true_check_names
    assert SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT.script_name == "session_triage_intervention_mix_smoke"
    assert SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT.runner_name == "run_session_triage_intervention_mix_smoke"
    assert SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT.contract == SESSION_TRIAGE_INTERVENTION_MIX_CONTRACT
    assert "stdout_picker_target_mix_line: picker_intervention_target_mix= True" in SESSION_TRIAGE_INTERVENTION_MIX_CONTRACT.required_line_prefixes
    assert "stdout_switcher_continuation_mix_line: switcher_intervention_continuation_mix= True" in SESSION_TRIAGE_INTERVENTION_MIX_CONTRACT.required_line_prefixes
    assert "summary_after_switcher_continuation_mix" in SESSION_TRIAGE_INTERVENTION_MIX_CONTRACT.true_check_names
    assert SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT.script_name == "smoke_script_malformed_result_smoke"
    assert SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT.runner_name == "run_smoke_script_malformed_result_smoke"
    assert "assertion_message: result[" in SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT.required_line_prefixes
    assert "malformed_result_reported" in SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT.true_check_names
    assert SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT.script_name == "smoke_script_malformed_detail_smoke"
    assert SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT.runner_name == "run_smoke_script_malformed_detail_smoke"
    assert "missing_detail_assertion: stdout_fix_check_summary" in SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT.required_line_prefixes
    assert "boolean_detail_reported" in SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT.true_check_names


def test_shared_smoke_script_contract_assertion_helpers_accept_exported_artifact_roots_contract() -> None:
    assert_smoke_script_output_matches_contract(
        _matching_contract_output_lines(SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT),
        SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
    )
    assert_smoke_script_output_matches_contract(
        _matching_contract_output_lines(SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT),
        SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    )

    assert_smoke_script_results_match_contract(
        _matching_contract_results(SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT),
        SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
    )
    assert_smoke_script_results_match_contract(
        _matching_contract_results(SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT),
        SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    )


@pytest.mark.parametrize(
    "case",
    (
        STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
        SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
        SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    ),
    ids=lambda case: case.script_name,
)
def test_assert_smoke_script_output_matches_contract_reports_offending_prefix_and_check(
    case: SmokeScriptContractCase,
) -> None:
    output_lines = _matching_contract_output_lines(case)
    missing_prefix = case.required_line_prefixes[0]
    output_without_prefix = [
        line for line in output_lines if not line.startswith(missing_prefix)
    ]

    with pytest.raises(AssertionError) as missing_prefix_error:
        assert_smoke_script_output_matches_contract(output_without_prefix, case)
    assert missing_prefix_error.value.args == (missing_prefix,)

    missing_check_name = case.true_check_names[0]
    output_without_check = [
        line for line in output_lines if line != f"{missing_check_name}= True"
    ]

    with pytest.raises(AssertionError) as missing_check_error:
        assert_smoke_script_output_matches_contract(output_without_check, case)
    assert missing_check_error.value.args == (missing_check_name,)


@pytest.mark.parametrize(
    "case",
    (
        STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
        SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
        SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    ),
    ids=lambda case: case.script_name,
)
def test_assert_smoke_script_results_match_contract_reports_offending_prefix_and_check(
    case: SmokeScriptContractCase,
) -> None:
    results = _matching_contract_results(case)
    missing_detail_name, expected_detail_prefix = _required_contract_detail_with_value_prefix(case)
    results_without_detail = [
        (name, value) for name, value in results if name != missing_detail_name
    ]

    with pytest.raises(AssertionError) as missing_detail_error:
        assert_smoke_script_results_match_contract(results_without_detail, case)
    assert missing_detail_error.value.args == (missing_detail_name,)

    results_with_mismatched_detail_prefix = [
        (
            name,
            f"unexpected-{expected_detail_prefix}fixture"
            if name == missing_detail_name
            else value,
        )
        for name, value in results
    ]

    with pytest.raises(AssertionError) as mismatched_detail_prefix_error:
        assert_smoke_script_results_match_contract(results_with_mismatched_detail_prefix, case)
    assert mismatched_detail_prefix_error.value.args == (missing_detail_name,)

    results_with_boolean_detail = [
        (name, True if name == missing_detail_name else value)
        for name, value in results
    ]

    with pytest.raises(AssertionError) as boolean_detail_error:
        assert_smoke_script_results_match_contract(results_with_boolean_detail, case)
    assert boolean_detail_error.value.args == (missing_detail_name,)

    missing_check_name = case.true_check_names[0]
    results_with_false_check = [
        (name, False if name == missing_check_name else value)
        for name, value in results
    ]

    with pytest.raises(AssertionError) as missing_check_error:
        assert_smoke_script_results_match_contract(results_with_false_check, case)
    assert missing_check_error.value.args == (missing_check_name,)


@pytest.mark.parametrize(
    "case",
    (
        STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
        SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
        SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    ),
    ids=lambda case: case.script_name,
)
def test_assert_smoke_script_results_match_contract_accepts_reordered_results_and_last_duplicate_repairs(
    case: SmokeScriptContractCase,
) -> None:
    results = _matching_contract_results(case)
    detail_name, expected_detail_prefix = _required_contract_detail_with_value_prefix(case)
    check_name = case.true_check_names[0]

    reordered_results = list(reversed(results))
    assert_smoke_script_results_match_contract(reordered_results, case)

    repaired_duplicate_results = [
        (
            name,
            f"unexpected-{expected_detail_prefix}fixture"
            if name == detail_name
            else (False if name == check_name else value)
        )
        for name, value in reordered_results
    ] + [
        (detail_name, f"{expected_detail_prefix}repaired"),
        (check_name, True),
    ]

    assert_smoke_script_results_match_contract(repaired_duplicate_results, case)


@pytest.mark.parametrize(
    "case",
    (
        STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
        SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
        SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    ),
    ids=lambda case: case.script_name,
)
def test_assert_smoke_script_results_match_contract_reports_final_duplicate_detail_and_check(
    case: SmokeScriptContractCase,
) -> None:
    results = _matching_contract_results(case)
    detail_name, expected_detail_prefix = _required_contract_detail_with_value_prefix(case)
    check_name = case.true_check_names[0]

    with pytest.raises(AssertionError) as final_detail_error:
        assert_smoke_script_results_match_contract(
            results + [(detail_name, f"unexpected-{expected_detail_prefix}fixture")],
            case,
        )
    assert final_detail_error.value.args == (detail_name,)

    with pytest.raises(AssertionError) as final_check_error:
        assert_smoke_script_results_match_contract(
            results + [(check_name, False)],
            case,
        )
    assert final_check_error.value.args == (check_name,)


@pytest.mark.parametrize(
    "case",
    (
        STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
        SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
        SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    ),
    ids=lambda case: case.script_name,
)
def test_assert_smoke_script_results_match_contract_rejects_malformed_non_pair_entries(
    case: SmokeScriptContractCase,
) -> None:
    results = _matching_contract_results(case)
    malformed_index = len(results)

    with pytest.raises(AssertionError) as triple_entry_error:
        assert_smoke_script_results_match_contract(
            results + [("malformed", "value", "extra")],
            case,
        )
    assert triple_entry_error.value.args == (
        f"result[{malformed_index}]: ('malformed', 'value', 'extra')",
    )

    with pytest.raises(AssertionError) as scalar_entry_error:
        assert_smoke_script_results_match_contract(
            results + [True],
            case,
        )
    assert scalar_entry_error.value.args == (f"result[{malformed_index}]: True",)


def test_build_malformed_smoke_script_result_results_replays_result_index_contract() -> None:
    source_results = _matching_contract_results(STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT)

    malformed_results = build_malformed_smoke_script_result_results(
        source_results,
        source_case=STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
        malformed_entry=("malformed", "value", "extra"),
    )

    assert_smoke_script_results_match_contract(
        malformed_results,
        SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT,
    )
    assert dict(malformed_results)["assertion_message"] == (
        f"result[{len(source_results)}]: ('malformed', 'value', 'extra')"
    )


def test_build_malformed_smoke_script_detail_results_replays_detail_contract() -> None:
    source_results = _matching_contract_results(STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT)

    malformed_results = build_malformed_smoke_script_detail_results(
        source_results,
        source_case=STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
    )

    assert_smoke_script_results_match_contract(
        malformed_results,
        SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT,
    )
    malformed_result_map = dict(malformed_results)
    assert malformed_result_map["missing_detail_assertion"] == "stdout_fix_check_summary"
    assert malformed_result_map["mismatched_detail_assertion"] == "stdout_fix_check_summary"
    assert malformed_result_map["boolean_detail_assertion"] == "stdout_fix_check_summary"
