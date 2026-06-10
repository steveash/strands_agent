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

**Phase 1 is complete, Phase 2 now splits the shell-command seam into direct read-only inspection plus approval-gated test execution alongside higher-signal workspace summary and conservative edit/mutation seams, Phase 3 includes resumable session-artifact replay plus both launch-time and in-app recent-session reopen flows, Phase 4 now persists restart-safe session state beyond approvals so confirm-needed mutations, replay/filter context, partially typed follow-up prompts, and the in-app session-switcher chooser state can survive a TUI restart, and Phase 5 now adds compact restore-state badges, selected-session preview blocks, shell/test outcome rollups, workspace-inspect vs workspace-edit triage lanes, dedicated workspace/shell/tool/intervention backlog rollup headers with overlap and page summaries across both reopen surfaces, compact tool-failure and intervention-family/request mix summaries for those tool/intervention headers, pending/denied approval backlog rollups with queue volume, family mix, restored-queue hints, and oldest-age cues across both reopen surfaces, denied-approval triage filters, approval-age and stale-session cues for recent-session triage, absolute UTC timestamps alongside approval/stale/intervention age cues plus the tool/workspace/shell lane rollups, attention sorting that now distinguishes denied test approvals from denied edits and executed test failures, recent multi-tool streak summaries, restart-safe launch-time picker state, lane-collapsed workspace/shell previews inside focused triage filters so overlap sessions stop leaking off-lane history, explicit pending-only lane hints when `workspace-edit` or `shell-test` matches are coming from queued approvals rather than executed lane events yet, dedicated pending-only queue-mix summary lines for focused `workspace-edit` and `shell-test` views with oldest pending age/timestamp cues that now fall back to session activity when approval timestamps are missing and explicitly label when that fallback was used, selected-session preview provenance lines that now show pending-only age/timestamp/source plus fresh-vs-restored queue provenance and bounded numbered multi-approval queue breakdowns inside both reopen surfaces, explicit stale-cutoff hints in picker/switcher legends, prompts, empty states, and stale page-level rollup lines, a stubbed live-runtime approval-restore smoke path that persists/reloads approval metadata end-to-end, restored multi-approval queue breakdowns that mirror the existing pending-triage wording while collapsing after three visible items with an explicit hidden-count cue, shared approval queue/age metadata that now follows confirmation-required, approved, denied, and continuation events into both fake/live runtime flows and the TUI banners, compact event-timeline summary lines that expose approval provenance, queue context, and tool/result previews without forcing the operator to parse raw event dicts, recent-session intervention previews/rollups that now reuse the same timeline wording plus target-kind and continuation mix metrics, and operator-controlled timeline detail/raw toggles whose compact-vs-expanded state now survives a TUI restart.**

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
- approval lifecycle events that now carry shared `steering_stage`, `approval_tool_family`, normalized approval target metadata, and synthetic continuation metadata so fake/live approval recovery can be inspected with the same mental model,
- compact intervention timeline summaries that now distinguish direct approval outcomes from the synthetic post-approval `approval continued ...` follow-up prompt-preparation step, including target and tool-result cues,
- recent-session intervention previews now reuse the same timeline wording, pending approvals render as normalized `approval pending ...` queue summaries, and intervention triage headers now expose family, target-kind, and continuation mix metrics across both reopen surfaces,
- a dedicated event timeline pane for runtime milestones, tool activity, failures, compact human-readable summary lines, and raw structured event data,
- keyboard-driven event filtering in the timeline pane for all/runtime/tool/failure/persistence/intervention views,
- keyboard-driven `Ctrl+T` detail and `Ctrl+R` raw-data toggles so the event pane can switch between compact summary-only and fully expanded observability views,
- per-session artifact persistence under `artifacts/sessions/<session-id>/` with both `turns.jsonl` and `transcript.md`,
- structured event payloads with timestamps and metadata for both fake and live runtime paths,
- explicit `artifact_saved` persistence events emitted by the app after each turn is written,
- response metadata capture for provider, mode, model, workspace root, tool count, and elapsed time where available,
- deterministic fake-runtime event emission for inspect, search, write, and edit activity, including confirm-needed mutation prompts, so UI behavior is testable without live model calls,
- compact replay navigation for resumed sessions so the conversation pane can browse older turns without dumping the full backlog into the live transcript view,
- restart-safe restoration of event-filter, timeline detail/raw view, replay-focus, and draft-prompt state so reopening a session can preserve the user's inspection context as well as pending approvals,
- a compact recent-session picker plus a `--resume-last` shortcut so reopen flow is no longer gated on manually passing `--session-dir`,
- launch-time CLI picker triage controls for all/pending/denied/restore/restored-approval/stale-approval/stale-pending/stale-denied/stale-restored/tool/workspace-inspect/workspace-edit/intervention/shell/shell-inspect/shell-test filters plus recent-vs-attention sorting, including `--pick-filter` / `--pick-sort` defaults and interactive `A` / `P` / `D` / `R` / `V` / `O` / `Q` / `X` / `U` / `T` / `W` / `E` / `G` / `H` / `I` / `Y` / `S` toggles,
- an in-app `F11` session switcher that reuses the same recent-session summaries after startup, can jump into another saved session without restarting the TUI, and can start a fresh session inline even when the active filter has zero visible matches,
- keyboard-driven session-switcher navigation with ↑/↓ (or J/K), Enter-to-switch, and a highlighted selection row rather than number-only switching,
- in-app session-switcher triage controls for all/pending/denied/restore/restored-approval/stale-approval/stale-pending/stale-denied/stale-restored/tool/workspace-inspect/workspace-edit/intervention/shell/shell-inspect/shell-test filters plus recent-vs-attention sorting so denser recent-session summaries stay skimmable as the list grows,
- restart-safe session-switcher restoration so reopening a session can bring back the chooser with the prior target selection preserved where possible,
- richer recent-session summaries in both the CLI picker and in-app switcher, including pending-approval markers, compact restore-state badges, explicit pending-approval age cues, stale-session badges, intervention rollups/previews, workspace-lane badges/previews for inspect vs edit activity, workspace/shell/tool/intervention backlog rollup headers with focus + overlap/page summaries, compact tool-failure and intervention-family/request mix details, pending/denied approval backlog headers with queue volume + family mix + restored-queue/age cues, broad tool triage that now keeps fresh/restored pending edit/test queues visible even before an execution event exists, last-event previews, bounded recent-tool streak summaries, explicit recent shell/test outcome rollups, and overlap badges when one session spans multiple triage lanes,
- focused workspace/shell triage views that now collapse preview snippets to the active lane instead of echoing unrelated mixed-lane history from the same saved session,
- focused `workspace-edit` and `shell-test` triage rows/previews that now explicitly say when a session only matches because a pending approval exists and no executed lane event has happened yet,
- focused `workspace-edit` and `shell-test` backlog summaries that now add queue-mix metrics for `pending-only` vs `restored pending-only` matches plus oldest pending age/timestamp cues that can fall back to session activity when approval timestamps are missing, and those summary lines now explicitly label when the displayed oldest-age cue came from that fallback path, so approval-backed lane matches are visible and auditable at the page level too,
- selected-session previews in both the launch-time picker and in-app `F11` switcher that now also show pending-only age, absolute UTC timestamp, whether that cue came from approval `created_at` or session-activity fallback, and bounded numbered queue breakdowns when multiple approvals share the focused pending-only lane, so operators can audit a highlighted queue-backed lane match without mentally joining it to the page-level rollup,
- a selected-session preview block inside the in-app `F11` switcher so the highlighted session now exposes the same richer summary context as the launch-time picker,
- explicit empty-filter guidance across both recent-session reopen surfaces so zero-match triage states say how many saved sessions still exist plus which keys recover all/pending/denied/restore/stale-approval/stale-pending/stale-denied/stale-restored/tool/workspace-inspect/workspace-edit/intervention/shell/shell-inspect/shell-test views, and the in-app switcher now advertises/exercises the same Enter-or-N fresh-session fallback as the launch-time picker,
- active stale-approval cutoff hints echoed in picker/switcher legends, prompts, empty-state guidance, and stale page-level rollup lines so stale triage semantics stay visible even when the cutoff comes from CLI or env config,
- deterministic recent-session ordering that now prefers the newest artifact turn timestamp instead of relying only on filesystem mtime ties,
- attention sorting that now pulls sessions with pending approvals first, recently denied approvals next, then recent tool failures above generic restore/tool activity so blocked or broken work stays easier to spot,
- tests that cover TUI state, config merging, tool safety, runtime selection, session selection, live-tool event capture, event rendering, and artifact persistence,
- a local smoke script for validating the real runtime without committing secrets,
- a standalone `smoke_cli_docs` smoke target that audits smoke-wrapper `--help` text against the README and emits actionable missing-snippet diagnostics,
- drift-only smoke-doc rendering that can now emit review artifacts (`.md` sections, JSON manifest summaries/checksums, unified diff) for multi-wrapper README repairs,
- repair/check smoke-doc tooling that can now persist machine-readable drift/repair reports to disk for CI or manual review,
- a configurable `scripts/smoke_cli_docs_artifacts_smoke.py` contract runner that can now preserve synthetic drift/review bundles under explicit source/output paths for any public smoke wrapper and persist one machine-readable bundle index for CI or later review,
- a dedicated `scripts/timeline_smoke.py` walkthrough that exercises runtime vs persistence timeline summaries without needing live credentials,
- and a dedicated `scripts/session_triage_intervention_mix_smoke.py` contract runner that exercises the public session-triage wrapper and asserts intervention target/continuation mix lines end-to-end across both picker and switcher flows.

