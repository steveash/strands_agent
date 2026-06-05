from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from shutil import rmtree
from textwrap import dedent
from typing import Any, Callable, Iterator, Literal

from .smoke_cli_doc_artifacts import (
    load_review_matrix_summary,
    output_path_from_prefixed_lines,
    resolve_checkout_path,
    resolve_review_artifact_paths,
)

SMOKE_MATRIX_REVIEW_METADATA_PREFIX = "[smoke-matrix] review metadata: "
SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX = "[smoke-matrix] review artifacts: "
SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "


@dataclass(frozen=True)
class SmokeScriptRunResult:
    checkout_root: Path
    exit_code: int
    stdout: str
    stderr: str
    cleanup_callback: Callable[[], None]

    @property
    def stdout_lines(self) -> list[str]:
        return self.stdout.splitlines()

    @property
    def stderr_lines(self) -> list[str]:
        return self.stderr.splitlines()

    def cleanup(self) -> None:
        self.cleanup_callback()


@dataclass(frozen=True)
class SmokeScriptContractMetadata:
    required_line_prefixes: tuple[str, ...]
    true_check_names: tuple[str, ...]


@dataclass(frozen=True)
class SmokeScriptContractCase:
    script_name: str
    runner_name: str
    contract: SmokeScriptContractMetadata

    @property
    def required_line_prefixes(self) -> tuple[str, ...]:
        return self.contract.required_line_prefixes

    @property
    def true_check_names(self) -> tuple[str, ...]:
        return self.contract.true_check_names


@dataclass(frozen=True)
class ReviewArtifactOutputObservation:
    checkout_root: Path
    metadata_index: int | None
    artifacts_index: int | None
    matrix_summary_index: int | None
    metadata_line: str
    artifacts_line: str
    matrix_summary_line: str
    metadata_payload: dict[str, object]
    metadata_paths: dict[str, Path]
    metadata_matrix_summary_path: Path | None
    matrix_summary_path: Path | None
    matrix_summary_payload: dict[str, object]
    matrix_summary_paths: dict[str, Path]

    @property
    def metadata_line_present(self) -> bool:
        return bool(self.metadata_line)

    @property
    def artifacts_line_present(self) -> bool:
        return bool(self.artifacts_line)

    @property
    def matrix_summary_line_present(self) -> bool:
        return bool(self.matrix_summary_line)

    @property
    def matrix_summary_artifact_exists(self) -> bool:
        return self.matrix_summary_path is not None and self.matrix_summary_path.exists()

    def metadata_targets(self, target_name: str) -> bool:
        return self.metadata_payload.get("target_name") == target_name

    def metadata_artifact_root_matches(self, artifact_root: str) -> bool:
        return self.metadata_payload.get("artifact_root") == artifact_root

    def metadata_matrix_summary_matches(self, matrix_summary_path: str) -> bool:
        return self.metadata_payload.get("matrix_summary_path") == matrix_summary_path

    def metadata_bundle_index_rerun_hint_matches(self, rerun_hint: str) -> bool:
        return self.metadata_payload.get("bundle_index_rerun_hint") == rerun_hint

    def matrix_summary_targets(self, target_name: str) -> bool:
        return self.matrix_summary_payload.get("target_name") == target_name

    def matrix_summary_artifact_root_matches(self, artifact_root: str) -> bool:
        return self.matrix_summary_payload.get("artifact_root") == artifact_root

    def matrix_summary_path_matches(self, matrix_summary_path: str) -> bool:
        return self.matrix_summary_payload.get("matrix_summary_path") == matrix_summary_path

    def matrix_summary_bundle_index_rerun_hint_matches(self, rerun_hint: str) -> bool:
        return self.matrix_summary_payload.get("bundle_index_rerun_hint") == rerun_hint

    def matrix_summary_path_matches_metadata(self) -> bool:
        return self.matrix_summary_payload.get("matrix_summary_path") == self.metadata_payload.get(
            "matrix_summary_path"
        )

    def matrix_summary_line_matches_metadata_path(self) -> bool:
        return self.matrix_summary_path == self.metadata_matrix_summary_path

    def _payload_for_source(self, source: Literal["metadata", "matrix_summary"]) -> dict[str, object]:
        if source == "metadata":
            return self.metadata_payload
        return self.matrix_summary_payload

    def _paths_for_source(self, source: Literal["metadata", "matrix_summary"]) -> dict[str, Path]:
        if source == "metadata":
            return self.metadata_paths
        return self.matrix_summary_paths

    def payload_path_matches(
        self,
        source: Literal["metadata", "matrix_summary"],
        key: str,
        expected_path: str,
    ) -> bool:
        return self._payload_for_source(source).get(key) == expected_path

    def payload_paths_match(
        self,
        source: Literal["metadata", "matrix_summary"],
        expected_paths: Mapping[str, str],
    ) -> bool:
        return all(
            self.payload_path_matches(source, key, expected_path)
            for key, expected_path in expected_paths.items()
        )

    def resolved_path_matches(
        self,
        source: Literal["metadata", "matrix_summary"],
        key: str,
        expected_path: Path,
    ) -> bool:
        return self._paths_for_source(source).get(key) == expected_path

    def resolved_paths_match(
        self,
        source: Literal["metadata", "matrix_summary"],
        expected_paths: Mapping[str, Path],
    ) -> bool:
        return all(
            self.resolved_path_matches(source, key, expected_path)
            for key, expected_path in expected_paths.items()
        )


SmokeWrapperFailureStep = Literal["failed", "hint", "failure_summary"]


@dataclass(frozen=True)
class SmokeWrapperFailureObservation:
    failed_index: int | None
    hint_index: int | None
    failure_summary_index: int | None
    failed_line: str
    hint_line: str
    failure_summary_line: str

    def index(self, step: SmokeWrapperFailureStep) -> int | None:
        if step == "failed":
            return self.failed_index
        if step == "hint":
            return self.hint_index
        return self.failure_summary_index

    def line(self, step: SmokeWrapperFailureStep) -> str:
        if step == "failed":
            return self.failed_line
        if step == "hint":
            return self.hint_line
        return self.failure_summary_line

    def present(self, step: SmokeWrapperFailureStep) -> bool:
        return bool(self.line(step))

    def appears_before(self, left: SmokeWrapperFailureStep, right: SmokeWrapperFailureStep) -> bool:
        left_index = self.index(left)
        right_index = self.index(right)
        return left_index is not None and right_index is not None and left_index < right_index


