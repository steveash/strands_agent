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

**Phase 1 is complete, Phase 2 now splits the shell-command seam into direct read-only inspection plus approval-gated test execution alongside higher-signal workspace summary and conservative edit/mutation seams, Phase 3 includes resumable session-artifact replay plus both launch-time and in-app recent-session reopen flows, Phase 4 now persists restart-safe session state beyond approvals so confirm-needed mutations, replay/filter context, partially typed follow-up prompts, and the in-app session-switcher chooser state can survive a TUI restart, and Phase 5 now adds compact restore-state badges to recent-session triage alongside keyboard-driven session switching.**

What exists now:
- a runnable Textual TUI scaffold,
- a thin runtime boundary separate from the UI,
- a deterministic **fake Strands runtime** for reliable local verification,
- a live **Strands + OpenAI** runtime path driven by environment variables,
- explicit CLI overrides for runtime, model, workspace, and saved-session selection,
- status-line rendering plus a dedicated workspace/session banner in the TUI,
- workspace tools for `summarize_workspace`, `list_files`, `read_file`, `search_files`, a conservative `write_file`, and an exact-match `replace_text`,
- a narrowly scoped `run_shell_command` tool for `pwd`, `ls`, read-only `git status`/`git diff`, and `pytest`/`python -m pytest`, where read-only inspection commands run directly but test commands still require explicit approval,
- live runtime tool registration that binds those tools to the active workspace root,
- runtime-side instrumentation that records real `tool_started`, `tool_finished`, and `tool_failed` events when live Strands tools execute,
- a first-pass steering policy seam that evaluates workspace tool calls before execution and emits explicit `steering_decision`, `steering_confirmation_required`, or `steering_blocked` events,
- default conservative steering that requires confirmation for overwrite requests and multi-occurrence edits unless explicitly enabled, and still protects sensitive file patterns like `.env*`, `*.pem`, and `*.key`,
- a lightweight approval queue plus `F9` approve / `F10` deny controls so confirm-needed mutation requests can resume from inside the TUI instead of stopping at an event-only warning,
- persisted `session_state.json` plus legacy-compatible `pending_approvals.json` so queued confirmations, lightweight TUI view state, and partially typed prompt drafts can be restored after restart instead of disappearing with process memory,
- approval-aware fake runtime flows that can demonstrate multiple queued approvals in sequence without needing live credentials,
- live-runtime tool wiring that can queue confirm-needed mutations, wait for explicit approval, execute the approved tool, and then continue the Strands conversation with a follow-up prompt,
- a dedicated event timeline pane for runtime milestones, tool activity, failures, and compact structured event data,
- keyboard-driven event filtering in the timeline pane for all/runtime/tool/failure/persistence views,
- per-session artifact persistence under `artifacts/sessions/<session-id>/` with both `turns.jsonl` and `transcript.md`,
- structured event payloads with timestamps and metadata for both fake and live runtime paths,
- explicit `artifact_saved` persistence events emitted by the app after each turn is written,
- response metadata capture for provider, mode, model, workspace root, tool count, and elapsed time where available,
- deterministic fake-runtime event emission for inspect, search, write, and edit activity, including confirm-needed mutation prompts, so UI behavior is testable without live model calls,
- compact replay navigation for resumed sessions so the conversation pane can browse older turns without dumping the full backlog into the live transcript view,
- restart-safe restoration of event-filter, replay-focus, and draft-prompt state so reopening a session can preserve the user's inspection context as well as pending approvals,
- a compact recent-session picker plus a `--resume-last` shortcut so reopen flow is no longer gated on manually passing `--session-dir`,
- an in-app `F11` session switcher that reuses the same recent-session summaries after startup, can jump into another saved session without restarting the TUI, and can start a fresh session inline,
- keyboard-driven session-switcher navigation with ↑/↓ (or J/K), Enter-to-switch, and a highlighted selection row rather than number-only switching,
- restart-safe session-switcher restoration so reopening a session can bring back the chooser with the prior target selection preserved where possible,
- richer recent-session summaries in both the CLI picker and in-app switcher, including pending-approval markers, compact restore-state badges, and last-event previews before selection,
- deterministic recent-session ordering that now prefers the newest artifact turn timestamp instead of relying only on filesystem mtime ties,
- tests that cover TUI state, config merging, tool safety, runtime selection, session selection, live-tool event capture, event rendering, and artifact persistence,
- a local smoke script for validating the real runtime without committing secrets.

