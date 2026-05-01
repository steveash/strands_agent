from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch

DEFAULT_PROTECTED_GLOBS = (".env", ".env.*", "*.pem", "*.key")


@dataclass(slots=True)
class SteeringDecision:
    allowed: bool
    reason: str
    severity: str = "info"
    category: str = "allow"
    details: dict[str, object] = field(default_factory=dict)
    disposition: str = "allow"

    @property
    def requires_confirmation(self) -> bool:
        return self.disposition == "confirm"


@dataclass(slots=True)
class ToolSteeringPolicy:
    allow_overwrite: bool = False
    protected_globs: tuple[str, ...] = DEFAULT_PROTECTED_GLOBS

    def evaluate(self, tool_name: str, args: dict[str, object]) -> SteeringDecision:
        if tool_name == "write_file":
            return self._evaluate_write(args)
        if tool_name == "replace_text":
            return self._evaluate_replace(args)
        if tool_name == "run_shell_command":
            return self._evaluate_shell_command(args)
        return SteeringDecision(allowed=True, reason="Tool call allowed.")

    def _evaluate_write(self, args: dict[str, object]) -> SteeringDecision:
        relative_path = str(args.get("relative_path", ""))
        overwrite = bool(args.get("overwrite", False))
        if self._matches_protected_path(relative_path):
            return SteeringDecision(
                allowed=False,
                reason="Blocked write to protected file pattern.",
                severity="error",
                category="deny",
                details={"relative_path": relative_path, "protected": True},
                disposition="deny",
            )
        if overwrite and not self.allow_overwrite:
            return SteeringDecision(
                allowed=False,
                reason="Overwrite request requires confirmation under the default steering policy.",
                severity="warn",
                category="confirm_needed",
                details={"relative_path": relative_path, "overwrite": True},
                disposition="confirm",
            )
        if overwrite:
            return SteeringDecision(
                allowed=True,
                reason="Allowed overwrite because policy opt-in is enabled.",
                severity="warn",
                category="allow_with_notice",
                details={"relative_path": relative_path, "overwrite": True},
            )
        return SteeringDecision(
            allowed=True,
            reason="Allowed bounded workspace write.",
            details={"relative_path": relative_path, "overwrite": False},
        )

    def _evaluate_replace(self, args: dict[str, object]) -> SteeringDecision:
        relative_path = str(args.get("relative_path", ""))
        expected_occurrences = int(args.get("expected_occurrences", 1))
        if self._matches_protected_path(relative_path):
            return SteeringDecision(
                allowed=False,
                reason="Blocked exact-match edit to protected file pattern.",
                severity="error",
                category="deny",
                details={"relative_path": relative_path, "protected": True},
                disposition="deny",
            )
        if expected_occurrences > 1:
            return SteeringDecision(
                allowed=False,
                reason="Multi-occurrence edit requires confirmation before execution.",
                severity="warn",
                category="confirm_needed",
                details={"relative_path": relative_path, "expected_occurrences": expected_occurrences},
                disposition="confirm",
            )
        return SteeringDecision(
            allowed=True,
            reason="Allowed exact-match edit.",
            details={"relative_path": relative_path, "expected_occurrences": expected_occurrences},
        )

    def _evaluate_shell_command(self, args: dict[str, object]) -> SteeringDecision:
        command = str(args.get("command", "")).strip()
        relative_path = str(args.get("relative_path", "."))
        return SteeringDecision(
            allowed=False,
            reason="Shell command execution requires explicit confirmation in this prototype.",
            severity="warn",
            category="confirm_needed",
            details={"command": command, "relative_path": relative_path},
            disposition="confirm",
        )

    def _matches_protected_path(self, relative_path: str) -> bool:
        normalized = relative_path.strip()
        return any(fnmatch(normalized, pattern) for pattern in self.protected_globs)


def build_default_policy(*, allow_overwrite: bool = False, protected_globs: tuple[str, ...] | None = None) -> ToolSteeringPolicy:
    return ToolSteeringPolicy(
        allow_overwrite=allow_overwrite,
        protected_globs=protected_globs or DEFAULT_PROTECTED_GLOBS,
    )
