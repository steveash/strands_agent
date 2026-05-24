from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_cli_doc_fix_parser,
    collect_smoke_cli_readme_diffs,
    repair_smoke_cli_readme_sections,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.diff and args.stdout:
        parser.error("--diff cannot be combined with --stdout")
    if args.check and args.stdout:
        parser.error("--check cannot be combined with --stdout")

    readme_path = Path(args.readme_path)
    original_markdown, repaired_markdown, repaired_script_names = repair_readme(
        readme_path,
        requested_target_name=args.target,
    )

    if args.diff:
        diff_sections = collect_smoke_cli_readme_diffs(
            original_markdown,
            requested_target_name=args.target,
        )
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

    if args.stdout:
        print(repaired_markdown, end="" if repaired_markdown.endswith("\n") else "\n")
        return 0

    if args.check:
        if repaired_markdown == original_markdown:
            print(f"smoke README already up to date: {readme_path}")
            return 0
        repaired_names = ", ".join(repaired_script_names)
        print(
            f"smoke README drift detected in {len(repaired_script_names)} section(s) for {readme_path}: {repaired_names}"
        )
        return 1

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