What changed this run:
- split shell-command steering into distinct policy levels so read-only inspection commands are allowed immediately while `pytest`/`python -m pytest` still queue explicit approval,
- added shared shell-command classification so steering can reject unsupported commands earlier and tag shell events with compact `inspect` vs `test` policy metadata,
- refreshed fake-runtime coverage plus `scripts/shell_tool_smoke.py` so the direct-inspection path and approval-gated test path are both runnable without launching the full TUI.

Why this matters now:
- It removes unnecessary approval friction from safe repo-inspection commands like `pwd` and `git status` while keeping mutation-adjacent test execution visibly gated.
- It makes shell steering behavior more legible in the event timeline because inspection vs test intent is now explicit instead of hidden behind one blanket approval rule.
- It tightens the shell seam into something closer to a real coding-agent workstation without broadening the command allowlist.

How we know the prototype is working right now:
- unit tests verify runtime behavior, config merging, deterministic fake-event emission, approval queue behavior, live tool registration, live tool-event capture, structured event payloads, and default artifact-root derivation,
- tool tests verify bounded reads, bounded search, guarded writes, exact-match replacement rules, workspace confinement, and event-sink instrumentation,
- app tests verify prompt submission, status rendering, workspace banner rendering, approval banner rendering, event timeline updates, approval blocking/approval resume behavior, restart-safe draft-prompt recovery, restore-state badges in the session switcher, restart-safe session-switcher recovery, and on-disk artifact persistence for both success and failure cases,
- runtime errors are surfaced visibly in both the transcript and event pane, and are also written to session artifacts with structured metadata,
- `pytest` currently passes for the expanded Phase 2/3/4 seam, including recent-session selection, in-app session switching, in-app approval flows, restart-safe approval recovery, restart-safe view-state recovery, restart-safe draft recovery, and the shell-command seam,
- the CLI help still renders correctly for launch controls.

Current evidence:
- automated tests: `76 passed`
- runnable shell-policy verification: `.venv/bin/python scripts/shell_tool_smoke.py` prints direct `pwd` and `git status --short` results with `Policy level: inspect`, then queues `run_shell_command` approval for `pytest -q`,
- runnable approval-restart verification: `.venv/bin/python scripts/approval_restart_smoke.py` still saves a queued approval snapshot, restores it into a fresh runtime, approves it, and leaves the next queued approval persisted,
- runnable session-switch verification: `.venv/bin/python scripts/session_switcher_smoke.py` still reports `switcher_default_selection_is_current= True`, `switcher_has_pending_marker= True`, `switcher_has_restore_badges= True`, `switcher_restored= True`, `restored_selection_is_newer= True`, then switches from `session-older` to `session-newer` and prints `latest_event= session_switched`,
- CLI verification: `strands-agent --help` still shows `--runtime`, `--model`, `--workspace`, `--session-dir`, `--pick-session`, and `--resume-last`,
- recent-session verification by test: recent session summaries still surface pending approvals, restore-state badges, and last-event previews while `latest_session(...)` still returns the newest artifact turn even when filesystem mtimes tie,
- live runtime verification by test: a stubbed live Strands runtime still records real `read_file` tool activity plus structured metadata in the returned event timeline,
- artifact verification by test: persisted `turns.jsonl` entries still include schema version, timestamped events, and response metadata,
- UI verification by test: fake mode still renders pending approval state in both status and approval banners, blocks new prompts until the approval is resolved, surfaces restore-state badges in the session switcher, and persists the approval resolution turn to session artifacts,
- steering verification by test: default policy now auto-allows read-only shell inspection, still requires confirmation for shell test runs plus overwrite and multi-occurrence edit requests, rejects unsupported shell commands earlier, opt-in overwrite mode still emits an allow-with-notice steering event, and protected-file mutations remain denied.

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
- `summarize_workspace` tool for a bounded repo-shape briefing before deeper inspection,
- `list_files` tool with optional recursive listing,
- `read_file` tool with bounded excerpts,
- bounded `search_files` tool for repo-wide inspection,
- approval-gated `run_shell_command` for a small `pwd`/`ls`/`git status`/`git diff`/`pytest` seam,
- conservative `write_file` tool that blocks overwrite unless explicitly enabled,
- conservative `replace_text` tool that requires an exact expected match count,
- workspace-root confinement checks,
- workspace root banner in the TUI,
- launch-time workspace override via `--workspace`,
- side-by-side event timeline pane for runtime and tool events,
- deterministic fake-runtime tool events for inspect, search, write, and edit flows,
- live-runtime tool instrumentation that emits actual tool lifecycle events with args, elapsed time, and failures,
- stable event categories plus filter shortcuts so the timeline can isolate runtime, tool, failure, or persistence activity,
- a first-pass steering seam for pre-tool allow/deny decisions on risky file mutations.

