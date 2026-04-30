from pathlib import Path

import pytest

from strands_agent_tui.runtime import build_workspace_tools
from strands_agent_tui.tools.workspace import WorkspaceTools


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceTools:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\nprint('world')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("sample\n", encoding="utf-8")
    return WorkspaceTools(tmp_path)


def test_list_files_returns_workspace_relative_entries(workspace: WorkspaceTools) -> None:
    rendered = workspace.list_files()

    assert "Workspace root:" in rendered
    assert "README.md" in rendered
    assert "src/" in rendered


def test_summarize_workspace_reports_repo_shape(workspace: WorkspaceTools) -> None:
    rendered = workspace.summarize_workspace()

    assert "Summary path: ." in rendered
    assert "Top-level entries:" in rendered
    assert "Notable directories:" in rendered
    assert "- src/" in rendered
    assert "Notable files:" in rendered
    assert "- README.md" in rendered
    assert "Dominant file types:" in rendered
    assert "Python: 1 file(s)" in rendered
    assert "Representative files:" in rendered
    assert "src/main.py" in rendered


def test_read_file_returns_excerpt_with_line_range(workspace: WorkspaceTools) -> None:
    rendered = workspace.read_file("src/main.py", start_line=2, max_lines=1)

    assert "File: src/main.py" in rendered
    assert "Lines: 2-2" in rendered
    assert "print('world')" in rendered


def test_search_files_returns_line_matches(workspace: WorkspaceTools) -> None:
    rendered = workspace.search_files("world", glob_pattern="*.py")

    assert "Search: query='world'" in rendered
    assert "src/main.py:2: print('world')" in rendered


def test_write_file_creates_new_file_but_refuses_implicit_overwrite(workspace: WorkspaceTools) -> None:
    rendered = workspace.write_file("notes/todo.txt", "ship it\n")

    assert "Action: wrote" in rendered
    assert "File: notes/todo.txt" in rendered
    assert workspace.read_file("notes/todo.txt").endswith("ship it")

    with pytest.raises(FileExistsError, match="overwrite=True"):
        workspace.write_file("notes/todo.txt", "new text\n")


def test_replace_text_updates_exact_match(workspace: WorkspaceTools) -> None:
    rendered = workspace.replace_text(
        "src/main.py",
        "print('world')",
        "print('strands')",
    )

    assert "Action: replaced text" in rendered
    assert "Occurrences: 1" in rendered
    assert "print('strands')" in workspace.read_file("src/main.py")


def test_replace_text_rejects_missing_or_ambiguous_matches(workspace: WorkspaceTools) -> None:
    with pytest.raises(ValueError, match="not found"):
        workspace.replace_text("src/main.py", "print('missing')", "print('x')")

    (workspace.root / "repeat.txt").write_text("alpha\nalpha\n", encoding="utf-8")
    with pytest.raises(ValueError, match="occurrence count mismatch"):
        workspace.replace_text("repeat.txt", "alpha", "beta")


def test_workspace_rejects_paths_outside_root(workspace: WorkspaceTools) -> None:
    with pytest.raises(ValueError, match="escapes workspace root"):
        workspace.read_file("../secrets.txt")


def test_build_workspace_tools_returns_workspace_tool_set(tmp_path: Path) -> None:
    tools = build_workspace_tools(tmp_path)

    names = [tool.tool_name for tool in tools]

    assert names == ["summarize_workspace", "list_files", "read_file", "search_files", "write_file", "replace_text"]


def test_build_workspace_tools_emits_events_via_sink(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    events = []
    tools = {tool.tool_name: tool for tool in build_workspace_tools(tmp_path, event_sink=events.append)}

    rendered = tools["read_file"](relative_path="notes.txt")

    assert "hello" in rendered
    assert [event.kind for event in events] == ["steering_decision", "tool_started", "tool_finished"]
    assert events[0].title == "read_file"
    assert events[0].data["tool_name"] == "read_file"
    assert events[0].data["allowed"] is True
    assert "notes.txt" in events[1].detail
    assert events[1].data["tool_name"] == "read_file"
    assert events[1].data["args"]["relative_path"] == "notes.txt"
    assert "elapsed_ms=" in events[2].detail
    assert "elapsed_ms" in events[2].data
