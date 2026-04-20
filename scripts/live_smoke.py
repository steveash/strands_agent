from __future__ import annotations

from strands_agent_tui.config import load_config
from strands_agent_tui.runtime import build_runtime


def main() -> None:
    config = load_config()
    runtime = build_runtime(mode=config.runtime_mode, openai_model=config.openai_model)
    result = runtime.run("Reply with exactly: live runtime ok")
    print(result.text)
    print(f"provider={result.provider} mode={result.mode}")


if __name__ == "__main__":
    main()