**Why this matters**
This is the point where the app stops being a generic chat shell and starts becoming a coding-agent platform.

**Success test for Phase 2**
- agent can inspect files and propose/edit code in a test workspace,
- TUI visibly shows tool calls and results,
- integration tests validate tool registration and at least one workspace task end-to-end.

### Phase 3, Agent event timeline + observability

Status: **Started**

**Objective**
Make the Strands loop legible by exposing intermediate events, tool uses, failures, and timings in the TUI.

**Feature slice**
- event log pane,
- structured rendering for tool call start/end,
- token/latency counters where feasible,
- error surfacing,
- saved run transcript/artifact output.

**Implemented so far**
- session-scoped `turns.jsonl` artifact output for structured replay/debugging,
- session-scoped `transcript.md` output for quick human inspection,
- artifact capture for both successful turns and runtime failures,
- default artifact-root derivation under the active workspace,
- persisted event payloads that now include timestamps, structured metadata, and real live-tool lifecycle entries when the Strands runtime uses workspace tools,
- response metadata capture so replay artifacts retain model/runtime context without scraping prose,
- event-pane filtering and explicit persistence events so replay/debugging concepts are also visible in the live TUI,
- steering decision events in the same timeline so policy behavior is inspectable without reading code.

**Why this matters**
If the goal is to understand Strands deeply, hidden orchestration is the enemy. This phase turns the loop into something inspectable.

**Success test for Phase 3**
- a user can distinguish model output from tool activity,
- failed tools/errors are visible in the UI,
- transcript artifacts are written to disk,
- tests validate event serialization/rendering.

### Phase 4, Steering hooks + safety rails

Status: **In progress**

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

**Implemented so far**
- default allow / deny / confirm-needed steering decisions for workspace mutations,
- protected-path blocking for `.env*`, `*.pem`, and `*.key`,
- visible steering decision events in the timeline pane,
- in-app `F9` approve / `F10` deny controls for confirm-needed requests,
- approval-aware fake runtime and live runtime seams that can continue after explicit operator approval.

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

If you want to explicitly allow overwriting existing files for an experiment, opt in locally:

```bash
export STRANDS_AGENT_ALLOW_OVERWRITE=true
```

The TUI status line will show `Overwrite: on` so the posture is visible while you test.

### Live smoke check

To verify the live runtime outside the TUI:

```bash
export STRANDS_AGENT_RUNTIME=live
export STRANDS_AGENT_OPENAI_MODEL=gpt-4o-mini
python scripts/live_smoke.py
```

Expected result is a short successful reply plus a provider/mode line.

