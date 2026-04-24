# strands_agent

Prototype repo for learning the **Strands Agent SDK** deeply by building a simple, interactive **terminal UI coding-agent platform**.

The goal is not to clone Claude Code or Kiro exactly. The goal is to understand the Strands mental model by building a compact platform that feels similar in spirit:
- chat-first,
- tool-using,
- coding-oriented,
- interactive in a terminal,
- incrementally extensible.

This repo should stay focused on one core question:

**What is the smallest useful coding-agent platform we can build using Strands as the primary agent runtime?**

## Product direction

Build a local TUI app that launches a coding agent workspace with:
- a conversation pane,
- tool execution visibility,
- file/workspace awareness,
- session history,
- and guardrails/steering hooks.

The platform should help Steve learn Strands by making the agent loop visible and hackable rather than hidden behind a black box.

## Why this prototype

Strands appears to be a strong fit for this because it gives us:
- a model-driven agent loop,
- tool definitions as normal functions,
- MCP support,
- streaming support,
- steering hooks / middleware,
- multi-agent extensibility later.

That makes it a very good substrate for a coding-agent TUI where the interesting part is not just chat, but:
- how tools are exposed,
- how the loop is observed,
- how tool calls are steered,
- how state/history is managed,
- and how coding workflows feel in practice.

## Initial product shape

The first version should be a Python TUI application that:
- opens in the terminal,
- lets the user type tasks/questions,
- runs a Strands agent behind the scenes,
- shows streaming responses,
- shows tool calls/results as separate UI events,
- can operate against a local workspace,
- and supports a small built-in coding-tool set.

## Architecture sketch

```text
strands_agent/
  README.md
  pyproject.toml
  src/
    strands_agent_tui/
      app.py                 # TUI entrypoint
      ui/                    # panes, widgets, input handling
      runtime/               # strands agent orchestration
      tools/                 # local coding tools
      steering/              # policy and guardrail hooks
      sessions/              # transcript/session persistence
      models/                # provider config and model factory
  tests/
  scripts/
  artifacts/
  reports/daily/
```

## Current status

**Phase 1 is complete, and Phase 2 now has bounded inspect + search + first-write tooling wired into the Strands runtime seam with observable fake events.**

What exists now:
- a runnable Textual TUI scaffold,
- a thin runtime boundary separate from the UI,
- a deterministic **fake Strands runtime** for reliable local verification,
- a live **Strands + OpenAI** runtime path driven by environment variables,
- explicit CLI overrides for runtime, model, and workspace selection,
- status-line rendering plus a dedicated workspace banner in the TUI,
- workspace tools for `list_files`, `read_file`, `search_files`, and a conservative `write_file`,
- live runtime tool registration that binds those tools to the active workspace root,
- a dedicated event timeline pane for runtime milestones, tool activity, and failures,
- deterministic fake-runtime event emission for inspect, search, and write activity so UI behavior is testable without live model calls,
- tests that cover TUI state, config merging, tool safety, runtime selection, search/write behavior, and event rendering,
- a local smoke script for validating the real runtime without committing secrets.

What changed this run:
- added a bounded `search_files` workspace tool with query, path, glob, and result limits,
- added a conservative `write_file` tool that refuses overwrites unless `overwrite=True`,
- registered both tools in the live Strands runtime so the coding-agent seam is broader than read-only inspection,
- taught the fake runtime to emit deterministic search and write events in addition to listing events,
- expanded tests to cover search hits, guarded writes, tool registration, and richer fake runtime event sequences.

Why this matters now:
- It gives the prototype its first real mutation path while staying conservative enough to study safely.
- It makes Strands tool design more tangible, because Steve can now compare inspect, search, and write behaviors through one runtime boundary.
- It moves Phase 2 closer to a useful coding-agent loop without jumping straight to risky shell execution.

How we know the prototype is working right now:
- unit tests verify runtime behavior, config merging, deterministic fake-event emission, and live tool registration,
- tool tests verify bounded reads, bounded search, guarded writes, and workspace confinement,
- app tests verify prompt submission, status rendering, workspace banner rendering, and event timeline updates,
- runtime errors are surfaced visibly in both the transcript and event pane,
- `pytest` currently passes for the expanded Phase 1 plus deeper Phase 2 tool scaffold,
- the CLI help still renders correctly for launch controls.

Current evidence:
- automated tests: `20 passed`
- CLI verification: `strands-agent --help` shows `--runtime`, `--model`, and `--workspace`
- tool verification by test: `search_files` returns bounded matches and `write_file` refuses implicit overwrite
- UI verification by test: fake mode now renders deterministic `list_files`, `search_files`, and `write_file` events

