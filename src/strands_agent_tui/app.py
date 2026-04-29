from __future__ import annotations

import argparse

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from strands_agent_tui.config import AppConfig, load_config
from strands_agent_tui.runtime import AgentRuntime, RuntimeEvent, build_runtime, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact


class StrandsAgentApp(App):
    TITLE = "strands_agent"
    SUB_TITLE = "Strands-powered coding agent TUI prototype"
    BINDINGS = [
        Binding("f1", "set_event_filter('all')", "All events"),
        Binding("f2", "set_event_filter('runtime')", "Runtime events"),
        Binding("f3", "set_event_filter('tool')", "Tool events"),
        Binding("f4", "set_event_filter('failure')", "Failure events"),
        Binding("f5", "set_event_filter('persistence')", "Persistence events"),
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
        )
        self.history: list[tuple[str, str]] = []
        self.events: list[RuntimeEvent] = []
        self.event_filter = "all"
        self.artifact_store = artifact_store or SessionArtifactStore(config.artifacts_root)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            with Horizontal():
                with Vertical(id="main-pane"):
                    yield Static(self.render_history(), id="output")
                with Vertical(id="event-pane"):
                    yield Static(self.render_events(), id="events")
            yield Static(self.render_status_summary(), id="status")
            yield Static(f"Workspace: {self.config.workspace_path}", id="workspace")
        yield Input(placeholder="Ask the coding agent something...", id="prompt")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value
        event.input.value = ""
        try:
            response = self.runtime.run(prompt)
            self.history.append((prompt, response.text))
            self.events.extend(response.events)
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

    def render_status_summary(
        self,
        provider: str | None = None,
        mode: str | None = None,
        runtime_label: str | None = None,
    ) -> str:
        runtime_value = runtime_label or provider or self.runtime.__class__.__name__
        mode_value = mode or self.config.runtime_mode
        return (
            f"Runtime: {runtime_value} | Mode: {mode_value} | "
            f"Model: {self.config.openai_model} | Turns: {len(self.history)} | Events: {len(self.events)}"
        )

    def render_history(self) -> str:
        if not self.history:
            return (
                "Conversation\n\n"
                "Phase 1 proves the basic TUI-to-agent loop.\n"
                "Phase 2 now starts making agent behavior visible.\n"
                "Submit a prompt below to exercise the runtime boundary."
            )

        parts: list[str] = []
        for index, (prompt, response) in enumerate(self.history, start=1):
            parts.append(f"Turn {index}\nUser: {prompt}\nAgent: {response}")
        return "\n\n".join(parts)

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
    args = parser.parse_args()
    return load_config().merge(
        runtime_mode=args.runtime,
        openai_model=args.model,
        workspace_root=args.workspace,
    )


def main() -> None:
    StrandsAgentApp(config=parse_args()).run()


if __name__ == "__main__":
    main()
