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
from typing import Any, Callable, Iterator, Literal, TextIO

from .smoke_cli_doc_artifacts import (
    load_review_matrix_summary,
    output_path_from_prefixed_lines,
    resolve_checkout_path,
    resolve_review_artifact_paths,
)
from .smoke_cli_assertions import smoke_cli_docs_parity_rerun_hint
from .smoke_output import emit_smoke_target_run_stdout_lines
from .smoke_runner import STANDALONE_DOCS_PARITY_FOLLOW_UP_FAILURE_FIXTURES

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
class SmokeTargetRunFailureFixture:
    stdout_lines: tuple[str, ...] = ()
    stderr_lines: tuple[str, ...] = ()
    observed_lines: tuple[str, ...] = ()

    @classmethod
    def build_failed_fast(
        cls,
        *,
        target_name: str,
        failed_line: str,
        stdout_lines: Sequence[str] = (),
        observed_lines: Sequence[str] = (),
    ) -> SmokeTargetRunFailureFixture:
        return cls(
            stdout_lines=tuple(stdout_lines),
            stderr_lines=(f"{target_name} smoke failed fast: {failed_line}",),
            observed_lines=tuple(observed_lines),
        )

    def emit_observed_lines(
        self,
        *,
        output_line_observer: Callable[[str], None] | None = None,
    ) -> None:
        if output_line_observer is None:
            return
        for line in self.observed_lines:
            output_line_observer(f"{line}\n")

    def emit_stdout_lines(
        self,
        *,
        stdout: TextIO,
        output_line_observer: Callable[[str], None] | None = None,
        output_line_filter: Callable[[str], bool] | None = None,
    ) -> None:
        emit_smoke_target_run_stdout_lines(
            self.stdout_lines,
            stdout=stdout,
            output_line_observer=output_line_observer,
            output_line_filter=output_line_filter,
        )

    def emit_stderr_lines(self, *, stderr: TextIO) -> None:
        for line in self.stderr_lines:
            print(line, file=stderr)
        stderr.flush()

    def emit_failed_target_run(
        self,
        *,
        stdout: TextIO,
        stderr: TextIO,
        output_line_observer: Callable[[str], None] | None = None,
        output_line_filter: Callable[[str], bool] | None = None,
    ) -> int:
        self.emit_observed_lines(output_line_observer=output_line_observer)
        self.emit_stdout_lines(
            stdout=stdout,
            output_line_observer=output_line_observer,
            output_line_filter=output_line_filter,
        )
        self.emit_stderr_lines(stderr=stderr)
        return 1


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


def smoke_script_contract_case_id(case: SmokeScriptContractCase) -> str:
    return case.script_name


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

SmokeMatrixDocsReviewMatrixSummaryAssertionCheck = Literal[
    "metadata_expected_path",
    "matrix_summary_expected_path",
    "matrix_summary_matches_metadata",
    "matrix_summary_line_matches_metadata_path",
    "bundle_rerun_hint_matches_matrix_summary_hint",
]

SmokeMatrixDocsReviewMatrixSummaryAssertionBundle = Literal[
    "all_review_order_failure",
    "all_review_missing_api_key_failure",
    "docs_review_hint_failure",
]


def _matrix_summary_assertion_bundle_checks(
    bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
) -> tuple[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck, ...]:
    if bundle == "all_review_order_failure":
        return (
            "metadata_expected_path",
            "matrix_summary_matches_metadata",
            "matrix_summary_line_matches_metadata_path",
        )
    if bundle == "all_review_missing_api_key_failure":
        return (
            "metadata_expected_path",
            "matrix_summary_matches_metadata",
            "matrix_summary_line_matches_metadata_path",
            "bundle_rerun_hint_matches_matrix_summary_hint",
        )
    return (
        "metadata_expected_path",
        "matrix_summary_expected_path",
        "bundle_rerun_hint_matches_matrix_summary_hint",
    )


