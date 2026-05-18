from io import StringIO

from strands_agent_tui.testing import emit_smoke_check, emit_smoke_checks


def test_emit_smoke_check_formats_boolean_result_line() -> None:
    stdout = StringIO()

    ok = emit_smoke_check("replay_live_view", True, stdout=stdout)

    assert ok is True
    assert stdout.getvalue() == "replay_live_view= True\n"


def test_emit_smoke_checks_returns_nonzero_when_any_check_fails() -> None:
    stdout = StringIO()

    exit_code = emit_smoke_checks(
        [
            ("shell_tool_pwd", True),
            ("shell_tool_test_approval", False),
            ("summary_backlog_counts", True),
        ],
        stdout=stdout,
    )

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == [
        "shell_tool_pwd= True",
        "shell_tool_test_approval= False",
        "summary_backlog_counts= True",
    ]
