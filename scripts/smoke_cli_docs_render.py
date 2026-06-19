from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    collect_smoke_cli_readme_diffs,
    render_smoke_cli_readme_section,
    render_smoke_cli_readme_sections,
    resolve_smoke_cli_doc_target_names,
    smoke_cli_doc_parser_spec,
)
from strands_agent_tui.testing.smoke_cli_doc_artifacts import (
    build_smoke_cli_doc_render_manifest_payload,
    format_diff_output,
    write_text_output,
)


def build_parser() -> argparse.ArgumentParser:
    return smoke_cli_doc_parser_spec("smoke_cli_docs_render").build_parser()


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


def _write_rendered_sections(
    output_dir: Path,
    rendered_sections: tuple[tuple[str, str], ...],
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    for script_name, text in rendered_sections:
        path = output_dir / f"{script_name}.md"
        path.write_text(text + "\n", encoding="utf-8")
        written_paths.append(path)
    return tuple(written_paths)


def _json_manifest(
    *,
    requested_target_name: str | None,
    selected_script_names: tuple[str, ...],
    rendered_sections: tuple[tuple[str, str], ...],
    written_paths: tuple[Path, ...],
    readme_path: Path,
    output_dir: Path | None,
    manifest_output: Path,
    diff_output: Path | None,
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...],
    body_only: bool,
) -> str:
    return json.dumps(
        build_smoke_cli_doc_render_manifest_payload(
            body_only=body_only,
            requested_target_name=requested_target_name,
            selected_script_names=selected_script_names,
            rendered_sections=rendered_sections,
            written_paths=written_paths,
            readme_path=readme_path,
            output_dir=output_dir,
            manifest_output=manifest_output,
            diff_output=diff_output,
            diff_sections=diff_sections,
        ),
        indent=2,
        sort_keys=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.manifest_output is not None and not args.drift_only:
        parser.error("--manifest-output requires --drift-only")
    if args.diff_output is not None and not args.drift_only:
        parser.error("--diff-output requires --drift-only")

    selected_script_names = tuple(resolve_smoke_cli_doc_target_names(args.target))

    rendered_sections: tuple[tuple[str, str], ...]
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...] = ()
    readme_path = Path(args.readme_path)
    if args.drift_only:
        diff_sections = collect_smoke_cli_readme_diffs(
            readme_path.read_text(encoding="utf-8"),
            requested_target_name=args.target,
        )
        if not diff_sections:
            if args.diff_output is not None:
                write_text_output(args.diff_output, "")
            if args.manifest_output is not None:
                write_text_output(
                    args.manifest_output,
                    _json_manifest(
                        requested_target_name=args.target,
                        selected_script_names=selected_script_names,
                        rendered_sections=(),
                        written_paths=(),
                        readme_path=readme_path,
                        output_dir=args.output_dir,
                        manifest_output=args.manifest_output,
                        diff_output=args.diff_output,
                        diff_sections=(),
                        body_only=args.body_only,
                    ),
                )
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

    written_paths: tuple[Path, ...] = ()
    if args.output_dir is not None:
        written_paths = _write_rendered_sections(args.output_dir, rendered_sections)
        for path in written_paths:
            print(path)
        print(f"wrote {len(written_paths)} rendered smoke README sections to {args.output_dir}")
    else:
        rendered_text = "\n\n".join(text for _, text in rendered_sections)
        print(rendered_text)

    if args.diff_output is not None:
        write_text_output(args.diff_output, format_diff_output(diff_sections))
    if args.manifest_output is not None:
        write_text_output(
            args.manifest_output,
            _json_manifest(
                requested_target_name=args.target,
                selected_script_names=selected_script_names,
                rendered_sections=rendered_sections,
                written_paths=written_paths,
                readme_path=readme_path,
                output_dir=args.output_dir,
                manifest_output=args.manifest_output,
                diff_output=args.diff_output,
                diff_sections=diff_sections,
                body_only=args.body_only,
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