SmokeMatrixDocsReviewFailureStep = Literal[
    "failed",
    "metadata",
    "artifacts",
    "matrix_summary",
    "bundle_rerun_hint",
    "docs_review_only_hint",
    "live_runtime_hint",
    "missing_api_key_hint",
    "failure_summary",
]


@dataclass(frozen=True)
class SmokeMatrixDocsReviewFailureObservation:
    review_output: ReviewArtifactOutputObservation
    failed_index: int | None
    bundle_rerun_hint_index: int | None
    docs_review_only_hint_index: int | None
    live_runtime_hint_index: int | None
    missing_api_key_hint_index: int | None
    failure_summary_index: int | None
    failed_line: str
    bundle_rerun_hint_line: str
    docs_review_only_hint_line: str
    live_runtime_hint_line: str
    missing_api_key_hint_line: str
    failure_summary_line: str

    def index(self, step: SmokeMatrixDocsReviewFailureStep) -> int | None:
        if step == "failed":
            return self.failed_index
        if step == "metadata":
            return self.review_output.metadata_index
        if step == "artifacts":
            return self.review_output.artifacts_index
        if step == "matrix_summary":
            return self.review_output.matrix_summary_index
        if step == "bundle_rerun_hint":
            return self.bundle_rerun_hint_index
        if step == "docs_review_only_hint":
            return self.docs_review_only_hint_index
        if step == "live_runtime_hint":
            return self.live_runtime_hint_index
        if step == "missing_api_key_hint":
            return self.missing_api_key_hint_index
        return self.failure_summary_index

    def line(self, step: SmokeMatrixDocsReviewFailureStep) -> str:
        if step == "failed":
            return self.failed_line
        if step == "metadata":
            return self.review_output.metadata_line
        if step == "artifacts":
            return self.review_output.artifacts_line
        if step == "matrix_summary":
            return self.review_output.matrix_summary_line
        if step == "bundle_rerun_hint":
            return self.bundle_rerun_hint_line
        if step == "docs_review_only_hint":
            return self.docs_review_only_hint_line
        if step == "live_runtime_hint":
            return self.live_runtime_hint_line
        if step == "missing_api_key_hint":
            return self.missing_api_key_hint_line
        return self.failure_summary_line

    def present(self, step: SmokeMatrixDocsReviewFailureStep) -> bool:
        return bool(self.line(step))

    def appears_before(
        self,
        left: SmokeMatrixDocsReviewFailureStep,
        right: SmokeMatrixDocsReviewFailureStep,
    ) -> bool:
        left_index = self.index(left)
        right_index = self.index(right)
        return left_index is not None and right_index is not None and left_index < right_index


@dataclass(frozen=True)
class SmokeMatrixDocsReviewObserverSpec:
    requested_target_name: str
    expected_target_name: str
    expected_artifact_root: str
    expected_matrix_summary_path: str
    expected_bundle_index_rerun_hint: str
    expected_artifact_paths: dict[str, str]
    driver_filename: str
    metadata_prefix: str = SMOKE_MATRIX_REVIEW_METADATA_PREFIX
    artifacts_prefix: str = SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX
    matrix_summary_prefix: str = SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX

    def observer_kwargs(self) -> dict[str, str]:
        return {
            "metadata_prefix": self.metadata_prefix,
            "artifacts_prefix": self.artifacts_prefix,
            "matrix_summary_prefix": self.matrix_summary_prefix,
        }

    def expected_path(self, key: str) -> str | None:
        return self.expected_artifact_paths.get(key)

    def resolve_expected_paths(self, *, checkout_root: Path) -> dict[str, Path]:
        return {
            key: resolve_checkout_path(value, checkout_root=checkout_root)
            for key, value in self.expected_artifact_paths.items()
        }

    def metadata_artifact_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.payload_paths_match("metadata", self.expected_artifact_paths)

    def matrix_summary_artifact_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.payload_paths_match("matrix_summary", self.expected_artifact_paths)

    def metadata_resolved_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.resolved_paths_match(
            "metadata",
            self.resolve_expected_paths(checkout_root=observation.checkout_root),
        )

    def matrix_summary_resolved_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.resolved_paths_match(
            "matrix_summary",
            self.resolve_expected_paths(checkout_root=observation.checkout_root),
        )

    def resolved_artifact_paths_exist(self, observation: ReviewArtifactOutputObservation) -> bool:
        return all(
            path.exists()
            for path in self.resolve_expected_paths(checkout_root=observation.checkout_root).values()
        )


def build_smoke_matrix_docs_review_observer_spec(
    smoke_matrix_module: Any,
    *,
    requested_target_name: Literal["review", "all-review"],
    driver_stem: str,
) -> SmokeMatrixDocsReviewObserverSpec:
    targets = smoke_matrix_module.CLI_SPEC.resolve_targets(
        script_dir=smoke_matrix_module.SCRIPT_DIR,
        requested_target_name=requested_target_name,
    )
    docs_review_targets = [
        target
        for target in targets
        if target.name
        in {
            smoke_matrix_module.DOCS_REVIEW_TARGET_NAME,
            smoke_matrix_module.DOCS_REVIEW_ALL_TARGET_NAME,
        }
    ]
    if len(docs_review_targets) != 1:
        raise ValueError(
            "requested_target_name must resolve to exactly one docs-review smoke-matrix target"
        )
    target = docs_review_targets[0]
    metadata = smoke_matrix_module._docs_review_artifact_metadata(target)
    if not isinstance(metadata, dict):
        raise ValueError("docs-review smoke-matrix target metadata is required")

    target_name = metadata.get("target_name")
    artifact_root = metadata.get("artifact_root")
    matrix_summary_path = metadata.get("matrix_summary_path")
    bundle_index_rerun_hint = metadata.get("bundle_index_rerun_hint")
    artifact_paths = {
        key: value
        for key, value in metadata.items()
        if key not in {"display_name", "target_name", "bundle_index_rerun_hint"}
        and isinstance(value, str)
        and value
    }

    if not isinstance(target_name, str) or not target_name:
        raise ValueError("docs-review smoke-matrix target metadata must include target_name")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise ValueError("docs-review smoke-matrix target metadata must include artifact_root")
    if not isinstance(matrix_summary_path, str) or not matrix_summary_path:
        raise ValueError("docs-review smoke-matrix target metadata must include matrix_summary_path")
    if not isinstance(bundle_index_rerun_hint, str) or not bundle_index_rerun_hint:
        raise ValueError(
            "docs-review smoke-matrix target metadata must include bundle_index_rerun_hint"
        )

    normalized_driver_stem = driver_stem.removesuffix(".py")
    if not normalized_driver_stem.startswith("run_"):
        normalized_driver_stem = f"run_{normalized_driver_stem}"
    return SmokeMatrixDocsReviewObserverSpec(
        requested_target_name=requested_target_name,
        expected_target_name=target_name,
        expected_artifact_root=artifact_root,
        expected_matrix_summary_path=matrix_summary_path,
        expected_bundle_index_rerun_hint=bundle_index_rerun_hint,
        expected_artifact_paths=artifact_paths,
        driver_filename=f"{normalized_driver_stem}.py",
    )