What changed this run:
- updated `src/strands_agent_tui/app.py` so pressing `Enter` inside the in-app `F11` switcher now starts a fresh session when the active filter has zero visible matches instead of doing nothing,
- updated `src/strands_agent_tui/sessions/summary_utils.py` so the shared zero-match switcher guidance now reflects the new Enter-or-`N` fallback clearly,
- added regression coverage in `tests/test_app.py` and `tests/test_summary_utils.py`, plus smoke coverage in `scripts/session_switcher_smoke.py` and `scripts/summary_utils_smoke.py`, to lock both the copy and the new zero-match Enter behavior,
- tightened the smoke-doc review harness rerun-hint assertion helper so smoke scripts can derive expected bundle-hint prefixes from shared defaults instead of repeating raw prefix strings, with matching regression coverage in `tests/test_smoke_script_harness.py`,
- validated the change with focused app/summary pytest coverage, the public `session_triage_smoke.py both` bundle, the summary-utils smoke target, and the full pytest suite,
- and no destructive unblock step was needed this run.

Why this matters now:
- the launch-time picker already treated zero-match triage as a place where Steve could immediately branch into a fresh session, but the in-app switcher still had a small dead-end interaction seam,
- letting `Enter` start a fresh session from that zero-match state makes the reopen UX more consistent and keeps session triage feeling like an active control surface instead of a passive report,
- and that makes it easier to study how Strands session persistence and operator steering behave when Steve pivots from blocked or over-filtered work into a new coding loop.

