"""Closed-loop Grok-primary execution with QA-specific correction."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence

from facetta.image_agent.contracts import (
    AttemptError,
    CheckSeverity,
    FailureCategory,
    ImageAgentPlan,
    ImageAgentResult,
    ImageAttemptSummary,
    ImageQualityReport,
    ImageRoute,
    ImageRunStatus,
    ImageRunSummary,
    QualityCheck,
    QualityVerdict,
)
from facetta.image_agent.errors import (
    ImageEvaluationFailure,
    ImagePlanValidationError,
    ImageProviderFailure,
    ImageQualityFailure,
    ProviderCallError,
)
from facetta.image_agent.localization import derive_automatic_localization
from facetta.image_agent.planning import (
    attempt_cache_key,
    bind_localization_mask,
    route_for_attempt,
)
from facetta.image_agent.prompts import (
    MAX_PROVIDER_PROMPT_CHARS,
    RETRYABLE_VISUAL_WARNING_CODES,
    compile_correction_prompt,
    compile_initial_prompt,
)
from facetta.image_agent.providers import (
    ROUTE_METADATA,
    ImageProvider,
    RoutedImageProvider,
    available_fallback_route,
)
from facetta.image_agent.quality import RingQualityEvaluator


def _sha256(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


def _retryable_evaluation_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in (
        "timeout", "timed out", "handshake", "connection reset",
        "connection refused", "temporarily unavailable", "429", "502",
        "503", "504",
    ))


def _evaluate_with_transport_retry(call):
    """Retry one transient QA transport failure on the same image bytes."""
    try:
        return call(), 0
    except Exception as first:
        if not _retryable_evaluation_error(first):
            raise
        try:
            return call(), 1
        except Exception as second:
            raise second from first


def _record_evaluation_recovery(
    report: ImageQualityReport,
    retries: int,
) -> ImageQualityReport:
    if retries == 0:
        return report
    return report.model_copy(update={
        "checks": (*report.checks, QualityCheck(
            code="evaluation_transport_recovered",
            passed=True,
            severity=CheckSeverity.WARNING,
            message=(
                "quality evaluation recovered by retrying the audit on the "
                "same generated image bytes"
            ),
            evidence={"retry_count": retries, "image_regenerated": False},
        )),
    })


def _merge_source_precondition_warning(
    report: ImageQualityReport,
    source_report: ImageQualityReport | None,
) -> ImageQualityReport:
    if (source_report is None
            or source_report.verdict is not QualityVerdict.WARN):
        return report
    checks = (*report.checks, *source_report.failed_checks)
    if any(
        not check.passed and check.severity is CheckSeverity.HARD
        for check in checks
    ):
        verdict = QualityVerdict.FAIL
    elif any(not check.passed for check in checks):
        verdict = QualityVerdict.WARN
    else:
        verdict = QualityVerdict.PASS
    score = report.score
    if score is not None:
        score = min(score, 60.0)
    return report.model_copy(update={
        "verdict": verdict,
        "checks": checks,
        "score": score,
        "notes": (*report.notes, *source_report.notes),
    })


class JewelryImageAgent:
    """Execute at most Grok, corrected Grok, then a task-safe fallback."""

    def __init__(
        self,
        provider: ImageProvider | None = None,
        evaluator: RingQualityEvaluator | None = None,
        *,
        attempt_routes: Sequence[ImageRoute] | None = None,
        use_available_fallback: bool | None = None,
    ) -> None:
        using_default_provider = provider is None
        self.provider = provider or RoutedImageProvider()
        self.evaluator = evaluator or RingQualityEvaluator()
        self.attempt_routes = (
            None if attempt_routes is None else tuple(attempt_routes)
        )
        if self.attempt_routes is not None and not 1 <= len(self.attempt_routes) <= 3:
            raise ValueError("attempt_routes must contain between one and three routes")
        self.use_available_fallback = (
            using_default_provider
            if use_available_fallback is None
            else use_available_fallback
        )

    def run(
        self,
        plan: ImageAgentPlan,
        *,
        source_image: bytes | None = None,
        mask_bytes: bytes | None = None,
    ) -> ImageAgentResult:
        if mask_bytes is None and plan.mask_hash is None:
            localization = derive_automatic_localization(plan, source_image)
            if localization is not None:
                mask_bytes = localization.mask_bytes
                plan = bind_localization_mask(
                    plan,
                    mask_bytes,
                    provenance=localization.provenance,
                    evidence=localization.evidence,
                )
        self._verify_inputs(plan, source_image, mask_bytes)
        source_warning_report: ImageQualityReport | None = None
        source_preflight = getattr(
            self.evaluator, "evaluate_source_precondition", None)
        if callable(source_preflight) and source_image is not None:
            try:
                source_report, source_retries = _evaluate_with_transport_retry(
                    lambda: source_preflight(plan, source_image))
            except Exception as exc:
                raise ImageEvaluationFailure(
                    f"source topology could not be quality-gated: {exc}",
                    plan=plan,
                ) from exc
            if source_report is not None:
                source_report = _record_evaluation_recovery(
                    source_report, source_retries)
            if (source_report is not None
                    and source_report.verdict is QualityVerdict.FAIL):
                raise ImageQualityFailure(
                    "source image does not prove the recorded setting topology",
                    report=source_report,
                    plan=plan,
                )
            if (source_report is not None
                    and source_report.verdict is QualityVerdict.WARN):
                source_warning_report = source_report
        original_prompt = compile_initial_prompt(plan)
        if len(original_prompt) > MAX_PROVIDER_PROMPT_CHARS:
            raise ImagePlanValidationError(
                "compiled image prompt exceeds the provider's 8000-character "
                "limit; reduce visual contract complexity before execution",
                plan=plan,
            )
        attempts: list[ImageAttemptSummary] = []
        prior_report: ImageQualityReport | None = None
        prior_provider_error: ProviderCallError | None = None

        for number in range(1, 4):
            route = (
                route_for_attempt(plan, number)
                if self.attempt_routes is None
                else (
                    self.attempt_routes[number - 1]
                    if number <= len(self.attempt_routes)
                    else None
                )
            )
            if route is None:
                break
            if number == 3 and self.use_available_fallback:
                route = available_fallback_route(route)
            fallback_reason = None
            is_provider_fallback = (
                number > 1
                and attempts
                and ROUTE_METADATA[route][0] != attempts[-1].provider
            )
            if number == 3 and (
                self.attempt_routes is None or is_provider_fallback
            ):
                if prior_provider_error is not None and prior_report is not None:
                    fallback_reason = "grok_provider_failed_after_qa_failure"
                elif prior_provider_error is not None:
                    fallback_reason = "grok_provider_failed"
                else:
                    fallback_reason = "grok_qa_failed"
            prompt = original_prompt
            corrective_instruction = None
            if prior_report is not None:
                prompt, corrective_instruction = compile_correction_prompt(
                    plan,
                    original_prompt,
                    prior_report,
                )
                if prior_provider_error is not None:
                    recovery = (
                        "The previous provider call returned no usable candidate. "
                        "Re-execute this exact QA correction without changing scope."
                    )
                    corrective_instruction += "\n" + recovery
                    prompt += "\nPROVIDER RECOVERY: " + recovery
            elif prior_provider_error is not None:
                corrective_instruction = (
                    "The previous provider call returned no usable candidate. "
                    "Re-execute the exact original contract without changing scope."
                )
                prompt = original_prompt + "\n\nPROVIDER RECOVERY: " + corrective_instruction

            if len(prompt) > MAX_PROVIDER_PROMPT_CHARS:
                raise ImagePlanValidationError(
                    "compiled corrective image prompt exceeds the provider's "
                    "8000-character limit",
                    attempts=attempts,
                    plan=plan,
                )

            provider_name, model = ROUTE_METADATA[route]
            prompt_hash = _sha256(prompt)
            cache_key = attempt_cache_key(plan, route, prompt, model)
            started = time.perf_counter()
            try:
                output = self.provider.execute(
                    plan,
                    route,
                    prompt,
                    source_image=source_image,
                    mask_bytes=mask_bytes,
                )
                if not output.image_bytes:
                    raise ProviderCallError("provider returned an empty image")
            except ProviderCallError as exc:
                elapsed = round((time.perf_counter() - started) * 1000)
                attempts.append(ImageAttemptSummary(
                    attempt_number=number,
                    route=route,
                    provider=provider_name,
                    model=model,
                    latency_ms=elapsed,
                    corrective_instruction=corrective_instruction,
                    fallback_reason=fallback_reason,
                    prompt_hash=prompt_hash,
                    cache_key=cache_key,
                    error_category=FailureCategory.PROVIDER,
                    error=AttemptError(
                        category=FailureCategory.PROVIDER,
                        code=exc.code,
                        message=exc.message,
                        retryable=exc.retryable,
                    ),
                ))
                prior_provider_error = exc
                if not exc.retryable:
                    break
                continue
            except Exception as exc:
                wrapped = ProviderCallError(f"unexpected provider failure: {exc}")
                elapsed = round((time.perf_counter() - started) * 1000)
                attempts.append(ImageAttemptSummary(
                    attempt_number=number,
                    route=route,
                    provider=provider_name,
                    model=model,
                    latency_ms=elapsed,
                    corrective_instruction=corrective_instruction,
                    fallback_reason=fallback_reason,
                    prompt_hash=prompt_hash,
                    cache_key=cache_key,
                    error_category=FailureCategory.PROVIDER,
                    error=AttemptError(
                        category=FailureCategory.PROVIDER,
                        code=wrapped.code,
                        message=wrapped.message,
                    ),
                ))
                prior_provider_error = wrapped
                continue

            output_hash = _sha256(output.image_bytes)
            try:
                report, evaluation_retries = _evaluate_with_transport_retry(
                    lambda: self.evaluator.evaluate(
                        plan,
                        output.image_bytes,
                        source_image=source_image,
                        mask_bytes=mask_bytes,
                    )
                )
                report = _record_evaluation_recovery(
                    report, evaluation_retries)
                report = _merge_source_precondition_warning(
                    report, source_warning_report)
            except Exception as exc:
                elapsed = round((time.perf_counter() - started) * 1000)
                attempt = ImageAttemptSummary(
                    attempt_number=number,
                    route=route,
                    provider=provider_name,
                    model=model,
                    latency_ms=elapsed,
                    cached=output.cached,
                    provider_request_id=output.provider_request_id,
                    corrective_instruction=corrective_instruction,
                    fallback_reason=fallback_reason,
                    output_hash=output_hash,
                    prompt_hash=prompt_hash,
                    cache_key=cache_key,
                    usage=output.usage,
                    cost=output.cost,
                    error_category=FailureCategory.EVALUATION,
                    error=AttemptError(
                        category=FailureCategory.EVALUATION,
                        code="quality_evaluator_failed",
                        message=str(exc),
                        retryable=False,
                    ),
                )
                attempts.append(attempt)
                raise ImageEvaluationFailure(
                    f"candidate could not be quality-gated: {exc}",
                    attempts=attempts,
                    plan=plan,
                ) from exc

            elapsed = round((time.perf_counter() - started) * 1000)
            attempt = ImageAttemptSummary(
                attempt_number=number,
                route=route,
                provider=provider_name,
                model=model,
                latency_ms=elapsed,
                cached=output.cached,
                provider_request_id=output.provider_request_id,
                qa_verdict=report.verdict,
                qa_checks=report.checks,
                quality_score=report.score,
                corrective_instruction=corrective_instruction,
                fallback_reason=fallback_reason,
                output_hash=output_hash,
                prompt_hash=prompt_hash,
                cache_key=cache_key,
                usage=output.usage,
                cost=output.cost,
            )
            attempts.append(attempt)
            prior_provider_error = None
            prior_report = report

            if report.verdict is QualityVerdict.PASS:
                return self._result(
                    plan,
                    output.image_bytes,
                    report,
                    attempts,
                    accepted=True,
                )
            if report.verdict is QualityVerdict.WARN:
                retryable_visual_warning = any(
                    not check.passed
                    and check.code in RETRYABLE_VISUAL_WARNING_CODES
                    for check in report.checks
                )
                if retryable_visual_warning and number < 3:
                    continue
                return self._result(
                    plan,
                    output.image_bytes,
                    report,
                    attempts,
                    accepted=False,
                )

        # Once a candidate has failed QA, a later unavailable fallback does not
        # rewrite the outcome as a provider-only failure. Keep the terminal
        # category truthful: Grok exhausted its quality correction, while the
        # final attempt record still explains that fallback was unavailable.
        if prior_report is not None:
            failures = ", ".join(
                check.code for check in prior_report.failed_checks
                if check.severity.value == "hard"
            )
            raise ImageQualityFailure(
                "no candidate passed jewelry QA" + (f": {failures}" if failures else ""),
                report=prior_report,
                attempts=attempts,
                plan=plan,
            )
        message = (prior_provider_error.message if prior_provider_error else
                   "no usable image candidate was produced")
        raise ImageProviderFailure(message, attempts=attempts, plan=plan)

    @staticmethod
    def _verify_inputs(plan: ImageAgentPlan, source_image: bytes | None,
                       mask_bytes: bytes | None) -> None:
        if plan.source_hash != (_sha256(source_image) if source_image else None):
            raise ImagePlanValidationError(
                "source image does not match the content hash in the plan",
                plan=plan)
        if plan.mask_hash != (_sha256(mask_bytes) if mask_bytes else None):
            raise ImagePlanValidationError(
                "markup mask does not match the content hash in the plan",
                plan=plan)

    @staticmethod
    def _result(
        plan: ImageAgentPlan,
        image_bytes: bytes,
        report: ImageQualityReport,
        attempts: list[ImageAttemptSummary],
        *,
        accepted: bool,
    ) -> ImageAgentResult:
        selected = attempts[-1]
        review_required = not accepted
        run = ImageRunSummary(
            status=(ImageRunStatus.ACCEPTED if accepted
                    else ImageRunStatus.REVIEW_REQUIRED),
            operation=plan.operation,
            normalized_intent=plan.normalized_intent,
            prompt_version=plan.prompt_version,
            source_hash=plan.source_hash,
            spec_visual_hash=plan.spec_visual_hash,
            variant=plan.variant,
            verdict=report.verdict,
            attempts=tuple(attempts),
            selected_attempt=selected.number,
            output_hash=selected.output_hash,
        )
        return ImageAgentResult(
            plan=plan,
            run=run,
            image_bytes=image_bytes,
            quality=report,
            accepted=accepted,
            review_required=review_required,
        )
