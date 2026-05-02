from __future__ import annotations

import argparse

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from strands_agent_tui.config import AppConfig, load_config
from strands_agent_tui.runtime import AgentRuntime, ApprovalRequest, RuntimeEvent, build_runtime, runtime_event
from strands_agent_tui.sessions import (
    SessionArtifactStore,
    SessionState,
    SessionSummary,
    TurnArtifact,
    latest_session,
    list_recent_sessions,
    pick_session,
)


class StrandsAgentApp(App):
    TITLE = "strands_agent"
    SUB_TITLE = "Strands-powered coding agent TUI prototype"
    LIVE_HISTORY_WINDOW = 3
    BINDINGS = [
        Binding("f1", "set_event_filter('all')", "All events"),
        Binding("f2", "set_event_filter('runtime')", "Runtime events"),
        Binding("f3", "set_event_filter('tool')", "Tool events"),
        Binding("f4", "set_event_filter('failure')", "Failure events"),
        Binding("f5", "set_event_filter('persistence')", "Persistence events"),
        Binding("f6", "history_older", "Older turn"),
        Binding("f7", "history_newer", "Newer turn"),
        Binding("f8", "history_live", "Live view"),
        Binding("f9", "approve_pending", "Approve pending"),
        Binding("f10", "deny_pending", "Deny pending"),
        Binding("f11", "toggle_session_switcher", "Switch session"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #main-pane {
        width: 2fr;
        height: 1fr;
    }

    #event-pane {
        width: 1fr;
        height: 1fr;
    }

    #output, #events {
        height: 1fr;
        padding: 1 2;
        border: solid green;
    }

    #status, #workspace, #approval {
        height: auto;
        padding: 0 2;
    }

    #status {
        color: cyan;
    }

    #workspace {
        color: yellow;
    }

    #approval {
        color: magenta;
    }

    #prompt {
        dock: bottom;
    }
    """

    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        config: AppConfig | None = None,
        artifact_store: SessionArtifactStore | None = None,
    ) -> None:
        super().__init__()
        config = config or load_config()
        self.config = config
        self.runtime = runtime or build_runtime(
            mode=config.runtime_mode,
            openai_model=config.openai_model,
            workspace_root=config.workspace_root,
            allow_overwrite=config.allow_overwrite,
        )
        self.history: list[tuple[str, str]] = []
        self.events: list[RuntimeEvent] = []
        self.event_filter = "all"
        self.history_focus_index: int | None = None
        self.draft_prompt = ""
        self.session_switcher_active = False
        self.session_switcher_summaries: list[SessionSummary] = []
        self.pending_approval: ApprovalRequest | None = None
        self.runtime_status_override: str | None = None
        self.artifact_store = artifact_store or SessionArtifactStore(
            config.artifacts_root,
            session_id=config.session_id,
        )
        self._load_existing_session()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            with Horizontal():
                with Vertical(id="main-pane"):
                    yield Static(self.render_history(), id="output")
                with Vertical(id="event-pane"):
                    yield Static(self.render_events(), id="events")
            yield Static(self.render_status_summary(), id="status")
            yield Static(self.render_context_banner(), id="workspace")
            yield Static(self.render_approval_banner(), id="approval")
        yield Input(value=self.draft_prompt, placeholder="Ask the coding agent something...", id="prompt")
        yield Footer()

    async def on_input_changed(self, event: Input.Changed) -> None:
        self.draft_prompt = event.value
        self._persist_session_view_state()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value

        if self.pending_approval is not None:
            event.input.value = prompt
            self.draft_prompt = prompt
            self.events.append(
                runtime_event(
                    kind="approval_input_blocked",
                    title="Resolve pending approval first",
                    detail="Use F9 to approve or F10 to deny the current mutation request before sending another prompt.",
                    data={
                        "approval_id": self.pending_approval.request_id,
                        "tool_name": self.pending_approval.tool_name,
                    },
                )
            )
            self._refresh_widgets()
            return

        event.input.value = ""
        self.draft_prompt = ""

        try:
            response = self.runtime.run(prompt)
            self._record_response(prompt, response)
        except Exception as exc:
            self._record_runtime_error(prompt, exc)
        self._refresh_widgets()

    async def on_key(self, event: events.Key) -> None:
        if not self.session_switcher_active:
            return

        key = event.key.lower()
        if key == "escape":
            self.session_switcher_active = False
            self.session_switcher_summaries = []
            self._refresh_widgets()
            event.stop()
            return

        if key == "n":
            self._start_new_session()
            event.stop()
            return

        if len(key) == 1 and key.isdigit():
            selected_index = int(key)
            if 1 <= selected_index <= len(self.session_switcher_summaries):
                self._switch_to_session(self.session_switcher_summaries[selected_index - 1])
            else:
                self.events.append(
                    runtime_event(
                        kind="session_switch_invalid",
                        title="Invalid session selection",
                        detail=f"Selection {selected_index} is outside the visible recent-session list.",
                        data={
                            "selected_index": selected_index,
                            "visible_sessions": len(self.session_switcher_summaries),
                            "session_id": self.artifact_store.session_id,
                        },
                    )
                )
                self._refresh_widgets()
            event.stop()

    def _load_existing_session(self) -> None:
        self._load_session(self.artifact_store)

    def _load_session(self, artifact_store: SessionArtifactStore) -> None:
        self.artifact_store = artifact_store
        self.config.session_id = artifact_store.session_id
        self.history = []
        self.events = []
        self.history_focus_index = None
        self.draft_prompt = ""
        self.pending_approval = None
        self.runtime_status_override = None
        self.session_switcher_active = False
        self.session_switcher_summaries = []
        if hasattr(self.runtime, "restore_pending_approvals"):
            self.runtime.restore_pending_approvals([])

        prior_turns = self.artifact_store.load_turns()
        for turn in prior_turns:
            self.history.append((turn.prompt, turn.response))
            self.events.extend(turn.events)

        session_state = self.artifact_store.load_session_state() or SessionState()
        self.event_filter = self._sanitize_event_filter(session_state.event_filter)
        self.history_focus_index = self._normalize_history_focus_index(session_state.history_focus_index)
        self.draft_prompt = session_state.draft_prompt

        pending_approvals = session_state.pending_approvals
        if pending_approvals and hasattr(self.runtime, "restore_pending_approvals"):
            self.runtime.restore_pending_approvals(pending_approvals)
            self.pending_approval = pending_approvals[0]
            self.events.append(
                runtime_event(
                    kind="session_state_restored",
                    title="Pending approvals restored",
                    detail=f"Restored {len(pending_approvals)} pending approval request(s) from session artifacts.",
                    data={
                        "session_id": self.artifact_store.session_id,
                        "pending_count": len(pending_approvals),
                        "approval_id": pending_approvals[0].request_id,
                        "tool_name": pending_approvals[0].tool_name,
                    },
                )
            )
        if (
            session_state.event_filter != "all"
            or session_state.history_focus_index is not None
            or session_state.draft_prompt
        ):
            restored_view = self.history_view_label()
            restored_bits = [
                f"Restored event filter `{self.event_filter}` and view `{restored_view}` from session state."
            ]
            if session_state.draft_prompt:
                restored_bits.append(f"Draft prompt restored ({len(session_state.draft_prompt)} chars).")
            self.events.append(
                runtime_event(
                    kind="session_view_restored",
                    title="Session view restored",
                    detail=" ".join(restored_bits),
                    data={
                        "session_id": self.artifact_store.session_id,
                        "event_filter": self.event_filter,
                        "history_focus_index": self.history_focus_index,
                        "view": restored_view,
                        "draft_prompt_length": len(session_state.draft_prompt),
                    },
                )
            )

    def render_context_banner(self) -> str:
        return f"Workspace: {self.config.workspace_path} | Session: {self.artifact_store.session_id}"

    def render_approval_banner(self) -> str:
        if self.pending_approval is None:
            return "Approval: none pending | F9 approve current request | F10 deny current request"
        args_preview = ", ".join(
            f"{key}={value!r}" for key, value in sorted(self.pending_approval.args.items())
        ) or "no args"
        return (
            f"Approval pending: {self.pending_approval.tool_name} ({self.pending_approval.request_id}) | "
            f"{self.pending_approval.reason} | args: {args_preview} | F9 approve | F10 deny"
        )

    def render_status_summary(
        self,
        provider: str | None = None,
        mode: str | None = None,
        runtime_label: str | None = None,
    ) -> str:
        runtime_value = runtime_label or self.runtime_status_override or provider or self.runtime.__class__.__name__
        mode_value = mode or self.config.runtime_mode
        overwrite_policy = "on" if self.config.allow_overwrite else "off"
        approval_state = f"pending:{self.pending_approval.tool_name}" if self.pending_approval else "none"
        return (
            f"Runtime: {runtime_value} | Mode: {mode_value} | "
            f"Model: {self.config.openai_model} | Overwrite: {overwrite_policy} | "
            f"Approval: {approval_state} | View: {self.history_view_label()} | "
            f"Turns: {len(self.history)} | Events: {len(self.events)}"
        )

    def render_history(self) -> str:
        if self.session_switcher_active:
            return self.render_session_switcher()

        if not self.history:
            return (
                "Conversation\n\n"
                "Phase 1 proves the basic TUI-to-agent loop.\n"
                "Phase 2 now starts making agent behavior visible.\n"
                "Submit a prompt below to exercise the runtime boundary."
            )

        total_turns = len(self.history)
        lines = [
            "Conversation",
            self.history_view_label(),
            "Keys: F6 older turn, F7 newer turn, F8 live/latest",
            "",
        ]

        if self.history_focus_index is None:
            start_index = max(0, total_turns - self.LIVE_HISTORY_WINDOW)
            lines.append(f"Showing turns {start_index + 1}-{total_turns} of {total_turns}")
            lines.append("")
            visible_turns = self.history[start_index:]
            lines.extend(
                self._render_turn(index, prompt, response)
                for index, (prompt, response) in enumerate(visible_turns, start=start_index + 1)
            )
            return "\n\n".join(lines)

        focus = self.history_focus_index
        prompt, response = self.history[focus]
        lines.append(f"Viewing turn {focus + 1} of {total_turns}")
        if focus > 0:
            lines.append(f"Older turns available: 1-{focus}")
        if focus < total_turns - 1:
            lines.append(f"Newer turns available: {focus + 2}-{total_turns}")
        lines.append("")
        lines.append(self._render_turn(focus + 1, prompt, response))
        return "\n\n".join(lines)

    def _render_turn(self, index: int, prompt: str, response: str) -> str:
        return f"Turn {index}\nUser: {prompt}\nAgent: {response}"

    def history_view_label(self) -> str:
        if self.session_switcher_active:
            return "session switcher"
        if not self.history:
            return "live"
        if self.history_focus_index is None:
            start_index = max(0, len(self.history) - self.LIVE_HISTORY_WINDOW)
            return f"live latest {start_index + 1}-{len(self.history)}"
        return f"replay {self.history_focus_index + 1}/{len(self.history)}"

    def render_session_switcher(self) -> str:
        lines = [
            "Session Switcher",
            f"Current session: {self.artifact_store.session_id}",
            f"Artifacts root: {self.artifact_store.root}",
            "Keys: 1-8 switch session, N new session, Esc/F11 cancel",
            "",
        ]

        if not self.session_switcher_summaries:
            lines.append("No saved sessions found.")
            return "\n".join(lines)

        for index, summary in enumerate(self.session_switcher_summaries, start=1):
            current_suffix = " (current)" if summary.session_id == self.artifact_store.session_id else ""
            lines.append(summary.render_line(index) + current_suffix)
        return "\n".join(lines)

    def render_events(self) -> str:
        filtered_events = self.filtered_events()
        if not self.events:
            return (
                "Event Timeline\n\n"
                "No events yet.\n"
                "Tool calls, runtime milestones, and failures will appear here."
            )

        lines = [
            "Event Timeline",
            f"Filter: {self.event_filter} ({len(filtered_events)}/{len(self.events)} events)",
            "Keys: F1 all, F2 runtime, F3 tool, F4 failure, F5 persistence",
            "",
        ]
        for index, item in enumerate(filtered_events[-12:], start=max(len(filtered_events) - 11, 1)):
            timestamp = item.timestamp[11:19] if item.timestamp else "--:--:--"
            lines.append(f"{index}. [{timestamp}] ({item.category}) kind={item.kind} | {item.title}")
            if item.data:
                compact_data = ", ".join(f"{key}={value!r}" for key, value in sorted(item.data.items()))
                lines.append(f"   {item.detail}")
                lines.append(f"   data: {compact_data}")
            else:
                lines.append(f"   {item.detail}")
        return "\n".join(lines)

    def filtered_events(self) -> list[RuntimeEvent]:
        if self.event_filter == "all":
            return self.events
        return [event for event in self.events if event.category == self.event_filter]

    def action_set_event_filter(self, value: str) -> None:
        self.event_filter = self._sanitize_event_filter(value)
        self._persist_session_view_state()
        self.query_one("#events", Static).update(self.render_events())

    def action_history_older(self) -> None:
        if not self.history:
            return
        if self.history_focus_index is None:
            self.history_focus_index = max(len(self.history) - 2, 0)
        else:
            self.history_focus_index = max(self.history_focus_index - 1, 0)
        self._persist_session_view_state()
        self._refresh_history_widgets()

    def action_history_newer(self) -> None:
        if not self.history or self.history_focus_index is None:
            return
        self.history_focus_index = min(self.history_focus_index + 1, len(self.history) - 1)
        self._persist_session_view_state()
        self._refresh_history_widgets()

    def action_history_live(self) -> None:
        if not self.history:
            return
        self.history_focus_index = None
        self._persist_session_view_state()
        self._refresh_history_widgets()

    def action_approve_pending(self) -> None:
        self._resolve_pending_approval(approve=True)

    def action_deny_pending(self) -> None:
        self._resolve_pending_approval(approve=False)

    def action_toggle_session_switcher(self) -> None:
        if self.session_switcher_active:
            self.session_switcher_active = False
            self.session_switcher_summaries = []
            self._refresh_widgets()
            return

        if self.pending_approval is not None:
            self.events.append(
                runtime_event(
                    kind="session_switch_blocked",
                    title="Session switch blocked",
                    detail="Resolve or deny the pending approval before switching sessions.",
                    data={
                        "session_id": self.artifact_store.session_id,
                        "approval_id": self.pending_approval.request_id,
                        "tool_name": self.pending_approval.tool_name,
                    },
                )
            )
            self._refresh_widgets()
            return

        self.session_switcher_summaries = list_recent_sessions(self.config.artifacts_root)
        self.session_switcher_active = True
        self._refresh_widgets()

    def _resolve_pending_approval(self, approve: bool) -> None:
        if self.pending_approval is None:
            return
        request = self.pending_approval
        prompt = (
            f"Approve pending {request.tool_name} ({request.request_id})"
            if approve
            else f"Deny pending {request.tool_name} ({request.request_id})"
        )
        try:
            response = self.runtime.resolve_pending_approval(request.request_id, approve=approve)
            self._record_response(prompt, response)
        except Exception as exc:
            self._record_runtime_error(prompt, exc)
        self._refresh_widgets()

    def _record_response(self, prompt: str, response) -> None:
        response_metadata = dict(response.metadata)
        if response.pending_approval is not None:
            response_metadata["pending_approval_id"] = response.pending_approval.request_id
            response_metadata["pending_approval_tool"] = response.pending_approval.tool_name
        self.history.append((prompt, response.text))
        self.events.extend(response.events)
        self.pending_approval = response.pending_approval
        self.runtime_status_override = None
        self.history_focus_index = None
        self.artifact_store.append_turn(
            TurnArtifact(
                prompt=prompt,
                response=response.text,
                provider=response.provider,
                mode=response.mode,
                events=response.events,
                response_metadata=response_metadata,
            )
        )
        self.events.append(
            runtime_event(
                kind="artifact_saved",
                title="Session artifact saved",
                detail=f"Saved turn to {self.artifact_store.session_dir}",
                data={
                    "session_id": self.artifact_store.session_id,
                    "session_dir": str(self.artifact_store.session_dir),
                    "pending_approval": self.pending_approval is not None,
                },
            )
        )
        self._sync_session_state(emit_pending_events=True)

    def _record_runtime_error(self, prompt: str, exc: Exception) -> None:
        error_text = f"Error: {exc}"
        error_event = runtime_event(
            kind="runtime_error",
            title="Runtime error",
            detail=str(exc),
            data={"provider": "runtime-error", "mode": self.config.runtime_mode},
        )
        self.history.append((prompt, error_text))
        self.events.append(error_event)
        self.pending_approval = None
        self.runtime_status_override = "Runtime error"
        self.history_focus_index = None
        self.artifact_store.append_turn(
            TurnArtifact(
                prompt=prompt,
                response=error_text,
                provider="runtime-error",
                mode=self.config.runtime_mode,
                events=[error_event],
                response_metadata={"provider": "runtime-error", "mode": self.config.runtime_mode},
                error=True,
            )
        )
        self.events.append(
            runtime_event(
                kind="artifact_saved",
                title="Session artifact saved",
                detail=f"Saved error turn to {self.artifact_store.session_dir}",
                data={
                    "session_id": self.artifact_store.session_id,
                    "session_dir": str(self.artifact_store.session_dir),
                    "error": True,
                },
            )
        )
        self._sync_session_state(emit_pending_events=True)

    def _switch_to_session(self, summary: SessionSummary) -> None:
        previous_session_id = self.artifact_store.session_id
        self._load_session(SessionArtifactStore.from_session_dir(summary.session_dir))
        self.events.append(
            runtime_event(
                kind="session_switched",
                title="Session switched",
                detail=f"Switched from {previous_session_id} to {summary.session_id}.",
                data={
                    "previous_session_id": previous_session_id,
                    "session_id": summary.session_id,
                    "turn_count": summary.turn_count,
                },
            )
        )
        self._refresh_widgets()

    def _start_new_session(self) -> None:
        previous_session_id = self.artifact_store.session_id
        new_store = SessionArtifactStore(self.config.artifacts_root)
        self._load_session(new_store)
        self.events.append(
            runtime_event(
                kind="session_started",
                title="New session started",
                detail=f"Started a fresh session after leaving {previous_session_id}.",
                data={
                    "previous_session_id": previous_session_id,
                    "session_id": new_store.session_id,
                },
            )
        )
        self._refresh_widgets()

    def _sync_session_state(self, *, emit_pending_events: bool) -> None:
        if not hasattr(self.runtime, "pending_approvals"):
            return
        pending_approvals = self.runtime.pending_approvals()
        state = SessionState(
            pending_approvals=pending_approvals,
            event_filter=self.event_filter,
            history_focus_index=self.history_focus_index,
            draft_prompt=self.draft_prompt,
        )

        previous_state = self.artifact_store.load_session_state() if emit_pending_events else None
        if state.is_default():
            cleared = self.artifact_store.clear_session_state()
            if emit_pending_events and cleared and previous_state and previous_state.pending_approvals:
                self.events.append(
                    runtime_event(
                        kind="session_state_cleared",
                        title="Pending approvals cleared",
                        detail="Removed persisted pending approval state because no confirmation requests remain.",
                        data={"session_id": self.artifact_store.session_id},
                    )
                )
            return

        self.artifact_store.save_session_state(state)
        if emit_pending_events and pending_approvals:
            self.events.append(
                runtime_event(
                    kind="session_state_saved",
                    title="Pending approvals saved",
                    detail=(
                        f"Persisted {len(pending_approvals)} pending approval request(s) plus restart-safe view state."
                    ),
                    data={
                        "session_id": self.artifact_store.session_id,
                        "pending_count": len(pending_approvals),
                        "approval_id": pending_approvals[0].request_id,
                        "tool_name": pending_approvals[0].tool_name,
                        "event_filter": self.event_filter,
                        "history_focus_index": self.history_focus_index,
                        "draft_prompt_length": len(self.draft_prompt),
                    },
                )
            )

    def _persist_session_view_state(self) -> None:
        self._sync_session_state(emit_pending_events=False)

    def _sanitize_event_filter(self, value: str) -> str:
        return value if value in {"all", "runtime", "tool", "failure", "persistence"} else "all"

    def _normalize_history_focus_index(self, value: int | None) -> int | None:
        if value is None or not self.history:
            return None if value is None else None
        if 0 <= value < len(self.history):
            return value
        return None

    def _refresh_history_widgets(self) -> None:
        self.query_one("#output", Static).update(self.render_history())
        self.query_one("#status", Static).update(self.render_status_summary())

    def _refresh_widgets(self) -> None:
        self.query_one("#output", Static).update(self.render_history())
        self.query_one("#events", Static).update(self.render_events())
        self.query_one("#status", Static).update(self.render_status_summary())
        self.query_one("#workspace", Static).update(self.render_context_banner())
        self.query_one("#approval", Static).update(self.render_approval_banner())
        prompt = self.query_one("#prompt", Input)
        if prompt.value != self.draft_prompt:
            prompt.value = self.draft_prompt
        prompt.disabled = self.session_switcher_active


def parse_args() -> AppConfig:
    parser = argparse.ArgumentParser(
        prog="strands-agent",
        description="Launch the Strands coding-agent TUI prototype.",
    )
    parser.add_argument(
        "--runtime",
        choices=["fake", "live"],
        help="Override the runtime mode for this launch.",
    )
    parser.add_argument(
        "--model",
        help="Override the OpenAI model id used by the live runtime.",
    )
    parser.add_argument(
        "--workspace",
        help="Override the workspace root used by coding tools.",
    )
    parser.add_argument(
        "--session-dir",
        help="Load and continue an existing session artifact directory.",
    )
    parser.add_argument(
        "--pick-session",
        action="store_true",
        help="Interactively choose a recent saved session from the configured artifacts root.",
    )
    parser.add_argument(
        "--resume-last",
        action="store_true",
        help="Resume the most recent saved session from the configured artifacts root.",
    )
    args = parser.parse_args()

    session_flags = [bool(args.session_dir), bool(args.pick_session), bool(args.resume_last)]
    if sum(session_flags) > 1:
        parser.error("Choose only one of --session-dir, --pick-session, or --resume-last.")

    config = load_config().merge(
        runtime_mode=args.runtime,
        openai_model=args.model,
        workspace_root=args.workspace,
    )

    selected_session_dir = None
    if args.session_dir:
        selected_session_dir = args.session_dir
    elif args.resume_last:
        summary = latest_session(config.artifacts_root)
        if summary is None:
            parser.error(f"No saved sessions found under {config.artifacts_root}")
        selected_session_dir = summary.session_dir
    elif args.pick_session:
        summary = pick_session(config.artifacts_root)
        if summary is not None:
            selected_session_dir = summary.session_dir

    if selected_session_dir:
        artifact_store = SessionArtifactStore.from_session_dir(selected_session_dir)
        config = config.merge(artifacts_root=str(artifact_store.root))
        config.session_id = artifact_store.session_id
    return config


def main() -> None:
    StrandsAgentApp(config=parse_args()).run()


if __name__ == "__main__":
    main()
