from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from os import getenv
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol

from strands import tool

from strands_agent_tui.steering import SteeringDecision, ToolSteeringPolicy, build_default_policy
from strands_agent_tui.tools.workspace import WorkspaceTools


@dataclass(slots=True)
class RuntimeEvent:
    kind: str
    title: str
    detail: str
    timestamp: str | None = None
    data: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(),
            "data": self.data,
        }

    @property
    def category(self) -> str:
        return categorize_event_kind(self.kind)


@dataclass(slots=True)
class ApprovalRequest:
    request_id: str
    tool_name: str
    reason: str
    args: dict[str, object] = field(default_factory=dict)
    source: str = "runtime"
    prompt: str = ""

    def summary(self) -> str:
        args_preview = ", ".join(f"{key}={value!r}" for key, value in sorted(self.args.items())) or "no args"
        return f"{self.tool_name} [{self.request_id}] | {self.reason} | {args_preview}"


@dataclass(slots=True)
class AgentResponse:
    text: str
    provider: str
    mode: str
    events: list[RuntimeEvent] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    pending_approval: ApprovalRequest | None = None


class AgentRuntime(Protocol):
    def run(self, prompt: str) -> AgentResponse:
        ...

    def resolve_pending_approval(self, approval_id: str, approve: bool) -> AgentResponse:
        ...


RuntimeEventSink = Callable[[RuntimeEvent], None]


@dataclass(slots=True)
class _PendingApproval:
    request: ApprovalRequest
    execute: Callable[[], str]


class _ApprovalQueue:
    def __init__(self) -> None:
        self._pending: list[_PendingApproval] = []
        self._counter = 0

    def reset(self) -> None:
        self._pending.clear()

    def enqueue(
        self,
        *,
        tool_name: str,
        reason: str,
        args: dict[str, object],
        source: str,
        prompt: str,
        execute: Callable[[], str],
    ) -> ApprovalRequest:
        self._counter += 1
        request = ApprovalRequest(
            request_id=f"approval-{self._counter:04d}",
            tool_name=tool_name,
            reason=reason,
            args=dict(args),
            source=source,
            prompt=prompt,
        )
        self._pending.append(_PendingApproval(request=request, execute=execute))
        return request

    def current(self) -> ApprovalRequest | None:
        if not self._pending:
            return None
        return self._pending[0].request

    def pending_count(self) -> int:
        return len(self._pending)

    def pop(self, approval_id: str) -> _PendingApproval:
        current = self.current()
        if current is None:
            raise ValueError("No pending approval request is available.")
        if current.request_id != approval_id:
            raise ValueError(
                f"Approval request {approval_id!r} is no longer current. Current request is {current.request_id!r}."
            )
        return self._pending.pop(0)


def runtime_event(
    kind: str,
    title: str,
    detail: str,
    *,
    data: dict[str, object] | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        kind=kind,
        title=title,
        detail=detail,
        timestamp=datetime.now(UTC).isoformat(),
        data=data or {},
    )


def categorize_event_kind(kind: str) -> str:
    if kind == "tool_failed":
        return "failure"
    if kind.startswith("tool_"):
        return "tool"
    if "error" in kind or "failed" in kind:
        return "failure"
    if kind.startswith("artifact_") or kind.startswith("session_"):
        return "persistence"
    return "runtime"


def _steering_event_kind(decision: SteeringDecision) -> str:
    if decision.requires_confirmation:
        return "steering_confirmation_required"
    if not decision.allowed:
        return "steering_blocked"
    return "steering_decision"


