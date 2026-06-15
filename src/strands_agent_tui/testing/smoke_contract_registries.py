from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StandaloneMalformedContractTargetSpec:
    target_name: str
    script_filename: str
    readme_description: str

    def command(self, *, script_name: str = "standalone_smoke.py") -> str:
        return f"{script_name} {self.target_name}"


STANDALONE_MALFORMED_RESULT_TARGET_NAME = "malformed-result"
STANDALONE_MALFORMED_DETAIL_TARGET_NAME = "malformed-detail"
STANDALONE_MALFORMED_CONTRACT_ALIAS_TARGET_NAME = "contract-negative"

STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS = (
    StandaloneMalformedContractTargetSpec(
        target_name=STANDALONE_MALFORMED_RESULT_TARGET_NAME,
        script_filename="smoke_script_malformed_result_smoke.py",
        readme_description=(
            "runs the malformed-result smoke-script contract regression that proves malformed "
            "three-item result tuples are reported before wrapper consumers depend on them"
        ),
    ),
    StandaloneMalformedContractTargetSpec(
        target_name=STANDALONE_MALFORMED_DETAIL_TARGET_NAME,
        script_filename="smoke_script_malformed_detail_smoke.py",
        readme_description=(
            "runs the malformed-detail smoke-script contract regression that proves missing, "
            "mismatched, and boolean detail payloads are reported"
        ),
    ),
)

STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES = tuple(
    spec.target_name for spec in STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS
)
STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS_BY_NAME = {
    spec.target_name: spec for spec in STANDALONE_MALFORMED_CONTRACT_TARGET_SPECS
}
STANDALONE_MALFORMED_CONTRACT_ALIAS_README_DESCRIPTION = (
    "re-runs only the malformed smoke-script contract alias "
    f"({', '.join(f'`{target_name}`' for target_name in STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES)})"
)


def standalone_malformed_contract_failure_check_name(target_name: str) -> str:
    malformed_prefix = "malformed-"
    if not target_name.startswith(malformed_prefix):
        raise ValueError(f"unknown malformed smoke target {target_name!r}")
    target_suffix = target_name.removeprefix(malformed_prefix)
    if not target_suffix or target_name not in STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES:
        raise ValueError(f"unknown malformed smoke target {target_name!r}")
    return f"{target_suffix.replace('-', '_')}_contract"


STANDALONE_MALFORMED_CONTRACT_FAILURE_CHECK_NAMES = {
    target_name: standalone_malformed_contract_failure_check_name(target_name)
    for target_name in STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES
}
