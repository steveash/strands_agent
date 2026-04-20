from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AgentResponse:
    text: str
    provider: str
    mode: str


class AgentRuntime(Protocol):
    def run(self, prompt: str) -> AgentResponse:
        ...


class FakeStrandsRuntime:
    """Deterministic runtime for local development and tests.

    This gives Phase 1 a stable way to prove the TUI <-> runtime boundary
    before relying on live model credentials.
    """

    provider_name = "fake-strands"

    def run(self, prompt: str) -> AgentResponse:
        normalized = prompt.strip()
        if not normalized:
            return AgentResponse(
                text="Please enter a prompt.",
                provider=self.provider_name,
                mode="fake",
            )
        return AgentResponse(
            text=f"(fake-strands) Echo: {normalized}",
            provider=self.provider_name,
            mode="fake",
        )


class StrandsSDKRuntime:
    """Thin adapter around the real Strands Agent SDK.

    Kept intentionally small so the UI can be tested independently.
    If the SDK is unavailable or not configured, callers should prefer the
    fake runtime until live setup is ready.
    """

    provider_name = "strands-sdk"

    def __init__(self, system_prompt: str | None = None) -> None:
        self.system_prompt = system_prompt or (
            "You are a concise coding assistant inside a terminal UI prototype."
        )

    def run(self, prompt: str) -> AgentResponse:
        from strands import Agent

        agent = Agent(system_prompt=self.system_prompt)
        result = agent(prompt)
        text = str(result)
        return AgentResponse(text=text, provider=self.provider_name, mode="live")


def build_runtime(mode: str = "fake") -> AgentRuntime:
    if mode == "live":
        return StrandsSDKRuntime()
    return FakeStrandsRuntime()