def find_prefixed_line_index(lines: Sequence[str], prefix: str) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


def _find_exact_line_index(lines: Sequence[str], expected_line: str) -> int | None:
    for index, line in enumerate(lines):
        if line == expected_line:
            return index
    return None


def _line_at_index(lines: Sequence[str], index: int | None) -> str:
    return lines[index] if index is not None else ""


def detail_safe_text(text: str) -> str:
    return text.replace("= False", "=False")


def merge_smoke_script_contract_metadata(
    *contracts: SmokeScriptContractMetadata,
    required_line_prefixes: Sequence[str] = (),
    true_check_names: Sequence[str] = (),
) -> SmokeScriptContractMetadata:
    merged_line_prefixes: list[str] = []
    merged_true_check_names: list[str] = []

    for contract in contracts:
        merged_line_prefixes.extend(contract.required_line_prefixes)
        merged_true_check_names.extend(contract.true_check_names)

    merged_line_prefixes.extend(required_line_prefixes)
    merged_true_check_names.extend(true_check_names)
    return SmokeScriptContractMetadata(
        required_line_prefixes=tuple(merged_line_prefixes),
        true_check_names=tuple(merged_true_check_names),
    )


STANDALONE_DOCS_RERUN_HINT_FAILED_LINE_PREFIX = "docs-artifacts smoke failed fast: "
STANDALONE_DOCS_RERUN_HINT_HINT_PREFIX = (
    "[standalone-smoke] hint: standalone wrapper docs drift is easiest to isolate with "
)
STANDALONE_DOCS_RERUN_HINT_SUMMARY_PREFIX = (
    "[standalone-smoke] summary: 5/6 targets passed before failure in "
)
STANDALONE_DOCS_RERUN_HINT_FIX_CHECK_SUMMARY_LINE = (
    "fix_check_summary: smoke README drift detected in 1 section(s) for README.md: standalone_smoke"
)
STANDALONE_DOCS_RERUN_HINT_FALSE_LINE = "fix_post_check= False"
STANDALONE_DOCS_RERUN_HINT_CONTRACT = SmokeScriptContractMetadata(
    required_line_prefixes=(
        "checkout_root: ",
        f"stdout_fix_check_summary: {STANDALONE_DOCS_RERUN_HINT_FIX_CHECK_SUMMARY_LINE}",
        f"stdout_false_line: {detail_safe_text(STANDALONE_DOCS_RERUN_HINT_FALSE_LINE)}",
        f"stderr_failed_line: {detail_safe_text(STANDALONE_DOCS_RERUN_HINT_FAILED_LINE_PREFIX + STANDALONE_DOCS_RERUN_HINT_FALSE_LINE)}",
        f"stderr_hint_line: {STANDALONE_DOCS_RERUN_HINT_HINT_PREFIX}",
        f"stderr_summary_line: {STANDALONE_DOCS_RERUN_HINT_SUMMARY_PREFIX}",
    ),
    true_check_names=(
        "exit_code_non_zero",
        "fix_check_summary_present",
        "false_line_present",
        "failed_line_present",
        "hint_line_present",
        "summary_line_present",
        "hint_after_failed_line",
        "hint_before_failure_summary",
    ),
)
STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="standalone_docs_rerun_hint_smoke",
    runner_name="run_standalone_docs_rerun_hint_smoke",
    contract=STANDALONE_DOCS_RERUN_HINT_CONTRACT,
)

_DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT = SmokeScriptContractMetadata(
    required_line_prefixes=(
        "checkout_root: ",
        'stderr_metadata_line: [smoke-matrix] review metadata: {"artifact_root": ',
        "stderr_artifacts_line: [smoke-matrix] review artifacts: ",
        "stderr_matrix_summary_line: [smoke-matrix] review matrix summary: ",
    ),
    true_check_names=(
        "exit_code_non_zero",
        "failed_line_present",
        "metadata_line_present",
        "artifacts_line_present",
        "matrix_summary_line_present",
        "summary_line_present",
        "metadata_targets_docs_review_all",
        "metadata_artifact_root_matches_all_review",
        "metadata_matrix_summary_matches_all_review",
        "metadata_bundle_index_rerun_hint_matches",
        "metadata_expected_artifact_paths_match",
        "metadata_resolved_paths_match_expected",
        "matrix_summary_artifact_exists",
        "matrix_summary_targets_docs_review_all",
        "matrix_summary_artifact_root_matches_all_review",
        "matrix_summary_bundle_index_rerun_hint_matches",
        "matrix_summary_expected_artifact_paths_match",
        "matrix_summary_resolved_paths_match_expected",
    ),
)

SMOKE_MATRIX_ALL_REVIEW_ORDER_CONTRACT = merge_smoke_script_contract_metadata(
    _DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT,
    required_line_prefixes=(
        "stderr_failed_line: standalone smoke failed fast: live_runtime_requested=False",
        "stderr_hint_line: [smoke-matrix] hint: `smoke_matrix.py all` and `smoke_matrix.py all-review` swap in `standalone_smoke.py all`;",
        "stderr_docs_hint_line: [smoke-matrix] hint: docs-review drift is easiest to isolate with `standalone_smoke.py docs-review-only`;",
        "stderr_summary_line: [smoke-matrix] summary: 0/4 bundles passed before failure in ",
    ),
    true_check_names=(
        "hint_line_present",
        "docs_hint_line_present",
        "matrix_summary_path_matches_metadata",
        "matrix_summary_line_matches_metadata_path",
        "metadata_before_hint",
        "artifacts_before_hint",
        "matrix_summary_before_hint",
        "live_hint_before_docs_hint",
        "docs_hint_before_failure_summary",
        "metadata_before_failure_summary",
        "artifacts_before_failure_summary",
        "matrix_summary_before_failure_summary",
    ),
)
SMOKE_MATRIX_ALL_REVIEW_ORDER_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_matrix_all_review_order_smoke",
    runner_name="run_smoke_matrix_all_review_order_smoke",
    contract=SMOKE_MATRIX_ALL_REVIEW_ORDER_CONTRACT,
)

SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_CONTRACT = merge_smoke_script_contract_metadata(
    _DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT,
    required_line_prefixes=(
        "stderr_failed_line: standalone smoke exited with status 1",
        "stderr_missing_api_key_hint_line: [smoke-matrix] hint: `smoke_matrix.py all`/`all-review` reached the live runtime, but `OPENAI_API_KEY` was missing;",
        "stderr_bundle_rerun_hint_line: [smoke-matrix] review bundle rerun hint: ",
        "stderr_docs_hint_line: [smoke-matrix] hint: docs-review drift is easiest to isolate with `standalone_smoke.py docs-review-only`;",
        "stderr_summary_line: [smoke-matrix] summary: 0/4 bundles passed before failure in ",
    ),
    true_check_names=(
        "missing_api_key_hint_line_present",
        "bundle_rerun_hint_line_present",
        "docs_hint_line_present",
        "matrix_summary_path_matches_metadata",
        "bundle_rerun_hint_line_matches_matrix_summary_hint",
        "matrix_summary_line_matches_metadata_path",
        "metadata_before_missing_api_key_hint",
        "artifacts_before_missing_api_key_hint",
        "matrix_summary_before_missing_api_key_hint",
        "bundle_rerun_hint_before_missing_api_key_hint",
        "bundle_rerun_hint_before_docs_hint",
        "missing_api_key_hint_before_docs_hint",
        "docs_hint_before_failure_summary",
        "metadata_before_failure_summary",
        "artifacts_before_failure_summary",
        "matrix_summary_before_failure_summary",
    ),
)
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_matrix_all_review_missing_api_key_smoke",
    runner_name="run_smoke_matrix_all_review_missing_api_key_smoke",
    contract=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_CONTRACT,
)

SMOKE_MATRIX_DOCS_REVIEW_HINT_CONTRACT = merge_smoke_script_contract_metadata(
    _DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT,
    required_line_prefixes=(
        "stdout_last_line: [smoke-matrix] running docs-review",
        "stderr_failed_line: docs-review smoke failed fast: render_manifest_payload=False",
        "stderr_bundle_rerun_hint_line: [smoke-matrix] review bundle rerun hint: ",
        "stderr_hint_line: [smoke-matrix] hint: docs-review drift is easiest to isolate with ",
        "stderr_summary_line: [smoke-matrix] summary: 3/4 bundles passed before failure in ",
    ),
    true_check_names=(
        "bundle_rerun_hint_line_present",
        "hint_line_present",
        "matrix_summary_path_matches_all_review",
        "bundle_rerun_hint_line_matches_matrix_summary_hint",
        "bundle_rerun_hint_after_matrix_summary",
        "hint_after_matrix_summary",
        "bundle_rerun_hint_before_docs_hint",
        "hint_before_failure_summary",
        "stdout_docs_review_started",
    ),
)
SMOKE_MATRIX_DOCS_REVIEW_HINT_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_matrix_docs_review_hint_smoke",
    runner_name="run_smoke_matrix_docs_review_hint_smoke",
    contract=SMOKE_MATRIX_DOCS_REVIEW_HINT_CONTRACT,
)

DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS = (
    SMOKE_MATRIX_ALL_REVIEW_ORDER_SCRIPT_CONTRACT,
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_SCRIPT_CONTRACT,
    SMOKE_MATRIX_DOCS_REVIEW_HINT_SCRIPT_CONTRACT,
)

_SMOKE_MATRIX_ARTIFACT_ROOTS_COMMON_LINE_PREFIX_SUFFIXES = (
    "artifact_root: ",
    "metadata_line: [smoke-matrix] review metadata: ",
    "artifacts_line: [smoke-matrix] review artifacts: ",
    "matrix_summary_line: [smoke-matrix] review matrix summary: ",
    "summary_line: [smoke-matrix] summary: 4/4 bundles passed in ",
    "rerun_hint_line: [smoke-matrix] review bundle rerun hint: ",
)

_SMOKE_MATRIX_ARTIFACT_ROOTS_COMMON_TRUE_CHECK_SUFFIXES = (
    "exit_code_zero",
    "stderr_empty",
    "metadata_line_present",
    "artifacts_line_present",
    "matrix_summary_line_present",
    "metadata_matrix_summary_matches_expected_path",
    "metadata_bundle_index_rerun_hint_matches",
    "metadata_expected_artifact_paths_match",
    "metadata_resolved_paths_match_expected",
    "matrix_summary_line_matches_expected_path",
    "rerun_hint_line_matches_expected_hint",
    "paths_loaded_from_matrix_summary",
    "artifacts_exist",
    "summary_bundle_index_rerun_hint_matches",
    "matrix_summary_expected_artifact_paths_match",
    "matrix_summary_resolved_paths_match_expected",
    "matrix_summary_path_matches_metadata",
    "matrix_summary_line_matches_metadata_path",
    "loaded_summary_path_matches_line",
    "summary_line_present",
    "rerun_hint_line_present",
)

_SMOKE_MATRIX_ARTIFACT_ROOTS_REVIEW_TRUE_CHECK_SUFFIXES = (
    "metadata_targets_docs_review",
    "metadata_artifact_root_matches_review",
    "summary_targets_docs_review",
    "summary_path_keeps_review_root",
)

_SMOKE_MATRIX_ARTIFACT_ROOTS_ALL_REVIEW_TRUE_CHECK_SUFFIXES = (
    "metadata_targets_docs_review_all",
    "metadata_artifact_root_matches_all_review",
    "summary_targets_docs_review_all",
    "summary_path_keeps_all_review_root",
)

SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT = SmokeScriptContractMetadata(
    required_line_prefixes=("checkout_root: ",)
    + tuple(
        f"review_{suffix}"
        for suffix in _SMOKE_MATRIX_ARTIFACT_ROOTS_COMMON_LINE_PREFIX_SUFFIXES
    )
    + tuple(
        f"all_review_{suffix}"
        for suffix in _SMOKE_MATRIX_ARTIFACT_ROOTS_COMMON_LINE_PREFIX_SUFFIXES
    ),
    true_check_names=tuple(
        f"review_{suffix}"
        for suffix in _SMOKE_MATRIX_ARTIFACT_ROOTS_COMMON_TRUE_CHECK_SUFFIXES
    )
    + tuple(
        f"review_{suffix}"
        for suffix in _SMOKE_MATRIX_ARTIFACT_ROOTS_REVIEW_TRUE_CHECK_SUFFIXES
    )
    + tuple(
        f"all_review_{suffix}"
        for suffix in _SMOKE_MATRIX_ARTIFACT_ROOTS_COMMON_TRUE_CHECK_SUFFIXES
    )
    + tuple(
        f"all_review_{suffix}"
        for suffix in _SMOKE_MATRIX_ARTIFACT_ROOTS_ALL_REVIEW_TRUE_CHECK_SUFFIXES
    )
    + (
        "artifact_roots_distinct",
        "review_index_preserved_after_all_review",
        "review_summary_preserved_after_all_review",
    ),
)
SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_matrix_artifact_roots_smoke",
    runner_name="run_smoke_matrix_artifact_roots_smoke",
    contract=SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT,
)

SMOKE_SCRIPT_CONTRACT_CASES = (
    STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
    *DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS,
    SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
)


def smoke_contract_detail_expectation(required_line_prefix: str) -> tuple[str, str]:
    detail_name, separator, detail_value_prefix = required_line_prefix.partition(": ")
    assert separator, required_line_prefix
    return detail_name, detail_value_prefix


def assert_smoke_script_output_matches_contract(
    output_lines: Sequence[str],
    case: SmokeScriptContractCase,
) -> None:
    for required_line_prefix in case.required_line_prefixes:
        assert any(line.startswith(required_line_prefix) for line in output_lines), required_line_prefix

    for check_name in case.true_check_names:
        assert f"{check_name}= True" in output_lines, check_name


def assert_smoke_script_results_match_contract(
    results: Mapping[str, object] | Iterable[tuple[str, object]],
    case: SmokeScriptContractCase,
) -> None:
    result_map = dict(results)

    for required_line_prefix in case.required_line_prefixes:
        detail_name, detail_value_prefix = smoke_contract_detail_expectation(required_line_prefix)
        assert detail_name in result_map, detail_name
        assert not isinstance(result_map[detail_name], bool), detail_name
        assert str(result_map[detail_name]).startswith(detail_value_prefix), detail_name

    for check_name in case.true_check_names:
        assert result_map.get(check_name) is True, check_name


def build_standalone_docs_rerun_hint_results(
    smoke_run: SmokeScriptRunResult,
    failure_output: SmokeWrapperFailureObservation,
) -> list[tuple[str, object]]:
    stdout_lines = smoke_run.stdout_lines
    return [
        ("checkout_root", str(smoke_run.checkout_root)),
        ("stdout_fix_check_summary", stdout_lines[0] if stdout_lines else ""),
        (
            "stdout_false_line",
            detail_safe_text(stdout_lines[1]) if len(stdout_lines) > 1 else "",
        ),
        ("stderr_failed_line", detail_safe_text(failure_output.failed_line)),
        ("stderr_hint_line", failure_output.hint_line),
        ("stderr_summary_line", failure_output.failure_summary_line),
        ("exit_code", smoke_run.exit_code),
        ("exit_code_non_zero", smoke_run.exit_code != 0),
        (
            "fix_check_summary_present",
            STANDALONE_DOCS_RERUN_HINT_FIX_CHECK_SUMMARY_LINE in stdout_lines,
        ),
        ("false_line_present", STANDALONE_DOCS_RERUN_HINT_FALSE_LINE in stdout_lines),
        ("failed_line_present", failure_output.present("failed")),
        ("hint_line_present", failure_output.present("hint")),
        ("summary_line_present", failure_output.present("failure_summary")),
        (
            "hint_after_failed_line",
            failure_output.appears_before("failed", "hint"),
        ),
        (
            "hint_before_failure_summary",
            failure_output.appears_before("hint", "failure_summary"),
        ),
    ]


def collect_smoke_wrapper_failure_output(
    output_lines: Sequence[str],
    *,
    hint_prefix: str,
    failure_summary_prefix: str,
    failed_line_prefix: str | None = None,
    failed_line_exact: str | None = None,
) -> SmokeWrapperFailureObservation:
    if (failed_line_prefix is None) == (failed_line_exact is None):
        raise ValueError("provide exactly one failed-line matcher: failed_line_prefix or failed_line_exact")

    failed_index = (
        _find_exact_line_index(output_lines, failed_line_exact)
        if failed_line_exact is not None
        else find_prefixed_line_index(output_lines, failed_line_prefix)
    )
    hint_index = find_prefixed_line_index(output_lines, hint_prefix)
    failure_summary_index = find_prefixed_line_index(output_lines, failure_summary_prefix)

    return SmokeWrapperFailureObservation(
        failed_index=failed_index,
        hint_index=hint_index,
        failure_summary_index=failure_summary_index,
        failed_line=_line_at_index(output_lines, failed_index),
        hint_line=_line_at_index(output_lines, hint_index),
        failure_summary_line=_line_at_index(output_lines, failure_summary_index),
    )


def collect_smoke_matrix_docs_review_failure_output(
    output_lines: Sequence[str],
    *,
    review_output: ReviewArtifactOutputObservation,
    failure_summary_prefix: str,
    failed_line_prefix: str | None = None,
    failed_line_exact: str | None = None,
    bundle_rerun_hint_prefix: str | None = None,
    docs_review_only_hint_prefix: str | None = None,
    live_runtime_hint_prefix: str | None = None,
    missing_api_key_hint_prefix: str | None = None,
) -> SmokeMatrixDocsReviewFailureObservation:
    if (failed_line_prefix is None) == (failed_line_exact is None):
        raise ValueError("provide exactly one failed-line matcher: failed_line_prefix or failed_line_exact")

    failed_index = (
        _find_exact_line_index(output_lines, failed_line_exact)
        if failed_line_exact is not None
        else find_prefixed_line_index(output_lines, failed_line_prefix)
    )
    bundle_rerun_hint_index = (
        find_prefixed_line_index(output_lines, bundle_rerun_hint_prefix)
        if bundle_rerun_hint_prefix is not None
        else None
    )
    docs_review_only_hint_index = (
        find_prefixed_line_index(output_lines, docs_review_only_hint_prefix)
        if docs_review_only_hint_prefix is not None
        else None
    )
    live_runtime_hint_index = (
        find_prefixed_line_index(output_lines, live_runtime_hint_prefix)
        if live_runtime_hint_prefix is not None
        else None
    )
    missing_api_key_hint_index = (
        find_prefixed_line_index(output_lines, missing_api_key_hint_prefix)
        if missing_api_key_hint_prefix is not None
        else None
    )
    failure_summary_index = find_prefixed_line_index(output_lines, failure_summary_prefix)

    return SmokeMatrixDocsReviewFailureObservation(
        review_output=review_output,
        failed_index=failed_index,
        bundle_rerun_hint_index=bundle_rerun_hint_index,
        docs_review_only_hint_index=docs_review_only_hint_index,
        live_runtime_hint_index=live_runtime_hint_index,
        missing_api_key_hint_index=missing_api_key_hint_index,
        failure_summary_index=failure_summary_index,
        failed_line=_line_at_index(output_lines, failed_index),
        bundle_rerun_hint_line=_line_at_index(output_lines, bundle_rerun_hint_index),
        docs_review_only_hint_line=_line_at_index(output_lines, docs_review_only_hint_index),
        live_runtime_hint_line=_line_at_index(output_lines, live_runtime_hint_index),
        missing_api_key_hint_line=_line_at_index(output_lines, missing_api_key_hint_index),
        failure_summary_line=_line_at_index(output_lines, failure_summary_index),
    )


