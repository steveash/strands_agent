from __future__ import annotations

from contextlib import redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from strands_agent_tui.testing import emit_smoke_checks as real_emit_smoke_checks

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _load_script_module(name: str):
    spec = spec_from_file_location(f"tests.{name}", SCRIPT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_smoke_main_emits_requested_live_contract(monkeypatch) -> None:
    live_smoke = _load_script_module("live_smoke")

    class _Runtime:
        def run(self, prompt: str):
            assert prompt == "Reply with exactly: live runtime ok"
            return SimpleNamespace(text="live runtime ok", provider="stub-provider", mode="live")

    monkeypatch.setattr(
        live_smoke,
        "load_config",
        lambda: SimpleNamespace(runtime_mode="live", openai_model="stub-model"),
    )
    monkeypatch.setattr(live_smoke, "build_runtime", lambda **_: _Runtime())

    output = StringIO()
    monkeypatch.setattr(
        live_smoke,
        "emit_smoke_checks",
        lambda checks: real_emit_smoke_checks(checks, stdout=output),
    )

    with redirect_stdout(output):
        exit_code = live_smoke.main()

    assert exit_code == 0
    assert output.getvalue().splitlines() == [
        "live runtime ok",
        "provider=stub-provider mode=live",
        "live_runtime_requested= True",
        "live_runtime_text= True",
        "live_runtime_provider_mode= True",
    ]


def test_smoke_matrix_defaults_to_local_bundle_sequence(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_targets(targets):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_targets", _run_smoke_targets)

    exit_code = smoke_matrix.main([])

    assert exit_code == 0
    assert seen == {
        "names": ["standalone-local", "triage", "recovery"],
        "args": [(), (), ()],
    }


def test_smoke_matrix_all_uses_live_inclusive_standalone_bundle(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_targets(targets):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_targets", _run_smoke_targets)

    exit_code = smoke_matrix.main(["all"])

    assert exit_code == 0
    assert seen == {
        "names": ["standalone-all", "triage", "recovery"],
        "args": [("all",), (), ()],
    }