How we know the prototype is working right now:
- focused pytest coverage now proves both the shared empty-state copy and the live TUI behavior when `Enter` is pressed from a zero-match switcher state,
- `summary_utils_smoke.py` exercises the shared guidance contract directly,
- `session_triage_smoke.py both` now covers the zero-match switcher hint plus the new `Enter`-starts-fresh-session smoke path end-to-end,
- and the full pytest suite still passes after the switcher interaction change.

Current evidence:
- focused app/summary coverage: `.venv/bin/pytest -q tests/test_summary_utils.py tests/test_app.py` => `84 passed in 44.00s`,
- summary rendering smoke: `.venv/bin/python scripts/summary_utils_smoke.py` => all checks passed,
- public triage smoke: `.venv/bin/python scripts/session_triage_smoke.py both` => `[session-triage-smoke] summary: 2/2 targets passed in 26.20s`,
- full automated tests: `.venv/bin/pytest -q` => `521 passed in 135.97s (0:02:15)`.

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
- compact `summary:` lines in the event pane for tool results, response completions, and approval/intervention queue context while preserving raw structured event payloads underneath,
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
.venv/bin/python scripts/live_smoke.py
```

Expected result includes `live_runtime_requested= True`, `live_runtime_text= True`, and `live_runtime_provider_mode= True` after the short reply plus provider/mode line.

### Standalone local smoke bundle
To verify the remaining local smoke surfaces with shared fail-fast `= False` handling:

```bash
.venv/bin/python scripts/standalone_smoke.py
```

This default `local` bundle runs `summary_utils`, `shell_tool`, `replay`, `timeline`, `smoke_cli_docs`, and `smoke_cli_docs_artifacts` smokes together, exits non-zero on the first failing boolean result line, and ends with a concise `[standalone-smoke] summary: ...` footer. Use `.venv/bin/python scripts/standalone_smoke.py contract-negative` to rerun the malformed smoke-script contract negatives around `standalone_docs_rerun_hint_smoke`, `.venv/bin/python scripts/standalone_smoke.py docs-contract` for the docs-adjacent contract bundle that combines the standalone rerun-hint, malformed-result/detail, and docs-review lane regressions, `.venv/bin/python scripts/standalone_smoke.py docs-parity-only` to rerun the docs parity alias plus its dedicated subprocess rerun-hint regression, `.venv/bin/python scripts/standalone_smoke.py docs-review-only` to rerun just the docs-review lane regressions, `.venv/bin/python scripts/standalone_smoke.py docs-focused` for the broader docs parity + docs-review lane bundle, or `.venv/bin/python scripts/standalone_smoke.py all` after exporting live-runtime env vars if you also want to include the live smoke target.

Operator shortcuts:
- `.venv/bin/python scripts/standalone_smoke.py local` explicitly re-runs the default `local` alias (`summary_utils`, `shell_tool`, `replay`, `timeline`, `smoke_cli_docs`, `smoke_cli_docs_artifacts`)
- `.venv/bin/python scripts/standalone_smoke.py all` runs the live-inclusive alias (`summary_utils`, `shell_tool`, `replay`, `timeline`, `smoke_cli_docs`, `smoke_cli_docs_artifacts`, `live`)
- `.venv/bin/python scripts/standalone_smoke.py timeline` runs just the timeline smoke target
- `.venv/bin/python scripts/standalone_smoke.py docs` runs just the smoke CLI docs parity target
- `.venv/bin/python scripts/standalone_smoke.py docs-artifacts` runs the smoke CLI render/fix artifact contract smoke end-to-end
- `.venv/bin/python scripts/standalone_smoke.py docs-rerun-hint` runs the real subprocess standalone wrapper docs-drift regression that proves the docs-parity-only rerun hint lands before the fail-fast summary
- `.venv/bin/python scripts/smoke_cli_docs_smoke.py standalone_smoke` audits only the standalone wrapper docs (`session_triage_smoke`, `session_recovery_smoke`, and `smoke_matrix` also work here)
- `.venv/bin/python scripts/smoke_cli_docs_smoke.py all` re-runs docs parity for every public smoke wrapper without the rest of the standalone bundle
- `.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py` exercises drifted README render/fix review artifacts end-to-end with fail-fast contract checks
- `.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py session_triage_smoke --output-dir artifacts/smoke-cli-docs-artifacts/session-triage` preserves a session-triage wrapper artifact bundle for later review
- `.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py all --output-dir artifacts/smoke-cli-docs-artifacts --readme-path README.md` preserves the all-wrapper contract bundle against a specific README copy while keeping predictable artifact paths
- `.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py all --output-dir artifacts/smoke-cli-docs-artifacts --bundle-index-path artifacts/smoke-cli-docs-artifacts/index.json` persists one machine-readable bundle index for CI or later review
- `.venv/bin/python scripts/smoke_cli_docs_render.py standalone_smoke --body-only` previews just the rendered standalone wrapper README body before a manual docs fix
- `.venv/bin/python scripts/smoke_cli_docs_render.py all --output-dir artifacts/smoke-cli-docs-preview` exports rendered README sections for every public smoke wrapper
- `.venv/bin/python scripts/smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview` exports only the currently drifted smoke wrapper README sections
- `.venv/bin/python scripts/smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview --manifest-output artifacts/smoke-cli-docs-preview.json --diff-output artifacts/smoke-cli-docs-review.patch` persists drift-only review artifacts as rendered sections plus JSON manifest summaries/checksums and unified diff files
- `.venv/bin/python scripts/smoke_cli_docs_fix.py standalone_smoke --diff` previews the standalone wrapper README diff before writing metadata-backed repairs
- `.venv/bin/python scripts/smoke_cli_docs_fix.py all --check` exits non-zero when any public smoke wrapper README section drifts
- `.venv/bin/python scripts/smoke_cli_docs_fix.py all --check --json` emits machine-readable drift results with manifest-style summaries/checksums for CI without scraping prose summaries
- `.venv/bin/python scripts/smoke_cli_docs_fix.py all --check --json-output artifacts/smoke-cli-docs-fix.json` persists the same machine-readable drift report with manifest-style summaries/checksums alongside the normal console summary
- `.venv/bin/python scripts/smoke_cli_docs_fix.py standalone_smoke` repairs the standalone wrapper README section in place from shared metadata
- `.venv/bin/python scripts/smoke_cli_docs_fix.py all` repairs every public smoke wrapper README section in place
- `.venv/bin/python scripts/standalone_smoke.py malformed-result` runs the malformed-result smoke-script contract regression that proves malformed three-item result tuples are reported before wrapper consumers depend on them
- `.venv/bin/python scripts/standalone_smoke.py malformed-detail` runs the malformed-detail smoke-script contract regression that proves missing, mismatched, and boolean detail payloads are reported
- `.venv/bin/python scripts/standalone_smoke.py contract-negative` re-runs only the malformed smoke-script contract alias (`malformed-result`, `malformed-detail`)
- `.venv/bin/python scripts/standalone_smoke.py docs-contract` re-runs the docs-adjacent smoke contract alias (`docs-rerun-hint`, `malformed-result`, `malformed-detail`, `matrix-artifact-roots`, `matrix-all-review-order`, `matrix-all-review-missing-api-key`, `matrix-docs-review-hint`)
- `.venv/bin/python scripts/standalone_smoke.py docs-parity-only` re-runs only the docs parity alias (`docs`, `docs-artifacts`, `docs-rerun-hint`)
- `.venv/bin/python scripts/standalone_smoke.py docs-focused` re-runs the broader docs parity + docs-review lane alias (`docs`, `docs-artifacts`, `docs-rerun-hint`, `matrix-artifact-roots`, `matrix-all-review-order`, `matrix-all-review-missing-api-key`, `matrix-docs-review-hint`)
- `.venv/bin/python scripts/standalone_smoke.py docs-review-only` re-runs only the docs-review lane regressions (`matrix-artifact-roots`, `matrix-all-review-order`, `matrix-all-review-missing-api-key`, `matrix-docs-review-hint`)
- `.venv/bin/python scripts/standalone_smoke.py matrix-artifact-roots` runs the fake-live smoke-matrix artifact-root regression that proves `review` and `all-review` keep distinct docs-review bundles
- `.venv/bin/python scripts/standalone_smoke.py matrix-all-review-order` runs the real `all-review` smoke-matrix regression that proves pending docs-review breadcrumbs appear before the live-runtime hint and the docs-review-only rerun hint lands before the fail-fast summary
- `.venv/bin/python scripts/standalone_smoke.py matrix-all-review-missing-api-key` runs the real subprocess `all-review` live-runtime failure regression that proves the missing-API-key hint lands after the persisted docs-review breadcrumbs and before the docs-review-only rerun hint
- `.venv/bin/python scripts/standalone_smoke.py matrix-docs-review-hint` runs the real subprocess docs-review failure regression that proves the docs-review-only rerun hint lands after the persisted review matrix-summary path
- `.venv/bin/python scripts/standalone_smoke.py replay` runs just the replay smoke target
### Timeline smoke check

To verify the compact runtime-vs-persistence timeline summaries without launching the TUI:

```bash
.venv/bin/python scripts/timeline_smoke.py
```

This walkthrough now also runs as the public `timeline` target inside `.venv/bin/python scripts/standalone_smoke.py` and therefore inside the default local `.venv/bin/python scripts/smoke_matrix.py` path.

Expected result includes `timeline_runtime_summary= True`, `timeline_persistence_summary= True`, and `timeline_filter_counts= True`, plus rendered timeline snapshots for the runtime and persistence filters.

### Session triage smoke bundle

To run the picker + switcher smoke surfaces together with shared fail-fast handling:

```bash
.venv/bin/python scripts/session_triage_smoke.py
```

This default bundle runs both triage targets, accepts either `both` or `all` for the combined picker+switcher selection, and ends with a concise `[session-triage-smoke] summary: ...` footer.

Operator shortcuts:
- `.venv/bin/python scripts/session_triage_smoke.py both` explicitly re-runs the default picker+switcher alias
- `.venv/bin/python scripts/session_triage_smoke.py all` is an explicit alias for the same picker+switcher bundle
- `.venv/bin/python scripts/session_triage_smoke.py picker` runs only the launch-time picker smoke

### Session recovery smoke bundle

To run the approval/session-state/live-restore smoke surfaces together with shared fail-fast handling:

```bash
.venv/bin/python scripts/session_recovery_smoke.py
```

This bundle runs all recovery targets by default and ends with a concise `[session-recovery-smoke] summary: ...` footer.

Operator shortcuts:
- `.venv/bin/python scripts/session_recovery_smoke.py all` explicitly selects the full recovery bundle (`approval`, `approval-restart`, `session-state`, `live-restore`, `live-restore-denied`)
- `.venv/bin/python scripts/session_recovery_smoke.py live-restore` runs only the live-restore recovery target
- `.venv/bin/python scripts/session_recovery_smoke.py approval` runs only the approval smoke target

### Full local smoke matrix
To run the current local smoke bundles together with fail-fast handling:

```bash
.venv/bin/python scripts/smoke_matrix.py
```

This default `local` matrix runs the standalone local bundle plus the session-triage and recovery bundles together, suppresses the nested wrapper summary footers so the combined output stays focused on per-check lines, prints bundle-level `running ...`, `... passed in ...s`, or `... failed in ...s` summaries, and finishes with an overall matrix summary line. Use `.venv/bin/python scripts/smoke_matrix.py all` after exporting live-runtime env vars if you want the `all` alias to swap in the live-inclusive standalone bundle, `.venv/bin/python scripts/smoke_matrix.py review` to append a smoke-doc artifact review lane that persists its bundle under `artifacts/smoke-cli-docs-artifacts/smoke-matrix-review`, or `.venv/bin/python scripts/smoke_matrix.py all-review` to combine both in one rerun while persisting the docs-review bundle under `artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review`.

Operator shortcuts:
- `.venv/bin/python scripts/smoke_matrix.py local` explicitly re-runs the default local matrix (`standalone`, `triage`, `recovery`)
- `.venv/bin/python scripts/smoke_matrix.py all` swaps in the live-inclusive standalone bundle (`standalone (live-inclusive)`, `triage`, `recovery`)
- `.venv/bin/python scripts/smoke_matrix.py review` adds the optional smoke-doc artifact review lane (`standalone`, `triage`, `recovery`, `docs-review`)
- `.venv/bin/python scripts/smoke_matrix.py all-review` combines the live-inclusive standalone bundle with the smoke-doc artifact review lane while persisting docs-review artifacts under `artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review` (`standalone (live-inclusive)`, `triage`, `recovery`, `docs-review`)
- `.venv/bin/python scripts/smoke_matrix.py triage` runs only the session-triage bundle
- `.venv/bin/python scripts/smoke_matrix.py standalone` runs only the standalone local bundle
- `.venv/bin/python scripts/smoke_matrix.py recovery` runs only the recovery bundle
- `.venv/bin/python scripts/smoke_matrix.py docs-review` runs only the smoke-doc artifact review lane with persisted artifacts under `artifacts/smoke-cli-docs-artifacts/smoke-matrix-review`
### Live approval-restore smoke check

To verify the live runtime's restored approval metadata flow without launching the TUI:

```bash
.venv/bin/python scripts/live_restore_smoke.py
```

Expected result includes `live_restore_initial_pending= True`, `live_restore_approved_event= True`, and `live_restore_summary= True`.

### Replay smoke check

To verify the compact live-view + replay-navigation rendering without launching the full TUI:

```bash
.venv/bin/python scripts/replay_smoke.py
```

Expected result includes both a `live latest 2-4` view and a `replay 3/4` view for the same saved session fixture, plus `replay_live_view= True` and `replay_replay_view= True`.

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
strands-agent --pick-session --pick-filter pending --pick-sort attention
```