## First five phases

The first five phases should optimize for learning Strands through a runnable vertical slice, not for shipping a giant framework.

### Phase 1, Basic Strands-backed TUI shell

Status: **Complete**

**Objective**
Build a minimal terminal UI that can:
- start,
- render a prompt/input area,
- send a user message to a Strands agent,
- and display the streamed or final assistant response.

**Feature slice**
- basic TUI layout,
- single-session chat loop,
- one configurable model provider,
- simple Strands runtime wrapper,
- local dev quickstart.

**Why this is first**
This proves the base interaction loop and forces us to understand the core Strands API surface before we add coding complexity.

**Success test for Phase 1**
- app launches locally with one command,
- user can enter a prompt,
- the runtime produces a response in the TUI,
- a deterministic fake runtime proves the UI loop without needing live credentials,
- tests validate app startup, runtime invocation boundary, and prompt submission behavior,
- a live OpenAI-backed Strands run succeeds locally.

### Phase 2, Coding tools + workspace awareness

Status: **In progress**

**Objective**
Add a compact local toolbelt so the agent can act like a coding assistant in a workspace.

**Feature slice**
- read file tool,
- write/edit file tool,
- list/search workspace tool,
- shell command tool with conservative limits,
- current working directory / repo context indicator in UI.

**Implemented so far**
- `list_files` tool with optional recursive listing,
- `read_file` tool with bounded excerpts,
- bounded `search_files` tool for repo-wide inspection,
- conservative `write_file` tool that blocks overwrite unless explicitly enabled,
- workspace-root confinement checks,
- workspace root banner in the TUI,
- launch-time workspace override via `--workspace`,
- side-by-side event timeline pane for runtime and tool events,
- deterministic fake-runtime tool events for inspect, search, and write flows.

**Why this matters**
This is the point where the app stops being a generic chat shell and starts becoming a coding-agent platform.

**Success test for Phase 2**
- agent can inspect files and propose/edit code in a test workspace,
- TUI visibly shows tool calls and results,
- integration tests validate tool registration and at least one workspace task end-to-end.

### Phase 3, Agent event timeline + observability

**Objective**
Make the Strands loop legible by exposing intermediate events, tool uses, failures, and timings in the TUI.

**Feature slice**
- event log pane,
- structured rendering for tool call start/end,
- token/latency counters where feasible,
- error surfacing,
- saved run transcript/artifact output.

**Why this matters**
If the goal is to understand Strands deeply, hidden orchestration is the enemy. This phase turns the loop into something inspectable.

**Success test for Phase 3**
- a user can distinguish model output from tool activity,
- failed tools/errors are visible in the UI,
- transcript artifacts are written to disk,
- tests validate event serialization/rendering.

### Phase 4, Steering hooks + safety rails

**Objective**
Use Strands steering/middleware style hooks to constrain or guide risky tool behavior.

**Feature slice**
- pre-tool execution checks,
- allow/deny/confirm behavior for risky actions,
- prompt/tool guidance injection,
- visible “why blocked” explanation in the TUI,
- configurable local safety policy.

**Why this matters**
This is one of the most interesting parts of Strands. A coding agent without steering becomes a demo; a coding agent with steering becomes a platform.

**Success test for Phase 4**
- dangerous commands or writes can be intercepted,
- the TUI shows the intervention reason,
- safe actions still flow normally,
- tests cover steering decisions for allowed, denied, and guided cases.

### Phase 5, Sessions, resumability, and multi-agent-ready seams

**Objective**
Make the app feel like a real agent workstation by adding session persistence and clean seams for later multi-agent or MCP expansion.

**Feature slice**
- session save/load,
- transcript persistence,
- basic workspace profile config,
- model/provider switching,
- architecture seams for MCP tools or sub-agents later.

**Why this matters**
This phase turns a cool demo into a platform Steve can iterate on interactively over time.

**Success test for Phase 5**
- user can reopen a past session,
- transcripts and metadata persist correctly,
- config switching works without breaking the runtime,
- tests cover session serialization and config loading.

## Testing strategy by phase

### Test layers

1. **Unit tests**
   - model/runtime wrappers,
   - tool registration,
   - steering decisions,
   - session serialization.

2. **Integration tests**
   - agent runtime + tool invocation,
   - TUI action flow where practical,
   - transcript/artifact generation.

3. **Manual acceptance checks**
   - launch app,
   - run a coding task,
   - inspect event log,
   - confirm steering behavior,
   - restore a saved session.

