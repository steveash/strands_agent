from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from strands_agent_tui.config import (
    load_config,
    render_workspace_profile_summary,
    summarize_workspace_profile,
)
from strands_agent_tui.testing import emit_smoke_checks


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        profile_path = root / "workspace-profile.json"
        workspace = root / "profile-workspace"
        artifacts = root / "profile-artifacts"
        profile_path.write_text(
            json.dumps(
                {
                    "name": "profile smoke",
                    "runtime": "fake",
                    "model": "profile-model",
                    "workspace": str(workspace),
                    "artifacts_root": str(artifacts),
                    "allow_overwrite": False,
                    "stale_approval_days": 4,
                    "ignored_future_field": "visible warning",
                }
            ),
            encoding="utf-8",
        )

        old_env = {
            name: os.environ.get(name)
            for name in [
                "STRANDS_AGENT_RUNTIME",
                "STRANDS_AGENT_OPENAI_MODEL",
                "STRANDS_AGENT_WORKSPACE_ROOT",
                "STRANDS_AGENT_ARTIFACTS_ROOT",
                "STRANDS_AGENT_ALLOW_OVERWRITE",
                "STRANDS_AGENT_STALE_APPROVAL_DAYS",
            ]
        }
        try:
            for name in old_env:
                os.environ.pop(name, None)
            profile_config = load_config(profile_path=str(profile_path))

            os.environ["STRANDS_AGENT_OPENAI_MODEL"] = "env-model"
            os.environ["STRANDS_AGENT_WORKSPACE_ROOT"] = str(root / "env-workspace")
            env_config = load_config(profile_path=str(profile_path))
        finally:
            for name, value in old_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        cli_config = env_config.merge(
            runtime_mode="live",
            stale_approval_warning_days=9,
        )

        print(f"profile_path: {profile_config.profile_path}")
        print(f"profile_sources: {profile_config.config_source_summary()}")
        print(f"env_sources: {env_config.config_source_summary()}")
        print(f"cli_sources: {cli_config.config_source_summary()}")
        profile_summary = summarize_workspace_profile(str(profile_path), config=cli_config)
        for line in render_workspace_profile_summary(profile_summary):
            print(line)

        return emit_smoke_checks(
            [
                (
                    "profile_config_sources",
                    profile_config.config_sources.get("runtime_mode") == "profile"
                    and profile_config.config_sources.get("openai_model") == "profile"
                    and profile_config.config_sources.get("workspace_root") == "profile"
                    and profile_config.config_sources.get("artifacts_root") == "profile",
                ),
                (
                    "env_config_sources",
                    env_config.openai_model == "env-model"
                    and env_config.config_sources.get("openai_model") == "env"
                    and env_config.config_sources.get("workspace_root") == "env"
                    and env_config.config_sources.get("runtime_mode") == "profile",
                ),
                (
                    "cli_config_sources",
                    cli_config.runtime_mode == "live"
                    and cli_config.stale_approval_warning_days == 9
                    and cli_config.config_sources.get("runtime_mode") == "cli"
                    and cli_config.config_sources.get("stale_approval_warning_days") == "cli",
                ),
                (
                    "profile_summary_effective_values",
                    profile_summary["effective"]["runtime_mode"]["value"] == "live"
                    and profile_summary["effective"]["runtime_mode"]["source"] == "cli"
                    and profile_summary["effective"]["openai_model"]["value"] == "env-model"
                    and profile_summary["effective"]["openai_model"]["source"] == "env"
                    and profile_summary["effective"]["stale_approval_warning_days"]["value"] == 9,
                ),
                (
                    "profile_summary_unknown_fields",
                    profile_summary["unknown_fields"] == ["ignored_future_field"]
                    and profile_summary["warnings"]
                    == ["Unknown profile field ignored: ignored_future_field"],
                ),
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