Those flows reload the saved prompt/response history plus timeline events from `turns.jsonl`, then continue appending new turns into the selected session directory.

The launch-time picker now mirrors the in-app triage model: use `J` / `K` to move the highlighted row, `Enter` to reopen the highlighted session, number keys for quick direct selection, `N` to start a fresh session, `A` for all sessions, `P` for pending approvals, `D` for denied approvals, `R` for restore-state sessions, `V` for restored-approval sessions, `O` / `Q` / `X` / `U` for stale-approval lanes, `T` for recent tool-active sessions, `W` for workspace-inspect sessions, `E` for workspace-edit sessions, `G` for intervention sessions, `H` / `I` / `Y` for shell lanes, and `S` to toggle recent-vs-attention sorting. When there are more than 8 matches, use `[` and `]` to page backward/forward so older sessions are still reachable before the TUI boots. If the active filter has zero matches, the picker now explains that saved sessions still exist, shows how to widen triage with `A` / `P` / `D` / `R` / `V` / `O` / `Q` / `X` / `U` / `T` / `W` / `E` / `G` / `H` / `I` / `Y`, and makes the `Enter` / `N` fresh-session fallback explicit. Pending and denied filters now also show backlog headers with approval counts, tool-family mix, restored-queue cues, oldest-age summaries, and exact UTC timestamps before the per-session rows. Restored approval activity is also grouped into a compact `approval restore:` badge so revived queues stay distinguishable from generic draft/filter replay state. The selected row also shows bounded tool/workspace previews plus explicit `pending at` / `last denied at` / restore timestamps so recent inspect, test, edit, and approval timing is visible before you reopen the session, and pending-only queue breakdowns now collapse after three visible approvals with an explicit hidden-count line so long queues stay skimmable.