def _result_name_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return prefix if prefix.endswith("_") else f"{prefix}_"


def build_review_artifact_failure_results(
    review_output: ReviewArtifactOutputObservation,
    review_spec: SmokeMatrixDocsReviewObserverSpec,
    *,
    target_suffix: str,
    artifact_suffix: str,
    detail_prefix: str = "stderr_",
    result_prefix: str = "",
) -> list[tuple[str, object]]:
    prefix = _result_name_prefix(result_prefix)
    return [
        (f"{prefix}{detail_prefix}metadata_line", review_output.metadata_line),
        (f"{prefix}{detail_prefix}artifacts_line", review_output.artifacts_line),
        (f"{prefix}{detail_prefix}matrix_summary_line", review_output.matrix_summary_line),
        (f"{prefix}metadata_line_present", review_output.metadata_line_present),
        (f"{prefix}artifacts_line_present", review_output.artifacts_line_present),
        (f"{prefix}matrix_summary_line_present", review_output.matrix_summary_line_present),
        (
            f"{prefix}metadata_targets_{target_suffix}",
            review_output.metadata_targets(review_spec.expected_target_name),
        ),
        (
            f"{prefix}metadata_artifact_root_matches_{artifact_suffix}",
            review_output.metadata_artifact_root_matches(review_spec.expected_artifact_root),
        ),
        (
            f"{prefix}metadata_bundle_index_rerun_hint_matches",
            review_output.metadata_bundle_index_rerun_hint_matches(
                review_spec.expected_bundle_index_rerun_hint
            ),
        ),
        (
            f"{prefix}metadata_expected_artifact_paths_match",
            review_spec.metadata_artifact_paths_match(review_output),
        ),
        (
            f"{prefix}metadata_resolved_paths_match_expected",
            review_spec.metadata_resolved_paths_match(review_output),
        ),
        (f"{prefix}matrix_summary_artifact_exists", review_output.matrix_summary_artifact_exists),
        (
            f"{prefix}matrix_summary_targets_{target_suffix}",
            review_output.matrix_summary_targets(review_spec.expected_target_name),
        ),
        (
            f"{prefix}matrix_summary_artifact_root_matches_{artifact_suffix}",
            review_output.matrix_summary_artifact_root_matches(review_spec.expected_artifact_root),
        ),
        (
            f"{prefix}matrix_summary_bundle_index_rerun_hint_matches",
            review_output.matrix_summary_bundle_index_rerun_hint_matches(
                review_spec.expected_bundle_index_rerun_hint
            ),
        ),
        (
            f"{prefix}matrix_summary_expected_artifact_paths_match",
            review_spec.matrix_summary_artifact_paths_match(review_output),
        ),
        (
            f"{prefix}matrix_summary_resolved_paths_match_expected",
            review_spec.matrix_summary_resolved_paths_match(review_output),
        ),
    ]


def build_review_artifact_success_results(
    review_output: ReviewArtifactOutputObservation,
    review_spec: SmokeMatrixDocsReviewObserverSpec,
    *,
    result_prefix: str,
    target_suffix: str,
    artifact_suffix: str,
    success_summary_line: str,
    success_summary_prefix: str,
    rerun_hint_line: str,
    rerun_hint_prefix: str,
    exit_code: int,
    stderr_text: str,
    artifacts_exist: bool,
) -> list[tuple[str, object]]:
    prefix = _result_name_prefix(result_prefix)
    expected_paths = review_spec.resolve_expected_paths(checkout_root=review_output.checkout_root)
    artifact_root = review_output.matrix_summary_paths.get("artifact_root")
    return [
        (f"{prefix}artifact_root", str(artifact_root) if artifact_root is not None else ""),
        (f"{prefix}metadata_line", review_output.metadata_line),
        (f"{prefix}artifacts_line", review_output.artifacts_line),
        (f"{prefix}matrix_summary_line", review_output.matrix_summary_line),
        (f"{prefix}summary_line", success_summary_line),
        (f"{prefix}rerun_hint_line", rerun_hint_line),
        (f"{prefix}exit_code_zero", exit_code == 0),
        (f"{prefix}stderr_empty", stderr_text == ""),
        (f"{prefix}metadata_line_present", review_output.metadata_line_present),
        (f"{prefix}artifacts_line_present", review_output.artifacts_line_present),
        (f"{prefix}matrix_summary_line_present", review_output.matrix_summary_line_present),
        (
            f"{prefix}metadata_targets_{target_suffix}",
            review_output.metadata_targets(review_spec.expected_target_name),
        ),
        (
            f"{prefix}metadata_artifact_root_matches_{artifact_suffix}",
            review_output.metadata_artifact_root_matches(review_spec.expected_artifact_root),
        ),
        (
            f"{prefix}metadata_matrix_summary_matches_expected_path",
            review_output.metadata_matrix_summary_matches(review_spec.expected_matrix_summary_path),
        ),
        (
            f"{prefix}metadata_bundle_index_rerun_hint_matches",
            review_output.metadata_bundle_index_rerun_hint_matches(
                review_spec.expected_bundle_index_rerun_hint
            ),
        ),
        (
            f"{prefix}metadata_expected_artifact_paths_match",
            review_spec.metadata_artifact_paths_match(review_output),
        ),
        (
            f"{prefix}metadata_resolved_paths_match_expected",
            review_spec.metadata_resolved_paths_match(review_output),
        ),
        (
            f"{prefix}matrix_summary_line_matches_expected_path",
            review_output.matrix_summary_path == expected_paths["matrix_summary_path"],
        ),
        (
            f"{prefix}rerun_hint_line_matches_expected_hint",
            rerun_hint_line == f"{rerun_hint_prefix}{review_spec.expected_bundle_index_rerun_hint}",
        ),
        (f"{prefix}paths_loaded_from_matrix_summary", bool(review_output.matrix_summary_paths)),
        (f"{prefix}artifacts_exist", artifacts_exist),
        (
            f"{prefix}summary_targets_{target_suffix}",
            review_output.matrix_summary_targets(review_spec.expected_target_name),
        ),
        (
            f"{prefix}summary_bundle_index_rerun_hint_matches",
            review_output.matrix_summary_bundle_index_rerun_hint_matches(
                review_spec.expected_bundle_index_rerun_hint
            ),
        ),
        (
            f"{prefix}matrix_summary_expected_artifact_paths_match",
            review_spec.matrix_summary_artifact_paths_match(review_output),
        ),
        (
            f"{prefix}matrix_summary_resolved_paths_match_expected",
            review_spec.matrix_summary_resolved_paths_match(review_output),
        ),
        (
            f"{prefix}matrix_summary_path_matches_metadata",
            review_output.matrix_summary_path_matches_metadata(),
        ),
        (
            f"{prefix}matrix_summary_line_matches_metadata_path",
            review_output.matrix_summary_line_matches_metadata_path(),
        ),
        (
            f"{prefix}loaded_summary_path_matches_line",
            review_output.matrix_summary_paths.get("matrix_summary_path")
            == review_output.matrix_summary_path,
        ),
        (
            f"{prefix}summary_path_keeps_{artifact_suffix}_root",
            artifact_root == expected_paths.get("artifact_root"),
        ),
        (f"{prefix}summary_line_present", success_summary_line.startswith(success_summary_prefix)),
        (f"{prefix}rerun_hint_line_present", rerun_hint_line.startswith(rerun_hint_prefix)),
    ]


