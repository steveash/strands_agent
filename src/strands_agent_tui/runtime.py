from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Protocol

from strands import tool

from strands_agent_tui.tools.workspace import WorkspaceTools


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


def build_workspace_tools(workspace_root: str | Path) -> list[object]:
    workspace = WorkspaceTools(Path(workspace_root))

    @tool
    def list_files(relative_path: str = ".", recursive: bool = False) -> str:
        """List files and directories inside the active workspace."""
        return workspace.list_files(relative_path=relative_path, recursive=recursive)

    @tool
    def read_file(relative_path: str, start_line: int = 1, max_lines: int = 200) -> str:
        """Read a text file from the active workspace."""
        return workspace.read_file(relative_path=relative_path, start_line=start_line, max_lines=max_lines)

    return [list_files, read_file]


class StrandsSDKRuntime:
    """Thin adapter around the real Strands Agent SDK using OpenAI.

    Kept intentionally small so the UI can be tested independently.
    """

    provider_name = "strands-openai"

    def __init__(
        self,
        system_prompt: str | None = None,
        openai_model: str = "gpt-4o-mini",
        workspace_root: str | Path = ".",
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.system_prompt = system_prompt or (
            "You are a concise coding assistant inside a terminal UI prototype. "
            f"You may inspect the workspace rooted at {self.workspace_root} using read-only tools."
        )
        self.openai_model = openai_model

    def run(self, prompt: str) -> AgentResponse:
        api_key = getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for live runtime mode")

        from strands import Agent
        from strands.models.openai import OpenAIModel

        model = OpenAIModel(
            client_args={"api_key": api_key},
            model_id=self.openai_model,
            params={"max_tokens": 300, "temperature": 0.2},
        )
        agent = Agent(
            model=model,
            system_prompt=self.system_prompt,
            tools=build_workspace_tools(self.workspace_root),
        )
        result = agent(prompt)
        text = str(result)
        return AgentResponse(text=text, provider=self.provider_name, mode="live")


def build_runtime(
    mode: str = "fake",
    openai_model: str = "gpt-4o-mini",
    workspace_root: str | Path = ".",
) -> AgentRuntime:
    if mode == "live":
        return StrandsSDKRuntime(openai_model=openai_model, workspace_root=workspace_root)
    return FakeStrandsRuntime()
