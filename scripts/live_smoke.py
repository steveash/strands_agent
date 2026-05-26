from __future__ import annotations

from strands_agent_tui.config import load_config
from strands_agent_tui.runtime import build_runtime
from strands_agent_tui.testing import emit_smoke_checks, emit_smoke_results


def main() -> int:
    config = load_config()
    try:
        runtime = build_runtime(mode=config.runtime_mode, openai_model=config.openai_model)
        result = runtime.run("Reply with exactly: live runtime ok")
    except Exception as exc:
        emit_smoke_results(
            [
                ("live_runtime_error", f"{type(exc).__name__}: {exc}"),
                ("live_runtime_requested", config.runtime_mode == "live"),
            ]
        )
        return 1

    print(result.text)
    print(f"provider={result.provider} mode={result.mode}")

    return emit_smoke_checks(
        [
            ("live_runtime_requested", config.runtime_mode == "live"),
            ("live_runtime_text", result.text.strip() == "live runtime ok"),
            ("live_runtime_provider_mode", bool(result.provider.strip()) and result.mode == "live"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