def collect_review_artifact_output(
    output_lines: str | Sequence[str],
    *,
    checkout_root: Path,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
) -> ReviewArtifactOutputObservation:
    lines = output_lines.splitlines() if isinstance(output_lines, str) else list(output_lines)
    metadata_index = find_prefixed_line_index(lines, metadata_prefix) if metadata_prefix is not None else None
    artifacts_index = find_prefixed_line_index(lines, artifacts_prefix) if artifacts_prefix is not None else None
    matrix_summary_index = find_prefixed_line_index(lines, matrix_summary_prefix)

    metadata_line = lines[metadata_index] if metadata_index is not None else ""
    artifacts_line = lines[artifacts_index] if artifacts_index is not None else ""
    matrix_summary_line = lines[matrix_summary_index] if matrix_summary_index is not None else ""

    metadata_payload: dict[str, object] = {}
    if metadata_line and metadata_prefix is not None:
        loaded_metadata = json.loads(metadata_line.removeprefix(metadata_prefix))
        if isinstance(loaded_metadata, dict):
            metadata_payload = loaded_metadata
    metadata_paths = (
        resolve_review_artifact_paths(metadata_payload, checkout_root=checkout_root) if metadata_payload else {}
    )
    metadata_matrix_summary_path = metadata_paths.get("matrix_summary_path")

    matrix_summary_path = output_path_from_prefixed_lines(
        lines,
        prefix=matrix_summary_prefix,
        checkout_root=checkout_root,
    )
    matrix_summary_payload, matrix_summary_paths = load_review_matrix_summary(
        matrix_summary_path,
        checkout_root=checkout_root,
    )

    return ReviewArtifactOutputObservation(
        checkout_root=checkout_root,
        metadata_index=metadata_index,
        artifacts_index=artifacts_index,
        matrix_summary_index=matrix_summary_index,
        metadata_line=metadata_line,
        artifacts_line=artifacts_line,
        matrix_summary_line=matrix_summary_line,
        metadata_payload=metadata_payload,
        metadata_paths=metadata_paths,
        metadata_matrix_summary_path=metadata_matrix_summary_path,
        matrix_summary_path=matrix_summary_path,
        matrix_summary_payload=matrix_summary_payload,
        matrix_summary_paths=matrix_summary_paths,
    )


def load_script_module(script_path: Path, module_name: str) -> Any:
    spec = spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


@contextmanager
def _unset_env(*variable_names: str) -> Iterator[None]:
    previous_values = {name: os.environ.get(name) for name in variable_names}
    for name in variable_names:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in previous_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_script_module_main_in_temp_checkout(
    *,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    temp_prefix: str,
    unset_env_names: Iterable[str] = (),
) -> SmokeScriptRunResult:
    module = load_script_module(script_path, module_name)
    checkout_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    stdout = StringIO()
    stderr = StringIO()
    with _pushd(checkout_root), _unset_env(*tuple(unset_env_names)):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = module.main(list(argv))
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=0 if exit_code is None else int(exit_code),
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        cleanup_callback=lambda: rmtree(checkout_root, ignore_errors=True),
    )


def run_loaded_script_module_main(
    module: Any,
    *,
    argv: Sequence[str],
    checkout_root: Path,
    unset_env_names: Iterable[str] = (),
) -> SmokeScriptRunResult:
    stdout = StringIO()
    stderr = StringIO()
    with _pushd(checkout_root), _unset_env(*tuple(unset_env_names)):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = module.main(list(argv))
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=0 if exit_code is None else int(exit_code),
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        cleanup_callback=lambda: None,
    )


def run_loaded_script_module_main_in_temp_checkout(
    module: Any,
    *,
    argv: Sequence[str],
    temp_prefix: str,
    unset_env_names: Iterable[str] = (),
) -> SmokeScriptRunResult:
    checkout_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    smoke_run = run_loaded_script_module_main(
        module,
        argv=argv,
        checkout_root=checkout_root,
        unset_env_names=unset_env_names,
    )
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=smoke_run.exit_code,
        stdout=smoke_run.stdout,
        stderr=smoke_run.stderr,
        cleanup_callback=lambda: rmtree(checkout_root, ignore_errors=True),
    )


