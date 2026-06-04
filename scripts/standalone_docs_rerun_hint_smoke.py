from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    STANDALONE_DOCS_RERUN_HINT_FAILED_LINE_PREFIX,
    STANDALONE_DOCS_RERUN_HINT_HINT_PREFIX,
    STANDALONE_DOCS_RERUN_HINT_SUMMARY_PREFIX,
    build_standalone_docs_rerun_hint_results,
    collect_smoke_wrapper_failure_output,
    emit_smoke_results,
    run_script_module_main_via_driver_in_temp_checkout,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
STANDALONE_SMOKE_SCRIPT_PATH = SCRIPT_DIR / "standalone_smoke.py"


def run_standalone_docs_rerun_hint_smoke() -> list[tuple[str, object]]:
    smoke_run = run_script_module_main_via_driver_in_temp_checkout(
        repo_root=REPO_ROOT,
        script_path=STANDALONE_SMOKE_SCRIPT_PATH,
        module_name="scripts.standalone_docs_rerun_hint_smoke_target",
        argv=["local"],
        temp_prefix="standalone-docs-rerun-hint-",
        driver_filename="run_standalone_docs_rerun_hint.py",
        hook_source="""
        from strands_agent_tui.testing import smoke_runner

        def fake_run_smoke_target(target, **kwargs):
            observer = kwargs.get('output_line_observer')
            stdout = kwargs['stdout']
            stderr = kwargs['stderr']
            if target.name == 'docs-artifacts':
                for line in (
                    'fix_check_summary: smoke README drift detected in 1 section(s) for README.md: standalone_smoke\\n',
                    'fix_post_check= False\\n',
                ):
                    if observer is not None:
                        observer(line)
                    print(line, end='', file=stdout)
                stdout.flush()
                print('docs-artifacts smoke failed fast: fix_post_check= False', file=stderr)
                return 1
            return 0

        smoke_runner.run_smoke_target = fake_run_smoke_target
        module.run_smoke_target = fake_run_smoke_target
        """,
    )
    try:
        failure_output = collect_smoke_wrapper_failure_output(
            smoke_run.stderr_lines,
            failed_line_prefix=STANDALONE_DOCS_RERUN_HINT_FAILED_LINE_PREFIX,
            hint_prefix=STANDALONE_DOCS_RERUN_HINT_HINT_PREFIX,
            failure_summary_prefix=STANDALONE_DOCS_RERUN_HINT_SUMMARY_PREFIX,
        )

        return build_standalone_docs_rerun_hint_results(smoke_run, failure_output)
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_standalone_docs_rerun_hint_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