def _summarize_tool_value(value: object, limit: int = 120) -> str:
    text = repr(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


class FakeStrandsRuntime:
    """Deterministic runtime for local development and tests.

    This gives Phase 1 a stable way to prove the TUI <-> runtime boundary
    before relying on live model credentials.
    """

    provider_name = "fake-strands"

    def __init__(self) -> None:
        self._approval_queue = _ApprovalQueue()

    def run(self, prompt: str) -> AgentResponse:
        normalized = prompt.strip()
        if not normalized:
            return AgentResponse(
                text="Please enter a prompt.",
                provider=self.provider_name,
                mode="fake",
                events=[
                    runtime_event(
                        kind="input_rejected",
                        title="Empty prompt",
                        detail="Prompt contained only whitespace, so the fake runtime returned guidance instead of running tools.",
                        data={"prompt_empty": True},
                    )
                ],
                metadata={"provider": self.provider_name, "mode": "fake"},
            )

        if self._approval_queue.pending_count() == 0:
            self._approval_queue.reset()

        events = [
            runtime_event(
                kind="prompt_received",
                title="Prompt accepted",
                detail=normalized,
                data={"prompt_length": len(normalized)},
            ),
            runtime_event(
                kind="steering_decision",
                title="fake-policy",
                detail="Fake runtime is using the default conservative steering posture.",
                data={"allow_overwrite": False, "source": "fake_runtime"},
            ),
        ]

        lowered = normalized.lower()
        overwrite_requested = any(keyword in lowered for keyword in ["overwrite", "replace existing", "overwrite existing"])
        broad_edit_requested = any(
            keyword in lowered
            for keyword in ["replace all", "all occurrences", "every occurrence", "bulk edit", "rewrite all"]
        )
        if any(keyword in lowered for keyword in ["file", "workspace", "repo", "read", "list"]):
            events.extend(
                [
                    runtime_event(
                        kind="tool_started",
                        title="list_files",
                        detail="Deterministic fake tool event for workspace inspection.",
                        data={"tool_name": "list_files", "source": "fake_runtime"},
                    ),
                    runtime_event(
                        kind="tool_finished",
                        title="list_files",
                        detail="Returned a simulated workspace listing without touching disk.",
                        data={"tool_name": "list_files", "source": "fake_runtime"},
                    ),
                ]
            )
        if any(keyword in lowered for keyword in ["summarize", "summary", "overview", "shape", "structure"]):
            events.extend(
                [
                    runtime_event(
                        kind="tool_started",
                        title="summarize_workspace",
                        detail="Deterministic fake summary event for fast workspace orientation.",
                        data={"tool_name": "summarize_workspace", "source": "fake_runtime"},
                    ),
                    runtime_event(
                        kind="tool_finished",
                        title="summarize_workspace",
                        detail="Returned a simulated workspace summary without walking the real filesystem.",
                        data={"tool_name": "summarize_workspace", "source": "fake_runtime"},
                    ),
                ]
            )
        if any(keyword in lowered for keyword in ["search", "find", "grep", "match"]):
            events.extend(
                [
                    runtime_event(
                        kind="tool_started",
                        title="search_files",
                        detail="Deterministic fake search event for repo-wide inspection.",
                        data={"tool_name": "search_files", "source": "fake_runtime"},
                    ),
                    runtime_event(
                        kind="tool_finished",
                        title="search_files",
                        detail="Returned simulated search hits from the fake workspace.",
                        data={"tool_name": "search_files", "source": "fake_runtime"},
                    ),
                ]
            )
        if any(keyword in lowered for keyword in ["write", "create", "save"]) and not overwrite_requested:
            events.extend(
                [
                    runtime_event(
                        kind="tool_started",
                        title="write_file",
                        detail="Deterministic fake write event for a conservative mutation path.",
                        data={"tool_name": "write_file", "source": "fake_runtime"},
                    ),
                    runtime_event(
                        kind="tool_finished",
                        title="write_file",
                        detail="Simulated a bounded workspace write without changing disk.",
                        data={"tool_name": "write_file", "source": "fake_runtime"},
                    ),
                ]
            )
        if any(keyword in lowered for keyword in ["edit", "replace", "rewrite", "change"]) and not broad_edit_requested:
            events.extend(
                [
                    runtime_event(
                        kind="tool_started",
                        title="replace_text",
                        detail="Deterministic fake exact-match edit event for conservative code mutation.",
                        data={"tool_name": "replace_text", "source": "fake_runtime"},
                    ),
                    runtime_event(
                        kind="tool_finished",
                        title="replace_text",
                        detail="Simulated an exact text replacement without touching disk.",
                        data={"tool_name": "replace_text", "source": "fake_runtime"},
                    ),
                ]
            )

        self._approval_queue.reset()
        for spec in self._build_fake_pending_requests(normalized):
            self._approval_queue.enqueue(
                tool_name=spec["tool_name"],
                reason=spec["reason"],
                args=spec["args"],
                source="fake_runtime",
                prompt=normalized,
                execute=lambda spec=spec: self._execute_fake_pending_tool(spec),
            )

        pending_approval = self._approval_queue.current()
        if pending_approval is not None:
            events.append(
                runtime_event(
                    kind="steering_confirmation_required",
                    title=pending_approval.tool_name,
                    detail=pending_approval.reason,
                    data={
                        "tool_name": pending_approval.tool_name,
                        "source": pending_approval.source,
                        "disposition": "confirm",
                        "requires_confirmation": True,
                        "approval_id": pending_approval.request_id,
                        "pending_count": self._approval_queue.pending_count(),
                        **pending_approval.args,
                    },
                )
            )

        events.append(
            runtime_event(
                kind="response_completed",
                title="Assistant response ready",
                detail=f"Provider={self.provider_name}, mode=fake",
                data={
                    "provider": self.provider_name,
                    "mode": "fake",
                    "pending_approval": pending_approval is not None,
                    "pending_count": self._approval_queue.pending_count(),
                },
            )
        )
        text = f"(fake-strands) Echo: {normalized}"
        if pending_approval is not None:
            text = (
                f"(fake-strands) Approval required before continuing: {pending_approval.tool_name}. "
                f"Use F9 to approve or F10 to deny in the TUI."
            )
        return AgentResponse(
            text=text,
            provider=self.provider_name,
            mode="fake",
            events=events,
            metadata={
                "provider": self.provider_name,
                "mode": "fake",
                "pending_approval": pending_approval is not None,
                "pending_count": self._approval_queue.pending_count(),
            },
            pending_approval=pending_approval,
        )

    def resolve_pending_approval(self, approval_id: str, approve: bool) -> AgentResponse:
        pending = self._approval_queue.pop(approval_id)
        events: list[RuntimeEvent] = []

        if approve:
            events.append(
                runtime_event(
                    kind="steering_approved",
                    title=pending.request.tool_name,
                    detail="User approved the pending mutation request in the TUI.",
                    data={
                        "tool_name": pending.request.tool_name,
                        "approval_id": pending.request.request_id,
                        **pending.request.args,
                    },
                )
            )
            events.append(
                runtime_event(
                    kind="tool_started",
                    title=pending.request.tool_name,
                    detail="Executing previously approved fake mutation request.",
                    data={
                        "tool_name": pending.request.tool_name,
                        "approval_id": pending.request.request_id,
                        "source": "fake_runtime",
                        **pending.request.args,
                    },
                )
            )
            tool_result = pending.execute()
            events.append(
                runtime_event(
                    kind="tool_finished",
                    title=pending.request.tool_name,
                    detail=tool_result,
                    data={
                        "tool_name": pending.request.tool_name,
                        "approval_id": pending.request.request_id,
                        "source": "fake_runtime",
                        **pending.request.args,
                    },
                )
            )
            text = f"(fake-strands) Approved {pending.request.tool_name}. {tool_result}"
        else:
            events.append(
                runtime_event(
                    kind="steering_denied",
                    title=pending.request.tool_name,
                    detail="User denied the pending mutation request in the TUI.",
                    data={
                        "tool_name": pending.request.tool_name,
                        "approval_id": pending.request.request_id,
                        **pending.request.args,
                    },
                )
            )
            text = f"(fake-strands) Skipped {pending.request.tool_name} at user request."

        next_pending = self._approval_queue.current()
        if next_pending is not None:
            events.append(
                runtime_event(
                    kind="steering_confirmation_required",
                    title=next_pending.tool_name,
                    detail=next_pending.reason,
                    data={
                        "tool_name": next_pending.tool_name,
                        "source": next_pending.source,
                        "disposition": "confirm",
                        "requires_confirmation": True,
                        "approval_id": next_pending.request_id,
                        "pending_count": self._approval_queue.pending_count(),
                        **next_pending.args,
                    },
                )
            )
            text += f" Next approval required: {next_pending.tool_name}."

        events.append(
            runtime_event(
                kind="response_completed",
                title="Assistant response ready",
                detail=f"Provider={self.provider_name}, mode=fake",
                data={
                    "provider": self.provider_name,
                    "mode": "fake",
                    "pending_approval": next_pending is not None,
                    "pending_count": self._approval_queue.pending_count(),
                },
            )
        )
        return AgentResponse(
            text=text,
            provider=self.provider_name,
            mode="fake",
            events=events,
            metadata={
                "provider": self.provider_name,
                "mode": "fake",
                "approval_action": "approved" if approve else "denied",
                "pending_approval": next_pending is not None,
                "pending_count": self._approval_queue.pending_count(),
            },
            pending_approval=next_pending,
        )

    def _build_fake_pending_requests(self, prompt: str) -> list[dict[str, object]]:
        lowered = prompt.lower()
        requests: list[dict[str, object]] = []
        if any(keyword in lowered for keyword in ["overwrite", "replace existing", "overwrite existing"]):
            requests.append(
                {
                    "tool_name": "write_file",
                    "reason": "Fake runtime flagged an overwrite request that requires confirmation before execution.",
                    "args": {
                        "relative_path": "notes.txt",
                        "overwrite": True,
                    },
                }
            )
        if any(
            keyword in lowered
            for keyword in ["replace all", "all occurrences", "every occurrence", "bulk edit", "rewrite all"]
        ):
            requests.append(
                {
                    "tool_name": "replace_text",
                    "reason": "Fake runtime flagged a broad edit request that requires confirmation before execution.",
                    "args": {
                        "relative_path": "notes.txt",
                        "expected_occurrences": 2,
                    },
                }
            )
        return requests

    def _execute_fake_pending_tool(self, spec: dict[str, object]) -> str:
        tool_name = str(spec["tool_name"])
        args = dict(spec["args"])
        relative_path = str(args.get("relative_path", "notes.txt"))
        if tool_name == "write_file":
            return f"Simulated overwrite of {relative_path}."
        if tool_name == "replace_text":
            occurrences = int(args.get("expected_occurrences", 1))
            return f"Simulated exact text replacement across {occurrences} occurrence(s) in {relative_path}."
        return f"Simulated execution of {tool_name}."


def build_workspace_tools(
    workspace_root: str | Path,
    event_sink: RuntimeEventSink | None = None,
    steering_policy: ToolSteeringPolicy | None = None,
    approval_queue: _ApprovalQueue | None = None,
    approval_source: str = "live_runtime",
    prompt_provider: Callable[[], str] | None = None,
) -> list[object]:
    workspace = WorkspaceTools(Path(workspace_root))
    policy = steering_policy or build_default_policy()

    def execute_with_events(tool_name: str, action: Callable[..., str], kwargs: dict[str, object]) -> str:
        started_at = perf_counter()
        if event_sink is not None:
            event_sink(
                runtime_event(
                    kind="tool_started",
                    title=tool_name,
                    detail=f"args={_summarize_tool_value(kwargs)}",
                    data={"tool_name": tool_name, "args": kwargs},
                )
            )
        try:
            result = action(**kwargs)
        except Exception as exc:
            elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
            if event_sink is not None:
                event_sink(
                    runtime_event(
                        kind="tool_failed",
                        title=tool_name,
                        detail=f"error={exc} | elapsed_ms={elapsed_ms}",
                        data={"tool_name": tool_name, "error": str(exc), "elapsed_ms": elapsed_ms},
                    )
                )
            raise
        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        if event_sink is not None:
            event_sink(
                runtime_event(
                    kind="tool_finished",
                    title=tool_name,
                    detail=f"elapsed_ms={elapsed_ms} | result={_summarize_tool_value(result)}",
                    data={"tool_name": tool_name, "elapsed_ms": elapsed_ms},
                )
            )
        return result

    def instrument(tool_name: str, action: Callable[..., str]) -> Callable[..., str]:
        def wrapped(**kwargs: object) -> str:
            decision = policy.evaluate(tool_name, kwargs)
            if decision.requires_confirmation and approval_queue is not None:
                request = approval_queue.enqueue(
                    tool_name=tool_name,
                    reason=decision.reason,
                    args=dict(kwargs),
                    source=approval_source,
                    prompt=prompt_provider() if prompt_provider is not None else "",
                    execute=lambda: execute_with_events(tool_name, action, dict(kwargs)),
                )
                if event_sink is not None:
                    event_sink(
                        runtime_event(
                            kind=_steering_event_kind(decision),
                            title=tool_name,
                            detail=decision.reason,
                            data={
                                "tool_name": tool_name,
                                "allowed": decision.allowed,
                                "requires_confirmation": decision.requires_confirmation,
                                "disposition": decision.disposition,
                                "severity": decision.severity,
                                "category": decision.category,
                                "approval_id": request.request_id,
                                **decision.details,
                            },
                        )
                    )
                return (
                    f"Approval required for {tool_name}. "
                    f"Request id: {request.request_id}. Reason: {decision.reason}"
                )

            if event_sink is not None:
                event_sink(
                    runtime_event(
                        kind=_steering_event_kind(decision),
                        title=tool_name,
                        detail=decision.reason,
                        data={
                            "tool_name": tool_name,
                            "allowed": decision.allowed,
                            "requires_confirmation": decision.requires_confirmation,
                            "disposition": decision.disposition,
                            "severity": decision.severity,
                            "category": decision.category,
                            **decision.details,
                        },
                    )
                )
            if not decision.allowed:
                if decision.requires_confirmation:
                    raise PermissionError(f"Confirmation required: {decision.reason}")
                raise PermissionError(decision.reason)
            return execute_with_events(tool_name, action, dict(kwargs))

        return wrapped

    @tool
    def summarize_workspace(relative_path: str = ".", max_files: int = 400) -> str:
        """Summarize workspace shape, key files, and dominant file types before deeper inspection."""
        return instrument("summarize_workspace", workspace.summarize_workspace)(
            relative_path=relative_path,
            max_files=max_files,
        )

    @tool
    def list_files(relative_path: str = ".", recursive: bool = False) -> str:
        """List files and directories inside the active workspace."""
        return instrument("list_files", workspace.list_files)(relative_path=relative_path, recursive=recursive)

    @tool
    def read_file(relative_path: str, start_line: int = 1, max_lines: int = 200) -> str:
        """Read a text file from the active workspace."""
        return instrument("read_file", workspace.read_file)(
            relative_path=relative_path,
            start_line=start_line,
            max_lines=max_lines,
        )

    @tool
    def search_files(
        query: str,
        relative_path: str = ".",
        glob_pattern: str = "*",
        case_sensitive: bool = False,
        max_results: int = 20,
    ) -> str:
        """Search text files in the active workspace for a query string."""
        return instrument("search_files", workspace.search_files)(
            query=query,
            relative_path=relative_path,
            glob_pattern=glob_pattern,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )

    @tool
    def write_file(relative_path: str, content: str, overwrite: bool = False) -> str:
        """Write a text file inside the active workspace, refusing overwrites unless explicitly allowed."""
        return instrument("write_file", workspace.write_file)(
            relative_path=relative_path,
            content=content,
            overwrite=overwrite,
        )

    @tool
    def replace_text(
        relative_path: str,
        old_text: str,
        new_text: str,
        expected_occurrences: int = 1,
    ) -> str:
        """Replace exact text in a workspace file, failing if the match count is not what was expected."""
        return instrument("replace_text", workspace.replace_text)(
            relative_path=relative_path,
            old_text=old_text,
            new_text=new_text,
            expected_occurrences=expected_occurrences,
        )

    return [summarize_workspace, list_files, read_file, search_files, write_file, replace_text]


class StrandsSDKRuntime:
    """Thin adapter around the real Strands Agent SDK using OpenAI.

    Kept intentionally small so the UI can be tested independently.
    """

    provider_name = "strands-openai"

    def __init__(
        self,
        system_prompt: str | None = None,
        openai_model: str = "gpt-4o-mini",
        workspace_root: str | Path = ".",
        allow_overwrite: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.allow_overwrite = allow_overwrite
        self.system_prompt = system_prompt or (
            "You are a concise coding assistant inside a terminal UI prototype. "
            f"You may inspect and conservatively edit the workspace rooted at {self.workspace_root} "
            "using bounded local tools. Prefer summarize_workspace before broad searches when you need repo shape, "
            "and prefer exact-match edits over broad rewrites when possible. "
            "Overwrites are blocked unless the local steering policy explicitly allows them. "
            "If a tool result says approval is required, stop asking that tool to mutate files, explain why approval is needed, "
            "and wait for the TUI to approve or deny the request."
        )
        self.openai_model = openai_model
        self._agent = None
        self._tool_count = 0
        self._event_sink: RuntimeEventSink | None = None
        self._approval_queue = _ApprovalQueue()
        self._active_prompt = ""

    def _build_agent(self, api_key: str, event_sink: RuntimeEventSink | None = None):
        from strands import Agent
        from strands.models.openai import OpenAIModel

        model = OpenAIModel(
            client_args={"api_key": api_key},
            model_id=self.openai_model,
            params={"max_tokens": 300, "temperature": 0.2},
        )
        tools = build_workspace_tools(
            self.workspace_root,
            event_sink=event_sink,
            steering_policy=build_default_policy(allow_overwrite=self.allow_overwrite),
            approval_queue=self._approval_queue,
            approval_source="live_runtime",
            prompt_provider=lambda: self._active_prompt,
        )
        return Agent(model=model, system_prompt=self.system_prompt, tools=tools), len(tools)

    def _ensure_agent(self, api_key: str):
        if self._agent is None:
            self._agent, self._tool_count = self._build_agent(api_key, event_sink=self._emit_event)
        return self._agent, self._tool_count

    def _emit_event(self, event: RuntimeEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def run(self, prompt: str) -> AgentResponse:
        api_key = getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for live runtime mode")

        if self._approval_queue.pending_count() == 0:
            self._approval_queue.reset()

        events = [
            runtime_event(
                kind="prompt_received",
                title="Prompt accepted",
                detail=prompt.strip() or "<empty>",
                data={"prompt_length": len(prompt.strip()), "workspace_root": str(self.workspace_root)},
            )
        ]
        self._event_sink = events.append
        self._active_prompt = prompt
        agent, tool_count = self._ensure_agent(api_key)
        started_at = perf_counter()
        try:
            result = agent(prompt)
        finally:
            self._event_sink = None
        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        pending_approval = self._approval_queue.current()
        text = str(result)
        events.append(
            runtime_event(
                kind="response_completed",
                title="Assistant response ready",
                detail=(
                    f"Provider={self.provider_name}, mode=live, tools={tool_count}, elapsed_ms={elapsed_ms}"
                ),
                data={
                    "provider": self.provider_name,
                    "mode": "live",
                    "model": self.openai_model,
                    "tool_count": tool_count,
                    "elapsed_ms": elapsed_ms,
                    "workspace_root": str(self.workspace_root),
                    "pending_approval": pending_approval is not None,
                    "pending_count": self._approval_queue.pending_count(),
                },
            )
        )
        return AgentResponse(
            text=text,
            provider=self.provider_name,
            mode="live",
            events=events,
            metadata={
                "provider": self.provider_name,
                "mode": "live",
                "model": self.openai_model,
                "tool_count": tool_count,
                "workspace_root": str(self.workspace_root),
                "elapsed_ms": elapsed_ms,
                "pending_approval": pending_approval is not None,
                "pending_count": self._approval_queue.pending_count(),
            },
            pending_approval=pending_approval,
        )

    def resolve_pending_approval(self, approval_id: str, approve: bool) -> AgentResponse:
        api_key = getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for live runtime mode")

        agent, tool_count = self._ensure_agent(api_key)
        pending = self._approval_queue.pop(approval_id)
        events: list[RuntimeEvent] = []
        self._event_sink = events.append
        started_at = perf_counter()

        try:
            if approve:
                events.append(
                    runtime_event(
                        kind="steering_approved",
                        title=pending.request.tool_name,
                        detail="User approved the pending mutation request in the TUI.",
                        data={
                            "tool_name": pending.request.tool_name,
                            "approval_id": pending.request.request_id,
                            **pending.request.args,
                        },
                    )
                )
                tool_result = pending.execute()
                follow_up_prompt = (
                    f"User approved pending tool `{pending.request.tool_name}` in the TUI. "
                    f"The tool executed with args {pending.request.args!r} and returned:\n{tool_result}\n"
                    "Continue the original task from there and summarize the change concisely."
                )
            else:
                events.append(
                    runtime_event(
                        kind="steering_denied",
                        title=pending.request.tool_name,
                        detail="User denied the pending mutation request in the TUI.",
                        data={
                            "tool_name": pending.request.tool_name,
                            "approval_id": pending.request.request_id,
                            **pending.request.args,
                        },
                    )
                )
                follow_up_prompt = (
                    f"User denied pending tool `{pending.request.tool_name}` in the TUI. "
                    "Do not execute that mutation. Continue with the safest useful next step."
                )

            self._active_prompt = follow_up_prompt
            result = agent(follow_up_prompt)
            text = str(result)
        finally:
            self._event_sink = None

        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        next_pending = self._approval_queue.current()
        events.append(
            runtime_event(
                kind="response_completed",
                title="Assistant response ready",
                detail=(
                    f"Provider={self.provider_name}, mode=live, tools={tool_count}, elapsed_ms={elapsed_ms}"
                ),
                data={
                    "provider": self.provider_name,
                    "mode": "live",
                    "model": self.openai_model,
                    "tool_count": tool_count,
                    "elapsed_ms": elapsed_ms,
                    "workspace_root": str(self.workspace_root),
                    "pending_approval": next_pending is not None,
                    "pending_count": self._approval_queue.pending_count(),
                    "approval_action": "approved" if approve else "denied",
                },
            )
        )
        return AgentResponse(
            text=text,
            provider=self.provider_name,
            mode="live",
            events=events,
            metadata={
                "provider": self.provider_name,
                "mode": "live",
                "model": self.openai_model,
                "tool_count": tool_count,
                "workspace_root": str(self.workspace_root),
                "elapsed_ms": elapsed_ms,
                "approval_action": "approved" if approve else "denied",
                "pending_approval": next_pending is not None,
                "pending_count": self._approval_queue.pending_count(),
            },
            pending_approval=next_pending,
        )


def build_runtime(
    mode: str = "fake",
    openai_model: str = "gpt-4o-mini",
    workspace_root: str | Path = ".",
    allow_overwrite: bool = False,
) -> AgentRuntime:
    if mode == "live":
        return StrandsSDKRuntime(
            openai_model=openai_model,
            workspace_root=workspace_root,
            allow_overwrite=allow_overwrite,
        )
    return FakeStrandsRuntime()
