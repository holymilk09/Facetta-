"""Disposable real HTTP server for the Studio TypeScript acceptance harness.

This module deliberately configures the canonical FastAPI app through its
documented dependency seams.  It does not replace the API with a fake server:
the TypeScript acceptance process still crosses uvicorn, FastAPI routing,
validation, SQLAlchemy persistence, candidate stores, and response decoding.
Only paid/non-deterministic image generation is replaced by an offline provider
whose output is accepted by the same image-agent and QA contracts.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from facetta.api.studio import (
    get_pre_spec_presentation_generator,
    get_studio_visual_preview_generator,
)
from facetta.creative_workflow import (
    get_creative_prompt_generator,
    get_creative_render_generator,
)
from facetta.db import Base, get_db
from facetta.image_agent import (
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
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


def _accepted_result(plan, image: bytes, *, source: bytes | None = None):
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
    )


def _prompt_generator(prompt: str, variant: int):
    image = _png((50 + variant, 90 + variant, 130 + variant))
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        prompt,
        variant=variant,
    )
    return _accepted_result(plan, image)


def _render_generator(
    source: bytes,
    instruction: str,
    variant: int,
    *,
    quality_source_image: bytes | None = None,
):
    image = _png((70 + variant, 105 + variant, 140 + variant))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        instruction,
        source_image=source,
        quality_source_image=quality_source_image,
        variant=variant,
    )
    return _accepted_result(plan, image, source=source)


def _visual_preview_generator(
    source: bytes,
    instruction: str,
    scope: str,
    mask: bytes | None,
    variant: int,
):
    assert scope == "appearance"
    assert mask is None
    image = _png((175 + variant, 120 + variant, 95 + variant))
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
    image = _png((225, 218, 205))
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
