from pathlib import Path

from strands_agent_tui.runtime import _ApprovalQueue, build_workspace_tools
from strands_agent_tui.testing import emit_smoke_checks
from strands_agent_tui.tools.workspace import WorkspaceTools


def main() -> int:
    workspace = WorkspaceTools(Path(__file__).resolve().parents[1])
    pwd_output = workspace.run_shell_command("pwd")
    print(pwd_output)
    print("---")

    git_status_output = workspace.run_shell_command("git status --short")
    print(git_status_output)
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
    approval_output = tools["run_shell_command"](command="pytest -q")
    print(approval_output)
    current_approval = approvals.current()
    print("queued_approval=", current_approval.tool_name if current_approval else None)

    return emit_smoke_checks(
        [
            (
                "shell_tool_pwd",
                "Action: shell command" in pwd_output
                and "Policy level: inspect" in pwd_output
                and "Command: pwd" in pwd_output
                and str(workspace.root) in pwd_output,
            ),
            (
                "shell_tool_git_status",
                "Action: shell command" in git_status_output
                and "Policy level: inspect" in git_status_output
                and "Command: git status --short" in git_status_output
                and "Exit code: 0" in git_status_output,
            ),
            (
                "shell_tool_test_approval",
                "Approval required for run_shell_command." in approval_output
                and current_approval is not None
                and current_approval.tool_name == "run_shell_command"
                and current_approval.args.get("command") == "pytest -q"
                and current_approval.args.get("relative_path") == "."
                and current_approval.args.get("timeout_seconds") == 5,
            ),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
