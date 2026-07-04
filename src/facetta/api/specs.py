from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from facetta import prose as prose_layer
from facetta.db import utcnow
from facetta.dxf import svg_to_dxf
from facetta.mockup import (
    SceneUnsupported, compile_finish_request, compile_render_request,
    compile_restage_request,
)
from facetta.plate import render_control_image, render_presentation_plate
from facetta.prototype import compile_render_prompt, render_color_preview
from facetta.spec import Spec
from facetta.svg_sheet import (
    SheetUnsupported, render_sheet, render_stack_sheet, render_true_size_sheet,
)
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


@router.post("/true-size.svg")
def true_size_preview(spec: Spec, instructions: bool = True):
    """The 1:1 overlay page: outlines at exact physical size for printing at
    100% and laying the finished piece on the paper. The sheet carries a
    100 mm calibration rule so the designer can verify the print scale.
    ?instructions=false renders outlines and rule only — a clean page for
    photographing the piece on the printout."""
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        svg = render_true_size_sheet(result.spec, instructions=instructions)
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


@router.post("/plate.svg")
def plate_preview(spec: Spec, paper: str = "ivory"):
    """The presentation plate: atelier-sketch styling over the engine's exact
    geometry — station counts and measurements are always true because code
    draws them; only the aesthetic is hand-drawn. ?paper= picks the rendering
    ground: ivory, white, grey (the gouache tradition), midnight, black, blush."""
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        svg = render_presentation_plate(result.spec, paper=paper)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/control-image.svg")
def control_image(spec: Spec):
    """The geometry scaffold for image-model finishing: exact positions and
    hardware, zero lettering. Rasterize it and send it as the edit input
    with the /specs/finish-request instruction."""
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        svg = render_control_image(result.spec)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


class FinishRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    style: str = "photo"  # "photo" | "atelier_sketch"
    lighting: str = "studio"


@router.post("/finish-request")
def finish_request(body: FinishRequestBody):
    """The instruction that pairs with the control image: the image model
    paints realism over our exact geometry — trace, don't redesign."""
    result = validate_spec(body.spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        return compile_finish_request(result.spec, body.style, body.lighting)
    except SceneUnsupported as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "valid_options": exc.valid},
        )


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
    style: str = "photo"  # "photo" | "atelier_sketch"


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
        return compile_render_request(result.spec, body.lighting, body.worn_on,
                                      body.style)
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


class PhotoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    media_type: Annotated[str, Field(pattern=r"^image/(jpeg|png|webp)$")] = "image/jpeg"
    notes: Annotated[str, Field(max_length=2000)] = ""
    created_by: str = "usr_pending"


@router.post("/from-photo")
def from_photo(request: PhotoRequest):
    """Reverse-engineer a photograph of a finished piece into a DRAFT spec.

    Vision proposes the parameters; a photo can never give exact millimeters,
    so the designer reviews and corrects dimensions in the builder before
    saving. The same validation gate applies as everywhere else.
    """
    try:
        spec = prose_layer.generate_spec_from_photo(
            request.image_base64, request.media_type, request.notes)
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
                "detail": "vision output failed spec validation; add notes with "
                          "measurements or adjust the draft by hand",
                "issues": [issue.as_detail() for issue in result.issues],
            },
        )
    return result.spec


class RestageRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jewelry_type: str = "ring"
    lighting: str = "studio"
    worn_on: str = "product"


@router.post("/restage-request")
def restage_request(body: RestageRequestBody):
    """Scene instruction for re-staging a PHOTO of a finished piece — the
    uploaded photograph is the geometry; only the scene changes."""
    try:
        return compile_restage_request(body.jewelry_type, body.lighting,
                                       body.worn_on)
    except SceneUnsupported as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "valid_options": exc.valid},
        )


@router.post("/sheet.dxf")
def sheet_dxf(spec: Spec):
    """The technical sheet as a DXF R12 drawing — the 2D underlay format
    jewelry CAD packages (Rhino, MatrixGold) import natively."""
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
    return Response(
        content=svg_to_dxf(svg), media_type="application/dxf",
        headers={"Content-Disposition":
                 f'attachment; filename="{result.spec.design_id}_v{result.spec.version}.dxf"'})
