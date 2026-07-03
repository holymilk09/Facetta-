from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from facetta import prose as prose_layer
from facetta.db import utcnow
from facetta.mockup import SceneUnsupported, compile_render_request
from facetta.prototype import compile_render_prompt, render_color_preview
from facetta.spec import Spec
from facetta.svg_sheet import SheetUnsupported, render_sheet, render_stack_sheet
from facetta.validation import nesting_clearance, validate_spec
from facetta.vocabulary import get_vocabulary

router = APIRouter(prefix="/specs", tags=["specs"])


@router.post("/validate")
def validate(spec: Spec):
    """Validate a spec against the vocabulary and the physical density model.

    Returns the validated spec (ring inner diameter auto-derived when absent),
    or a structured 422 listing every failed rule with its valid options or
    computed expected values.
    """
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    return result.spec


@router.post("/sheet.svg")
def sheet_preview(spec: Spec):
    """Stateless sheet preview: validate the spec, then render it. The saved,
    versioned sheet lives under /designs/{id}/versions/{v}/sheet.svg."""
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        svg = render_sheet(result.spec)
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/prototype.svg")
def prototype_preview(spec: Spec):
    """Deterministic colored prototype: vocabulary hues and metal tones over
    the exact sheet geometry."""
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        svg = render_color_preview(result.spec)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/render-prompt")
def render_prompt(spec: Spec):
    """Compile the photoreal-render prompt for an external image model. The
    prompt carries the numbers; a control image carries the geometry."""
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    return compile_render_prompt(result.spec)


class RenderRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    lighting: str = "studio"
    worn_on: str = "product"


@router.post("/render-request")
def render_request(body: RenderRequestBody):
    """Scene-controlled, geometry-locked mockup request: the same design renders
    the same composition every time — edit one spec parameter and only that
    parameter moves. Feed the payload to any ControlNet-capable image provider."""
    result = validate_spec(body.spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        return compile_render_request(result.spec, body.lighting, body.worn_on)
    except SceneUnsupported as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "valid_options": exc.valid},
        )


class StackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_a: Spec
    spec_b: Spec


@router.post("/stack.svg")
def stack_preview(request: StackRequest):
    """Overlay two pieces on one sheet with their nesting clearance.

    Two bangles/cuffs nest (per-axis clearance); two rings stack on the finger
    (combined stack height). A pair that cannot nest is rejected with the
    negative clearance numbers.
    """
    validated = []
    for label, spec in (("spec_a", request.spec_a), ("spec_b", request.spec_b)):
        result = validate_spec(spec, get_vocabulary())
        if not result.ok:
            return JSONResponse(
                status_code=422,
                content={"detail": [{**i.as_detail(), "piece": label} for i in result.issues]},
            )
        validated.append(result.spec)
    spec_a, spec_b = validated
    try:
        clearance = nesting_clearance(spec_a, spec_b)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    if not clearance.nests:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "these pieces do not nest — negative clearance",
                "clearance": clearance.as_dict(),
            },
        )
    svg = render_stack_sheet(spec_a, spec_b, clearance)
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"X-Nesting-Clearance": str(clearance.as_dict())})


class ProseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prose: Annotated[str, Field(min_length=1, max_length=8000)]
    created_by: str = "usr_pending"


@router.post("/from-prose")
def from_prose(request: ProseRequest):
    """Translate designer prose into a validated spec via the Claude API.

    The model only maps language onto the controlled vocabulary; the result is
    re-validated with the same rules as hand-built specs, so invalid model
    output never reaches the DB — the designer receives the validated spec and
    saves it via POST /designs like any other.
    """
    try:
        spec = prose_layer.generate_spec(request.prose)
    except prose_layer.ProseUnavailable as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    spec = spec.model_copy(update={
        "created_by": request.created_by,
        "created_at": utcnow(),
        "version": 1,
    })
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=502,
            content={
                "detail": "model output failed spec validation; please retry or adjust the prose",
                "issues": [issue.as_detail() for issue in result.issues],
            },
        )
    return result.spec
