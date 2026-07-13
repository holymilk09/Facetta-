"""Disposable real HTTP server for the Studio TypeScript acceptance harness.

This module deliberately configures the canonical FastAPI app through its
documented dependency seams.  It does not replace the API with a fake server:
the TypeScript acceptance process still crosses uvicorn, FastAPI routing,
validation, SQLAlchemy persistence, candidate stores, and response decoding.
Only paid/non-deterministic image generation is replaced by an offline provider
whose output is accepted by the same image-agent and QA contracts.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import io
import json
import os
import base64
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from facetta.api.studio import (
    get_pre_spec_presentation_generator,
    get_studio_visual_preview_generator,
)
from facetta.api import catalog as catalog_api
from facetta.api import projects as projects_api
from facetta.api.specs import PhotoRequest
from facetta import catalog_component_targeting
from facetta.catalog_structural_mapper import (
    GROK_RING_COMPONENT_MAPPER_CONTRACT,
    GrokRingComponentMapper,
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
    ImageRunReview,
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
from facetta.image_identity import spec_visual_hash
from facetta.spec import Spec
from facetta.studio_presentation_candidates import (
    clear_studio_presentation_candidates_for_tests,
)
from facetta.studio_visual_candidates import (
    clear_studio_visual_candidates_for_tests,
)
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


Box = tuple[float, float, float, float]
STRUCTURAL_PRE_SPEC_PROMPT = "__FACETTA_ACCEPTANCE_STRUCTURAL_PRE_SPEC_RING__"


# This is an acceptance-only segmentation fixture, not corpus calibration.
# It deliberately uses the production mapper contract and activation boundary
# while replacing its paid vision observations with deterministic semantic
# regions for one narrow ring stone.cut path.
_RING_COMPONENT_INVENTORY: tuple[
    tuple[str, str, str, tuple[Box, ...]], ...
] = (
    ("center_stone.main", "center_stone", "Center stone", ((0.42, 0.28, 0.58, 0.44),)),
    (
        "stone_group.side",
        "stone_group",
        "Side stones",
        ((0.24, 0.30, 0.32, 0.38), (0.68, 0.30, 0.76, 0.38)),
    ),
    (
        "prongs.center",
        "prongs",
        "Center prongs",
        (
            (0.39, 0.25, 0.42, 0.30),
            (0.58, 0.25, 0.61, 0.30),
            (0.39, 0.42, 0.42, 0.47),
            (0.58, 0.42, 0.61, 0.47),
        ),
    ),
    (
        "setting.center",
        "setting",
        "Center setting",
        (
            (0.35, 0.20, 0.65, 0.24),
            (0.35, 0.24, 0.39, 0.50),
            (0.61, 0.24, 0.65, 0.50),
            (0.39, 0.47, 0.61, 0.51),
        ),
    ),
    (
        "shank.main",
        "shank",
        "Shank",
        (
            (0.30, 0.64, 0.38, 0.86),
            (0.62, 0.64, 0.70, 0.86),
            (0.38, 0.78, 0.62, 0.86),
        ),
    ),
    (
        "shoulders.main",
        "shoulders",
        "Shoulders",
        ((0.27, 0.54, 0.37, 0.64), (0.63, 0.54, 0.73, 0.64)),
    ),
    ("gallery.main", "gallery", "Gallery", ((0.42, 0.53, 0.58, 0.59),)),
    (
        "metal_zone.main",
        "metal_zone",
        "Visible metal",
        ((0.20, 0.18, 0.80, 0.86),),
    ),
    (
        "background.main",
        "background",
        "Background",
        (
            (0.00, 0.00, 1.00, 0.14),
            (0.00, 0.91, 1.00, 1.00),
            (0.00, 0.15, 0.14, 0.90),
            (0.86, 0.15, 1.00, 0.90),
        ),
    ),
)


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format="PNG")
    return output.getvalue()


def _semantic_ring_png() -> bytes:
    """Render a stable product-view raster for the structural HTTP flow."""
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    colors = {
        "center_stone": (45, 120, 190),
        "stone_group": (110, 170, 220),
        "prongs": (235, 205, 110),
        "setting": (210, 170, 70),
        "shank": (190, 145, 50),
        "shoulders": (205, 160, 55),
        "gallery": (180, 135, 45),
    }
    # The aggregate metal and background are segmentation evidence, not
    # separately painted layers. Paint only visible leaf semantics.
    for _component_id, kind, _label, boxes in _RING_COMPONENT_INVENTORY:
        if kind not in colors:
            continue
        for left, top, right, bottom in boxes:
            draw.rectangle(
                (
                    round(left * 99),
                    round(top * 99),
                    round(right * 99),
                    round(bottom * 99),
                ),
                fill=colors[kind],
            )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _semantic_observation(*_args: object) -> dict:
    return {
        "components": [
            {
                "parent_component_id": component_id,
                "kind": kind,
                "resolution": "resolved",
                "polygons": [
                    {
                        "points": [
                            {"x": left, "y": top},
                            {"x": right, "y": top},
                            {"x": right, "y": bottom},
                            {"x": left, "y": bottom},
                        ]
                    }
                    for left, top, right, bottom in boxes
                ],
            }
            for component_id, kind, _label, boxes in _RING_COMPONENT_INVENTORY
        ]
    }


def _confirmed_ring_spec(source_image: bytes) -> dict:
    """Return exact audited import truth for the disposable raster only."""
    base = {
        "schema_version": 1,
        "design_id": "dsn_acceptance_structural",
        "version": 1,
        "created_by": "usr_structural_api_acceptance",
        "created_at": "2026-07-13T00:00:00Z",
        "jewelry_type": "ring",
        "template": "solitaire_prong",
        "mode": "pro",
        "stone": {
            "species": "sapphire",
            "cut": "oval_brilliant",
            "carat": 2.0,
            "dimensions_mm": {"length": 8.6, "width": 6.4, "depth": 4.1},
            "color": {
                "trade": "Royal Blue",
                "gia": "vivid violetish blue, tone 6, saturation 6",
                "hue_code": "vB",
                "tone": 6,
                "saturation": 6,
            },
            "clarity": {
                "system": "gia_type_ii",
                "grade": "VS",
                "eye_clean": True,
            },
            "origin": "Sri Lanka",
            "treatment": "heated",
            "phenomena": [],
        },
        "setting": {
            "style": "4_prong_basket",
            "prong_count": 4,
            "prong_tip_mm": 0.9,
            "gallery_height_mm": 4.5,
        },
        "metal": {
            "material": "gold",
            "karat": 18,
            "color": "yellow",
            "finish": "high_polish",
        },
        "band": {"profile": "half_round", "width_mm": 1.8, "thickness_mm": 1.6},
        "ring_size": {"system": "US", "value": 6.5, "inner_diameter_mm": 16.9},
        "side_stones": [],
    }
    evidence_sha256 = hashlib.sha256(source_image).hexdigest()
    visible = (
        ("assembly.primary", "Complete deterministic ring assembly.", ("template",)),
        ("stone.center", "Deterministic center-stone group.", ("stone",)),
        ("setting.primary", "Deterministic primary setting.", ("setting",)),
        ("metal.body", "Deterministic visible metal body.", ("metal",)),
        ("band.shank", "Deterministic ring shank.", ("band",)),
        ("ring.size", "Designer-confirmed ring-size record.", ("ring_size",)),
    )
    base["source_component_coverage"] = {
        "source_kind": "imported_reference",
        "components": [
            {
                "component_id": component_id,
                "source_view": "unspecified",
                "source_description": description,
                "source_confidence": 1.0,
                "canonical_spec_paths": list(paths),
                "unresolved_reason": None,
                "independent_audit": {
                    "kind": "independent_component_audit",
                    "verdict": "pass",
                    "auditor": "facetta.deterministic-acceptance-source-audit.v1",
                    "source_view": "unspecified",
                    "observed_description": description,
                    "evidence_sha256": evidence_sha256,
                },
            }
            for component_id, description, paths in visible
        ],
    }
    validated = validate_spec(Spec.model_validate(base), get_vocabulary())
    if not validated.ok:  # pragma: no cover - disposable fixture invariant
        raise RuntimeError("structural acceptance spec is invalid")
    base["source_component_coverage"]["audited_spec_visual_hash"] = (
        spec_visual_hash(validated.spec)
    )
    final = validate_spec(Spec.model_validate(base), get_vocabulary())
    if not final.ok:  # pragma: no cover - disposable fixture invariant
        raise RuntimeError("structural acceptance spec lost validation")
    return final.spec.model_dump(mode="json", exclude_none=True)


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
    mask: bytes | None = None,
):
    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=image)

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="acceptance_fixture_quality",
                    passed=True,
                    severity=CheckSeverity.HARD,
                    message="Acceptance fixture candidate passed.",
                ),),
                score=98,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(
        plan,
        source_image=source,
        quality_source_image=quality_source,
        mask_bytes=mask,
    )


class _OfflineCatalogAgent:
    """Deterministic paid-provider substitute behind the production route."""

    def run(
        self,
        plan,
        *,
        source_image: bytes | None = None,
        mask_bytes: bytes | None = None,
        **_kwargs,
    ):
        if source_image is None or mask_bytes is None:
            raise AssertionError("catalog acceptance requires exact source and mask")
        source = Image.open(io.BytesIO(source_image)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
        if mask.size != source.size:
            raise AssertionError("catalog acceptance mask changed raster size")
        child = source.copy()
        child.paste((55, 205, 205), (0, 0, *source.size), mask)
        output = io.BytesIO()
        child.save(output, format="PNG")
        return _accepted_result(
            plan,
            output.getvalue(),
            source=source_image,
            mask=mask_bytes,
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
    image = (
        _semantic_ring_png()
        if prompt == STRUCTURAL_PRE_SPEC_PROMPT
        else _png(_fixture_color("prompt", prompt, variant))
    )
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
    image = (
        source
        if instruction.startswith("Warm the yellow-gold appearance")
        else _png(_fixture_color(
            "visual-preview", source, instruction, scope, mask or b"", variant,
        ))
    )
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
            "accepted_image_reviews": db.scalar(select(func.count()).select_from(
                ImageRunReview).where(
                    ImageRunReview.created_by == owner,
                    ImageRunReview.decision == "accepted",
                    ImageRunReview.accepted_asset_id.is_not(None),
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


def _acceptance_design_reader(request: PhotoRequest) -> Spec:
    """Read deterministic facts only for the disposable structural fixture."""

    image = base64.b64decode(request.image_base64, validate=True)
    return Spec.model_validate(_confirmed_ring_spec(image))


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
projects_api.from_photo = _acceptance_design_reader

# Exercise the production catalog plan, persistence, candidate, job, and Apply
# paths while keeping this disposable harness offline. The evidence hash
# attests only this deterministic acceptance fixture; it is not an external
# frozen-corpus or founder/GIA calibration claim.
_acceptance_mapper = GrokRingComponentMapper(
    inspect_single=_semantic_observation,
    inspect_pair=_semantic_observation,
)
_acceptance_mapper_evidence = hashlib.sha256(json.dumps(
    _semantic_observation(),
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")).hexdigest()


def _configure_acceptance_structural_dependencies() -> None:
    catalog_component_targeting.configure_catalog_structural_component_mapper(
        _acceptance_mapper,
        mapper_contract=GROK_RING_COMPONENT_MAPPER_CONTRACT,
        calibration_evidence_sha256=_acceptance_mapper_evidence,
        supported_paths={"stone.cut"},
        readiness_probe=lambda: True,
    )
    catalog_api._trusted_image_agent = lambda: _OfflineCatalogAgent()


_production_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _acceptance_lifespan(application):
    # The production lifespan intentionally composes from environment and
    # starts fail-closed in this offline process. Install the deterministic
    # acceptance dependencies only after that production startup completes.
    async with _production_lifespan(application):
        _configure_acceptance_structural_dependencies()
        yield


app.router.lifespan_context = _acceptance_lifespan
