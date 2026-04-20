from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Input, Static

from strands_agent_tui.config import load_config
from strands_agent_tui.runtime import AgentRuntime, build_runtime


class StrandsAgentApp(App):
    TITLE = "strands_agent"
    SUB_TITLE = "Strands-powered coding agent TUI prototype"

    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #output {
        height: 1fr;
        padding: 1 2;
        border: solid green;
    }

    #status {
        height: auto;
        padding: 0 2;
        color: cyan;
    }

    #prompt {
        dock: bottom;
    }
    """

    def __init__(self, runtime: AgentRuntime | None = None) -> None:
        super().__init__()
        config = load_config()
        self.runtime = runtime or build_runtime(
            mode=config.runtime_mode,
            openai_model=config.openai_model,
        )
        self.history: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="body"):
            yield Static(
                "Welcome to strands_agent.\n\n"
                "Phase 1 proves the basic TUI-to-agent loop.\n"
                "Submit a prompt below to exercise the runtime boundary.",
                id="output",
            )
            yield Static(
                f"Runtime: {self.runtime.__class__.__name__}",
                id="status",
            )
        yield Input(placeholder="Ask the coding agent something...", id="prompt")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value
        event.input.value = ""
        try:
            response = self.runtime.run(prompt)
            self.history.append((prompt, response.text))
            self.query_one("#status", Static).update(
                f"Runtime: {response.provider} | Mode: {response.mode} | Turns: {len(self.history)}"
            )
        except Exception as exc:
            self.history.append((prompt, f"Error: {exc}"))
            self.query_one("#status", Static).update(
                f"Runtime error | Turns: {len(self.history)}"
            )
        self.query_one("#output", Static).update(self.render_history())

    def render_history(self) -> str:
        if not self.history:
            return (
                "Welcome to strands_agent.\n\n"
                "Phase 1 proves the basic TUI-to-agent loop.\n"
                "Submit a prompt below to exercise the runtime boundary."
            )

        parts: list[str] = []
        for index, (prompt, response) in enumerate(self.history, start=1):
            parts.append(f"Turn {index}\nUser: {prompt}\nAgent: {response}")
        return "\n\n".join(parts)


def main() -> None:
    StrandsAgentApp().run()


if __name__ == "__main__":
    main()
