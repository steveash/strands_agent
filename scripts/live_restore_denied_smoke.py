from strands_agent_tui.smokes import run_live_restore_denied_smoke


def main() -> None:
    results = run_live_restore_denied_smoke()
    for key, value in results.items():
        print(f"{key}= {value}")


if __name__ == "__main__":
    main()
