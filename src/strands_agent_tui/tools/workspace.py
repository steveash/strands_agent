from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from strands import tool

MAX_READ_CHARS = 4000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 20
MAX_WRITE_CHARS = 12000


@dataclass(slots=True)
class WorkspaceTools:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve()

    def resolve_path(self, candidate: str | Path = ".") -> Path:
        requested = Path(candidate)
        target = (self.root / requested).resolve() if not requested.is_absolute() else requested.resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace root: {candidate}") from exc
        return target

    def list_files(self, relative_path: str = ".", recursive: bool = False) -> str:
        """List files and directories inside the current workspace.

        Parameters:
          relative_path: Directory relative to the workspace root. Defaults to the workspace root.
          recursive: When true, walk subdirectories recursively.

        Returns:
          A newline-delimited listing rooted at the workspace.
        """
        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {relative_path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {relative_path}")

        if recursive:
            paths = sorted(path.relative_to(self.root) for path in target.rglob("*"))
        else:
            paths = sorted(path.relative_to(self.root) for path in target.iterdir())

        rendered: list[str] = []
        for item in paths[:MAX_LIST_ENTRIES]:
            suffix = "/" if self.root.joinpath(item).is_dir() else ""
            rendered.append(f"{item}{suffix}")
        if len(paths) > MAX_LIST_ENTRIES:
            rendered.append(f"... truncated after {MAX_LIST_ENTRIES} entries")

        location = str(target.relative_to(self.root)) if target != self.root else "."
        return f"Workspace root: {self.root}\nListing: {location}\n" + ("\n".join(rendered) if rendered else "<empty>")

    def read_file(self, relative_path: str, start_line: int = 1, max_lines: int = 200) -> str:
        """Read a text file from the current workspace.

        Parameters:
          relative_path: File path relative to the workspace root.
          start_line: 1-based line number to start from.
          max_lines: Maximum number of lines to return.

        Returns:
          The requested file excerpt, truncated when necessary.
        """
        if start_line < 1:
            raise ValueError("start_line must be >= 1")
        if max_lines < 1:
            raise ValueError("max_lines must be >= 1")

        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {relative_path}")
        if not target.is_file():
            raise IsADirectoryError(f"Path is not a file: {relative_path}")

        text = target.read_text(encoding="utf-8")
        lines = text.splitlines()
        start_index = start_line - 1
        excerpt = lines[start_index : start_index + max_lines]
        body = "\n".join(excerpt)
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS] + "\n... truncated by character limit"
        elif start_index + max_lines < len(lines):
            body += "\n... truncated by line limit"
        return f"File: {target.relative_to(self.root)}\nLines: {start_line}-{start_line + len(excerpt) - 1}\n{body}"

    def search_files(
        self,
        query: str,
        relative_path: str = ".",
        glob_pattern: str = "*",
        case_sensitive: bool = False,
        max_results: int = MAX_SEARCH_RESULTS,
    ) -> str:
        """Search workspace text files for a string, with bounded output."""
        normalized_query = query if case_sensitive else query.lower()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if max_results < 1:
            raise ValueError("max_results must be >= 1")

        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {relative_path}")

        candidates = [target] if target.is_file() else sorted(path for path in target.rglob("*") if path.is_file())
        matches: list[str] = []
        scanned = 0
        for path in candidates:
            relative = path.relative_to(self.root)
            if not fnmatch(relative.name, glob_pattern) and not fnmatch(str(relative), glob_pattern):
                continue
            scanned += 1
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.lower()
                if normalized_query in haystack:
                    matches.append(f"{relative}:{line_number}: {line}")
                    if len(matches) >= max_results:
                        return (
                            f"Workspace root: {self.root}\n"
                            f"Search: query={query!r}, path={relative_path}, glob={glob_pattern}, scanned_files={scanned}\n"
                            + "\n".join(matches)
                            + f"\n... truncated after {max_results} matches"
                        )
        body = "\n".join(matches) if matches else "<no matches>"
        return (
            f"Workspace root: {self.root}\n"
            f"Search: query={query!r}, path={relative_path}, glob={glob_pattern}, scanned_files={scanned}\n"
            f"{body}"
        )

    def write_file(self, relative_path: str, content: str, overwrite: bool = False) -> str:
        """Write a text file inside the workspace with conservative overwrite behavior."""
        if len(content) > MAX_WRITE_CHARS:
            raise ValueError(f"content exceeds max size of {MAX_WRITE_CHARS} characters")

        target = self.resolve_path(relative_path)
        if target.exists() and target.is_dir():
            raise IsADirectoryError(f"Path is a directory: {relative_path}")
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing file without overwrite=True: {relative_path}"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        action = "overwrote" if overwrite else "wrote"
        return (
            f"Workspace root: {self.root}\n"
            f"Action: {action}\n"
            f"File: {target.relative_to(self.root)}\n"
            f"Characters: {len(content)}"
        )


_DEFAULT_TOOLS = WorkspaceTools(Path.cwd())


@tool
def list_files(relative_path: str = ".", recursive: bool = False) -> str:
    return _DEFAULT_TOOLS.list_files(relative_path=relative_path, recursive=recursive)


@tool
def read_file(relative_path: str, start_line: int = 1, max_lines: int = 200) -> str:
    return _DEFAULT_TOOLS.read_file(relative_path=relative_path, start_line=start_line, max_lines=max_lines)


@tool
def search_files(
    query: str,
    relative_path: str = ".",
    glob_pattern: str = "*",
    case_sensitive: bool = False,
    max_results: int = MAX_SEARCH_RESULTS,
) -> str:
    return _DEFAULT_TOOLS.search_files(
        query=query,
        relative_path=relative_path,
        glob_pattern=glob_pattern,
        case_sensitive=case_sensitive,
        max_results=max_results,
    )


@tool
def write_file(relative_path: str, content: str, overwrite: bool = False) -> str:
    return _DEFAULT_TOOLS.write_file(relative_path=relative_path, content=content, overwrite=overwrite)
