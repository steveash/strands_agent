from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import TextIO

from strands_agent_tui.testing import (
    NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES,
    SMOKE_MATRIX_WRAPPER,
    SmokeScriptTarget,
    run_smoke_target,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
CLI_SPEC = smoke_wrapper_cli_spec("smoke_matrix")
SMOKE_BUNDLES = CLI_SPEC.build_targets(script_dir=SCRIPT_DIR)
LOCAL_BUNDLE_NAMES = list(CLI_SPEC.default_target_names())
ALL_BUNDLE_NAMES = list(CLI_SPEC.resolve_target_names("all"))
SUPPRESSED_NESTED_SUMMARY_PREFIXES = NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES
LIVE_INCLUSIVE_STANDALONE_TARGET_NAME = "standalone-all"
DOCS_REVIEW_TARGET_NAME = "docs-review"
DOCS_REVIEW_ALL_TARGET_NAME = "docs-review-all"
DOCS_REVIEW_OUTPUT_DIR_FLAG = "--output-dir"
DOCS_REVIEW_BUNDLE_INDEX_FLAG = "--bundle-index-path"
DOCS_REVIEW_DRIFTED_README_FLAG = "--drifted-readme-path"
DOCS_REVIEW_RENDER_OUTPUT_DIR_FLAG = "--render-output-dir"
DOCS_REVIEW_RENDER_MANIFEST_FLAG = "--render-manifest-path"
DOCS_REVIEW_RENDER_DIFF_FLAG = "--render-diff-path"
DOCS_REVIEW_FIX_CHECK_JSON_FLAG = "--fix-check-json-path"
DOCS_REVIEW_FIX_REPAIR_JSON_FLAG = "--fix-repair-json-path"
DOCS_REVIEW_FIX_POST_CHECK_JSON_FLAG = "--fix-post-check-json-path"
DOCS_REVIEW_MATRIX_SUMMARY_FILENAME = "matrix-summary.json"
DOCS_FOCUSED_RERUN_HINT = (
    "hint: docs-review drift is easiest to isolate with `standalone_smoke.py docs-focused`; rerun "
    "`.venv/bin/python scripts/standalone_smoke.py docs-focused` to recheck docs parity + docs-review "
    "artifacts without the rest of the matrix."
)
LIVE_RUNTIME_REQUESTED_FALSE_LINE = "live_runtime_requested= False"
LIVE_RUNTIME_API_KEY_ERROR = "OPENAI_API_KEY is required for live runtime mode"
DOCS_REVIEW_ARTIFACT_METADATA_KEYS = (
    "artifact_root",
    "bundle_index_path",
    "drifted_readme_path",
    "render_output_dir",
    "render_manifest_path",
    "render_diff_path",
    "fix_check_json_path",
    "fix_repair_json_path",
    "fix_post_check_json_path",
    "matrix_summary_path",
)


def _emit_matrix_line(message: str, *, stream) -> None:
    print(SMOKE_MATRIX_WRAPPER.format_line(message), file=stream)
    stream.flush()


def _should_emit_bundle_output_line(line: str) -> bool:
    normalized_line = line.rstrip("\n")
    return not any(normalized_line.startswith(prefix) for prefix in SUPPRESSED_NESTED_SUMMARY_PREFIXES)


def _extract_target_arg_path(target: SmokeScriptTarget, flag_name: str) -> str | None:
    args = target.args
    for index, arg in enumerate(args[:-1]):
        if arg == flag_name:
            return args[index + 1]
    return None


def _docs_review_artifact_paths(target: SmokeScriptTarget) -> dict[str, str]:
    if target.name not in {DOCS_REVIEW_TARGET_NAME, DOCS_REVIEW_ALL_TARGET_NAME}:
        return {}

    metadata_paths = {
        key: value
        for key in DOCS_REVIEW_ARTIFACT_METADATA_KEYS
        if (value := target.metadata.get(key))
    }
    if metadata_paths:
        return metadata_paths

    output_dir = _extract_target_arg_path(target, DOCS_REVIEW_OUTPUT_DIR_FLAG)
    bundle_index_path = _extract_target_arg_path(target, DOCS_REVIEW_BUNDLE_INDEX_FLAG)

    artifact_root: Path | None = None
    if output_dir:
        artifact_root = Path(output_dir)
    elif bundle_index_path:
        artifact_root = Path(bundle_index_path).parent

    drifted_readme_path = _extract_target_arg_path(target, DOCS_REVIEW_DRIFTED_README_FLAG)
    render_output_dir = _extract_target_arg_path(target, DOCS_REVIEW_RENDER_OUTPUT_DIR_FLAG)
    render_manifest_path = _extract_target_arg_path(target, DOCS_REVIEW_RENDER_MANIFEST_FLAG)
    render_diff_path = _extract_target_arg_path(target, DOCS_REVIEW_RENDER_DIFF_FLAG)
    fix_check_json_path = _extract_target_arg_path(target, DOCS_REVIEW_FIX_CHECK_JSON_FLAG)
    fix_repair_json_path = _extract_target_arg_path(target, DOCS_REVIEW_FIX_REPAIR_JSON_FLAG)
    fix_post_check_json_path = _extract_target_arg_path(target, DOCS_REVIEW_FIX_POST_CHECK_JSON_FLAG)
    matrix_summary_path = None

    if artifact_root is not None:
        drifted_readme_path = drifted_readme_path or str(artifact_root / "README-drifted.md")
        render_output_dir = render_output_dir or str(artifact_root / "rendered")
        render_manifest_path = render_manifest_path or str(artifact_root / "render-manifest.json")
        render_diff_path = render_diff_path or str(artifact_root / "render-review.patch")
        fix_check_json_path = fix_check_json_path or str(artifact_root / "fix-check.json")
        fix_repair_json_path = fix_repair_json_path or str(artifact_root / "fix-repair.json")
        fix_post_check_json_path = fix_post_check_json_path or str(artifact_root / "fix-post-check.json")
        matrix_summary_path = str(artifact_root / DOCS_REVIEW_MATRIX_SUMMARY_FILENAME)

    paths: dict[str, str] = {}
    if output_dir:
        paths["artifact_root"] = output_dir
    elif artifact_root is not None:
        paths["artifact_root"] = str(artifact_root)
    if bundle_index_path:
        paths["bundle_index_path"] = bundle_index_path
    if drifted_readme_path:
        paths["drifted_readme_path"] = drifted_readme_path
    if render_output_dir:
        paths["render_output_dir"] = render_output_dir
    if render_manifest_path:
        paths["render_manifest_path"] = render_manifest_path
    if render_diff_path:
        paths["render_diff_path"] = render_diff_path
    if fix_check_json_path:
        paths["fix_check_json_path"] = fix_check_json_path
    if fix_repair_json_path:
        paths["fix_repair_json_path"] = fix_repair_json_path
    if fix_post_check_json_path:
        paths["fix_post_check_json_path"] = fix_post_check_json_path
    if matrix_summary_path:
        paths["matrix_summary_path"] = matrix_summary_path
    return paths


def _docs_review_artifact_metadata(target: SmokeScriptTarget) -> dict[str, str] | None:
    paths = _docs_review_artifact_paths(target)
    if not paths:
        return None
    return {
        "display_name": target.display_label,
        "target_name": target.name,
        **paths,
    }


def _persist_docs_review_artifact_metadata_summary(metadata: dict[str, str] | None) -> dict[str, str] | None:
    if metadata is None:
        return None
    matrix_summary_path = metadata.get("matrix_summary_path")
    if matrix_summary_path is None:
        return metadata
    summary_path = Path(matrix_summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def _docs_review_artifact_metadata_message(metadata: dict[str, str] | None) -> str | None:
    if metadata is None:
        return None
    return f"review metadata: {json.dumps(metadata, sort_keys=True)}"


def _docs_review_target_for_failure(
    targets: Sequence[SmokeScriptTarget],
    *,
    current_index: int,
) -> SmokeScriptTarget | None:
    target_names = {DOCS_REVIEW_TARGET_NAME, DOCS_REVIEW_ALL_TARGET_NAME}
    current_target = targets[current_index]
    if current_target.name in target_names:
        return current_target
    for pending_target in targets[current_index + 1 :]:
        if pending_target.name in target_names:
            return pending_target
    return None


def _docs_review_artifact_location_messages(target: SmokeScriptTarget) -> tuple[str, ...]:
    paths = _docs_review_artifact_paths(target)
    if not paths:
        return ()

    output_dir = paths.get("artifact_root")
    bundle_index_path = paths.get("bundle_index_path")
    drifted_readme_path = paths.get("drifted_readme_path")
    render_output_dir = paths.get("render_output_dir")
    render_manifest_path = paths.get("render_manifest_path")
    render_diff_path = paths.get("render_diff_path")
    fix_check_json_path = paths.get("fix_check_json_path")
    fix_repair_json_path = paths.get("fix_repair_json_path")
    fix_post_check_json_path = paths.get("fix_post_check_json_path")
    matrix_summary_path = paths.get("matrix_summary_path")

    messages: list[str] = []
    if output_dir and bundle_index_path:
        messages.append(f"review artifacts: {output_dir} (index: {bundle_index_path})")
    elif bundle_index_path:
        messages.append(f"review artifact index: {bundle_index_path}")
    elif output_dir:
        messages.append(f"review artifacts: {output_dir}")

    if matrix_summary_path:
        messages.append(f"review matrix summary: {matrix_summary_path}")
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


def _docs_review_rerun_hint(target: SmokeScriptTarget) -> str | None:
    if target.name not in {DOCS_REVIEW_TARGET_NAME, DOCS_REVIEW_ALL_TARGET_NAME}:
        return None
    return DOCS_FOCUSED_RERUN_HINT


def _live_inclusive_failure_hint(target: SmokeScriptTarget, observed_lines: Sequence[str]) -> str | None:
    if target.name != LIVE_INCLUSIVE_STANDALONE_TARGET_NAME:
        return None
    normalized_lines = [line.rstrip("\n") for line in observed_lines]
    if any(LIVE_RUNTIME_REQUESTED_FALSE_LINE in line for line in normalized_lines):
        return (
            "hint: `smoke_matrix.py all` and `smoke_matrix.py all-review` swap in `standalone_smoke.py all`; export "
            "`STRANDS_AGENT_RUNTIME=live` and `OPENAI_API_KEY` "
            "(optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning the live-inclusive matrix."
        )
    if any(LIVE_RUNTIME_API_KEY_ERROR in line for line in normalized_lines):
        return (
            "hint: `smoke_matrix.py all`/`all-review` reached the live runtime, but `OPENAI_API_KEY` was missing; "
            "export `OPENAI_API_KEY` (and optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
        )
    return None


def run_smoke_matrix(
    targets: Sequence[SmokeScriptTarget],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    total_started_at = perf_counter()
    passed_count = 0
    total_count = len(targets)

    for index, target in enumerate(targets):
        _emit_matrix_line(SMOKE_MATRIX_WRAPPER.running_message(item_name=target.display_label), stream=stdout)
        started_at = perf_counter()
        observed_lines: list[str] = []
        exit_code = run_smoke_target(
            target,
            stdout=stdout,
            stderr=stderr,
            output_line_filter=_should_emit_bundle_output_line,
            output_line_observer=observed_lines.append,
        )
        elapsed = perf_counter() - started_at
        docs_review_target = _docs_review_target_for_failure(targets, current_index=index)
        artifact_metadata = None
        if target == docs_review_target:
            artifact_metadata = _persist_docs_review_artifact_metadata_summary(
                _docs_review_artifact_metadata(target)
            )
        elif exit_code != 0 and docs_review_target is not None:
            artifact_metadata = _docs_review_artifact_metadata(docs_review_target)
        if exit_code != 0:
            _emit_matrix_line(
                SMOKE_MATRIX_WRAPPER.failed_message(item_name=target.display_label, elapsed_seconds=elapsed),
                stream=stderr,
            )
            artifact_metadata_message = _docs_review_artifact_metadata_message(artifact_metadata)
            if artifact_metadata_message is not None:
                _emit_matrix_line(artifact_metadata_message, stream=stderr)
            if target == docs_review_target:
                for artifact_location_message in _docs_review_artifact_location_messages(target):
                    _emit_matrix_line(artifact_location_message, stream=stderr)
                docs_review_hint = _docs_review_rerun_hint(target)
                if docs_review_hint is not None:
                    _emit_matrix_line(docs_review_hint, stream=stderr)
            hint = _live_inclusive_failure_hint(target, observed_lines)
            if hint is not None:
                _emit_matrix_line(hint, stream=stderr)
            total_elapsed = perf_counter() - total_started_at
            _emit_matrix_line(
                SMOKE_MATRIX_WRAPPER.failure_summary_message(
                    passed_count=passed_count,
                    total_count=total_count,
                    elapsed_seconds=total_elapsed,
                ),
                stream=stderr,
            )
            return exit_code
        passed_count += 1
        _emit_matrix_line(
            SMOKE_MATRIX_WRAPPER.passed_message(item_name=target.display_label, elapsed_seconds=elapsed),
            stream=stdout,
        )
        artifact_metadata_message = _docs_review_artifact_metadata_message(artifact_metadata)
        if artifact_metadata_message is not None:
            _emit_matrix_line(artifact_metadata_message, stream=stdout)
        for artifact_location_message in _docs_review_artifact_location_messages(target):
            _emit_matrix_line(artifact_location_message, stream=stdout)

    total_elapsed = perf_counter() - total_started_at
    _emit_matrix_line(
        SMOKE_MATRIX_WRAPPER.success_summary_message(
            passed_count=passed_count,
            total_count=total_count,
            elapsed_seconds=total_elapsed,
        ),
        stream=stdout,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_smoke_matrix(CLI_SPEC.resolve_targets(script_dir=SCRIPT_DIR, requested_target_name=args.target))


def build_parser() -> argparse.ArgumentParser:
    return CLI_SPEC.build_parser(script_dir=SCRIPT_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
