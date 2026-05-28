from __future__ import annotations

import hashlib
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_cli_doc_drift_report_payload,
    build_smoke_cli_doc_render_manifest_payload,
    build_smoke_cli_doc_repair_report_payload,
    collect_smoke_cli_readme_diffs,
    render_smoke_cli_readme_section,
    replace_markdown_section,
    smoke_cli_doc_spec,
)


README_PATH = Path(__file__).resolve().parent.parent / "README.md"
README_TEXT = README_PATH.read_text(encoding="utf-8")


def _drift_fixture() -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...], tuple[tuple[str, str], ...]]:
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    diff_sections = collect_smoke_cli_readme_diffs(
        drifted_markdown,
        requested_target_name="standalone_smoke",
    )
    rendered_sections = (("standalone_smoke", render_smoke_cli_readme_section("standalone_smoke")),)
    return drifted_markdown, diff_sections, rendered_sections


def test_build_smoke_cli_doc_render_manifest_payload_tracks_review_artifacts(tmp_path) -> None:
    drifted_markdown, diff_sections, rendered_sections = _drift_fixture()
    output_dir = tmp_path / "rendered"
    written_path = output_dir / "standalone_smoke.md"
    manifest_path = tmp_path / "artifacts" / "smoke-cli-docs-preview.json"
    diff_path = tmp_path / "artifacts" / "smoke-cli-docs-review.patch"

    payload = build_smoke_cli_doc_render_manifest_payload(
        body_only=False,
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        rendered_sections=rendered_sections,
        written_paths=(written_path,),
        readme_path=tmp_path / "README.md",
        output_dir=output_dir,
        manifest_output=manifest_path,
        diff_output=diff_path,
        diff_sections=diff_sections,
    )

    section = payload["sections"][0]
    assert payload["manifest_path"] == str(manifest_path)
    assert payload["diff_output_path"] == str(diff_path)
    assert payload["selected_targets"] == ["standalone_smoke"]
    assert payload["rendered_targets"] == ["standalone_smoke"]
    assert payload["drift_count"] == 1
    assert payload["up_to_date"] is False
    assert payload["rendered_bundle_sha256"] == hashlib.sha256(
        f"### standalone_smoke\n{rendered_sections[0][1]}".encode("utf-8")
    ).hexdigest()
    assert section["output_path"] == str(written_path)
    assert section["rendered_summary"] == "### Standalone local smoke bundle"
    assert section["diff_lines"] == list(diff_sections[0][1])
    assert section["diff_stats"]["hunk_count"] == 1
    assert section["diff_sha256"] == hashlib.sha256(
        "\n".join(diff_sections[0][1]).encode("utf-8")
    ).hexdigest()
    assert drifted_markdown != README_TEXT


def test_build_smoke_cli_doc_drift_report_payload_can_hide_raw_diff_lines() -> None:
    drifted_markdown, diff_sections, rendered_sections = _drift_fixture()
    render_output_dir = Path("artifacts/rendered")
    render_manifest_path = Path("artifacts/render-manifest.json")
    render_diff_path = Path("artifacts/render-review.patch")

    payload = build_smoke_cli_doc_drift_report_payload(
        readme_path=Path("README.md"),
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        include_diff_lines=False,
        check=True,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
    )

    section = payload["sections"][0]
    assert payload["check"] is True
    assert payload["diff"] is False
    assert payload["drifted_sections"] == [{"script_name": "standalone_smoke"}]
    assert payload["drifted_targets"] == ["standalone_smoke"]
    assert payload["readme_path"] == "README.md"
    assert payload["render_output_dir"] == str(render_output_dir)
    assert payload["render_manifest_path"] == str(render_manifest_path)
    assert payload["render_diff_path"] == str(render_diff_path)
    assert section["script_name"] == "standalone_smoke"
    assert section["rendered_summary"] == "### Standalone local smoke bundle"
    assert section["diff_stats"]["line_count"] == len(diff_sections[0][1])
    assert "diff_lines" not in section
    assert drifted_markdown != README_TEXT


def test_build_smoke_cli_doc_repair_report_payload_tracks_stdout_vs_write_mode() -> None:
    drifted_markdown, diff_sections, rendered_sections = _drift_fixture()
    render_output_dir = Path("artifacts/rendered")
    render_manifest_path = Path("artifacts/render-manifest.json")
    render_diff_path = Path("artifacts/render-review.patch")

    payload = build_smoke_cli_doc_repair_report_payload(
        readme_path=Path("README.md"),
        requested_target_name="standalone_smoke",
        selected_script_names=("standalone_smoke",),
        repaired_script_names=("standalone_smoke",),
        original_markdown=drifted_markdown,
        repaired_markdown=README_TEXT,
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        stdout=True,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
    )

    section = payload["sections"][0]
    assert payload["changed"] is True
    assert payload["mode"] == "stdout"
    assert payload["repaired_count"] == 1
    assert payload["repaired_targets"] == ["standalone_smoke"]
    assert payload["render_output_dir"] == str(render_output_dir)
    assert payload["render_manifest_path"] == str(render_manifest_path)
    assert payload["render_diff_path"] == str(render_diff_path)
    assert payload["wrote_readme"] is False
    assert payload["readme_sha256_before"] == hashlib.sha256(drifted_markdown.encode("utf-8")).hexdigest()
    assert payload["readme_sha256_after"] == hashlib.sha256(README_TEXT.encode("utf-8")).hexdigest()
    assert section["rendered_summary"] == "### Standalone local smoke bundle"
    assert section["diff_stats"]["hunk_count"] == 1
    assert "diff_lines" not in section
