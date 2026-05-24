from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_cli_doc_render_parser,
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

    if args.output_dir is not None:
        written_paths = write_rendered_sections(
            args.output_dir,
            requested_target_name=args.target,
            body_only=args.body_only,
        )
        for path in written_paths:
            print(path)
        print(f"wrote {len(written_paths)} rendered smoke README sections to {args.output_dir}")
        return 0

    rendered_text = "\n\n".join(
        text
        for _, text in render_smoke_cli_readme_sections(
            requested_target_name=args.target,
            body_only=args.body_only,
        )
    )
    print(rendered_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