### Definition of “phase complete”

A phase is only done when:
- the feature works locally,
- tests exist for the critical path,
- README usage notes are updated,
- and the TUI demonstrates the new capability clearly.

## How to run locally

### Setup

```bash
cd /home/steve/.openclaw/workspace/strands_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

### Launch the TUI

```bash
strands-agent
```

Current default behavior uses the fake runtime, which is intentional for Phase 1 verification.

### Override runtime or model at launch

You can now override config per launch without editing environment defaults:

```bash
strands-agent --runtime fake
strands-agent --runtime live --model gpt-4.1-mini
strands-agent --runtime live --model gpt-4.1-mini --workspace /path/to/repo
```

This matters because it makes runtime experimentation explicit and visible, which is useful for comparing fake vs live Strands behavior during development, and for pointing the coding tools at a specific repo without changing shell state.

### Use live runtime locally

If `OPENAI_API_KEY` is already present in your shell environment, you can switch the app to live mode without storing any secrets in the repo:

```bash
export STRANDS_AGENT_RUNTIME=live
export STRANDS_AGENT_OPENAI_MODEL=gpt-4o-mini
strands-agent
```

The app will then use the Strands SDK with the OpenAI model provider.

### Live smoke check

To verify the live runtime outside the TUI:

```bash
export STRANDS_AGENT_RUNTIME=live
export STRANDS_AGENT_OPENAI_MODEL=gpt-4o-mini
python scripts/live_smoke.py
```

Expected result is a short successful reply plus a provider/mode line.

### Run tests

```bash
pytest
```

### What the current tests prove

- `tests/test_runtime.py`
  - fake runtime returns deterministic output
  - empty prompt handling works
  - runtime builder defaults safely
  - live runtime selection works
  - live runtime fails safely when `OPENAI_API_KEY` is missing
  - config merge logic applies CLI-style overrides safely

- `tests/test_app.py`
  - app renders runtime status
  - app renders the active workspace banner
  - entering text and pressing Enter updates the transcript/history
  - status line reflects turn count, runtime mode, and selected model
  - runtime failures are rendered in the UI instead of crashing silently
  - CLI argument parsing overrides runtime/model/workspace selection correctly

- `tests/test_tools.py`
  - workspace listing returns workspace-relative paths
  - file reads return bounded excerpts with line metadata
  - repo search returns bounded text matches
  - guarded writes create new files but reject implicit overwrite
  - path traversal outside the workspace is rejected
  - live-runtime tool registration returns the expected Strands tool set

This is the current anti-regression contract for Phase 1.

## Suggested near-term technical choices

My current recommendation:
- **Python** for fastest alignment with the Strands Python SDK,
- **Textual** for the TUI,
- **pytest** for tests,
- a thin runtime abstraction around Strands so the UI is not tightly coupled to SDK details.

Why this stack:
- Strands Python looks mature enough for fast iteration,
- Textual is probably the fastest path to a pleasant TUI with panes and event views,
- keeping the runtime wrapper thin should make the learning sharper.

## Next highest-value implementation order

1. enrich the live runtime event model so real Strands tool activity can populate the timeline pane
2. add a tightly scoped edit/replace flow now that conservative file creation exists
3. keep the fake runtime path green while introducing richer Strands tool registration seams
4. grow observability and steering on top of the tested runtime seam
5. persist timeline artifacts so event inspection survives across sessions

1. scaffold Python project + TUI entrypoint
2. add thin Strands runtime wrapper
3. get one prompt/response loop working
4. add coding tools and event timeline
5. add steering hooks before broadening tool power

## What Steve should learn from this repo

By building this in phases, Steve should come away with a practical understanding of:
- how Strands structures an agent loop,
- how tools are exposed and controlled,
- how observability should work for a coding agent,
- how steering hooks can outperform prompt-only guardrails,
- and where Strands is strong or awkward as a foundation for an interactive agent platform.

## Daily prototype run policy

Future daily iterations should:
- continue in this repo rather than creating unrelated prototypes,
- implement one meaningful phase step at a time,
- keep the app runnable,
- keep tests green or clearly document failures,
- and update this README as the architecture and findings evolve.

## Next iteration ideas

- add a tightly scoped edit/replace tool that follows the same conservative posture as `write_file`
- enrich live-mode event capture so real Strands tool calls appear in the timeline, not just fake-mode simulations
- persist timeline artifacts to disk for later replay and debugging
- add higher-signal workspace summaries so the agent can explain repo shape before reaching for shell commands
- keep live runtime support optional so fake-mode regression tests stay fast and deterministic
