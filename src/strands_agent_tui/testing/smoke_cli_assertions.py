from __future__ import annotations

from collections.abc import Iterable


def normalize_cli_text(text: str) -> str:
    return " ".join(text.split())


def matches_public_cli_invalid_choice(
    text: str,
    *,
    invalid_target: str,
    expected_choices: str,
) -> bool:
    normalized = normalize_cli_text(text)
    return f"invalid choice: '{invalid_target}'" in normalized and expected_choices in normalized


def matches_public_cli_help(
    text: str,
    *,
    required_snippets: Iterable[str],
) -> bool:
    normalized = normalize_cli_text(text)
    return all(snippet in normalized for snippet in required_snippets)
