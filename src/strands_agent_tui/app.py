from __future__ import annotations

import argparse

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from strands_agent_tui.config import AppConfig, load_config
from strands_agent_tui.runtime import AgentRuntime, RuntimeEvent, build_runtime, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact, latest_session, pick_session


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

    #status, #workspace {
        height: auto;
        padding: 0 2;
    }

    #status {
        color: cyan;
    }

    #workspace {
        color: yellow;
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
        yield Input(placeholder="Ask the coding agent something...", id="prompt")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value
        event.input.value = ""
        try:
            response = self.runtime.run(prompt)
            self.history.append((prompt, response.text))
            self.events.extend(response.events)
            self.history_focus_index = None
            self.artifact_store.append_turn(
                TurnArtifact(
                    prompt=prompt,
                    response=response.text,
                    provider=response.provider,
                    mode=response.mode,
                    events=response.events,
                    response_metadata=response.metadata,
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
                    },
                )
            )
            self.query_one("#status", Static).update(self.render_status_summary(response.provider, response.mode))
        except Exception as exc:
            error_text = f"Error: {exc}"
            error_event = runtime_event(
                kind="runtime_error",
                title="Runtime error",
                detail=str(exc),
                data={"provider": "runtime-error", "mode": self.config.runtime_mode},
            )
            self.history.append((prompt, error_text))
            self.events.append(error_event)
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
            self.query_one("#status", Static).update(
                self.render_status_summary(runtime_label="Runtime error")
            )
        self.query_one("#output", Static).update(self.render_history())
        self.query_one("#events", Static).update(self.render_events())

    def _load_existing_session(self) -> None:
        prior_turns = self.artifact_store.load_turns()
        for turn in prior_turns:
            self.history.append((turn.prompt, turn.response))
            self.events.extend(turn.events)

    def render_context_banner(self) -> str:
        return f"Workspace: {self.config.workspace_path} | Session: {self.artifact_store.session_id}"

    def render_status_summary(
        self,
        provider: str | None = None,
        mode: str | None = None,
        runtime_label: str | None = None,
    ) -> str:
        runtime_value = runtime_label or provider or self.runtime.__class__.__name__
        mode_value = mode or self.config.runtime_mode
        overwrite_policy = "on" if self.config.allow_overwrite else "off"
        return (
            f"Runtime: {runtime_value} | Mode: {mode_value} | "
            f"Model: {self.config.openai_model} | Overwrite: {overwrite_policy} | "
            f"View: {self.history_view_label()} | "
            f"Turns: {len(self.history)} | Events: {len(self.events)}"
        )

    def render_history(self) -> str:
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
        if not self.history:
            return "live"
        if self.history_focus_index is None:
            start_index = max(0, len(self.history) - self.LIVE_HISTORY_WINDOW)
            return f"live latest {start_index + 1}-{len(self.history)}"
        return f"replay {self.history_focus_index + 1}/{len(self.history)}"

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
        self.event_filter = value
        self.query_one("#events", Static).update(self.render_events())

    def action_history_older(self) -> None:
        if not self.history:
            return
        if self.history_focus_index is None:
            self.history_focus_index = max(len(self.history) - 2, 0)
        else:
            self.history_focus_index = max(self.history_focus_index - 1, 0)
        self._refresh_history_widgets()

    def action_history_newer(self) -> None:
        if not self.history or self.history_focus_index is None:
            return
        self.history_focus_index = min(self.history_focus_index + 1, len(self.history) - 1)
        self._refresh_history_widgets()

    def action_history_live(self) -> None:
        if not self.history:
            return
        self.history_focus_index = None
        self._refresh_history_widgets()

    def _refresh_history_widgets(self) -> None:
        self.query_one("#output", Static).update(self.render_history())
        self.query_one("#status", Static).update(self.render_status_summary())


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
