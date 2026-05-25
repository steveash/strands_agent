from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_cli_doc_fix_parser,
    collect_smoke_cli_readme_diffs,
    render_smoke_cli_readme_section,
    repair_smoke_cli_readme_sections,
    resolve_smoke_cli_doc_target_names,
)
from strands_agent_tui.testing.smoke_cli_doc_artifacts import (
    build_smoke_cli_doc_section_payloads,
    diff_bundle_sha256,
    rendered_bundle_sha256,
    sha256_text,
    write_text_output,
)


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_doc_fix_parser()


def repair_readme(
    readme_path: Path,
    *,
    requested_target_name: str | None = None,
) -> tuple[str, str, tuple[str, ...]]:
    original_markdown = readme_path.read_text(encoding="utf-8")
    repaired_markdown, repaired_script_names = repair_smoke_cli_readme_sections(
        original_markdown,
        requested_target_name=requested_target_name,
    )
    return original_markdown, repaired_markdown, repaired_script_names


def _rendered_sections_for_script_names(script_names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((script_name, render_smoke_cli_readme_section(script_name)) for script_name in script_names)


def _json_drift_report(
    *,
    readme_path: Path,
    requested_target_name: str | None,
    selected_script_names: tuple[str, ...],
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...],
    include_diff_lines: bool,
    check: bool,
) -> str:
    rendered_sections = _rendered_sections_for_script_names(
        tuple(script_name for script_name, _diff_lines in diff_sections)
    )
    drifted_sections: list[dict[str, object]] = []
    for script_name, diff_lines in diff_sections:
        section: dict[str, object] = {"script_name": script_name}
        if include_diff_lines:
            section["diff_lines"] = list(diff_lines)
        drifted_sections.append(section)
    payload = {
        "body_only": False,
        "check": check,
        "diff": include_diff_lines,
        "diff_bundle_sha256": diff_bundle_sha256(diff_sections),
        "drift_count": len(diff_sections),
        "drifted_sections": drifted_sections,
        "drifted_targets": [script_name for script_name, _ in diff_sections],
        "readme_path": str(readme_path),
        "rendered_bundle_sha256": rendered_bundle_sha256(rendered_sections),
        "rendered_count": len(rendered_sections),
        "rendered_targets": [script_name for script_name, _ in rendered_sections],
        "requested_target": requested_target_name,
        "sections": build_smoke_cli_doc_section_payloads(
            rendered_sections=rendered_sections,
            diff_sections=diff_sections,
            include_diff_lines=include_diff_lines,
        ),
        "selected_targets": list(selected_script_names),
        "up_to_date": not diff_sections,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _json_repair_report(
    *,
    readme_path: Path,
    requested_target_name: str | None,
    selected_script_names: tuple[str, ...],
    repaired_script_names: tuple[str, ...],
    original_markdown: str,
    repaired_markdown: str,
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...],
    stdout: bool,
) -> str:
    rendered_sections = _rendered_sections_for_script_names(repaired_script_names)
    payload = {
        "body_only": False,
        "changed": bool(repaired_script_names),
        "diff_bundle_sha256": diff_bundle_sha256(diff_sections),
        "drift_count": len(diff_sections),
        "drifted_targets": [script_name for script_name, _ in diff_sections],
        "mode": "stdout" if stdout else "repair",
        "readme_path": str(readme_path),
        "readme_sha256_after": sha256_text(repaired_markdown),
        "readme_sha256_before": sha256_text(original_markdown),
        "repaired_count": len(repaired_script_names),
        "repaired_targets": list(repaired_script_names),
        "rendered_bundle_sha256": rendered_bundle_sha256(rendered_sections),
        "rendered_count": len(rendered_sections),
        "rendered_targets": [script_name for script_name, _ in rendered_sections],
        "requested_target": requested_target_name,
        "sections": build_smoke_cli_doc_section_payloads(
            rendered_sections=rendered_sections,
            diff_sections=diff_sections,
            include_diff_lines=False,
        ),
        "selected_targets": list(selected_script_names),
        "up_to_date": not repaired_script_names,
        "wrote_readme": bool(repaired_script_names) and not stdout,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.diff and args.stdout:
        parser.error("--diff cannot be combined with --stdout")
    if args.check and args.stdout:
        parser.error("--check cannot be combined with --stdout")
    if args.json and args.stdout:
        parser.error("--json cannot be combined with --stdout")
    if args.json and not (args.check or args.diff):
        parser.error("--json requires --check and/or --diff")

    readme_path = Path(args.readme_path)
    original_markdown = readme_path.read_text(encoding="utf-8")
    selected_script_names = tuple(resolve_smoke_cli_doc_target_names(args.target))

    if args.diff or args.check:
        diff_sections = collect_smoke_cli_readme_diffs(
            original_markdown,
            requested_target_name=args.target,
        )
        json_report = None
        if args.json or args.json_output is not None:
            json_report = _json_drift_report(
                readme_path=readme_path,
                requested_target_name=args.target,
                selected_script_names=selected_script_names,
                diff_sections=diff_sections,
                include_diff_lines=args.diff,
                check=args.check,
            )
            if args.json_output is not None:
                write_text_output(args.json_output, json_report)
        if args.json:
            assert json_report is not None
            print(json_report)
            return 1 if args.check and diff_sections else 0
        if args.diff:
            if not diff_sections:
                print(f"smoke README already up to date: {readme_path}")
                return 0
            for index, (script_name, diff_lines) in enumerate(diff_sections):
                if index:
                    print()
                print(f"### {script_name}")
                for line in diff_lines:
                    print(line)
            if args.check:
                drifted_names = ", ".join(script_name for script_name, _ in diff_sections)
                print(
                    f"smoke README drift detected in {len(diff_sections)} section(s) for {readme_path}: {drifted_names}"
                )
                return 1
            return 0
        if not diff_sections:
            print(f"smoke README already up to date: {readme_path}")
            return 0
        drifted_names = ", ".join(script_name for script_name, _ in diff_sections)
        print(
            f"smoke README drift detected in {len(diff_sections)} section(s) for {readme_path}: {drifted_names}"
        )
        return 1

    original_markdown, repaired_markdown, repaired_script_names = repair_readme(
        readme_path,
        requested_target_name=args.target,
    )

    if args.json_output is not None:
        write_text_output(
            args.json_output,
            _json_repair_report(
                readme_path=readme_path,
                requested_target_name=args.target,
                selected_script_names=selected_script_names,
                repaired_script_names=repaired_script_names,
                original_markdown=original_markdown,
                repaired_markdown=repaired_markdown,
                diff_sections=collect_smoke_cli_readme_diffs(
                    original_markdown,
                    requested_target_name=args.target,
                ),
                stdout=args.stdout,
            ),
        )

    if args.stdout:
        print(repaired_markdown, end="" if repaired_markdown.endswith("\n") else "\n")
        return 0

    if repaired_markdown != original_markdown:
        readme_path.write_text(repaired_markdown, encoding="utf-8")
        repaired_names = ", ".join(repaired_script_names)
        print(
            f"repaired {len(repaired_script_names)} smoke README section(s) in {readme_path}: {repaired_names}"
        )
    else:
        print(f"smoke README already up to date: {readme_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
