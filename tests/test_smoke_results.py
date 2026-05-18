from io import StringIO

from strands_agent_tui.testing import emit_smoke_check, emit_smoke_checks, emit_smoke_results


def test_emit_smoke_check_writes_result_line_and_returns_status() -> None:
    stdout = StringIO()

    ok = emit_smoke_check("approval_restart_saved_queue", True, stdout=stdout)

    assert ok is True
    assert stdout.getvalue() == "approval_restart_saved_queue= True\n"


def test_emit_smoke_checks_returns_nonzero_when_any_check_fails() -> None:
    stdout = StringIO()

    exit_code = emit_smoke_checks(
        [
            ("approval_restart_saved_queue", True),
            ("approval_restart_remaining_queue", False),
        ],
        stdout=stdout,
    )

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == [
        "approval_restart_saved_queue= True",
        "approval_restart_remaining_queue= False",
    ]


def test_emit_smoke_results_preserves_detail_lines_and_boolean_exit_code() -> None:
    stdout = StringIO()

    exit_code = emit_smoke_results(
        [
            ("summary_value", "approved write_file via live_runtime | resumed | remaining 0"),
            ("live_restore_summary", True),
            ("notes_text", "updated from restored approval"),
            ("live_restore_tool_event", False),
            ("result_count", 2),
        ],
        stdout=stdout,
    )

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == [
        "summary_value: approved write_file via live_runtime | resumed | remaining 0",
        "live_restore_summary= True",
        "notes_text: updated from restored approval",
        "live_restore_tool_event= False",
        "result_count: 2",
    ]