Partially typed prompt text is also persisted in `session_state.json`, so a restart or session reload can reopen with the draft still in the input instead of discarding it.

After startup, `F11` opens the same recent-session summaries inside the TUI so you can switch to another saved session or start a fresh one without restarting. Use ↑/↓ (or `J`/`K`) to move the highlighted row, `Enter` to switch to the highlighted session, number keys for quick direct selection, `W` / `E` to isolate workspace-inspect vs workspace-edit sessions, `V` to isolate restored-approval sessions, `G` for intervention-heavy sessions, `H` / `I` / `Y` for shell lanes, and `N` for a fresh session. Pending and denied switcher filters now reuse the same backlog headers as the launch-time picker, so approval volume and age are visible before you switch sessions. The highlighted row now expands into a selected-session preview block, including pending approval details, restored-approval badges, restore badges, workspace-lane cues, last prompt, last tool, and bounded recent tool/workspace streaks. If the active switcher filter narrows to zero matches, the switcher now explains how many saved sessions still exist, which triage keys widen the view again, when `Esc`/`F11` returns to the active session, and that `Enter` or `N` can immediately start a fresh session from that empty state. If the target session has persisted approvals, they are restored automatically; if the current session still has an unresolved approval, switching is blocked until you approve or deny it.

If you restart while the switcher is open, the app now restores that chooser mode and preserves the previously highlighted target session where possible, so you can keep triaging recent work instead of manually reopening the same picker state.

