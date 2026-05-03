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
    MAX_RECENT_SESSIONS,
    SessionArtifactStore,
    SessionState,
    SessionSummary,
    count_recent_sessions,
    TurnArtifact,
    latest_session,
    list_recent_sessions,
    pick_session,
    sanitize_session_switcher_filter_mode,
    sanitize_session_switcher_sort_mode,
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
        self.session_switcher_selected_index = 0
        self.session_switcher_filter_mode = "all"
        self.session_switcher_sort_mode = "recent"
        self.session_switcher_page_index = 0
        self.session_switcher_total_matches = 0
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
        prompt = Input(value=self.draft_prompt, placeholder="Ask the coding agent something...", id="prompt")
        prompt.disabled = self.session_switcher_active
        yield prompt
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
            self._close_session_switcher()
            event.stop()
            return

        if key == "n":
            self._start_new_session()
            event.stop()
            return

        if key == "a":
            self._set_session_switcher_filter_mode("all")
            event.stop()
            return

        if key == "p":
            self._toggle_session_switcher_filter_mode("pending")
            event.stop()
            return

        if key == "r":
            self._toggle_session_switcher_filter_mode("restore")
            event.stop()
            return

        if key == "t":
            self._toggle_session_switcher_filter_mode("tool")
            event.stop()
            return

        if key == "s":
            self._cycle_session_switcher_sort_mode()
            event.stop()
            return

        if key in {"pageup", "[", "left_square_bracket"}:
            self._page_session_switcher(-1)
            event.stop()
            return

        if key in {"pagedown", "]", "right_square_bracket"}:
            self._page_session_switcher(1)
            event.stop()
            return

        if key in {"up", "k"}:
            self._move_session_switcher_selection(-1)
            event.stop()
            return

        if key in {"down", "j"}:
            self._move_session_switcher_selection(1)
            event.stop()
            return

        if key == "enter":
            self._select_active_session_switcher_entry()
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
        self.session_switcher_selected_index = 0
        self.session_switcher_filter_mode = "all"
        self.session_switcher_sort_mode = "recent"
        self.session_switcher_page_index = 0
        self.session_switcher_total_matches = 0
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

        if session_state.session_switcher_active:
            self._open_session_switcher(
                selected_session_id=session_state.session_switcher_selected_session_id or None,
                filter_mode=session_state.session_switcher_filter_mode,
                sort_mode=session_state.session_switcher_sort_mode,
                page_index=session_state.session_switcher_page_index,
                restored=True,
                refresh_widgets=False,
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
            (
                "Keys: ↑/↓ or J/K move, PgUp/PgDn or bracket keys page, Enter switch, 1-8 quick switch, "
                "A all, P pending, R restore, T tool, S sort, N new session, Esc/F11 cancel"
            ),
            (
                f"Filter: {self.session_switcher_filter_mode} | Sort: {self.session_switcher_sort_mode} | "
                f"Page: {self.session_switcher_page_label()} | "
                f"Showing: {self.session_switcher_page_window_label()}"
            ),
            "",
        ]

        if not self.session_switcher_summaries:
            if self.session_switcher_filter_mode == "all":
                lines.append("No saved sessions found.")
            else:
                lines.append("No saved sessions match the active switcher filter.")
            return "\n".join(lines)

        for index, summary in enumerate(self.session_switcher_summaries, start=1):
            current_suffix = " (current)" if summary.session_id == self.artifact_store.session_id else ""
            marker = ">" if index - 1 == self.session_switcher_selected_index else " "
            lines.append(f"{marker} {summary.render_line(index)}{current_suffix}")
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
            self._close_session_switcher()
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

        self._open_session_switcher()

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

    def _open_session_switcher(
        self,
        *,
        selected_session_id: str | None = None,
        filter_mode: str | None = None,
        sort_mode: str | None = None,
        page_index: int | None = None,
        restored: bool = False,
        refresh_widgets: bool = True,
    ) -> None:
        self.session_switcher_active = True
        self.session_switcher_filter_mode = sanitize_session_switcher_filter_mode(
            filter_mode or self.session_switcher_filter_mode
        )
        self.session_switcher_sort_mode = sanitize_session_switcher_sort_mode(sort_mode or self.session_switcher_sort_mode)
        if page_index is not None:
            self.session_switcher_page_index = max(page_index, 0)
        self._refresh_session_switcher_summaries(selected_session_id=selected_session_id)
        self._persist_session_view_state()
        if restored:
            selected_summary = self._current_session_switcher_summary()
            self.events.append(
                runtime_event(
                    kind="session_switcher_restored",
                    title="Session switcher restored",
                    detail="Reopened the recent-session chooser with its prior selection preserved where possible.",
                    data={
                        "session_id": self.artifact_store.session_id,
                        "selected_session_id": selected_summary.session_id if selected_summary else None,
                        "selected_index": self.session_switcher_selected_index,
                        "visible_sessions": len(self.session_switcher_summaries),
                        "filter_mode": self.session_switcher_filter_mode,
                        "sort_mode": self.session_switcher_sort_mode,
                        "page_index": self.session_switcher_page_index,
                        "total_matches": self.session_switcher_total_matches,
                    },
                )
            )
        if refresh_widgets:
            self._refresh_widgets()

    def _close_session_switcher(self) -> None:
        self.session_switcher_active = False
        self.session_switcher_summaries = []
        self.session_switcher_selected_index = 0
        self.session_switcher_filter_mode = "all"
        self.session_switcher_sort_mode = "recent"
        self.session_switcher_page_index = 0
        self.session_switcher_total_matches = 0
        self._persist_session_view_state()
        self._refresh_widgets()

    def _default_session_switcher_index(self, selected_session_id: str | None) -> int:
        if not self.session_switcher_summaries:
            return 0
        target_session_id = selected_session_id or self.artifact_store.session_id
        for index, summary in enumerate(self.session_switcher_summaries):
            if summary.session_id == target_session_id:
                return index
        return 0

    def _move_session_switcher_selection(self, delta: int) -> None:
        if not self.session_switcher_summaries:
            return
        last_index = len(self.session_switcher_summaries) - 1
        if delta < 0 and self.session_switcher_selected_index == 0 and self.session_switcher_page_index > 0:
            self.session_switcher_page_index -= 1
            self._refresh_session_switcher_summaries()
            self.session_switcher_selected_index = len(self.session_switcher_summaries) - 1
            self._persist_session_view_state()
            self._refresh_widgets()
            return
        if (
            delta > 0
            and self.session_switcher_selected_index == last_index
            and self._session_switcher_has_next_page()
        ):
            self.session_switcher_page_index += 1
            self._refresh_session_switcher_summaries()
            self.session_switcher_selected_index = 0
            self._persist_session_view_state()
            self._refresh_widgets()
            return
        self.session_switcher_selected_index = max(0, min(self.session_switcher_selected_index + delta, last_index))
        self._persist_session_view_state()
        self._refresh_widgets()

    def _refresh_session_switcher_summaries(self, *, selected_session_id: str | None = None) -> None:
        self.session_switcher_total_matches = count_recent_sessions(
            self.config.artifacts_root,
            filter_mode=self.session_switcher_filter_mode,
            sort_mode=self.session_switcher_sort_mode,
        )
        if self.session_switcher_total_matches == 0:
            self.session_switcher_page_index = 0
            self.session_switcher_summaries = []
            self.session_switcher_selected_index = 0
            return

        max_page_index = (self.session_switcher_total_matches - 1) // MAX_RECENT_SESSIONS
        if selected_session_id:
            all_summaries = list_recent_sessions(
                self.config.artifacts_root,
                limit=self.session_switcher_total_matches,
                filter_mode=self.session_switcher_filter_mode,
                sort_mode=self.session_switcher_sort_mode,
            )
            for index, summary in enumerate(all_summaries):
                if summary.session_id == selected_session_id:
                    self.session_switcher_page_index = index // MAX_RECENT_SESSIONS
                    break
            else:
                self.session_switcher_page_index = min(self.session_switcher_page_index, max_page_index)
        else:
            self.session_switcher_page_index = min(self.session_switcher_page_index, max_page_index)

        self.session_switcher_summaries = list_recent_sessions(
            self.config.artifacts_root,
            filter_mode=self.session_switcher_filter_mode,
            sort_mode=self.session_switcher_sort_mode,
            offset=self.session_switcher_page_index * MAX_RECENT_SESSIONS,
        )
        self.session_switcher_selected_index = self._default_session_switcher_index(selected_session_id)

    def _set_session_switcher_filter_mode(self, filter_mode: str) -> None:
        preferred_session_id = None
        current_summary = self._current_session_switcher_summary()
        if current_summary is not None:
            preferred_session_id = current_summary.session_id
        self.session_switcher_filter_mode = sanitize_session_switcher_filter_mode(filter_mode)
        self._refresh_session_switcher_summaries(selected_session_id=preferred_session_id)
        self._persist_session_view_state()
        self._refresh_widgets()

    def _toggle_session_switcher_filter_mode(self, filter_mode: str) -> None:
        next_mode = "all" if self.session_switcher_filter_mode == filter_mode else filter_mode
        self._set_session_switcher_filter_mode(next_mode)

    def _cycle_session_switcher_sort_mode(self) -> None:
        preferred_session_id = None
        current_summary = self._current_session_switcher_summary()
        if current_summary is not None:
            preferred_session_id = current_summary.session_id
        if self.session_switcher_sort_mode == "recent":
            self.session_switcher_sort_mode = "attention"
        else:
            self.session_switcher_sort_mode = "recent"
        self._refresh_session_switcher_summaries(selected_session_id=preferred_session_id)
        self._persist_session_view_state()
        self._refresh_widgets()

    def _page_session_switcher(self, delta: int) -> None:
        if self.session_switcher_total_matches <= MAX_RECENT_SESSIONS:
            return

        max_page_index = (self.session_switcher_total_matches - 1) // MAX_RECENT_SESSIONS
        next_page_index = max(0, min(self.session_switcher_page_index + delta, max_page_index))
        if next_page_index == self.session_switcher_page_index:
            return

        self.session_switcher_page_index = next_page_index
        self._refresh_session_switcher_summaries()
        if delta > 0:
            self.session_switcher_selected_index = 0
        elif self.session_switcher_summaries:
            self.session_switcher_selected_index = len(self.session_switcher_summaries) - 1
        self._persist_session_view_state()
        self._refresh_widgets()

    def _session_switcher_has_next_page(self) -> bool:
        if self.session_switcher_total_matches <= 0:
            return False
        return (self.session_switcher_page_index + 1) * MAX_RECENT_SESSIONS < self.session_switcher_total_matches

    def session_switcher_page_label(self) -> str:
        if self.session_switcher_total_matches <= 0:
            return "0/0"
        total_pages = ((self.session_switcher_total_matches - 1) // MAX_RECENT_SESSIONS) + 1
        return f"{self.session_switcher_page_index + 1}/{total_pages}"

    def session_switcher_page_window_label(self) -> str:
        if self.session_switcher_total_matches <= 0 or not self.session_switcher_summaries:
            return "0 of 0"
        start = self.session_switcher_page_index * MAX_RECENT_SESSIONS + 1
        end = start + len(self.session_switcher_summaries) - 1
        return f"{start}-{end} of {self.session_switcher_total_matches}"

    def _current_session_switcher_summary(self) -> SessionSummary | None:
        if not self.session_switcher_summaries:
            return None
        if self.session_switcher_selected_index >= len(self.session_switcher_summaries):
            self.session_switcher_selected_index = len(self.session_switcher_summaries) - 1
        return self.session_switcher_summaries[self.session_switcher_selected_index]

    def _select_active_session_switcher_entry(self) -> None:
        summary = self._current_session_switcher_summary()
        if summary is None:
            return
        self._switch_to_session(summary)

    def _sync_session_state(self, *, emit_pending_events: bool) -> None:
        pending_approvals = self.runtime.pending_approvals() if hasattr(self.runtime, "pending_approvals") else []
        selected_summary = self._current_session_switcher_summary() if self.session_switcher_active else None
        state = SessionState(
            pending_approvals=pending_approvals,
            event_filter=self.event_filter,
            history_focus_index=self.history_focus_index,
            draft_prompt=self.draft_prompt,
            session_switcher_active=self.session_switcher_active,
            session_switcher_selected_session_id=selected_summary.session_id if selected_summary else "",
            session_switcher_filter_mode=self.session_switcher_filter_mode,
            session_switcher_sort_mode=self.session_switcher_sort_mode,
            session_switcher_page_index=self.session_switcher_page_index,
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
                        "session_switcher_page_index": self.session_switcher_page_index,
                        "session_switcher_selected_session_id": selected_summary.session_id if selected_summary else None,
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
        "--pick-filter",
        choices=["all", "pending", "restore", "tool"],
        help="Set the initial recent-session picker filter when using --pick-session.",
    )
    parser.add_argument(
        "--pick-sort",
        choices=["recent", "attention"],
        help="Set the initial recent-session picker sort mode when using --pick-session.",
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
    if (args.pick_filter or args.pick_sort) and not args.pick_session:
        parser.error("Use --pick-filter/--pick-sort only with --pick-session.")

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
        summary = pick_session(
            config.artifacts_root,
            filter_mode=args.pick_filter or "all",
            sort_mode=args.pick_sort or "recent",
        )
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