def _validate_review_output_stream(output_stream: Literal["stdout", "stderr"] | str) -> None:
    if output_stream not in {"stdout", "stderr"}:
        raise ValueError(f"output_stream must be 'stdout' or 'stderr', got {output_stream!r}")


def _review_output_lines(
    smoke_run: SmokeScriptRunResult,
    *,
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> list[str]:
    _validate_review_output_stream(output_stream)
    return smoke_run.stdout_lines if output_stream == "stdout" else smoke_run.stderr_lines


def observe_review_artifact_output_in_temp_checkout(
    *,
    temp_prefix: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    output_stream: Literal["stdout", "stderr"] = "stdout",
    module: Any | None = None,
    argv: Sequence[str] | None = None,
    unset_env_names: Iterable[str] = (),
    driver_source: str | None = None,
    driver_filename: str | None = None,
    python_executable: str | None = None,
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    _validate_review_output_stream(output_stream)

    module_selected = module is not None
    driver_selected = driver_source is not None
    if module_selected == driver_selected:
        raise ValueError("provide exactly one review artifact source: module or driver_source")

    if module is not None:
        if argv is None:
            raise ValueError("argv is required when observing a loaded review artifact module")
        smoke_run = run_loaded_script_module_main_in_temp_checkout(
            module,
            argv=argv,
            temp_prefix=temp_prefix,
            unset_env_names=unset_env_names,
        )
    else:
        if driver_filename is None:
            raise ValueError("driver_filename is required when driver_source is provided")
        smoke_run = run_python_driver_in_temp_checkout(
            driver_source=driver_source,
            temp_prefix=temp_prefix,
            driver_filename=driver_filename,
            python_executable=python_executable,
        )

    review_output = collect_review_artifact_output(
        _review_output_lines(smoke_run, output_stream=output_stream),
        checkout_root=smoke_run.checkout_root,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
    )
    return smoke_run, review_output


def observe_loaded_review_artifact_output(
    module: Any,
    *,
    argv: Sequence[str],
    checkout_root: Path,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    unset_env_names: Iterable[str] = (),
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    _validate_review_output_stream(output_stream)
    smoke_run = run_loaded_script_module_main(
        module,
        argv=argv,
        checkout_root=checkout_root,
        unset_env_names=unset_env_names,
    )
    review_output = collect_review_artifact_output(
        _review_output_lines(smoke_run, output_stream=output_stream),
        checkout_root=checkout_root,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
    )
    return smoke_run, review_output


def observe_loaded_review_artifact_output_in_temp_checkout(
    module: Any,
    *,
    argv: Sequence[str],
    temp_prefix: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    unset_env_names: Iterable[str] = (),
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    return observe_review_artifact_output_in_temp_checkout(
        module=module,
        argv=argv,
        temp_prefix=temp_prefix,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
        unset_env_names=unset_env_names,
        output_stream=output_stream,
    )


def build_script_driver_source(
    *,
    repo_root: Path,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    env_assignments: Mapping[str, str] | None = None,
    env_unsets: Sequence[str] = (),
    hook_source: str = "",
) -> str:
    env_assignments = env_assignments or {}
    lines = [
        "from __future__ import annotations",
        "",
        "import os",
        "import sys",
        "from importlib.util import module_from_spec, spec_from_file_location",
        "from pathlib import Path",
        "",
        f"repo_root = Path({str(repo_root)!r})",
        "sys.path.insert(0, str(repo_root / 'src'))",
        f"script_path = Path({str(script_path)!r})",
        f"spec = spec_from_file_location({module_name!r}, script_path)",
        "assert spec is not None and spec.loader is not None",
        "module = module_from_spec(spec)",
        "spec.loader.exec_module(module)",
    ]
    for name, value in env_assignments.items():
        lines.append(f"os.environ[{name!r}] = {value!r}")
    for name in env_unsets:
        lines.append(f"os.environ.pop({name!r}, None)")
    body = dedent(hook_source).strip()
    if body:
        lines.extend(["", body])
    lines.extend(["", f"raise SystemExit(module.main({list(argv)!r}))", ""])
    return "\n".join(lines)


def run_python_driver_in_temp_checkout(
    *,
    driver_source: str,
    temp_prefix: str,
    driver_filename: str,
    python_executable: str | None = None,
) -> SmokeScriptRunResult:
    checkout_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    driver_path = checkout_root / driver_filename
    driver_path.write_text(driver_source, encoding="utf-8")
    result = subprocess.run(
        [python_executable or sys.executable, str(driver_path)],
        cwd=checkout_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        cleanup_callback=lambda: rmtree(checkout_root, ignore_errors=True),
    )


def run_script_module_main_via_driver_in_temp_checkout(
    *,
    repo_root: Path,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    temp_prefix: str,
    driver_filename: str,
    env_assignments: Mapping[str, str] | None = None,
    env_unsets: Sequence[str] = (),
    hook_source: str = "",
    python_executable: str | None = None,
) -> SmokeScriptRunResult:
    return run_python_driver_in_temp_checkout(
        driver_source=build_script_driver_source(
            repo_root=repo_root,
            script_path=script_path,
            module_name=module_name,
            argv=argv,
            env_assignments=env_assignments,
            env_unsets=env_unsets,
            hook_source=hook_source,
        ),
        temp_prefix=temp_prefix,
        driver_filename=driver_filename,
        python_executable=python_executable,
    )



def observe_subprocess_review_artifact_output(
    *,
    driver_source: str,
    temp_prefix: str,
    driver_filename: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    python_executable: str | None = None,
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    return observe_review_artifact_output_in_temp_checkout(
        driver_source=driver_source,
        temp_prefix=temp_prefix,
        driver_filename=driver_filename,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
        python_executable=python_executable,
        output_stream=output_stream,
    )



def observe_script_module_main_via_driver_review_artifact_output(
    *,
    repo_root: Path,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    temp_prefix: str,
    driver_filename: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    env_assignments: Mapping[str, str] | None = None,
    env_unsets: Sequence[str] = (),
    hook_source: str = "",
    python_executable: str | None = None,
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    return observe_subprocess_review_artifact_output(
        driver_source=build_script_driver_source(
            repo_root=repo_root,
            script_path=script_path,
            module_name=module_name,
            argv=argv,
            env_assignments=env_assignments,
            env_unsets=env_unsets,
            hook_source=hook_source,
        ),
        temp_prefix=temp_prefix,
        driver_filename=driver_filename,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
        python_executable=python_executable,
        output_stream=output_stream,
    )