When a resumed session has multiple turns, the conversation pane stays in a compact live view showing only the latest 3 turns. Use `F6` for older turns, `F7` for newer turns, and `F8` to jump back to the live/latest view.

### Event timeline filters

Inside the TUI, use these shortcuts to focus the event pane:

- `F1` all events
- `F2` runtime events
- `F3` tool events
- `F4` failure events
- `F5` persistence events
- `F12` intervention / approval events
- `Ctrl+T` toggle event detail lines on/off
- `Ctrl+R` toggle raw structured event data on/off

Each event row now also includes a compact `summary:` line when the formatter can derive something higher-signal than the raw detail string, for example approval queue position/source, resumed-after-approval state, shell command previews, or artifact/session-state save context.

The current detail/raw toggle state is shown at the top of the pane and is also persisted in `session_state.json`, so a restart can reopen the same compact or expanded timeline view.

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

Expected result shows an initial queued `write_file` approval, an approve/resume step, then a follow-on `replace_text` approval that can be denied. It now also prints readable intervention summary checks such as `timeline_pending_summary= True`, `timeline_approved_summary= True`, and `timeline_denied_summary= True` so the event language itself is under smoke coverage.

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
  - the in-app session switcher supports highlighted keyboard navigation, direct number shortcuts, selected-session preview rendering, explicit empty-filter triage guidance, zero-match `Enter` fresh-session fallback, and restart-safe chooser restoration
