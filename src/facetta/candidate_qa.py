"""Shared fail-closed QA validation for temporary Studio candidates."""

from __future__ import annotations

from collections.abc import Mapping


def _candidate_checks(
    qa: Mapping[str, object],
) -> list[dict[str, object]] | None:
    checks = qa.get("checks")
    if (
        not isinstance(checks, list)
        or not checks
        or any(
            not isinstance(check, dict)
            or type(check.get("passed")) is not bool
            or check.get("severity") not in {"hard", "warning"}
            for check in checks
        )
    ):
        return None
    return checks


def reviewable_candidate_qa(
    verdict: str,
    qa: Mapping[str, object],
) -> bool:
    """Return whether QA evidence may enter an explicit review decision.

    Provider routes reject hard failures before candidate storage. Durable
    candidate services repeat that check because persisted JSON can be stale,
    partially migrated, or corrupted before a later Apply/Save decision.
    """

    checks = _candidate_checks(qa)
    if checks is None:
        return False
    failed = [check for check in checks if check["passed"] is False]
    hard_failure = any(check["severity"] == "hard" for check in failed)
    if hard_failure or qa.get("verdict") != verdict:
        return False
    if verdict == "pass":
        return (
            not failed
            and qa.get("accepted") is True
            and qa.get("review_required") is False
        )
    if verdict == "warn":
        return (
            bool(failed)
            and qa.get("accepted") is False
            and qa.get("review_required") is True
        )
    return False


def reviewable_candidate_qa_payload(qa: object) -> bool:
    """Validate a provider PASS/WARN payload using its persisted verdict."""

    if not isinstance(qa, Mapping):
        return False
    verdict = qa.get("verdict")
    return (
        isinstance(verdict, str)
        and reviewable_candidate_qa(verdict, qa)
    )


def forced_review_candidate_qa(qa: object) -> bool:
    """Validate QA that deliberately awaits a designer despite a pass.

    Exact Views and specification-bound Present outputs are never promoted by
    automated QA alone. Their provider verdict remains PASS or WARN, while the
    candidate-level acceptance flags are deliberately forced into review.
    """

    if not isinstance(qa, Mapping):
        return False
    checks = _candidate_checks(qa)
    if checks is None:
        return False
    failed = [check for check in checks if check["passed"] is False]
    if any(check["severity"] == "hard" for check in failed):
        return False
    verdict = qa.get("verdict")
    if (
        verdict not in {"pass", "warn"}
        or qa.get("accepted") is not False
        or qa.get("review_required") is not True
    ):
        return False
    return (verdict == "pass" and not failed) or (
        verdict == "warn" and bool(failed)
    )
