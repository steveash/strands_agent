from __future__ import annotations

import argparse
import json
from pathlib import Path

from strands_agent_tui.sessions import (
    load_or_refresh_session_manifest,
    render_session_manifest_summary,
    summarize_session_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a compact operator summary for a saved Strands Agent TUI session manifest.",
    )
    parser.add_argument(
        "session_dir",
        type=Path,
        help="Path to an artifacts/sessions/session-* directory containing manifest.json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the normalized summary as JSON instead of readable text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_or_refresh_session_manifest(args.session_dir)
    summary = summarize_session_manifest(manifest)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for line in render_session_manifest_summary(summary):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
