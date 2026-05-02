from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import shlex
import subprocess

from strands import tool

MAX_READ_CHARS = 4000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 20
MAX_WRITE_CHARS = 12000
MAX_REPLACE_OCCURRENCES = 10
MAX_SHELL_OUTPUT_CHARS = 4000
MAX_SHELL_TIMEOUT_SECONDS = 20
MAX_SUMMARY_FILES = 400
MAX_SUMMARY_TOP_LEVEL = 12
MAX_SUMMARY_REPRESENTATIVE_FILES = 8
MAX_SUMMARY_TYPE_BUCKETS = 6

ALLOWED_LS_FLAGS = {"-1", "-a", "-l", "-la"}
ALLOWED_GIT_STATUS_FLAGS = {"--short", "--branch"}
ALLOWED_GIT_DIFF_FLAGS = {"--stat", "--cached"}
ALLOWED_PYTEST_FLAGS = {"-q", "-x", "-vv"}

NOTABLE_FILES = (
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
)

NOTABLE_DIRECTORIES = ("src", "app", "lib", "tests", "docs", "scripts", "artifacts")

SUMMARY_IGNORED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}

FILE_TYPE_LABELS = {
    ".py": "Python",
    ".md": "Markdown",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".sh": "Shell",
    ".txt": "Text",
}


@dataclass(slots=True, frozen=True)
class ShellCommandProfile:
    argv: tuple[str, ...]
    policy_level: str
    family: str


