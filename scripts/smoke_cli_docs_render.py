from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_cli_doc_render_parser,
    collect_smoke_cli_readme_diffs,
    render_smoke_cli_readme_section,
    render_smoke_cli_readme_sections,
    resolve_smoke_cli_doc_target_names,
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


def _normalize_text_output(payload: str) -> str:
    if payload and not payload.endswith("\n"):
        payload += "\n"
    return payload


def _write_text_output(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_normalize_text_output(payload), encoding="utf-8")


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


def _format_diff_output(diff_sections: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    lines: list[str] = []
    for index, (script_name, diff_lines) in enumerate(diff_sections):
        if index:
            lines.append("")
        lines.append(f"### {script_name}")
        lines.extend(diff_lines)
    return "\n".join(lines)


def _sha256_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _diff_stats(diff_lines: tuple[str, ...]) -> dict[str, int]:
    return {
        "added_line_count": sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        ),
        "hunk_count": sum(1 for line in diff_lines if line.startswith("@@ ")),
        "line_count": len(diff_lines),
        "removed_line_count": sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        ),
    }


def _rendered_summary(text: str) -> str:
    for line in text.splitlines():
        summary = line.strip()
        if summary:
            return summary if len(summary) <= 120 else summary[:119] + "…"
    return ""


def _rendered_bundle_sha256(rendered_sections: tuple[tuple[str, str], ...]) -> str | None:
    if not rendered_sections:
        return None
    return _sha256_text("\n\n".join(f"### {script_name}\n{text}" for script_name, text in rendered_sections))


def _diff_bundle_sha256(diff_sections: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    if not diff_sections:
        return None
    return _sha256_text(_normalize_text_output(_format_diff_output(diff_sections)))


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
    diff_lines_by_script_name = {
        script_name: tuple(diff_lines) for script_name, diff_lines in diff_sections
    }
    rendered_text_by_script_name = {
        script_name: text for script_name, text in rendered_sections
    }
    written_path_by_script_name = {
        path.stem: str(path) for path in written_paths
    }
    payload = {
        "body_only": body_only,
        "diff_bundle_sha256": _diff_bundle_sha256(diff_sections),
        "diff_output_path": str(diff_output) if diff_output is not None else None,
        "drift_count": len(diff_sections),
        "drift_only": True,
        "manifest_path": str(manifest_output),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "readme_path": str(readme_path),
        "rendered_bundle_sha256": _rendered_bundle_sha256(rendered_sections),
        "rendered_count": len(rendered_sections),
        "rendered_targets": [script_name for script_name, _ in rendered_sections],
        "requested_target": requested_target_name,
        "sections": [
            {
                "diff_lines": list(diff_lines_by_script_name[script_name]),
                "diff_sha256": _sha256_text("\n".join(diff_lines_by_script_name[script_name])),
                "diff_stats": _diff_stats(diff_lines_by_script_name[script_name]),
                "output_path": written_path_by_script_name.get(script_name),
                "rendered_char_count": len(rendered_text_by_script_name[script_name]),
                "rendered_line_count": len(rendered_text_by_script_name[script_name].splitlines()),
                "rendered_sha256": _sha256_text(rendered_text_by_script_name[script_name]),
                "rendered_summary": _rendered_summary(rendered_text_by_script_name[script_name]),
                "script_name": script_name,
            }
            for script_name, _ in rendered_sections
        ],
        "selected_targets": list(selected_script_names),
        "up_to_date": not diff_sections,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


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
                _write_text_output(args.diff_output, "")
            if args.manifest_output is not None:
                _write_text_output(
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
        _write_text_output(args.diff_output, _format_diff_output(diff_sections))
    if args.manifest_output is not None:
        _write_text_output(
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
