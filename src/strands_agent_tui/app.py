from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Input, Static


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

    #prompt {
        dock: bottom;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="body"):
            yield Static(
                "strands_agent prototype scaffold\n\n"
                "Phase 1 target: prove a basic Strands-backed TUI shell.\n"
                "This is the initial scaffold, not the final runtime.\n\n"
                "Next: wire this input to a Strands runtime wrapper.",
                id="output",
            )
        yield Input(placeholder="Ask the coding agent something...", id="prompt")
        yield Footer()


def main() -> None:
    StrandsAgentApp().run()


if __name__ == "__main__":
    main()
