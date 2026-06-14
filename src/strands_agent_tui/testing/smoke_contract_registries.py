from __future__ import annotations

STANDALONE_MALFORMED_RESULT_TARGET_NAME = "malformed-result"
STANDALONE_MALFORMED_DETAIL_TARGET_NAME = "malformed-detail"

STANDALONE_MALFORMED_CONTRACT_TARGET_NAMES = (
    STANDALONE_MALFORMED_RESULT_TARGET_NAME,
    STANDALONE_MALFORMED_DETAIL_TARGET_NAME,
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