### Replay smoke check

To verify the compact live-view + replay-navigation rendering without launching the full TUI:

```bash
.venv/bin/python scripts/replay_smoke.py
```

Expected result includes both a `live latest 2-4` view and a `replay 3/4` view for the same saved session fixture.

### Run tests

```bash
. .venv/bin/activate
pytest
```

### Current coding-tool seam

The prototype currently exposes these bounded workspace tools through the runtime:

- `summarize_workspace`
- `list_files`
- `read_file`
- `search_files`
- `run_shell_command`
- `write_file`
- `replace_text`

`replace_text` is intentionally strict: it only succeeds when the old text appears exactly the expected number of times, which makes it a good fit for studying safer agent-driven edits.

`run_shell_command` is intentionally narrow: it supports only `pwd`, `ls`, read-only `git status`/`git diff`, and `pytest`/`python -m pytest`. The steering layer now auto-allows the read-only inspection subset while still requiring explicit approval before test commands execute.

### Session artifacts

Each app session now writes artifacts under the active workspace by default:

```text
artifacts/sessions/session-YYYYMMDDTHHMMSSZ/
  turns.jsonl
  transcript.md
```

You can override the root with:

```bash
export STRANDS_AGENT_ARTIFACTS_ROOT=/path/to/artifacts
```

You can resume a saved session directly:

```bash
strands-agent --session-dir artifacts/sessions/session-YYYYMMDDTHHMMSSZ
```

Or use the new recent-session shortcuts so you do not need to type a full artifact path:

```bash
strands-agent --pick-session
strands-agent --resume-last
```

Those flows reload the saved prompt/response history plus timeline events from `turns.jsonl`, then continue appending new turns into the selected session directory.

Partially typed prompt text is also persisted in `session_state.json`, so a restart or session reload can reopen with the draft still in the input instead of discarding it.

After startup, `F11` opens the same recent-session summaries inside the TUI so you can switch to another saved session or start a fresh one without restarting. Use ↑/↓ (or `J`/`K`) to move the highlighted row, `Enter` to switch to the highlighted session, number keys for quick direct selection, and `N` for a fresh session. If the target session has persisted approvals, they are restored automatically; if the current session still has an unresolved approval, switching is blocked until you approve or deny it.

If you restart while the switcher is open, the app now restores that chooser mode and preserves the previously highlighted target session where possible, so you can keep triaging recent work instead of manually reopening the same picker state.

When a resumed session has multiple turns, the conversation pane stays in a compact live view showing only the latest 3 turns. Use `F6` for older turns, `F7` for newer turns, and `F8` to jump back to the live/latest view.

### Event timeline filters

Inside the TUI, use these shortcuts to focus the event pane:

- `F1` all events
- `F2` runtime events
- `F3` tool events
- `F4` failure events
- `F5` persistence events

This is intentionally simple, but it already makes it much easier to inspect Strands loop behavior without losing the complete turn transcript.

### Approval UX

When a mutation needs explicit approval, the app now keeps the request live inside the TUI instead of leaving it as a passive event:

- the approval banner shows the pending tool, approval id, reason, and key args
- `F9` approves the current request
- `F10` denies the current request
- while approval is pending, new prompt submission is blocked so the session state stays legible

For a deterministic walkthrough without launching the full TUI:

```bash
.venv/bin/python scripts/approval_smoke.py
```

Expected result shows an initial queued `write_file` approval, an approve/resume step, then a follow-on `replace_text` approval that can be denied.

### Current steering policy seam

The runtime now evaluates risky mutation tools before execution:

- `write_file(overwrite=True)` is blocked by default unless `STRANDS_AGENT_ALLOW_OVERWRITE=true`
- writes or edits targeting `.env*`, `*.pem`, or `*.key` are denied by policy
- read-only shell inspection commands like `pwd`, `ls`, `git status`, and `git diff --stat` are allowed directly within the narrow allowlist
- shell test commands like `pytest -q` and `python -m pytest -q` still require confirmation before execution
- multi-occurrence `replace_text` calls require confirmation before execution, so risky broad edits are visible before they run

