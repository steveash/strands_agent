from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.smokes import run_live_restore_denied_smoke, run_live_restore_smoke


def test_app_constructs() -> None:
    app = StrandsAgentApp()
    assert app.TITLE == "strands_agent"


def test_live_restore_smoke_exercises_restored_approval_metadata_end_to_end() -> None:
    results = run_live_restore_smoke()

    assert results["live_restore_initial_pending"] is True
    assert results["live_restore_saved_pending"] is True
    assert results["live_restore_restored_queue"] is True
    assert results["live_restore_approved_event"] is True
    assert results["live_restore_tool_event"] is True
    assert results["live_restore_summary"] is True
    assert results["summary_value"] == "approved write_file via live_runtime | resumed | remaining 0"
    assert results["notes_text"] == "updated from restored approval"


def test_live_restore_denied_smoke_exercises_restored_denial_metadata_end_to_end() -> None:
    results = run_live_restore_denied_smoke()

    assert results["live_restore_denied_initial_pending"] is True
    assert results["live_restore_denied_saved_pending"] is True
    assert results["live_restore_denied_restored_queue"] is True
    assert results["live_restore_denied_event"] is True
    assert results["live_restore_denied_no_tool_event"] is True
    assert results["live_restore_denied_summary"] is True
    assert results["summary_value"] == "denied write_file via live_runtime | remaining 0"
    assert results["notes_text"] == "old"