- the launch-time recent-session picker can page past the first 8 visible sessions while preserving the same triage filters and sorts, including restored-approval triage
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
  - session summaries include bounded last-prompt previews plus bounded recent-tool streak summaries
  - attention sorting now prioritizes denied test approvals ahead of denied edits and executed test/tool failures
  - restart-safe session state persists approvals, view focus, draft prompt text, and session-switcher chooser context together
  - the compact picker renders usable recent-session labels and richer selected-session previews
  - the picker returns the selected session, supports paged navigation, and handles an empty artifact root safely

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

1. reconcile the pinned prototype path with the canonical repo so future automation does not need recovery indirection
2. decide whether the now-explicit picker/switcher intervention-mix expectations should be factored into a smaller shared smoke assertion/helper instead of repeating required snippets inline
3. decide whether the now-capped selected-preview queue breakdowns should eventually support inline expand/collapse instead of a fixed three-item cap
4. decide whether the queue-preview cap should be configurable per surface or per lane once real-world session volume grows
5. decide whether the compact timeline view should eventually support per-event expansion instead of only global detail/raw toggles

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

- decide whether the compact timeline view should eventually support per-event expansion instead of only global detail/raw toggles
- decide whether smoke-doc artifact bundles should fold into `scripts/smoke_matrix.py` as an optional review lane
- decide whether the now-capped selected-preview queue breakdowns should eventually support inline expand/collapse instead of a fixed three-item cap
- decide whether the queue-preview cap should be configurable per surface or per lane once real-world session volume grows
- decide whether the repeated picker/switcher intervention-mix smoke requirements should collapse into a smaller shared assertion helper
- decide whether the `smoke_cli_docs` audit should expand beyond wrapper scripts if more operator-facing entrypoints become public