def resolve_shell_command(command: str) -> ShellCommandProfile:
    normalized_command = command.strip()
    if not normalized_command:
        raise ValueError("command must not be empty")

    argv = shlex.split(normalized_command)
    if not argv:
        raise ValueError("command must not be empty")

    executable = argv[0]
    args = argv[1:]

    if executable == "pwd":
        if args:
            raise ValueError("pwd does not accept additional arguments in this prototype")
        return ShellCommandProfile(argv=tuple(argv), policy_level="inspect", family="pwd")

    if executable == "ls":
        if len(args) > 1 or any(arg not in ALLOWED_LS_FLAGS for arg in args):
            raise ValueError("ls only supports an optional -1, -a, -l, or -la flag in this prototype")
        return ShellCommandProfile(argv=tuple(argv), policy_level="inspect", family="ls")

    if executable == "git":
        if not args:
            raise ValueError("git requires a supported read-only subcommand")
        subcommand = args[0]
        sub_args = args[1:]
        if subcommand == "status" and all(arg in ALLOWED_GIT_STATUS_FLAGS for arg in sub_args):
            return ShellCommandProfile(argv=tuple(argv), policy_level="inspect", family="git_status")
        if subcommand == "diff" and all(arg in ALLOWED_GIT_DIFF_FLAGS for arg in sub_args):
            return ShellCommandProfile(argv=tuple(argv), policy_level="inspect", family="git_diff")
        raise ValueError(
            "git only supports `status [--short] [--branch]` and `diff [--stat] [--cached]` in this prototype"
        )

    if executable == "pytest":
        if any(arg not in ALLOWED_PYTEST_FLAGS for arg in args):
            raise ValueError("pytest only supports -q, -x, and -vv flags in this prototype")
        return ShellCommandProfile(argv=tuple(argv), policy_level="test", family="pytest")

    if executable == "python" and len(args) >= 2 and args[0] == "-m" and args[1] == "pytest":
        pytest_args = args[2:]
        if any(arg not in ALLOWED_PYTEST_FLAGS for arg in pytest_args):
            raise ValueError("python -m pytest only supports -q, -x, and -vv flags in this prototype")
        return ShellCommandProfile(argv=tuple(argv), policy_level="test", family="pytest_module")

    raise ValueError(
        "shell command is outside the narrow allowlist: pwd, ls, git status/diff, pytest, python -m pytest"
    )


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

    def summarize_workspace(self, relative_path: str = ".", max_files: int = MAX_SUMMARY_FILES) -> str:
        """Summarize workspace structure so the agent can orient before deeper inspection."""
        if max_files < 1:
            raise ValueError("max_files must be >= 1")

        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {relative_path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {relative_path}")

        location = str(target.relative_to(self.root)) if target != self.root else "."
        top_level_entries = sorted(path for path in target.iterdir() if not self._should_ignore_summary_path(path))
        top_level_rendered = [
            f"- {path.relative_to(self.root)}{'/' if path.is_dir() else ''}"
            for path in top_level_entries[:MAX_SUMMARY_TOP_LEVEL]
        ]
        if len(top_level_entries) > MAX_SUMMARY_TOP_LEVEL:
            top_level_rendered.append(f"- ... truncated after {MAX_SUMMARY_TOP_LEVEL} entries")

        all_files = sorted(
            (path for path in target.rglob("*") if path.is_file() and not self._should_ignore_summary_path(path)),
            key=self._summary_file_sort_key,
        )
        scanned_files = all_files[:max_files]
        file_type_counts: dict[str, int] = {}
        representative_files: list[str] = []
        found_notable_files: list[str] = []
        found_notable_directories: list[str] = []

        seen_notable_files: set[str] = set()
        seen_notable_directories: set[str] = set()
        for path in scanned_files:
            relative = path.relative_to(self.root)
            relative_text = str(relative)
            suffix = path.suffix.lower()
            file_type = FILE_TYPE_LABELS.get(suffix, suffix or "<no extension>")
            file_type_counts[file_type] = file_type_counts.get(file_type, 0) + 1

            if len(representative_files) < MAX_SUMMARY_REPRESENTATIVE_FILES:
                representative_files.append(relative_text)

            if path.name in NOTABLE_FILES and relative_text not in seen_notable_files:
                found_notable_files.append(relative_text)
                seen_notable_files.add(relative_text)

            top_component = relative.parts[0] if relative.parts else ""
            if top_component in NOTABLE_DIRECTORIES and top_component not in seen_notable_directories:
                found_notable_directories.append(top_component)
                seen_notable_directories.add(top_component)

        dominant_types = sorted(file_type_counts.items(), key=lambda item: (-item[1], item[0]))
        dominant_rendered = [
            f"- {label}: {count} file(s)"
            for label, count in dominant_types[:MAX_SUMMARY_TYPE_BUCKETS]
        ]
        if len(dominant_types) > MAX_SUMMARY_TYPE_BUCKETS:
            dominant_rendered.append(f"- ... {len(dominant_types) - MAX_SUMMARY_TYPE_BUCKETS} more type bucket(s)")

        notable_directory_rendered = [f"- {name}/" for name in found_notable_directories] or ["- none"]
        notable_file_rendered = [f"- {name}" for name in found_notable_files] or ["- none"]
        representative_rendered = [f"- {name}" for name in representative_files] or ["- none"]

        scan_note = f"Scanned files: {len(scanned_files)}"
        if len(all_files) > len(scanned_files):
            scan_note += f" of {len(all_files)} total (truncated after {max_files})"
        else:
            scan_note += f" of {len(all_files)} total"

        return (
            f"Workspace root: {self.root}\n"
            f"Summary path: {location}\n"
            f"{scan_note}\n\n"
            f"Top-level entries:\n{chr(10).join(top_level_rendered) if top_level_rendered else '- <empty>'}\n\n"
            f"Notable directories:\n{chr(10).join(notable_directory_rendered)}\n\n"
            f"Notable files:\n{chr(10).join(notable_file_rendered)}\n\n"
            f"Dominant file types:\n{chr(10).join(dominant_rendered) if dominant_rendered else '- none'}\n\n"
            f"Representative files:\n{chr(10).join(representative_rendered)}\n\n"
            "Use read_file for specific docs/code and search_files for targeted text lookup."
        )

    def _should_ignore_summary_path(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            relative = path
        return any(part in SUMMARY_IGNORED_NAMES for part in relative.parts)

    def _summary_file_sort_key(self, path: Path) -> tuple[int, int, str]:
        relative = path.relative_to(self.root)
        parts = relative.parts
        top_component = parts[0] if parts else ""
        if path.name in NOTABLE_FILES:
            priority = 0
        elif top_component in NOTABLE_DIRECTORIES:
            priority = 1
        elif len(parts) == 1 and not path.name.startswith("."):
            priority = 2
        elif len(parts) == 1:
            priority = 3
        else:
            priority = 4
        return (priority, len(parts), str(relative))

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

    def run_shell_command(
        self,
        command: str,
        relative_path: str = ".",
        timeout_seconds: int = 5,
    ) -> str:
        """Run a narrowly scoped read/test shell command inside the workspace."""
        normalized_command = command.strip()
        if timeout_seconds < 1 or timeout_seconds > MAX_SHELL_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds must be between 1 and {MAX_SHELL_TIMEOUT_SECONDS}"
            )

        cwd = self.resolve_path(relative_path)
        if not cwd.exists():
            raise FileNotFoundError(f"Path does not exist: {relative_path}")
        if not cwd.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {relative_path}")

        profile = resolve_shell_command(normalized_command)
        argv = list(profile.argv)

        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"shell command timed out after {timeout_seconds}s: {normalized_command}"
            ) from exc

        location = str(cwd.relative_to(self.root)) if cwd != self.root else "."
        rendered_output = self._format_shell_output(completed.stdout, completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(
                f"Shell command failed with exit code {completed.returncode}.\n"
                f"CWD: {location}\n"
                f"Command: {normalized_command}\n"
                f"Output:\n{rendered_output}"
            )

        return (
            f"Workspace root: {self.root}\n"
            f"Action: shell command\n"
            f"Policy level: {profile.policy_level}\n"
            f"CWD: {location}\n"
            f"Command: {normalized_command}\n"
            f"Exit code: {completed.returncode}\n"
            f"Output:\n{rendered_output}"
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

    def replace_text(
        self,
        relative_path: str,
        old_text: str,
        new_text: str,
        expected_occurrences: int = 1,
    ) -> str:
        """Replace exact text inside a workspace file with bounded, predictable behavior."""
        if not old_text:
            raise ValueError("old_text must not be empty")
        if expected_occurrences < 1:
            raise ValueError("expected_occurrences must be >= 1")

        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {relative_path}")
        if not target.is_file():
            raise IsADirectoryError(f"Path is not a file: {relative_path}")

        original = target.read_text(encoding="utf-8")
        occurrences = original.count(old_text)
        if occurrences == 0:
            raise ValueError(f"old_text was not found in file: {relative_path}")
        if occurrences != expected_occurrences:
            raise ValueError(
                "old_text occurrence count mismatch: "
                f"expected {expected_occurrences}, found {occurrences}"
            )
        if occurrences > MAX_REPLACE_OCCURRENCES:
            raise ValueError(
                f"refusing to replace more than {MAX_REPLACE_OCCURRENCES} occurrences in one call"
            )

        updated = original.replace(old_text, new_text)
        if len(updated) > MAX_WRITE_CHARS and len(original) <= MAX_WRITE_CHARS:
            raise ValueError(f"updated content exceeds max size of {MAX_WRITE_CHARS} characters")

        target.write_text(updated, encoding="utf-8")
        return (
            f"Workspace root: {self.root}\n"
            f"Action: replaced text\n"
            f"File: {target.relative_to(self.root)}\n"
            f"Occurrences: {occurrences}"
        )

    def _format_shell_output(self, stdout: str, stderr: str) -> str:
        sections: list[str] = []
        stripped_stdout = stdout.strip()
        stripped_stderr = stderr.strip()
        if stripped_stdout:
            sections.append(f"stdout:\n{stripped_stdout}")
        if stripped_stderr:
            sections.append(f"stderr:\n{stripped_stderr}")
        rendered = "\n\n".join(sections) if sections else "<no output>"
        if len(rendered) > MAX_SHELL_OUTPUT_CHARS:
            return rendered[:MAX_SHELL_OUTPUT_CHARS] + "\n... truncated by output limit"
        return rendered


_DEFAULT_TOOLS = WorkspaceTools(Path.cwd())


@tool
def summarize_workspace(relative_path: str = ".", max_files: int = MAX_SUMMARY_FILES) -> str:
    return _DEFAULT_TOOLS.summarize_workspace(relative_path=relative_path, max_files=max_files)


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
def run_shell_command(command: str, relative_path: str = ".", timeout_seconds: int = 5) -> str:
    return _DEFAULT_TOOLS.run_shell_command(
        command=command,
        relative_path=relative_path,
        timeout_seconds=timeout_seconds,
    )


@tool
def write_file(relative_path: str, content: str, overwrite: bool = False) -> str:
    return _DEFAULT_TOOLS.write_file(relative_path=relative_path, content=content, overwrite=overwrite)


@tool
def replace_text(
    relative_path: str,
    old_text: str,
    new_text: str,
    expected_occurrences: int = 1,
) -> str:
    return _DEFAULT_TOOLS.replace_text(
        relative_path=relative_path,
        old_text=old_text,
        new_text=new_text,
        expected_occurrences=expected_occurrences,
    )
