from strands_agent_tui.runtime import AgentResponse, FakeStrandsRuntime, build_runtime


def test_fake_runtime_echoes_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("hello world")
    assert isinstance(result, AgentResponse)
    assert result.provider == "fake-strands"
    assert result.mode == "fake"
    assert result.text == "(fake-strands) Echo: hello world"


def test_fake_runtime_handles_empty_prompt() -> None:
    runtime = FakeStrandsRuntime()
    result = runtime.run("   ")
    assert result.text == "Please enter a prompt."


def test_build_runtime_defaults_to_fake() -> None:
    runtime = build_runtime()
    assert isinstance(runtime, FakeStrandsRuntime)
