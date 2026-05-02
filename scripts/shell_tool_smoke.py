from pathlib import Path

from strands_agent_tui.runtime import _ApprovalQueue, build_workspace_tools
from strands_agent_tui.tools.workspace import WorkspaceTools


def main() -> None:
    workspace = WorkspaceTools(Path(__file__).resolve().parents[1])
    print(workspace.run_shell_command("pwd"))
    print("---")
    print(workspace.run_shell_command("git status --short"))
    print("---")

    approvals = _ApprovalQueue()
    tools = {
        tool.tool_name: tool
        for tool in build_workspace_tools(
            workspace.root,
            approval_queue=approvals,
            prompt_provider=lambda: "run pytest -q",
        )
    }
    print(tools["run_shell_command"](command="pytest -q"))
    print("queued_approval=", approvals.current().tool_name if approvals.current() else None)


if __name__ == "__main__":
    main()
