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


def test_workspace_rejects_paths_outside_root(workspace: WorkspaceTools) -> None:
    with pytest.raises(ValueError, match="escapes workspace root"):
        workspace.read_file("../secrets.txt")


def test_build_workspace_tools_returns_workspace_tool_set(tmp_path: Path) -> None:
    tools = build_workspace_tools(tmp_path)

    names = [tool.tool_name for tool in tools]

    assert names == ["list_files", "read_file", "search_files", "write_file"]
