from pathlib import Path

from strands_agent_tui.tools.workspace import WorkspaceTools


def main() -> None:
    workspace = WorkspaceTools(Path(__file__).resolve().parents[1])
    print(workspace.run_shell_command("pwd"))
    print("---")
    print(workspace.run_shell_command("git status --short"))


if __name__ == "__main__":
    main()
