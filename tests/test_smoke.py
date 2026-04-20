from strands_agent_tui.app import StrandsAgentApp


def test_app_constructs() -> None:
    app = StrandsAgentApp()
    assert app.TITLE == "strands_agent"
