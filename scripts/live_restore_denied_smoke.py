from strands_agent_tui.smokes import run_live_restore_denied_smoke
from strands_agent_tui.testing import emit_smoke_results


def main() -> int:
    return emit_smoke_results(run_live_restore_denied_smoke().items())


if __name__ == "__main__":
    raise SystemExit(main())
