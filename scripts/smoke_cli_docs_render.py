from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_cli_doc_render_parser,
    collect_smoke_cli_readme_diffs,
    render_smoke_cli_readme_section,
    render_smoke_cli_readme_sections,
)


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_doc_render_parser()


def write_rendered_sections(
    output_dir: Path,
    *,
    requested_target_name: str | None = None,
    body_only: bool = False,
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    for script_name, text in render_smoke_cli_readme_sections(
        requested_target_name=requested_target_name,
        body_only=body_only,
    ):
        path = output_dir / f"{script_name}.md"
        path.write_text(text + "\n", encoding="utf-8")
        written_paths.append(path)
    return tuple(written_paths)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    rendered_sections: tuple[tuple[str, str], ...]
    if args.drift_only:
        readme_path = Path(args.readme_path)
        diff_sections = collect_smoke_cli_readme_diffs(
            readme_path.read_text(encoding="utf-8"),
            requested_target_name=args.target,
        )
        if not diff_sections:
            print(f"smoke README already up to date: {readme_path}")
            return 0
        rendered_sections = tuple(
            (script_name, render_smoke_cli_readme_section(script_name, body_only=args.body_only))
            for script_name, _diff_lines in diff_sections
        )
    else:
        rendered_sections = render_smoke_cli_readme_sections(
            requested_target_name=args.target,
            body_only=args.body_only,
        )

    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        written_paths: list[Path] = []
        for script_name, text in rendered_sections:
            path = args.output_dir / f"{script_name}.md"
            path.write_text(text + "\n", encoding="utf-8")
            written_paths.append(path)
        for path in written_paths:
            print(path)
        print(f"wrote {len(written_paths)} rendered smoke README sections to {args.output_dir}")
        return 0

    rendered_text = "\n\n".join(text for _, text in rendered_sections)
    print(rendered_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
