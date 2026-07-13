"""Disposable real HTTP server for the Studio TypeScript acceptance harness.

This module deliberately configures the canonical FastAPI app through its
documented dependency seams.  It does not replace the API with a fake server:
the TypeScript acceptance process still crosses uvicorn, FastAPI routing,
validation, SQLAlchemy persistence, candidate stores, and response decoding.
Only paid/non-deterministic image generation is replaced by an offline provider
whose output is accepted by the same image-agent and QA contracts.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from facetta.api.studio import (
    get_pre_spec_presentation_generator,
    get_studio_visual_preview_generator,
)
from facetta.creative_workflow import (
    get_creative_prompt_generator,
    get_creative_render_generator,
)
from facetta.db import (
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    get_db,
)
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.main import app
from facetta.studio_presentation_candidates import (
    clear_studio_presentation_candidates_for_tests,
)
from facetta.studio_visual_candidates import (
    clear_studio_visual_candidates_for_tests,
)


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format="PNG")
    return output.getvalue()


def _fixture_color(namespace: str, *parts: object) -> tuple[int, int, int]:
    """Return a stable, visibly useful color for one acceptance output.

    A variant-only fixture makes unrelated projects produce byte-identical
    images.  That is sufficient for a single happy path, but it can conceal
    cross-project mix-ups in the mixed-source acceptance matrix.  Include the
    complete provider input in a length-delimited digest so a sentence, each
    uploaded source, and each role-labeled reference board produce distinct,
    deterministic bytes without introducing a network provider.
    """
    digest = hashlib.sha256()
    for part in (namespace, *parts):
        value = part if isinstance(part, bytes) else str(part).encode("utf-8")
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    raw = digest.digest()
    # Avoid nearly black/white fixtures so comparisons remain visible in UI.
    return (
        32 + raw[0] % 192,
        32 + raw[1] % 192,
        32 + raw[2] % 192,
    )


def _accepted_result(
    plan,
    image: bytes,
    *,
    source: bytes | None = None,
    quality_source: bytes | None = None,
):
    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=image)

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(),
                score=98,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(
        plan,
        source_image=source,
        quality_source_image=quality_source,
    )


FAILED_QA_FIXTURE_PROMPT = "__FACETTA_ACCEPTANCE_FORCE_QA_FAIL__"


def _quality_rejected_result(plan, image: bytes):
    """Exercise the real closed-loop QA failure path in this server only.

    The trigger is interpreted solely by the dependency override in this
    disposable acceptance process. The production generator never imports or
    recognizes it, so ordinary prompts cannot activate fixture behavior.
    """

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=image)

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(QualityCheck(
                    code="acceptance_forced_fidelity_failure",
                    passed=False,
                    severity=CheckSeverity.HARD,
                    message="Acceptance fixture rejected the candidate.",
                ),),
                score=0,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(plan)


def _prompt_generator(prompt: str, variant: int):
    image = _png(_fixture_color("prompt", prompt, variant))
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        prompt,
        variant=variant,
    )
    if prompt == FAILED_QA_FIXTURE_PROMPT:
        return _quality_rejected_result(plan, image)
    return _accepted_result(plan, image)


def _render_generator(
    source: bytes,
    instruction: str,
    variant: int,
    *,
    quality_source_image: bytes | None = None,
):
    image = _png(_fixture_color(
        "render",
        source,
        quality_source_image or b"",
        instruction,
        variant,
    ))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        instruction,
        source_image=source,
        quality_source_image=quality_source_image,
        variant=variant,
    )
    return _accepted_result(
        plan,
        image,
        source=source,
        quality_source=quality_source_image,
    )


def _visual_preview_generator(
    source: bytes,
    instruction: str,
    scope: str,
    mask: bytes | None,
    variant: int,
):
    assert scope == "appearance"
    assert mask is None
    image = _png(_fixture_color(
        "visual-preview", source, instruction, scope, mask or b"", variant,
    ))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        instruction,
        source_image=source,
        variant=variant,
    )
    return _accepted_result(plan, image, source=source)


def _presentation_generator(
    source: bytes,
    intent: str,
    style_constraints: tuple[str, ...],
    expected_output: str,
    variant: int,
):
    image = _png(_fixture_color(
        "presentation",
        source,
        intent,
        "\x1f".join(style_constraints),
        expected_output,
        variant,
    ))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        intent,
        source_image=source,
        frozen=("exact visible jewelry",),
        style_constraints=style_constraints,
        expected_output=expected_output,
        variant=variant,
    )
    return _accepted_result(plan, image, source=source)


database_path = Path(os.environ["FACETTA_ACCEPTANCE_DB_PATH"])
engine = create_engine(
    f"sqlite:///{database_path}",
    connect_args={"check_same_thread": False},
)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)


@app.get("/__acceptance__/canonical-state/{owner}")
def _acceptance_canonical_state(owner: str) -> dict[str, int]:
    """Expose scoped persistence counts only in the disposable test process."""

    with Session() as db:
        return {
            "projects": db.scalar(select(func.count()).select_from(
                Project).where(Project.owner == owner)) or 0,
            "image_assets": db.scalar(select(func.count()).select_from(
                ImageAsset).where(ImageAsset.created_by == owner)) or 0,
            "revision_records": db.scalar(select(func.count()).select_from(
                ProjectRevisionRecord).where(
                    ProjectRevisionRecord.created_by == owner)) or 0,
            "designs": db.scalar(select(func.count()).select_from(
                Design).where(Design.created_by == owner)) or 0,
            "design_versions": db.scalar(select(func.count()).select_from(
                DesignVersion).join(Design).where(
                    Design.created_by == owner)) or 0,
            "accepted_image_runs": db.scalar(select(func.count()).select_from(
                ImageRun).where(
                    ImageRun.created_by == owner,
                    ImageRun.accepted_asset_id.is_not(None),
                )) or 0,
            "failed_image_runs": db.scalar(select(func.count()).select_from(
                ImageRun).where(
                    ImageRun.created_by == owner,
                    ImageRun.status == "failed",
                )) or 0,
            "charged_outputs": db.scalar(select(
                func.coalesce(func.sum(StudioJobRecord.charged_outputs), 0),
            ).where(StudioJobRecord.owner == owner)) or 0,
            "completed_outputs": db.scalar(select(
                func.coalesce(func.sum(StudioJobRecord.completed_outputs), 0),
            ).where(StudioJobRecord.owner == owner)) or 0,
        }


def _database():
    db = Session()
    try:
        yield db
    finally:
        db.close()


clear_studio_visual_candidates_for_tests()
clear_studio_presentation_candidates_for_tests()
app.dependency_overrides[get_db] = _database
app.dependency_overrides[get_creative_prompt_generator] = (
    lambda: _prompt_generator
)
app.dependency_overrides[get_creative_render_generator] = (
    lambda: _render_generator
)
app.dependency_overrides[get_studio_visual_preview_generator] = (
    lambda: _visual_preview_generator
)
app.dependency_overrides[get_pre_spec_presentation_generator] = (
    lambda: _presentation_generator
)