When confirmation is required, the runtime now exposes a resumable approval request to the TUI. In fake mode that request is deterministic and queueable for testing; in live mode it gives the agent a visible pause point before the approved tool is executed and the conversation continues.

This is still deliberately narrow, but it now creates the exact seam we will need for richer Strands guardrails, later in-app shell approvals, and eventual MCP-style interventions.

### What the current tests prove

- `tests/test_runtime.py`
  - fake runtime returns deterministic output
  - empty prompt handling works
  - runtime builder defaults safely
  - live runtime selection works
  - live runtime fails safely when `OPENAI_API_KEY` is missing
  - config merge logic applies CLI-style overrides safely
  - shell-command approvals can be queued in fake mode and restored/executed in live mode
  - read-only shell inspection commands now run without confirmation while shell test commands still queue approval
  - unsupported shell commands are denied before execution instead of reaching subprocesses
  - steering requires confirmation for overwrite and broad-edit requests by default, and can opt into overwrites explicitly
  - steering events are emitted before workspace tools run
  - approval requests can be queued and resumed deterministically

- `tests/test_app.py`
  - app renders runtime status
  - app renders the active workspace banner
  - entering text and pressing Enter updates the transcript/history
  - status line reflects turn count, runtime mode, and selected model
  - runtime failures are rendered in the UI instead of crashing silently
  - successful turns are persisted to `turns.jsonl` and `transcript.md`
  - runtime failures are also persisted as session artifacts
  - approval state is rendered in a dedicated banner
  - pending approvals block new prompts until resolved
  - approval resolutions persist as normal session turns
  - timeline filter shortcuts isolate tool and persistence activity correctly
  - resumed sessions render a compact live history window instead of dumping the full backlog
  - replay shortcuts browse older/newer turns and can return to live/latest view
  - restart-safe draft prompt state is restored into the input after restart
  - the in-app session switcher supports highlighted keyboard navigation, direct number shortcuts, and restart-safe chooser restoration
  - CLI argument parsing overrides runtime/model/workspace selection correctly
  - CLI session selection can load an explicit session dir, reopen the latest session, or pick from recent sessions interactively

- `tests/test_tools.py`
  - workspace summary reports top-level structure, notable files/directories, and dominant file types
  - workspace listing returns workspace-relative paths
  - file reads return bounded excerpts with line metadata
  - repo search returns bounded text matches
  - shell commands stay inside the narrow allowlist
  - guarded writes create new files but reject implicit overwrite
  - path traversal outside the workspace is rejected
  - live-runtime tool registration returns the expected Strands tool set

- `tests/test_sessions.py`
  - recent sessions are ordered by latest artifact activity
  - session summaries include bounded last-prompt previews
  - restart-safe session state persists approvals, view focus, draft prompt text, and session-switcher chooser context together
  - the compact picker renders usable recent-session labels
  - the picker returns the selected session and handles an empty artifact root safely

This is the current anti-regression contract for the active Phase 2/3/4 slice.

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

1. keep the fake runtime path green while refining the event schema around steering/intervention events
2. add even denser recent-session triage hints, such as compact multi-approval counts or last-tool-result snippets
3. reconcile the pinned prototype path with the canonical repo so future automation does not need recovery indirection
4. decide whether session-switcher restore should also preserve transient sort/filter modes once the chooser gets richer
5. decide whether direct shell inspection should surface richer command-result summaries in recent-session triage

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

- keep tightening the fake/live event schema around steering and intervention milestones
- add even denser recent-session triage hints, such as compact multi-approval counts or last-tool-result snippets
- decide whether the session switcher needs its own richer sort/filter affordances now that chooser restoration exists
- reconcile the pinned prototype path with the canonical repo so future automation does not need recovery indirection
- decide whether direct shell inspection should surface richer command-result summaries in recent-session triage
