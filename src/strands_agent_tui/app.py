from __future__ import annotations

import argparse

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Input, Static

from strands_agent_tui.config import AppConfig, load_config
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

    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        config: AppConfig | None = None,
    ) -> None:
        super().__init__()
        config = config or load_config()
        self.config = config
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
                self.render_status_summary(),
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
            self.query_one("#status", Static).update(self.render_status_summary(response.provider, response.mode))
        except Exception as exc:
            self.history.append((prompt, f"Error: {exc}"))
            self.query_one("#status", Static).update(
                self.render_status_summary(runtime_label="Runtime error")
            )
        self.query_one("#output", Static).update(self.render_history())

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
            f"Model: {self.config.openai_model} | Turns: {len(self.history)}"
        )

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
    args = parser.parse_args()
    return load_config().merge(
        runtime_mode=args.runtime,
        openai_model=args.model,
    )


def main() -> None:
    StrandsAgentApp(config=parse_args()).run()


if __name__ == "__main__":
    main()