def _matrix_summary_assertion_result_name_keyword(
    check: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
) -> str:
    if check == "metadata_expected_path":
        return "metadata_expected_path_result_name"
    if check == "matrix_summary_expected_path":
        return "matrix_summary_expected_path_result_name"
    if check == "matrix_summary_matches_metadata":
        return "matrix_summary_matches_metadata_result_name"
    if check == "matrix_summary_line_matches_metadata_path":
        return "matrix_summary_line_matches_metadata_result_name"
    return "bundle_rerun_hint_result_name"


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
class SmokeMatrixDocsReviewResultNaming:
    result_prefix: str
    target_suffix: str
    artifact_suffix: str

    def result_name(
        self,
        stem: str,
        *,
        result_prefix: str | None = None,
        line_detail_prefix: str = "",
    ) -> str:
        prefix = self.result_prefix if result_prefix is None else result_prefix
        name_prefix = f"{prefix}_" if prefix else ""
        return f"{name_prefix}{line_detail_prefix}{stem}"

    def observation_result_names(
        self,
        *,
        result_prefix: str | None = None,
        line_detail_prefix: str = "",
    ) -> SmokeMatrixDocsReviewObservationResultNames:
        return SmokeMatrixDocsReviewObservationResultNames(
            metadata_line=self.result_name(
                "metadata_line",
                result_prefix=result_prefix,
                line_detail_prefix=line_detail_prefix,
            ),
            artifacts_line=self.result_name(
                "artifacts_line",
                result_prefix=result_prefix,
                line_detail_prefix=line_detail_prefix,
            ),
            matrix_summary_line=self.result_name(
                "matrix_summary_line",
                result_prefix=result_prefix,
                line_detail_prefix=line_detail_prefix,
            ),
            metadata_line_present=self.result_name(
                "metadata_line_present",
                result_prefix=result_prefix,
            ),
            artifacts_line_present=self.result_name(
                "artifacts_line_present",
                result_prefix=result_prefix,
            ),
            matrix_summary_line_present=self.result_name(
                "matrix_summary_line_present",
                result_prefix=result_prefix,
            ),
            metadata_targets=self.result_name(
                f"metadata_targets_{self.target_suffix}",
                result_prefix=result_prefix,
            ),
            metadata_artifact_root_matches=self.result_name(
                f"metadata_artifact_root_matches_{self.artifact_suffix}",
                result_prefix=result_prefix,
            ),
            metadata_bundle_index_rerun_hint_matches=self.result_name(
                "metadata_bundle_index_rerun_hint_matches",
                result_prefix=result_prefix,
            ),
            metadata_expected_artifact_paths_match=self.result_name(
                "metadata_expected_artifact_paths_match",
                result_prefix=result_prefix,
            ),
            metadata_resolved_paths_match_expected=self.result_name(
                "metadata_resolved_paths_match_expected",
                result_prefix=result_prefix,
            ),
            matrix_summary_artifact_exists=self.result_name(
                "matrix_summary_artifact_exists",
                result_prefix=result_prefix,
            ),
            matrix_summary_targets=self.result_name(
                f"matrix_summary_targets_{self.target_suffix}",
                result_prefix=result_prefix,
            ),
            matrix_summary_artifact_root_matches=self.result_name(
                f"matrix_summary_artifact_root_matches_{self.artifact_suffix}",
                result_prefix=result_prefix,
            ),
            matrix_summary_bundle_index_rerun_hint_matches=self.result_name(
                "matrix_summary_bundle_index_rerun_hint_matches",
                result_prefix=result_prefix,
            ),
            matrix_summary_expected_artifact_paths_match=self.result_name(
                "matrix_summary_expected_artifact_paths_match",
                result_prefix=result_prefix,
            ),
            matrix_summary_resolved_paths_match_expected=self.result_name(
                "matrix_summary_resolved_paths_match_expected",
                result_prefix=result_prefix,
            ),
        )

    def matrix_summary_assertion_result_names(
        self,
        *,
        result_prefix: str | None = None,
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionResultNames:
        return SmokeMatrixDocsReviewMatrixSummaryAssertionResultNames(
            metadata_expected_path=self.result_name(
                f"metadata_matrix_summary_matches_{self.artifact_suffix}",
                result_prefix=result_prefix,
            ),
            matrix_summary_expected_path=self.result_name(
                f"matrix_summary_path_matches_{self.artifact_suffix}",
                result_prefix=result_prefix,
            ),
            matrix_summary_matches_metadata=self.result_name(
                "matrix_summary_path_matches_metadata",
                result_prefix=result_prefix,
            ),
            matrix_summary_line_matches_metadata_path=self.result_name(
                "matrix_summary_line_matches_metadata_path",
                result_prefix=result_prefix,
            ),
            bundle_rerun_hint_matches_matrix_summary_hint=self.result_name(
                "bundle_rerun_hint_line_matches_matrix_summary_hint",
                result_prefix=result_prefix,
            ),
        )

    def matrix_summary_assertion_result_name_kwargs(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
        result_prefix: str | None = None,
    ) -> dict[str, str]:
        return self.matrix_summary_assertion_selection(
            *checks,
            result_prefix=result_prefix,
        ).result_name_kwargs()

    def matrix_summary_assertion_selection(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
        result_prefix: str | None = None,
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionSelection:
        return self.matrix_summary_assertion_result_names(
            result_prefix=result_prefix,
        ).selected_selection(*checks)

    def matrix_summary_assertion_true_check_names(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
        result_prefix: str | None = None,
    ) -> tuple[str, ...]:
        return self.matrix_summary_assertion_selection(
            *checks,
            result_prefix=result_prefix,
        ).true_check_names()

    def matrix_summary_assertion_contract_metadata(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
        result_prefix: str | None = None,
    ) -> SmokeScriptContractMetadata:
        return self.matrix_summary_assertion_selection(
            *checks,
            result_prefix=result_prefix,
        ).contract_metadata()

    def matrix_summary_assertion_result_name_bundle_kwargs(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        result_prefix: str | None = None,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> dict[str, str]:
        return self.matrix_summary_assertion_bundle_selection(
            bundle,
            result_prefix=result_prefix,
            excluding_checks=excluding_checks,
        ).result_name_kwargs()

    def matrix_summary_assertion_bundle_selection(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        result_prefix: str | None = None,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionSelection:
        return self.matrix_summary_assertion_result_names(
            result_prefix=result_prefix,
        ).bundle_selection(bundle, excluding_checks=excluding_checks)

    def matrix_summary_assertion_bundle_true_check_names(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        result_prefix: str | None = None,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> tuple[str, ...]:
        return self.matrix_summary_assertion_bundle_selection(
            bundle,
            result_prefix=result_prefix,
            excluding_checks=excluding_checks,
        ).true_check_names()

    def matrix_summary_assertion_bundle_contract_metadata(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        result_prefix: str | None = None,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> SmokeScriptContractMetadata:
        return self.matrix_summary_assertion_bundle_selection(
            bundle,
            result_prefix=result_prefix,
            excluding_checks=excluding_checks,
        ).contract_metadata()

    def success_result_names(
        self,
        *,
        result_prefix: str | None = None,
    ) -> SmokeMatrixDocsReviewSuccessResultNames:
        return SmokeMatrixDocsReviewSuccessResultNames(
            observation=self.observation_result_names(result_prefix=result_prefix),
            artifact_root=self.result_name("artifact_root", result_prefix=result_prefix),
            summary_line=self.result_name("summary_line", result_prefix=result_prefix),
            rerun_hint_line=self.result_name("rerun_hint_line", result_prefix=result_prefix),
            exit_code_zero=self.result_name("exit_code_zero", result_prefix=result_prefix),
            stderr_empty=self.result_name("stderr_empty", result_prefix=result_prefix),
            metadata_matrix_summary_matches_expected_path=self.result_name(
                "metadata_matrix_summary_matches_expected_path",
                result_prefix=result_prefix,
            ),
            matrix_summary_line_matches_expected_path=self.result_name(
                "matrix_summary_line_matches_expected_path",
                result_prefix=result_prefix,
            ),
            rerun_hint_line_matches_expected_hint=self.result_name(
                "rerun_hint_line_matches_expected_hint",
                result_prefix=result_prefix,
            ),
            paths_loaded_from_matrix_summary=self.result_name(
                "paths_loaded_from_matrix_summary",
                result_prefix=result_prefix,
            ),
            artifacts_exist=self.result_name("artifacts_exist", result_prefix=result_prefix),
            summary_targets=self.result_name(
                f"summary_targets_{self.target_suffix}",
                result_prefix=result_prefix,
            ),
            summary_bundle_index_rerun_hint_matches=self.result_name(
                "summary_bundle_index_rerun_hint_matches",
                result_prefix=result_prefix,
            ),
            matrix_summary_path_matches_metadata=self.result_name(
                "matrix_summary_path_matches_metadata",
                result_prefix=result_prefix,
            ),
            matrix_summary_line_matches_metadata_path=self.result_name(
                "matrix_summary_line_matches_metadata_path",
                result_prefix=result_prefix,
            ),
            loaded_summary_path_matches_line=self.result_name(
                "loaded_summary_path_matches_line",
                result_prefix=result_prefix,
            ),
            summary_path_keeps_artifact_root=self.result_name(
                f"summary_path_keeps_{self.artifact_suffix}_root",
                result_prefix=result_prefix,
            ),
            summary_line_present=self.result_name("summary_line_present", result_prefix=result_prefix),
            rerun_hint_line_present=self.result_name(
                "rerun_hint_line_present",
                result_prefix=result_prefix,
            ),
        )

    def success_result_kwargs(self) -> dict[str, str]:
        return {"result_prefix": self.result_prefix}

    def failure_result_kwargs(
        self,
        *,
        detail_prefix: str = "stderr_",
        result_prefix: str = "",
    ) -> dict[str, str]:
        return {
            "detail_prefix": detail_prefix,
            "result_prefix": result_prefix,
        }


@dataclass(frozen=True)
class SmokeMatrixDocsReviewObservationResultNames:
    metadata_line: str
    artifacts_line: str
    matrix_summary_line: str
    metadata_line_present: str
    artifacts_line_present: str
    matrix_summary_line_present: str
    metadata_targets: str
    metadata_artifact_root_matches: str
    metadata_bundle_index_rerun_hint_matches: str
    metadata_expected_artifact_paths_match: str
    metadata_resolved_paths_match_expected: str
    matrix_summary_artifact_exists: str
    matrix_summary_targets: str
    matrix_summary_artifact_root_matches: str
    matrix_summary_bundle_index_rerun_hint_matches: str
    matrix_summary_expected_artifact_paths_match: str
    matrix_summary_resolved_paths_match_expected: str

    def detail_names(self) -> tuple[str, str, str]:
        return (
            self.metadata_line,
            self.artifacts_line,
            self.matrix_summary_line,
        )

    def true_check_names(self) -> tuple[str, ...]:
        return (
            self.metadata_line_present,
            self.artifacts_line_present,
            self.matrix_summary_line_present,
            self.metadata_targets,
            self.metadata_artifact_root_matches,
            self.metadata_bundle_index_rerun_hint_matches,
            self.metadata_expected_artifact_paths_match,
            self.metadata_resolved_paths_match_expected,
            self.matrix_summary_artifact_exists,
            self.matrix_summary_targets,
            self.matrix_summary_artifact_root_matches,
            self.matrix_summary_bundle_index_rerun_hint_matches,
            self.matrix_summary_expected_artifact_paths_match,
            self.matrix_summary_resolved_paths_match_expected,
        )


@dataclass(frozen=True)
class SmokeMatrixDocsReviewMatrixSummaryAssertionResultNames:
    metadata_expected_path: str
    matrix_summary_expected_path: str
    matrix_summary_matches_metadata: str
    matrix_summary_line_matches_metadata_path: str
    bundle_rerun_hint_matches_matrix_summary_hint: str

    def result_name(
        self,
        check: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> str:
        return getattr(self, check)

    def selected_selection(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionSelection:
        return SmokeMatrixDocsReviewMatrixSummaryAssertionSelection(
            result_names=self,
            checks=tuple(checks),
        )

    def bundle_selection(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionSelection:
        excluded_check_set = set(excluding_checks)
        return self.selected_selection(
            *(check for check in self.bundle_checks(bundle) if check not in excluded_check_set)
        )

    def selected_result_name_kwargs(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> dict[str, str]:
        return self.selected_selection(*checks).result_name_kwargs()

    def selected_true_check_names(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> tuple[str, ...]:
        return self.selected_selection(*checks).true_check_names()

    def bundle_checks(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
    ) -> tuple[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck, ...]:
        return _matrix_summary_assertion_bundle_checks(bundle)

    def bundle_result_name_kwargs(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> dict[str, str]:
        return self.bundle_selection(bundle, excluding_checks=excluding_checks).result_name_kwargs()

    def bundle_true_check_names(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> tuple[str, ...]:
        return self.bundle_selection(bundle, excluding_checks=excluding_checks).true_check_names()

    def selected_contract_metadata(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> SmokeScriptContractMetadata:
        return self.selected_selection(*checks).contract_metadata()

    def bundle_contract_metadata(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> SmokeScriptContractMetadata:
        return self.bundle_selection(
            bundle,
            excluding_checks=excluding_checks,
        ).contract_metadata()

    def true_check_names(self) -> tuple[str, ...]:
        return (
            self.metadata_expected_path,
            self.matrix_summary_expected_path,
            self.matrix_summary_matches_metadata,
            self.matrix_summary_line_matches_metadata_path,
            self.bundle_rerun_hint_matches_matrix_summary_hint,
        )


@dataclass(frozen=True)
class SmokeMatrixDocsReviewMatrixSummaryAssertionSelection:
    result_names: SmokeMatrixDocsReviewMatrixSummaryAssertionResultNames
    checks: tuple[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck, ...]

    def result_name_kwargs(self) -> dict[str, str]:
        return {
            _matrix_summary_assertion_result_name_keyword(check): self.result_names.result_name(check)
            for check in self.checks
        }

    def contract_metadata(self) -> SmokeScriptContractMetadata:
        return SmokeScriptContractMetadata(
            required_line_prefixes=(),
            true_check_names=self.true_check_names(),
        )

    def true_check_names(self) -> tuple[str, ...]:
        return tuple(self.result_names.result_name(check) for check in self.checks)


@dataclass(frozen=True)
class SmokeMatrixDocsReviewSuccessResultNames:
    observation: SmokeMatrixDocsReviewObservationResultNames
    artifact_root: str
    summary_line: str
    rerun_hint_line: str
    exit_code_zero: str
    stderr_empty: str
    metadata_matrix_summary_matches_expected_path: str
    matrix_summary_line_matches_expected_path: str
    rerun_hint_line_matches_expected_hint: str
    paths_loaded_from_matrix_summary: str
    artifacts_exist: str
    summary_targets: str
    summary_bundle_index_rerun_hint_matches: str
    matrix_summary_path_matches_metadata: str
    matrix_summary_line_matches_metadata_path: str
    loaded_summary_path_matches_line: str
    summary_path_keeps_artifact_root: str
    summary_line_present: str
    rerun_hint_line_present: str

    @property
    def metadata_line(self) -> str:
        return self.observation.metadata_line

    @property
    def artifacts_line(self) -> str:
        return self.observation.artifacts_line

    @property
    def matrix_summary_line(self) -> str:
        return self.observation.matrix_summary_line

    def matrix_summary_assertion_result_names(
        self,
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionResultNames:
        return SmokeMatrixDocsReviewMatrixSummaryAssertionResultNames(
            metadata_expected_path=self.metadata_matrix_summary_matches_expected_path,
            matrix_summary_expected_path=self.matrix_summary_line_matches_expected_path,
            matrix_summary_matches_metadata=self.matrix_summary_path_matches_metadata,
            matrix_summary_line_matches_metadata_path=self.matrix_summary_line_matches_metadata_path,
            bundle_rerun_hint_matches_matrix_summary_hint=self.rerun_hint_line_matches_expected_hint,
        )

    def matrix_summary_assertion_selection(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionSelection:
        return self.matrix_summary_assertion_result_names().selected_selection(*checks)

    def matrix_summary_assertion_result_name_kwargs(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> dict[str, str]:
        return self.matrix_summary_assertion_selection(*checks).result_name_kwargs()

    def matrix_summary_assertion_true_check_names(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> tuple[str, ...]:
        return self.matrix_summary_assertion_selection(*checks).true_check_names()

    def matrix_summary_assertion_contract_metadata(
        self,
        *checks: SmokeMatrixDocsReviewMatrixSummaryAssertionCheck,
    ) -> SmokeScriptContractMetadata:
        return self.matrix_summary_assertion_selection(*checks).contract_metadata()

    def matrix_summary_assertion_bundle_selection(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> SmokeMatrixDocsReviewMatrixSummaryAssertionSelection:
        return self.matrix_summary_assertion_result_names().bundle_selection(
            bundle,
            excluding_checks=excluding_checks,
        )

    def matrix_summary_assertion_result_name_bundle_kwargs(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> dict[str, str]:
        return self.matrix_summary_assertion_bundle_selection(
            bundle,
            excluding_checks=excluding_checks,
        ).result_name_kwargs()

    def matrix_summary_assertion_bundle_true_check_names(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> tuple[str, ...]:
        return self.matrix_summary_assertion_bundle_selection(
            bundle,
            excluding_checks=excluding_checks,
        ).true_check_names()

    def matrix_summary_assertion_bundle_contract_metadata(
        self,
        bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
        *,
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> SmokeScriptContractMetadata:
        return self.matrix_summary_assertion_bundle_selection(
            bundle,
            excluding_checks=excluding_checks,
        ).contract_metadata()

    def required_line_prefixes(
        self,
        *,
        success_defaults: SmokeMatrixDocsReviewSuccessDefaults,
    ) -> tuple[str, ...]:
        return (
            f"{self.artifact_root}: ",
            f"{self.metadata_line}: {SMOKE_MATRIX_REVIEW_METADATA_PREFIX}",
            f"{self.artifacts_line}: {SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX}",
            f"{self.matrix_summary_line}: {SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX}",
            f"{self.summary_line}: {success_defaults.success_summary_prefix}",
            f"{self.rerun_hint_line}: {success_defaults.rerun_hint_prefix}",
        )

    def true_check_names(self) -> tuple[str, ...]:
        return (
            self.exit_code_zero,
            self.stderr_empty,
            *self.observation.true_check_names(),
            self.metadata_matrix_summary_matches_expected_path,
            self.matrix_summary_line_matches_expected_path,
            self.rerun_hint_line_matches_expected_hint,
            self.paths_loaded_from_matrix_summary,
            self.artifacts_exist,
            self.summary_targets,
            self.summary_bundle_index_rerun_hint_matches,
            self.matrix_summary_path_matches_metadata,
            self.matrix_summary_line_matches_metadata_path,
            self.loaded_summary_path_matches_line,
            self.summary_path_keeps_artifact_root,
            self.summary_line_present,
            self.rerun_hint_line_present,
        )


def _smoke_matrix_docs_review_result_naming(
    requested_target_name: str,
) -> SmokeMatrixDocsReviewResultNaming:
    if requested_target_name == "review":
        return SmokeMatrixDocsReviewResultNaming(
            result_prefix="review",
            target_suffix="docs_review",
            artifact_suffix="review",
        )
    if requested_target_name == "all-review":
        return SmokeMatrixDocsReviewResultNaming(
            result_prefix="all_review",
            target_suffix="docs_review_all",
            artifact_suffix="all_review",
        )
    raise ValueError(f"unsupported docs-review smoke-matrix target: {requested_target_name!r}")


def build_smoke_matrix_docs_review_result_naming(
    requested_target_name: str,
    *,
    result_prefix: str | None = None,
) -> SmokeMatrixDocsReviewResultNaming:
    result_naming = _smoke_matrix_docs_review_result_naming(requested_target_name)
    if result_prefix is None or result_prefix == result_naming.result_prefix:
        return result_naming
    return SmokeMatrixDocsReviewResultNaming(
        result_prefix=result_prefix,
        target_suffix=result_naming.target_suffix,
        artifact_suffix=result_naming.artifact_suffix,
    )


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

    @property
    def result_naming(self) -> SmokeMatrixDocsReviewResultNaming:
        return build_smoke_matrix_docs_review_result_naming(self.requested_target_name)

    def observer_kwargs(self) -> dict[str, str]:
        return {
            "metadata_prefix": self.metadata_prefix,
            "artifacts_prefix": self.artifacts_prefix,
            "matrix_summary_prefix": self.matrix_summary_prefix,
        }

    def success_result_kwargs(self) -> dict[str, str]:
        return self.result_naming.success_result_kwargs()

    def failure_result_kwargs(
        self,
        *,
        detail_prefix: str = "stderr_",
        result_prefix: str = "",
    ) -> dict[str, str]:
        return self.result_naming.failure_result_kwargs(
            detail_prefix=detail_prefix,
            result_prefix=result_prefix,
        )

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


def load_smoke_matrix_docs_review_module_and_spec(
    script_path: Path,
    module_name: str,
    *,
    requested_target_name: Literal["review", "all-review"],
    driver_stem: str,
) -> tuple[Any, SmokeMatrixDocsReviewObserverSpec]:
    smoke_matrix_module = load_script_module(script_path, module_name)
    return smoke_matrix_module, build_smoke_matrix_docs_review_observer_spec(
        smoke_matrix_module,
        requested_target_name=requested_target_name,
        driver_stem=driver_stem,
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


def _normalize_review_artifact_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    return str(path)


@dataclass(frozen=True)
class SmokeMatrixDocsReviewSuccessDefaults:
    success_summary_prefix: str
    rerun_hint_prefix: str

    def format_success_summary_line(self, elapsed_seconds: float | str) -> str:
        elapsed_suffix = (
            elapsed_seconds if isinstance(elapsed_seconds, str) else f"{elapsed_seconds:.2f}s"
        )
        return f"{self.success_summary_prefix}{elapsed_suffix}"

    def matches_success_summary_line(self, line: str) -> bool:
        return line.startswith(self.success_summary_prefix)

    def format_bundle_rerun_hint_line(self, rerun_hint: str) -> str:
        return f"{self.rerun_hint_prefix}{rerun_hint}"

    def format_rerun_hint_line(self, rerun_hint: str) -> str:
        return self.format_bundle_rerun_hint_line(rerun_hint)

    def format_rerun_hint_message(self, rerun_hint: str) -> str:
        return self.format_rerun_hint_line(rerun_hint).removeprefix("[smoke-matrix] ")

    def bundle_rerun_hint_line_prefix(self) -> str:
        return self.rerun_hint_prefix


def build_smoke_matrix_review_metadata_payload(
    *,
    artifact_root: str | Path | None = None,
    bundle_index_path: str | Path | None = None,
    matrix_summary_path: str | Path | None = None,
    drifted_readme_path: str | Path | None = None,
    render_output_dir: str | Path | None = None,
    render_manifest_path: str | Path | None = None,
    render_diff_path: str | Path | None = None,
    fix_check_json_path: str | Path | None = None,
    fix_repair_json_path: str | Path | None = None,
    fix_post_check_json_path: str | Path | None = None,
    bundle_index_rerun_hint: str | None = None,
    display_name: str = "docs-review",
    target_name: str = "docs-review",
) -> dict[str, str]:
    artifact_root = _normalize_review_artifact_path(artifact_root)
    bundle_index_path = _normalize_review_artifact_path(bundle_index_path)
    matrix_summary_path = _normalize_review_artifact_path(matrix_summary_path)
    drifted_readme_path = _normalize_review_artifact_path(drifted_readme_path)
    render_output_dir = _normalize_review_artifact_path(render_output_dir)
    render_manifest_path = _normalize_review_artifact_path(render_manifest_path)
    render_diff_path = _normalize_review_artifact_path(render_diff_path)
    fix_check_json_path = _normalize_review_artifact_path(fix_check_json_path)
    fix_repair_json_path = _normalize_review_artifact_path(fix_repair_json_path)
    fix_post_check_json_path = _normalize_review_artifact_path(fix_post_check_json_path)

    if artifact_root is None and bundle_index_path is not None:
        artifact_root = str(Path(bundle_index_path).parent)

    if artifact_root is not None:
        artifact_root_path = Path(artifact_root)
        bundle_index_path = bundle_index_path or str(artifact_root_path / "index.json")
        matrix_summary_path = matrix_summary_path or str(
            artifact_root_path / "matrix-summary.json"
        )
        drifted_readme_path = drifted_readme_path or str(
            artifact_root_path / "README-drifted.md"
        )
        render_output_dir = render_output_dir or str(artifact_root_path / "rendered")
        render_manifest_path = render_manifest_path or str(
            artifact_root_path / "render-manifest.json"
        )
        render_diff_path = render_diff_path or str(artifact_root_path / "render-review.patch")
        fix_check_json_path = fix_check_json_path or str(artifact_root_path / "fix-check.json")
        fix_repair_json_path = fix_repair_json_path or str(artifact_root_path / "fix-repair.json")
        fix_post_check_json_path = fix_post_check_json_path or str(
            artifact_root_path / "fix-post-check.json"
        )

    payload = {
        "display_name": display_name,
        "target_name": target_name,
        "bundle_index_rerun_hint": bundle_index_rerun_hint or smoke_cli_docs_parity_rerun_hint(),
    }
    optional_paths = (
        ("artifact_root", artifact_root),
        ("bundle_index_path", bundle_index_path),
        ("drifted_readme_path", drifted_readme_path),
        ("render_output_dir", render_output_dir),
        ("render_manifest_path", render_manifest_path),
        ("render_diff_path", render_diff_path),
        ("fix_check_json_path", fix_check_json_path),
        ("fix_repair_json_path", fix_repair_json_path),
        ("fix_post_check_json_path", fix_post_check_json_path),
        ("matrix_summary_path", matrix_summary_path),
    )
    for key, value in optional_paths:
        if value is not None:
            payload[key] = value
    return payload


def build_smoke_matrix_review_metadata_line(**kwargs: object) -> str:
    return (
        f"{SMOKE_MATRIX_REVIEW_METADATA_PREFIX}"
        f"{json.dumps(build_smoke_matrix_review_metadata_payload(**kwargs), sort_keys=True)}"
    )


@dataclass(frozen=True)
class SmokeMatrixDocsReviewObservationFixture:
    review_output: ReviewArtifactOutputObservation
    review_spec: SmokeMatrixDocsReviewObserverSpec
    metadata_payload: dict[str, str]
    summary_path: Path


def build_smoke_matrix_docs_review_observation_fixture(
    checkout_root: Path,
    *,
    requested_target_name: Literal["review", "all-review"],
    artifact_root: str = "artifacts/review",
    bundle_index_rerun_hint: str | None = None,
    driver_filename: str = "unused.py",
) -> SmokeMatrixDocsReviewObservationFixture:
    if requested_target_name == "review":
        target_name = "docs-review"
    elif requested_target_name == "all-review":
        target_name = "docs-review-all"
    else:
        raise ValueError(
            "requested_target_name must be one of {'review', 'all-review'}"
        )

    metadata_payload = build_smoke_matrix_review_metadata_payload(
        artifact_root=artifact_root,
        bundle_index_rerun_hint=bundle_index_rerun_hint,
        display_name=target_name,
        target_name=target_name,
    )
    expected_artifact_paths = {
        key: value
        for key, value in metadata_payload.items()
        if key not in {"display_name", "target_name", "bundle_index_rerun_hint"}
    }
    summary_path = resolve_checkout_path(
        metadata_payload["matrix_summary_path"],
        checkout_root=checkout_root,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(metadata_payload, indent=2) + "\n", encoding="utf-8")

    review_output = collect_review_artifact_output(
        [
            build_smoke_matrix_review_metadata_line(**metadata_payload),
            f"{SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX}{metadata_payload['artifact_root']}",
            (
                f"{SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX}"
                f"{metadata_payload['matrix_summary_path']}"
            ),
        ],
        checkout_root=checkout_root,
        metadata_prefix=SMOKE_MATRIX_REVIEW_METADATA_PREFIX,
        artifacts_prefix=SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX,
        matrix_summary_prefix=SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX,
    )
    review_spec = SmokeMatrixDocsReviewObserverSpec(
        requested_target_name=requested_target_name,
        expected_target_name=target_name,
        expected_artifact_root=metadata_payload["artifact_root"],
        expected_matrix_summary_path=metadata_payload["matrix_summary_path"],
        expected_bundle_index_rerun_hint=metadata_payload["bundle_index_rerun_hint"],
        expected_artifact_paths=expected_artifact_paths,
        driver_filename=driver_filename,
    )
    return SmokeMatrixDocsReviewObservationFixture(
        review_output=review_output,
        review_spec=review_spec,
        metadata_payload=metadata_payload,
        summary_path=summary_path,
    )


def build_smoke_matrix_review_artifact_location_messages(
    *,
    artifact_root: str | None = None,
    bundle_index_path: str | None = None,
    matrix_summary_path: str | None = None,
    drifted_readme_path: str | None = None,
    render_output_dir: str | None = None,
    render_manifest_path: str | None = None,
    render_diff_path: str | None = None,
    fix_check_json_path: str | None = None,
    fix_repair_json_path: str | None = None,
    fix_post_check_json_path: str | None = None,
    rerun_hint: str | None = None,
    success_defaults: SmokeMatrixDocsReviewSuccessDefaults,
) -> tuple[str, ...]:
    metadata = build_smoke_matrix_review_metadata_payload(
        artifact_root=artifact_root,
        bundle_index_path=bundle_index_path,
        matrix_summary_path=matrix_summary_path,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        fix_check_json_path=fix_check_json_path,
        fix_repair_json_path=fix_repair_json_path,
        fix_post_check_json_path=fix_post_check_json_path,
        bundle_index_rerun_hint=rerun_hint,
    )
    artifact_root = metadata.get("artifact_root")
    bundle_index_path = metadata.get("bundle_index_path")
    matrix_summary_path = metadata.get("matrix_summary_path")
    drifted_readme_path = metadata.get("drifted_readme_path")
    render_output_dir = metadata.get("render_output_dir")
    render_manifest_path = metadata.get("render_manifest_path")
    render_diff_path = metadata.get("render_diff_path")
    fix_check_json_path = metadata.get("fix_check_json_path")
    fix_repair_json_path = metadata.get("fix_repair_json_path")
    fix_post_check_json_path = metadata.get("fix_post_check_json_path")
    rerun_hint = metadata.get("bundle_index_rerun_hint")

    messages: list[str] = []
    if artifact_root and bundle_index_path:
        messages.append(f"review artifacts: {artifact_root} (index: {bundle_index_path})")
    elif bundle_index_path:
        messages.append(f"review artifact index: {bundle_index_path}")
    elif artifact_root:
        messages.append(f"review artifacts: {artifact_root}")

    if matrix_summary_path:
        messages.append(f"review matrix summary: {matrix_summary_path}")
    if rerun_hint:
        messages.append(success_defaults.format_rerun_hint_message(rerun_hint))
    if drifted_readme_path:
        messages.append(f"review drifted README: {drifted_readme_path}")
    if render_output_dir:
        messages.append(f"review rendered sections: {render_output_dir}")
    if render_manifest_path:
        messages.append(f"review render manifest: {render_manifest_path}")
    if render_diff_path:
        messages.append(f"review render diff: {render_diff_path}")
    if fix_check_json_path:
        messages.append(f"review fix-check JSON: {fix_check_json_path}")
    if fix_repair_json_path:
        messages.append(f"review fix-repair JSON: {fix_repair_json_path}")
    if fix_post_check_json_path:
        messages.append(f"review fix-post-check JSON: {fix_post_check_json_path}")
    return tuple(messages)


def build_smoke_matrix_review_artifact_location_lines(
    **kwargs: object,
) -> tuple[str, ...]:
    return tuple(
        f"[smoke-matrix] {message}"
        for message in build_smoke_matrix_review_artifact_location_messages(**kwargs)
    )


@dataclass(frozen=True)
class SmokeMatrixDocsReviewFailureDefaults:
    failure_summary_prefix: str
    failed_line_prefix: str | None = None
    failed_line_exact: str | None = None
    bundle_rerun_hint_prefix: str | None = None
    docs_review_only_hint_prefix: str | None = None
    live_runtime_hint_prefix: str | None = None
    missing_api_key_hint_prefix: str | None = None
    stdout_running_prefix: str | None = None

    def __post_init__(self) -> None:
        if (self.failed_line_prefix is None) == (self.failed_line_exact is None):
            raise ValueError(
                "provide exactly one failed-line matcher: failed_line_prefix or failed_line_exact"
            )

    def bundle_rerun_hint_line_prefix(self) -> str | None:
        return self.bundle_rerun_hint_prefix

    def format_bundle_rerun_hint_line(self, rerun_hint: str) -> str | None:
        prefix = self.bundle_rerun_hint_line_prefix()
        if prefix is None:
            return None
        return f"{prefix}{rerun_hint}"

    def collect_kwargs(self) -> dict[str, str]:
        kwargs: dict[str, str] = {"failure_summary_prefix": self.failure_summary_prefix}
        optional_fields = (
            "failed_line_prefix",
            "failed_line_exact",
            "bundle_rerun_hint_prefix",
            "docs_review_only_hint_prefix",
            "live_runtime_hint_prefix",
            "missing_api_key_hint_prefix",
        )
        for field_name in optional_fields:
            value = getattr(self, field_name)
            if value is not None:
                kwargs[field_name] = value
        return kwargs


SmokeMatrixDocsReviewFailureLineResultName = tuple[
    str,
    SmokeMatrixDocsReviewFailureStep,
]
SmokeMatrixDocsReviewFailureOrderingResultName = tuple[
    str,
    SmokeMatrixDocsReviewFailureStep,
    SmokeMatrixDocsReviewFailureStep,
]


@dataclass(frozen=True)
class SmokeMatrixDocsReviewFailureResultPreset:
    matrix_summary_bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle
    extra_line_result_names: tuple[SmokeMatrixDocsReviewFailureLineResultName, ...] = ()
    extra_present_result_names: tuple[SmokeMatrixDocsReviewFailureLineResultName, ...] = ()
    ordering_result_names: tuple[SmokeMatrixDocsReviewFailureOrderingResultName, ...] = ()
    failed_line_result_name: str = "stderr_failed_line"
    failed_line_detail_safe: bool = False
    stdout_last_line_result_name: str | None = None
    stdout_last_line_startswith_result_name: str | None = None
    stdout_last_line_startswith_prefix: str | None = None

    def _line_value_prefix_for_step(
        self,
        step: SmokeMatrixDocsReviewFailureStep,
        *,
        failure_defaults: SmokeMatrixDocsReviewFailureDefaults,
    ) -> str | None:
        if step == "bundle_rerun_hint":
            return failure_defaults.bundle_rerun_hint_line_prefix()
        if step == "docs_review_only_hint":
            return failure_defaults.docs_review_only_hint_prefix
        if step == "live_runtime_hint":
            return failure_defaults.live_runtime_hint_prefix
        if step == "missing_api_key_hint":
            return failure_defaults.missing_api_key_hint_prefix
        if step == "failure_summary":
            return failure_defaults.failure_summary_prefix
        return None

    def required_line_prefixes(
        self,
        *,
        failure_defaults: SmokeMatrixDocsReviewFailureDefaults,
        failed_line_value_prefix: str,
        stdout_last_line_value_prefix: str | None = None,
    ) -> tuple[str, ...]:
        required_line_prefixes: list[str] = []

        if self.stdout_last_line_result_name is not None:
            resolved_stdout_last_line_value_prefix = stdout_last_line_value_prefix
            if resolved_stdout_last_line_value_prefix is None:
                resolved_stdout_last_line_value_prefix = failure_defaults.stdout_running_prefix
            if resolved_stdout_last_line_value_prefix is None:
                raise ValueError(
                    "stdout_last_line_value_prefix or failure_defaults.stdout_running_prefix "
                    "is required when stdout_last_line_result_name is set"
                )
            required_line_prefixes.append(
                f"{self.stdout_last_line_result_name}: {resolved_stdout_last_line_value_prefix}"
            )

        required_line_prefixes.append(f"{self.failed_line_result_name}: {failed_line_value_prefix}")
        for result_name, step in self.extra_line_result_names:
            line_value_prefix = self._line_value_prefix_for_step(
                step,
                failure_defaults=failure_defaults,
            )
            if line_value_prefix is None:
                raise ValueError(
                    f"{step} line prefix is required when {result_name} is declared"
                )
            required_line_prefixes.append(f"{result_name}: {line_value_prefix}")

        required_line_prefixes.append(
            f"stderr_summary_line: {failure_defaults.failure_summary_prefix}"
        )
        return tuple(required_line_prefixes)

    def matrix_summary_contract_metadata(
        self,
        *,
        result_naming: SmokeMatrixDocsReviewResultNaming,
        result_prefix: str = "",
        excluding_checks: Sequence[SmokeMatrixDocsReviewMatrixSummaryAssertionCheck] = (),
    ) -> SmokeScriptContractMetadata:
        return result_naming.matrix_summary_assertion_bundle_contract_metadata(
            self.matrix_summary_bundle,
            result_prefix=result_prefix,
            excluding_checks=excluding_checks,
        )

    def true_check_names(
        self,
        *,
        result_naming: SmokeMatrixDocsReviewResultNaming,
        result_prefix: str = "",
        common_matrix_summary_excluding_checks: Sequence[
            SmokeMatrixDocsReviewMatrixSummaryAssertionCheck
        ] = (),
    ) -> tuple[str, ...]:
        return (
            *(result_name for result_name, _ in self.extra_present_result_names),
            *self.matrix_summary_contract_metadata(
                result_naming=result_naming,
                result_prefix=result_prefix,
                excluding_checks=common_matrix_summary_excluding_checks,
            ).true_check_names,
            *(result_name for result_name, _, _ in self.ordering_result_names),
            *(
                (self.stdout_last_line_startswith_result_name,)
                if self.stdout_last_line_startswith_result_name is not None
                else ()
            ),
        )

    def contract_metadata(
        self,
        *,
        failure_defaults: SmokeMatrixDocsReviewFailureDefaults,
        result_naming: SmokeMatrixDocsReviewResultNaming,
        failed_line_value_prefix: str,
        result_prefix: str = "",
        stdout_last_line_value_prefix: str | None = None,
        common_matrix_summary_excluding_checks: Sequence[
            SmokeMatrixDocsReviewMatrixSummaryAssertionCheck
        ] = (),
    ) -> SmokeScriptContractMetadata:
        return merge_smoke_script_contract_metadata(
            required_line_prefixes=self.required_line_prefixes(
                failure_defaults=failure_defaults,
                failed_line_value_prefix=failed_line_value_prefix,
                stdout_last_line_value_prefix=stdout_last_line_value_prefix,
            ),
            true_check_names=self.true_check_names(
                result_naming=result_naming,
                result_prefix=result_prefix,
                common_matrix_summary_excluding_checks=common_matrix_summary_excluding_checks,
            ),
        )

    def build_results(
        self,
        smoke_run: SmokeScriptRunResult,
        failure_output: SmokeMatrixDocsReviewFailureObservation,
        review_spec: SmokeMatrixDocsReviewObserverSpec,
        *,
        failure_defaults: SmokeMatrixDocsReviewFailureDefaults,
        detail_prefix: str = "stderr_",
        result_prefix: str = "",
    ) -> list[tuple[str, object]]:
        results = build_smoke_matrix_docs_review_failure_results(
            smoke_run,
            failure_output,
            review_spec,
            failure_defaults=failure_defaults,
            matrix_summary_bundle=self.matrix_summary_bundle,
            extra_line_result_names=self.extra_line_result_names,
            extra_present_result_names=self.extra_present_result_names,
            ordering_result_names=self.ordering_result_names,
            failed_line_result_name=self.failed_line_result_name,
            failed_line_detail_safe=self.failed_line_detail_safe,
            stdout_last_line_result_name=self.stdout_last_line_result_name,
            detail_prefix=detail_prefix,
            result_prefix=result_prefix,
        )
        if self.stdout_last_line_startswith_result_name is None:
            return results

        if self.stdout_last_line_result_name is None:
            raise ValueError(
                "stdout_last_line_result_name is required when "
                "stdout_last_line_startswith_result_name is set"
            )

        stdout_prefix = self.stdout_last_line_startswith_prefix
        if stdout_prefix is None:
            stdout_prefix = failure_defaults.stdout_running_prefix
        if stdout_prefix is None:
            raise ValueError(
                "stdout_last_line_startswith_prefix or failure_defaults.stdout_running_prefix "
                "is required when stdout_last_line_startswith_result_name is set"
            )

        stdout_last_line = dict(results).get(self.stdout_last_line_result_name, "")
        results.append(
            (
                self.stdout_last_line_startswith_result_name,
                str(stdout_last_line).startswith(stdout_prefix),
            )
        )
        return results


def resolve_smoke_matrix_docs_review_bundle_rerun_hint_prefix(
    defaults: SmokeMatrixDocsReviewSuccessDefaults | SmokeMatrixDocsReviewFailureDefaults | None,
) -> str | None:
    if defaults is None:
        return None
    return defaults.bundle_rerun_hint_line_prefix()


def format_smoke_matrix_docs_review_bundle_rerun_hint_line(
    rerun_hint: str,
    *,
    bundle_rerun_hint_prefix: str | None = None,
    bundle_rerun_hint_defaults: (
        SmokeMatrixDocsReviewSuccessDefaults | SmokeMatrixDocsReviewFailureDefaults | None
    ) = None,
) -> str | None:
    if bundle_rerun_hint_defaults is not None:
        return bundle_rerun_hint_defaults.format_bundle_rerun_hint_line(rerun_hint)
    if bundle_rerun_hint_prefix is None:
        return None
    return f"{bundle_rerun_hint_prefix}{rerun_hint}"


def smoke_matrix_docs_review_success_summary_prefix(
    *, passed_count: int = 4, total_count: int = 4
) -> str:
    return f"[smoke-matrix] summary: {passed_count}/{total_count} bundles passed in "


def smoke_matrix_docs_review_failure_summary_prefix(*, passed_count: int, total_count: int = 4) -> str:
    return f"[smoke-matrix] summary: {passed_count}/{total_count} bundles passed before failure in "


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


def build_standalone_docs_rerun_hint_contract() -> SmokeScriptContractMetadata:
    return SmokeScriptContractMetadata(
        required_line_prefixes=(
            "checkout_root: ",
            f"stdout_fix_check_summary: {STANDALONE_DOCS_RERUN_HINT_FIX_CHECK_SUMMARY_LINE}",
            f"stdout_false_line: {detail_safe_text(STANDALONE_DOCS_RERUN_HINT_FALSE_LINE)}",
            (
                "stderr_failed_line: "
                f"{detail_safe_text(STANDALONE_DOCS_RERUN_HINT_FAILED_LINE_PREFIX + STANDALONE_DOCS_RERUN_HINT_FALSE_LINE)}"
            ),
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


STANDALONE_DOCS_RERUN_HINT_CONTRACT = build_standalone_docs_rerun_hint_contract()
STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="standalone_docs_rerun_hint_smoke",
    runner_name="run_standalone_docs_rerun_hint_smoke",
    contract=STANDALONE_DOCS_RERUN_HINT_CONTRACT,
)

SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-review-only`;"
)
SMOKE_MATRIX_REVIEW_BUNDLE_RERUN_HINT_PREFIX = "[smoke-matrix] review bundle rerun hint: "
SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS = SmokeMatrixDocsReviewSuccessDefaults(
    success_summary_prefix=smoke_matrix_docs_review_success_summary_prefix(),
    rerun_hint_prefix=SMOKE_MATRIX_REVIEW_BUNDLE_RERUN_HINT_PREFIX,
)
SMOKE_MATRIX_DOCS_REVIEW_RUNNING_PREFIX = "[smoke-matrix] running docs-review"
SMOKE_MATRIX_DOCS_REVIEW_FAILED_LINE_PREFIX = "docs-review smoke failed fast: "
SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FALSE_FAILED_LINE = (
    "standalone smoke failed fast: live_runtime_requested= False"
)
SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_HINT_PREFIX = (
    "[smoke-matrix] hint: `smoke_matrix.py all` and `smoke_matrix.py all-review` swap in "
    "`standalone_smoke.py all`;"
)
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_RUNTIME_ERROR_LINE = (
    "RuntimeError: OPENAI_API_KEY is required for live runtime mode"
)
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILED_LINE = "standalone smoke exited with status 1"
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_HINT_PREFIX = (
    "[smoke-matrix] hint: `smoke_matrix.py all`/`all-review` reached the live runtime, but "
    "`OPENAI_API_KEY` was missing;"
)
SMOKE_MATRIX_DOCS_REVIEW_HINT_FALSE_LINE = "render_manifest_payload= False"
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_FIXTURE = SmokeTargetRunFailureFixture(
    observed_lines=(SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_RUNTIME_ERROR_LINE,),
    stderr_lines=(SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILED_LINE,),
)

SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS = SmokeMatrixDocsReviewFailureDefaults(
    failed_line_exact=SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FALSE_FAILED_LINE,
    live_runtime_hint_prefix=SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_HINT_PREFIX,
    docs_review_only_hint_prefix=SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
    failure_summary_prefix=smoke_matrix_docs_review_failure_summary_prefix(passed_count=0),
)
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS = SmokeMatrixDocsReviewFailureDefaults(
    failed_line_exact=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILED_LINE,
    bundle_rerun_hint_prefix=SMOKE_MATRIX_REVIEW_BUNDLE_RERUN_HINT_PREFIX,
    docs_review_only_hint_prefix=SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
    missing_api_key_hint_prefix=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_HINT_PREFIX,
    failure_summary_prefix=smoke_matrix_docs_review_failure_summary_prefix(passed_count=0),
)
SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS = SmokeMatrixDocsReviewFailureDefaults(
    failed_line_prefix=SMOKE_MATRIX_DOCS_REVIEW_FAILED_LINE_PREFIX,
    bundle_rerun_hint_prefix=SMOKE_MATRIX_REVIEW_BUNDLE_RERUN_HINT_PREFIX,
    docs_review_only_hint_prefix=SMOKE_MATRIX_DOCS_REVIEW_ONLY_HINT_PREFIX,
    failure_summary_prefix=smoke_matrix_docs_review_failure_summary_prefix(passed_count=3),
    stdout_running_prefix=SMOKE_MATRIX_DOCS_REVIEW_RUNNING_PREFIX,
)
SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_RESULT_PRESET = SmokeMatrixDocsReviewFailureResultPreset(
    matrix_summary_bundle="all_review_order_failure",
    extra_line_result_names=(
        ("stderr_hint_line", "live_runtime_hint"),
        ("stderr_docs_hint_line", "docs_review_only_hint"),
    ),
    extra_present_result_names=(
        ("hint_line_present", "live_runtime_hint"),
        ("docs_hint_line_present", "docs_review_only_hint"),
    ),
    ordering_result_names=(
        ("metadata_before_hint", "metadata", "live_runtime_hint"),
        ("artifacts_before_hint", "artifacts", "live_runtime_hint"),
        ("matrix_summary_before_hint", "matrix_summary", "live_runtime_hint"),
        ("live_hint_before_docs_hint", "live_runtime_hint", "docs_review_only_hint"),
        ("docs_hint_before_failure_summary", "docs_review_only_hint", "failure_summary"),
        ("metadata_before_failure_summary", "metadata", "failure_summary"),
        ("artifacts_before_failure_summary", "artifacts", "failure_summary"),
        ("matrix_summary_before_failure_summary", "matrix_summary", "failure_summary"),
    ),
    failed_line_detail_safe=True,
)
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_RESULT_PRESET = (
    SmokeMatrixDocsReviewFailureResultPreset(
        matrix_summary_bundle="all_review_missing_api_key_failure",
        extra_line_result_names=(
            ("stderr_missing_api_key_hint_line", "missing_api_key_hint"),
            ("stderr_bundle_rerun_hint_line", "bundle_rerun_hint"),
            ("stderr_docs_hint_line", "docs_review_only_hint"),
        ),
        extra_present_result_names=(
            ("missing_api_key_hint_line_present", "missing_api_key_hint"),
            ("bundle_rerun_hint_line_present", "bundle_rerun_hint"),
            ("docs_hint_line_present", "docs_review_only_hint"),
        ),
        ordering_result_names=(
            ("metadata_before_missing_api_key_hint", "metadata", "missing_api_key_hint"),
            ("artifacts_before_missing_api_key_hint", "artifacts", "missing_api_key_hint"),
            (
                "matrix_summary_before_missing_api_key_hint",
                "matrix_summary",
                "missing_api_key_hint",
            ),
            (
                "bundle_rerun_hint_before_missing_api_key_hint",
                "bundle_rerun_hint",
                "missing_api_key_hint",
            ),
            (
                "bundle_rerun_hint_before_docs_hint",
                "bundle_rerun_hint",
                "docs_review_only_hint",
            ),
            (
                "missing_api_key_hint_before_docs_hint",
                "missing_api_key_hint",
                "docs_review_only_hint",
            ),
            ("docs_hint_before_failure_summary", "docs_review_only_hint", "failure_summary"),
            ("metadata_before_failure_summary", "metadata", "failure_summary"),
            ("artifacts_before_failure_summary", "artifacts", "failure_summary"),
            ("matrix_summary_before_failure_summary", "matrix_summary", "failure_summary"),
        ),
    )
)
SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_RESULT_PRESET = SmokeMatrixDocsReviewFailureResultPreset(
    matrix_summary_bundle="docs_review_hint_failure",
    extra_line_result_names=(
        ("stderr_bundle_rerun_hint_line", "bundle_rerun_hint"),
        ("stderr_hint_line", "docs_review_only_hint"),
    ),
    extra_present_result_names=(
        ("bundle_rerun_hint_line_present", "bundle_rerun_hint"),
        ("hint_line_present", "docs_review_only_hint"),
    ),
    ordering_result_names=(
        ("bundle_rerun_hint_after_matrix_summary", "matrix_summary", "bundle_rerun_hint"),
        ("hint_after_matrix_summary", "matrix_summary", "docs_review_only_hint"),
        ("bundle_rerun_hint_before_docs_hint", "bundle_rerun_hint", "docs_review_only_hint"),
        ("hint_before_failure_summary", "docs_review_only_hint", "failure_summary"),
    ),
    failed_line_detail_safe=True,
    stdout_last_line_result_name="stdout_last_line",
    stdout_last_line_startswith_result_name="stdout_docs_review_started",
)

_ALL_REVIEW_FAILURE_RESULT_NAMING = build_smoke_matrix_docs_review_result_naming(
    "all-review",
    result_prefix="",
)
_ALL_REVIEW_FAILURE_OBSERVATION_RESULT_NAMES = (
    _ALL_REVIEW_FAILURE_RESULT_NAMING.observation_result_names()
)
_ALL_REVIEW_FAILURE_MATRIX_SUMMARY_ASSERTION_RESULT_NAMES = (
    _ALL_REVIEW_FAILURE_RESULT_NAMING.matrix_summary_assertion_result_names()
)

_DOCS_REVIEW_MATRIX_COMMON_FAILURE_MATRIX_SUMMARY_ASSERTION_CHECKS = (
    "metadata_expected_path",
)
_DOCS_REVIEW_MATRIX_COMMON_FAILURE_MATRIX_SUMMARY_ASSERTION_CONTRACT = (
    _ALL_REVIEW_FAILURE_MATRIX_SUMMARY_ASSERTION_RESULT_NAMES.selected_contract_metadata(
        *_DOCS_REVIEW_MATRIX_COMMON_FAILURE_MATRIX_SUMMARY_ASSERTION_CHECKS
    )
)

_DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT = merge_smoke_script_contract_metadata(
    _DOCS_REVIEW_MATRIX_COMMON_FAILURE_MATRIX_SUMMARY_ASSERTION_CONTRACT,
    required_line_prefixes=(
        "checkout_root: ",
        'stderr_metadata_line: [smoke-matrix] review metadata: {"artifact_root": ',
        "stderr_artifacts_line: [smoke-matrix] review artifacts: ",
        "stderr_matrix_summary_line: [smoke-matrix] review matrix summary: ",
    ),
    true_check_names=(
        "exit_code_non_zero",
        "failed_line_present",
        "summary_line_present",
        *_ALL_REVIEW_FAILURE_OBSERVATION_RESULT_NAMES.true_check_names(),
    ),
)

SMOKE_MATRIX_ALL_REVIEW_ORDER_CONTRACT = merge_smoke_script_contract_metadata(
    _DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT,
    SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_RESULT_PRESET.contract_metadata(
        failure_defaults=SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS,
        result_naming=_ALL_REVIEW_FAILURE_RESULT_NAMING,
        failed_line_value_prefix=detail_safe_text(
            SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FALSE_FAILED_LINE
        ),
        common_matrix_summary_excluding_checks=(
            _DOCS_REVIEW_MATRIX_COMMON_FAILURE_MATRIX_SUMMARY_ASSERTION_CHECKS
        ),
    ),
)
SMOKE_MATRIX_ALL_REVIEW_ORDER_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_matrix_all_review_order_smoke",
    runner_name="run_smoke_matrix_all_review_order_smoke",
    contract=SMOKE_MATRIX_ALL_REVIEW_ORDER_CONTRACT,
)

SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_CONTRACT = merge_smoke_script_contract_metadata(
    _DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT,
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_RESULT_PRESET.contract_metadata(
        failure_defaults=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS,
        result_naming=_ALL_REVIEW_FAILURE_RESULT_NAMING,
        failed_line_value_prefix=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILED_LINE,
        common_matrix_summary_excluding_checks=(
            _DOCS_REVIEW_MATRIX_COMMON_FAILURE_MATRIX_SUMMARY_ASSERTION_CHECKS
        ),
    ),
)
SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_matrix_all_review_missing_api_key_smoke",
    runner_name="run_smoke_matrix_all_review_missing_api_key_smoke",
    contract=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_CONTRACT,
)

SMOKE_MATRIX_DOCS_REVIEW_HINT_CONTRACT = merge_smoke_script_contract_metadata(
    _DOCS_REVIEW_MATRIX_COMMON_FAILURE_CONTRACT,
    SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_RESULT_PRESET.contract_metadata(
        failure_defaults=SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS,
        result_naming=_ALL_REVIEW_FAILURE_RESULT_NAMING,
        failed_line_value_prefix=detail_safe_text(
            f"docs-review smoke failed fast: {SMOKE_MATRIX_DOCS_REVIEW_HINT_FALSE_LINE}"
        ),
        stdout_last_line_value_prefix=SMOKE_MATRIX_DOCS_REVIEW_RUNNING_PREFIX,
        common_matrix_summary_excluding_checks=(
            _DOCS_REVIEW_MATRIX_COMMON_FAILURE_MATRIX_SUMMARY_ASSERTION_CHECKS
        ),
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

_SMOKE_MATRIX_ARTIFACT_ROOTS_REVIEW_RESULT_NAMES = build_smoke_matrix_docs_review_result_naming(
    "review"
).success_result_names()
_SMOKE_MATRIX_ARTIFACT_ROOTS_ALL_REVIEW_RESULT_NAMES = build_smoke_matrix_docs_review_result_naming(
    "all-review"
).success_result_names()

SMOKE_MATRIX_ARTIFACT_ROOTS_CONTRACT = SmokeScriptContractMetadata(
    required_line_prefixes=("checkout_root: ",)
    + _SMOKE_MATRIX_ARTIFACT_ROOTS_REVIEW_RESULT_NAMES.required_line_prefixes(
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    )
    + _SMOKE_MATRIX_ARTIFACT_ROOTS_ALL_REVIEW_RESULT_NAMES.required_line_prefixes(
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    ),
    true_check_names=_SMOKE_MATRIX_ARTIFACT_ROOTS_REVIEW_RESULT_NAMES.true_check_names()
    + _SMOKE_MATRIX_ARTIFACT_ROOTS_ALL_REVIEW_RESULT_NAMES.true_check_names()
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

SESSION_TRIAGE_INTERVENTION_MIX_CONTRACT = SmokeScriptContractMetadata(
    required_line_prefixes=(
        "checkout_root: ",
        "stdout_picker_surface_line: picker_intervention_surface= True",
        "stdout_picker_target_mix_line: picker_intervention_target_mix= True",
        "stdout_picker_continuation_mix_line: picker_intervention_continuation_mix= True",
        "stdout_switcher_filter_line: switcher_intervention_filter= True",
        "stdout_switcher_target_mix_line: switcher_intervention_target_mix= True",
        "stdout_switcher_continuation_mix_line: switcher_intervention_continuation_mix= True",
        "stdout_summary_line: [session-triage-smoke] summary: 2/2 targets passed in ",
        "stderr_summary: ",
    ),
    true_check_names=(
        "exit_code_zero",
        "stderr_empty",
        "picker_surface_line_present",
        "picker_target_mix_line_present",
        "picker_continuation_mix_line_present",
        "switcher_filter_line_present",
        "switcher_target_mix_line_present",
        "switcher_continuation_mix_line_present",
        "summary_line_present",
        "picker_target_mix_after_picker_surface",
        "picker_continuation_mix_after_picker_target_mix",
        "switcher_filter_after_picker_continuation_mix",
        "switcher_target_mix_after_switcher_filter",
        "switcher_continuation_mix_after_switcher_target_mix",
        "summary_after_switcher_continuation_mix",
    ),
)
SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="session_triage_intervention_mix_smoke",
    runner_name="run_session_triage_intervention_mix_smoke",
    contract=SESSION_TRIAGE_INTERVENTION_MIX_CONTRACT,
)

DEFAULT_MALFORMED_SMOKE_SCRIPT_RESULT_ENTRY = ("malformed", "value", "extra")


@dataclass(frozen=True)
class _MalformedSmokeScriptBasePreset:
    source_case: SmokeScriptContractCase
    source_contract_script_name_result_name: str = "source_contract_script_name"
    source_result_count_result_name: str = "source_result_count"
    source_contract_valid_check_name: str = "source_contract_valid"
    source_result_count_positive_check_name: str = "source_result_count_positive"

    def required_line_prefixes(self) -> tuple[str, str]:
        return (
            f"{self.source_contract_script_name_result_name}: {self.source_case.script_name}",
            f"{self.source_result_count_result_name}: ",
        )

    def true_check_names(self) -> tuple[str, str]:
        return (
            self.source_contract_valid_check_name,
            self.source_result_count_positive_check_name,
        )

    def detail_results(self, *, source_result_count: int) -> list[tuple[str, object]]:
        return [
            (self.source_contract_script_name_result_name, self.source_case.script_name),
            (self.source_result_count_result_name, source_result_count),
        ]

    def check_results(self, *, source_result_count: int) -> list[tuple[str, object]]:
        return [
            (self.source_contract_valid_check_name, True),
            (self.source_result_count_positive_check_name, source_result_count > 0),
        ]


@dataclass(frozen=True)
class _MalformedSmokeScriptResultPreset:
    base: _MalformedSmokeScriptBasePreset
    malformed_entry: object = DEFAULT_MALFORMED_SMOKE_SCRIPT_RESULT_ENTRY
    malformed_entry_result_name: str = "malformed_entry"
    assertion_message_result_name: str = "assertion_message"
    malformed_result_reported_check_name: str = "malformed_result_reported"
    malformed_result_index_matches_source_length_check_name: str = (
        "malformed_result_index_matches_source_length"
    )
    malformed_result_mentions_entry_check_name: str = "malformed_result_mentions_entry"

    @property
    def malformed_entry_text(self) -> str:
        return repr(self.malformed_entry)

    def contract_metadata(self) -> SmokeScriptContractMetadata:
        return SmokeScriptContractMetadata(
            required_line_prefixes=(
                *self.base.required_line_prefixes(),
                f"{self.malformed_entry_result_name}: {self.malformed_entry_text}",
                f"{self.assertion_message_result_name}: result[",
            ),
            true_check_names=(
                *self.base.true_check_names(),
                self.malformed_result_reported_check_name,
                self.malformed_result_index_matches_source_length_check_name,
                self.malformed_result_mentions_entry_check_name,
            ),
        )

    def result_index_assertion_message(self, *, malformed_index: int) -> str:
        return _malformed_smoke_script_result_entry_name(
            malformed_index,
            self.malformed_entry,
        )

    def build_results(
        self,
        *,
        source_result_count: int,
        assertion_message: str,
        malformed_index: int,
    ) -> list[tuple[str, object]]:
        return [
            *self.base.detail_results(source_result_count=source_result_count),
            (self.malformed_entry_result_name, self.malformed_entry_text),
            (self.assertion_message_result_name, assertion_message),
            *self.base.check_results(source_result_count=source_result_count),
            (
                self.malformed_result_reported_check_name,
                assertion_message == self.result_index_assertion_message(malformed_index=malformed_index),
            ),
            (
                self.malformed_result_index_matches_source_length_check_name,
                assertion_message.startswith(f"result[{malformed_index}]: "),
            ),
            (
                self.malformed_result_mentions_entry_check_name,
                self.malformed_entry_text in assertion_message,
            ),
        ]


@dataclass(frozen=True)
class _MalformedSmokeScriptDetailPreset:
    base: _MalformedSmokeScriptBasePreset
    detail_name: str
    expected_detail_prefix: str
    mismatched_detail_value: str
    malformed_detail_name_result_name: str = "malformed_detail_name"
    expected_detail_prefix_result_name: str = "expected_detail_prefix"
    mismatched_detail_value_result_name: str = "mismatched_detail_value"
    missing_detail_assertion_result_name: str = "missing_detail_assertion"
    mismatched_detail_assertion_result_name: str = "mismatched_detail_assertion"
    boolean_detail_assertion_result_name: str = "boolean_detail_assertion"
    malformed_detail_name_present_check_name: str = "malformed_detail_name_present"
    expected_detail_prefix_present_check_name: str = "expected_detail_prefix_present"
    missing_detail_reported_check_name: str = "missing_detail_reported"
    mismatched_detail_prefix_reported_check_name: str = "mismatched_detail_prefix_reported"
    boolean_detail_reported_check_name: str = "boolean_detail_reported"
    mismatched_detail_mentions_expected_prefix_check_name: str = (
        "mismatched_detail_mentions_expected_prefix"
    )

    def contract_metadata(self) -> SmokeScriptContractMetadata:
        return SmokeScriptContractMetadata(
            required_line_prefixes=(
                *self.base.required_line_prefixes(),
                f"{self.malformed_detail_name_result_name}: {self.detail_name}",
                f"{self.expected_detail_prefix_result_name}: {self.expected_detail_prefix}",
                f"{self.mismatched_detail_value_result_name}: {self.mismatched_detail_value}",
                f"{self.missing_detail_assertion_result_name}: {self.detail_name}",
                f"{self.mismatched_detail_assertion_result_name}: {self.detail_name}",
                f"{self.boolean_detail_assertion_result_name}: {self.detail_name}",
            ),
            true_check_names=(
                *self.base.true_check_names(),
                self.malformed_detail_name_present_check_name,
                self.expected_detail_prefix_present_check_name,
                self.missing_detail_reported_check_name,
                self.mismatched_detail_prefix_reported_check_name,
                self.boolean_detail_reported_check_name,
                self.mismatched_detail_mentions_expected_prefix_check_name,
            ),
        )

    def build_results(
        self,
        *,
        source_result_count: int,
        missing_detail_assertion: str,
        mismatched_detail_assertion: str,
        boolean_detail_assertion: str,
    ) -> list[tuple[str, object]]:
        return [
            *self.base.detail_results(source_result_count=source_result_count),
            (self.malformed_detail_name_result_name, self.detail_name),
            (self.expected_detail_prefix_result_name, self.expected_detail_prefix),
            (self.mismatched_detail_value_result_name, self.mismatched_detail_value),
            (self.missing_detail_assertion_result_name, missing_detail_assertion),
            (self.mismatched_detail_assertion_result_name, mismatched_detail_assertion),
            (self.boolean_detail_assertion_result_name, boolean_detail_assertion),
            *self.base.check_results(source_result_count=source_result_count),
            (self.malformed_detail_name_present_check_name, bool(self.detail_name)),
            (
                self.expected_detail_prefix_present_check_name,
                bool(self.expected_detail_prefix),
            ),
            (self.missing_detail_reported_check_name, missing_detail_assertion == self.detail_name),
            (
                self.mismatched_detail_prefix_reported_check_name,
                mismatched_detail_assertion == self.detail_name,
            ),
            (self.boolean_detail_reported_check_name, boolean_detail_assertion == self.detail_name),
            (
                self.mismatched_detail_mentions_expected_prefix_check_name,
                self.expected_detail_prefix in self.mismatched_detail_value,
            ),
        ]


def _build_malformed_smoke_script_result_preset(
    *,
    source_case: SmokeScriptContractCase,
    malformed_entry: object = DEFAULT_MALFORMED_SMOKE_SCRIPT_RESULT_ENTRY,
) -> _MalformedSmokeScriptResultPreset:
    return _MalformedSmokeScriptResultPreset(
        base=_MalformedSmokeScriptBasePreset(source_case=source_case),
        malformed_entry=malformed_entry,
    )


def _build_malformed_smoke_script_detail_preset(
    *,
    source_case: SmokeScriptContractCase,
) -> _MalformedSmokeScriptDetailPreset:
    detail_name, expected_detail_prefix = _required_smoke_script_detail_with_value_prefix(source_case)
    return _MalformedSmokeScriptDetailPreset(
        base=_MalformedSmokeScriptBasePreset(source_case=source_case),
        detail_name=detail_name,
        expected_detail_prefix=expected_detail_prefix,
        mismatched_detail_value=f"unexpected-{expected_detail_prefix}fixture",
    )


def build_malformed_smoke_script_result_contract(
    *,
    source_case: SmokeScriptContractCase,
    malformed_entry: object = DEFAULT_MALFORMED_SMOKE_SCRIPT_RESULT_ENTRY,
) -> SmokeScriptContractMetadata:
    return _build_malformed_smoke_script_result_preset(
        source_case=source_case,
        malformed_entry=malformed_entry,
    ).contract_metadata()


def _required_smoke_script_detail_with_value_prefix(
    case: SmokeScriptContractCase,
) -> tuple[str, str]:
    for required_line_prefix in case.required_line_prefixes:
        detail_name, separator, detail_value_prefix = required_line_prefix.partition(": ")
        assert separator, required_line_prefix
        if detail_value_prefix:
            return detail_name, detail_value_prefix
    raise AssertionError(f"no detail prefix found for {case.script_name}")


def build_malformed_smoke_script_detail_contract(
    *,
    source_case: SmokeScriptContractCase,
) -> SmokeScriptContractMetadata:
    return _build_malformed_smoke_script_detail_preset(
        source_case=source_case,
    ).contract_metadata()


SMOKE_SCRIPT_MALFORMED_RESULT_CONTRACT = build_malformed_smoke_script_result_contract(
    source_case=STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
)
SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_script_malformed_result_smoke",
    runner_name="run_smoke_script_malformed_result_smoke",
    contract=SMOKE_SCRIPT_MALFORMED_RESULT_CONTRACT,
)

SMOKE_SCRIPT_MALFORMED_DETAIL_CONTRACT = build_malformed_smoke_script_detail_contract(
    source_case=STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
)
SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT = SmokeScriptContractCase(
    script_name="smoke_script_malformed_detail_smoke",
    runner_name="run_smoke_script_malformed_detail_smoke",
    contract=SMOKE_SCRIPT_MALFORMED_DETAIL_CONTRACT,
)

SMOKE_SCRIPT_CONTRACT_CASES = (
    STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
    *DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS,
    SMOKE_MATRIX_ARTIFACT_ROOTS_SCRIPT_CONTRACT,
    SESSION_TRIAGE_INTERVENTION_MIX_SCRIPT_CONTRACT,
    SMOKE_SCRIPT_MALFORMED_RESULT_SCRIPT_CONTRACT,
    SMOKE_SCRIPT_MALFORMED_DETAIL_SCRIPT_CONTRACT,
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


_MISSING_SMOKE_RESULT = object()


def _malformed_smoke_script_result_entry_name(index: int, entry: object) -> str:
    return f"result[{index}]: {entry!r}"


def _normalize_smoke_script_result_items(
    results: Mapping[str, object] | Iterable[tuple[str, object]],
) -> Mapping[str, object] | tuple[tuple[str, object], ...]:
    if isinstance(results, Mapping):
        return results

    normalized: list[tuple[str, object]] = []
    for index, entry in enumerate(results):
        if not isinstance(entry, Sequence) or isinstance(entry, str | bytes) or len(entry) != 2:
            raise AssertionError(_malformed_smoke_script_result_entry_name(index, entry))
        normalized.append((entry[0], entry[1]))
    return tuple(normalized)


def _final_smoke_script_result_value(
    results: Mapping[str, object] | Iterable[tuple[str, object]],
    name: str,
) -> object:
    if isinstance(results, Mapping):
        return results.get(name, _MISSING_SMOKE_RESULT)

    value = _MISSING_SMOKE_RESULT
    for current_name, current_value in results:
        if current_name == name:
            value = current_value
    return value


def assert_smoke_script_results_match_contract(
    results: Mapping[str, object] | Iterable[tuple[str, object]],
    case: SmokeScriptContractCase,
) -> None:
    result_items = _normalize_smoke_script_result_items(results)

    for required_line_prefix in case.required_line_prefixes:
        detail_name, detail_value_prefix = smoke_contract_detail_expectation(required_line_prefix)
        detail_value = _final_smoke_script_result_value(result_items, detail_name)
        assert detail_value is not _MISSING_SMOKE_RESULT, detail_name
        assert not isinstance(detail_value, bool), detail_name
        assert str(detail_value).startswith(detail_value_prefix), detail_name

    for check_name in case.true_check_names:
        assert _final_smoke_script_result_value(result_items, check_name) is True, check_name


def _smoke_script_result_pairs(
    results: Mapping[str, object] | Iterable[tuple[str, object]],
) -> tuple[tuple[str, object], ...]:
    normalized_results = _normalize_smoke_script_result_items(results)
    if isinstance(normalized_results, Mapping):
        return tuple(normalized_results.items())
    return tuple(normalized_results)


def build_malformed_smoke_script_result_results(
    source_results: Mapping[str, object] | Iterable[tuple[str, object]],
    *,
    source_case: SmokeScriptContractCase,
    malformed_entry: object = DEFAULT_MALFORMED_SMOKE_SCRIPT_RESULT_ENTRY,
) -> list[tuple[str, object]]:
    source_result_pairs = _smoke_script_result_pairs(source_results)
    assert_smoke_script_results_match_contract(source_result_pairs, source_case)
    preset = _build_malformed_smoke_script_result_preset(
        source_case=source_case,
        malformed_entry=malformed_entry,
    )

    malformed_index = len(source_result_pairs)
    try:
        assert_smoke_script_results_match_contract(
            source_result_pairs + (malformed_entry,),
            source_case,
        )
    except AssertionError as error:
        assertion_message = str(error.args[0]) if error.args else ""
    else:
        assertion_message = ""

    return preset.build_results(
        source_result_count=len(source_result_pairs),
        assertion_message=assertion_message,
        malformed_index=malformed_index,
    )


def build_malformed_smoke_script_detail_results(
    source_results: Mapping[str, object] | Iterable[tuple[str, object]],
    *,
    source_case: SmokeScriptContractCase,
) -> list[tuple[str, object]]:
    source_result_pairs = _smoke_script_result_pairs(source_results)
    assert_smoke_script_results_match_contract(source_result_pairs, source_case)
    preset = _build_malformed_smoke_script_detail_preset(source_case=source_case)

    try:
        assert_smoke_script_results_match_contract(
            [
                (name, value)
                for name, value in source_result_pairs
                if name != preset.detail_name
            ],
            source_case,
        )
    except AssertionError as error:
        missing_detail_assertion = str(error.args[0]) if error.args else ""
    else:
        missing_detail_assertion = ""

    try:
        assert_smoke_script_results_match_contract(
            [
                (
                    name,
                    preset.mismatched_detail_value if name == preset.detail_name else value,
                )
                for name, value in source_result_pairs
            ],
            source_case,
        )
    except AssertionError as error:
        mismatched_detail_assertion = str(error.args[0]) if error.args else ""
    else:
        mismatched_detail_assertion = ""

    try:
        assert_smoke_script_results_match_contract(
            [
                (name, True if name == preset.detail_name else value)
                for name, value in source_result_pairs
            ],
            source_case,
        )
    except AssertionError as error:
        boolean_detail_assertion = str(error.args[0]) if error.args else ""
    else:
        boolean_detail_assertion = ""

    return preset.build_results(
        source_result_count=len(source_result_pairs),
        missing_detail_assertion=missing_detail_assertion,
        mismatched_detail_assertion=mismatched_detail_assertion,
        boolean_detail_assertion=boolean_detail_assertion,
    )


def build_standalone_docs_rerun_hint_results(
    smoke_run: SmokeScriptRunResult,
    failure_output: SmokeWrapperFailureObservation,
) -> list[tuple[str, object]]:
    expected_failure_fixture = STANDALONE_DOCS_PARITY_FOLLOW_UP_FAILURE_FIXTURES.require_fixture_for_target(
        "docs-artifacts"
    )
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
            expected_failure_fixture.stdout_line(0) in stdout_lines,
        ),
        ("false_line_present", expected_failure_fixture.failed_line in stdout_lines),
        (
            "failed_line_present",
            failure_output.failed_line
            == expected_failure_fixture.failed_fast_message(),
        ),
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


def build_review_artifact_observation_results(
    review_output: ReviewArtifactOutputObservation,
    review_spec: SmokeMatrixDocsReviewObserverSpec,
    *,
    result_prefix: str = "",
    line_detail_prefix: str = "",
) -> list[tuple[str, object]]:
    result_names = review_spec.result_naming.observation_result_names(
        result_prefix=result_prefix,
        line_detail_prefix=line_detail_prefix,
    )
    return [
        (result_names.metadata_line, review_output.metadata_line),
        (result_names.artifacts_line, review_output.artifacts_line),
        (result_names.matrix_summary_line, review_output.matrix_summary_line),
        (result_names.metadata_line_present, review_output.metadata_line_present),
        (result_names.artifacts_line_present, review_output.artifacts_line_present),
        (result_names.matrix_summary_line_present, review_output.matrix_summary_line_present),
        (
            result_names.metadata_targets,
            review_output.metadata_targets(review_spec.expected_target_name),
        ),
        (
            result_names.metadata_artifact_root_matches,
            review_output.metadata_artifact_root_matches(review_spec.expected_artifact_root),
        ),
        (
            result_names.metadata_bundle_index_rerun_hint_matches,
            review_output.metadata_bundle_index_rerun_hint_matches(
                review_spec.expected_bundle_index_rerun_hint
            ),
        ),
        (
            result_names.metadata_expected_artifact_paths_match,
            review_spec.metadata_artifact_paths_match(review_output),
        ),
        (
            result_names.metadata_resolved_paths_match_expected,
            review_spec.metadata_resolved_paths_match(review_output),
        ),
        (result_names.matrix_summary_artifact_exists, review_output.matrix_summary_artifact_exists),
        (
            result_names.matrix_summary_targets,
            review_output.matrix_summary_targets(review_spec.expected_target_name),
        ),
        (
            result_names.matrix_summary_artifact_root_matches,
            review_output.matrix_summary_artifact_root_matches(review_spec.expected_artifact_root),
        ),
        (
            result_names.matrix_summary_bundle_index_rerun_hint_matches,
            review_output.matrix_summary_bundle_index_rerun_hint_matches(
                review_spec.expected_bundle_index_rerun_hint
            ),
        ),
        (
            result_names.matrix_summary_expected_artifact_paths_match,
            review_spec.matrix_summary_artifact_paths_match(review_output),
        ),
        (
            result_names.matrix_summary_resolved_paths_match_expected,
            review_spec.matrix_summary_resolved_paths_match(review_output),
        ),
    ]


def build_review_artifact_failure_results(
    review_output: ReviewArtifactOutputObservation,
    review_spec: SmokeMatrixDocsReviewObserverSpec,
    *,
    detail_prefix: str = "stderr_",
    result_prefix: str = "",
) -> list[tuple[str, object]]:
    return build_review_artifact_observation_results(
        review_output,
        review_spec,
        result_prefix=result_prefix,
        line_detail_prefix=detail_prefix,
    )


def build_smoke_matrix_docs_review_failure_results(
    smoke_run: SmokeScriptRunResult,
    failure_output: SmokeMatrixDocsReviewFailureObservation,
    review_spec: SmokeMatrixDocsReviewObserverSpec,
    *,
    failure_defaults: SmokeMatrixDocsReviewFailureDefaults,
    matrix_summary_bundle: SmokeMatrixDocsReviewMatrixSummaryAssertionBundle,
    extra_line_result_names: Sequence[tuple[str, SmokeMatrixDocsReviewFailureStep]] = (),
    extra_present_result_names: Sequence[tuple[str, SmokeMatrixDocsReviewFailureStep]] = (),
    ordering_result_names: Sequence[
        tuple[str, SmokeMatrixDocsReviewFailureStep, SmokeMatrixDocsReviewFailureStep]
    ] = (),
    failed_line_result_name: str = "stderr_failed_line",
    failed_line_detail_safe: bool = False,
    stdout_last_line_result_name: str | None = None,
    detail_prefix: str = "stderr_",
    result_prefix: str = "",
) -> list[tuple[str, object]]:
    failed_line = failure_output.failed_line
    if failed_line_detail_safe:
        failed_line = detail_safe_text(failed_line)

    results: list[tuple[str, object]] = [("checkout_root", str(smoke_run.checkout_root))]
    if stdout_last_line_result_name is not None:
        stdout_lines = smoke_run.stdout_lines
        results.append((stdout_last_line_result_name, stdout_lines[-1] if stdout_lines else ""))

    results.extend(
        [
            (failed_line_result_name, failed_line),
            *build_review_artifact_failure_results(
                failure_output.review_output,
                review_spec,
                detail_prefix=detail_prefix,
                result_prefix=result_prefix,
            ),
        ]
    )
    results.extend(
        (result_name, failure_output.line(step))
        for result_name, step in extra_line_result_names
    )
    results.extend(
        [
            ("stderr_summary_line", failure_output.failure_summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", failure_output.present("failed")),
        ]
    )
    results.extend(
        (result_name, failure_output.present(step))
        for result_name, step in extra_present_result_names
    )
    results.append(("summary_line_present", failure_output.present("failure_summary")))

    matrix_summary_selection = review_spec.result_naming.matrix_summary_assertion_bundle_selection(
        matrix_summary_bundle,
        result_prefix=result_prefix,
    )
    matrix_summary_kwargs = matrix_summary_selection.result_name_kwargs()
    if "bundle_rerun_hint_result_name" in matrix_summary_kwargs:
        matrix_summary_kwargs.update(
            {
                "bundle_rerun_hint_line": failure_output.bundle_rerun_hint_line,
                "bundle_rerun_hint_defaults": failure_defaults,
            }
        )
    results.extend(
        build_review_artifact_matrix_summary_assertion_results(
            failure_output.review_output,
            review_spec,
            result_prefix=result_prefix,
            **matrix_summary_kwargs,
        )
    )
    results.extend(
        (result_name, failure_output.appears_before(left, right))
        for result_name, left, right in ordering_result_names
    )
    return results


def build_review_artifact_matrix_summary_assertion_results(
    review_output: ReviewArtifactOutputObservation,
    review_spec: SmokeMatrixDocsReviewObserverSpec,
    *,
    result_prefix: str = "",
    metadata_expected_path_result_name: str | None = None,
    matrix_summary_expected_path_result_name: str | None = None,
    matrix_summary_matches_metadata_result_name: str | None = None,
    matrix_summary_line_matches_metadata_result_name: str | None = None,
    bundle_rerun_hint_line: str | None = None,
    bundle_rerun_hint_prefix: str | None = None,
    bundle_rerun_hint_defaults: (
        SmokeMatrixDocsReviewSuccessDefaults | SmokeMatrixDocsReviewFailureDefaults | None
    ) = None,
    bundle_rerun_hint_result_name: str | None = None,
) -> list[tuple[str, object]]:
    resolved_bundle_rerun_hint_prefix = bundle_rerun_hint_prefix
    if resolved_bundle_rerun_hint_prefix is None:
        resolved_bundle_rerun_hint_prefix = resolve_smoke_matrix_docs_review_bundle_rerun_hint_prefix(
            bundle_rerun_hint_defaults
        )

    if bundle_rerun_hint_result_name is not None and (
        bundle_rerun_hint_line is None or resolved_bundle_rerun_hint_prefix is None
    ):
        raise ValueError(
            "bundle_rerun_hint_line and a bundle_rerun_hint prefix/defaults are required when "
            "bundle_rerun_hint_result_name is set"
        )

    prefix = _result_name_prefix(result_prefix)
    results: list[tuple[str, object]] = []
    expected_paths: dict[str, Path] | None = None

    def _result_name(name: str) -> str:
        if prefix and name.startswith(prefix):
            return name
        return f"{prefix}{name}"

    def _expected_matrix_summary_path() -> Path | None:
        nonlocal expected_paths
        if expected_paths is None:
            expected_paths = review_spec.resolve_expected_paths(checkout_root=review_output.checkout_root)
        return expected_paths.get("matrix_summary_path")

    if metadata_expected_path_result_name is not None:
        results.append(
            (
                _result_name(metadata_expected_path_result_name),
                review_output.metadata_matrix_summary_matches(review_spec.expected_matrix_summary_path),
            )
        )
    if matrix_summary_expected_path_result_name is not None:
        results.append(
            (
                _result_name(matrix_summary_expected_path_result_name),
                review_output.matrix_summary_path == _expected_matrix_summary_path(),
            )
        )
    if matrix_summary_matches_metadata_result_name is not None:
        results.append(
            (
                _result_name(matrix_summary_matches_metadata_result_name),
                review_output.matrix_summary_path_matches_metadata(),
            )
        )
    if matrix_summary_line_matches_metadata_result_name is not None:
        results.append(
            (
                _result_name(matrix_summary_line_matches_metadata_result_name),
                review_output.matrix_summary_line_matches_metadata_path(),
            )
        )
    if bundle_rerun_hint_result_name is not None:
        expected_bundle_rerun_hint_line = format_smoke_matrix_docs_review_bundle_rerun_hint_line(
            review_spec.expected_bundle_index_rerun_hint,
            bundle_rerun_hint_prefix=resolved_bundle_rerun_hint_prefix,
            bundle_rerun_hint_defaults=bundle_rerun_hint_defaults,
        )
        results.append(
            (
                _result_name(bundle_rerun_hint_result_name),
                bundle_rerun_hint_line == expected_bundle_rerun_hint_line,
            )
        )
    return results


def build_review_artifact_success_results(
    review_output: ReviewArtifactOutputObservation,
    review_spec: SmokeMatrixDocsReviewObserverSpec,
    *,
    result_prefix: str,
    success_summary_line: str,
    rerun_hint_line: str,
    success_defaults: SmokeMatrixDocsReviewSuccessDefaults,
    exit_code: int,
    stderr_text: str,
    artifacts_exist: bool,
) -> list[tuple[str, object]]:
    expected_paths = review_spec.resolve_expected_paths(checkout_root=review_output.checkout_root)
    artifact_root = review_output.matrix_summary_paths.get("artifact_root")
    result_names = review_spec.result_naming.success_result_names(result_prefix=result_prefix)
    return [
        (result_names.artifact_root, str(artifact_root) if artifact_root is not None else ""),
        *build_review_artifact_observation_results(
            review_output,
            review_spec,
            result_prefix=result_prefix,
        ),
        (result_names.summary_line, success_summary_line),
        (result_names.rerun_hint_line, rerun_hint_line),
        (result_names.exit_code_zero, exit_code == 0),
        (result_names.stderr_empty, stderr_text == ""),
        *build_review_artifact_matrix_summary_assertion_results(
            review_output,
            review_spec,
            result_prefix=result_prefix,
            **result_names.matrix_summary_assertion_result_name_kwargs(
                "metadata_expected_path",
                "matrix_summary_expected_path",
                "matrix_summary_matches_metadata",
                "matrix_summary_line_matches_metadata_path",
                "bundle_rerun_hint_matches_matrix_summary_hint",
            ),
            bundle_rerun_hint_line=rerun_hint_line,
            bundle_rerun_hint_defaults=success_defaults,
        ),
        (result_names.paths_loaded_from_matrix_summary, bool(review_output.matrix_summary_paths)),
        (result_names.artifacts_exist, artifacts_exist),
        (
            result_names.summary_targets,
            review_output.matrix_summary_targets(review_spec.expected_target_name),
        ),
        (
            result_names.summary_bundle_index_rerun_hint_matches,
            review_output.matrix_summary_bundle_index_rerun_hint_matches(
                review_spec.expected_bundle_index_rerun_hint
            ),
        ),
        (
            result_names.loaded_summary_path_matches_line,
            review_output.matrix_summary_paths.get("matrix_summary_path")
            == review_output.matrix_summary_path,
        ),
        (
            result_names.summary_path_keeps_artifact_root,
            artifact_root == expected_paths.get("artifact_root"),
        ),
        (
            result_names.summary_line_present,
            success_defaults.matches_success_summary_line(success_summary_line),
        ),
        (
            result_names.rerun_hint_line_present,
            rerun_hint_line.startswith(success_defaults.rerun_hint_prefix),
        ),
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
