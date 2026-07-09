from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from facetta.db import get_db

from facetta import prose as prose_layer
from facetta.db import utcnow
from facetta.disclaimer import stamp_b64
from facetta.drawing_frame import frame_technical_drawing
from facetta.dxf import svg_to_dxf
from facetta.mockup import (
    SceneUnsupported, compile_artwork_restyle_request, compile_finish_request,
    compile_render_request, compile_restage_request,
)
from facetta.overlay import OverlayUnsupported, render_annotated_artwork
from facetta.plate import render_control_image, render_presentation_plate
from facetta.render import (
    RenderUnavailable, _sniff_media_type, generate_image,
    render_finished_image, render_from_spec, restyle_artwork,
)
from facetta.prototype import compile_render_prompt, render_color_preview
from facetta.spec import Spec
from facetta.specagent import (
    compile_render_instruction, generate_spec_sheet, infer_capability,
    localized_edit,
)
from facetta.svg_sheet import (
    Branding, SheetUnsupported, render_sheet, render_stack_sheet,
    render_true_size_sheet,
)
from facetta.validation import nesting_clearance, validate_spec
from facetta.vocabulary import get_vocabulary

router = APIRouter(prefix="/specs", tags=["specs"])

DbSession = Annotated[Session, Depends(get_db)]


def _branding(house: str | None, signature: str | None) -> Branding | None:
    """A designer's studio mark for a sheet — presentation only, never the
    spec. None when neither field is given, so unbranded sheets are unchanged."""
    return Branding(house=house, signature=signature) if (house or signature) else None


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
def sheet_preview(spec: Spec, house: str | None = None,
                  signature: str | None = None):
    """Stateless sheet preview: validate the spec, then render it. The saved,
    versioned sheet lives under /designs/{id}/versions/{v}/sheet.svg.

    ?house= and ?signature= stamp the designer's studio name and signature in
    the title block for pieces sent to clients and factories under their own
    brand — presentation only; the dimensions are untouched."""
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        svg = render_sheet(result.spec, branding=_branding(house, signature))
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=2000)]
    history: list[dict] = Field(default_factory=list)
    name: str = "Atelier"          # the designer can rename their assistant


@router.post("/assist")
def assist_endpoint(request: AssistRequest):
    """The from-scratch design assistant. The designer describes a piece; the
    assistant asks grounded clarifying questions until it knows enough, then
    returns a compiled brief plus the chosen output mode (render / sheet / both).
    Feed that brief to /specs/from-concept to build the piece."""
    from facetta.assistant import Turn, assist

    try:
        history = [Turn.model_validate(t) for t in request.history]
    except Exception as exc:
        return JSONResponse(status_code=422, content={
            "detail": f"bad history: {exc}"})
    try:
        reply = assist(history, request.message, name=request.name)
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return reply.model_dump()


class ConceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: Annotated[str, Field(min_length=3, max_length=600)]
    model: str = "grok_direct"
    variant: int = 0  # >0 asks Grok for a fresh take instead of the cached concept


@router.post("/from-concept")
def from_concept(request: ConceptRequest):
    """Grok invents an entirely new design from the brief; the platform reads
    it, applies real millimetres and metal in the proper places, and returns a
    spec that PASSES every jewelry rule — plus the corrections it had to make.
    The factory pack (sheet, blueprint, client render) then comes from the
    existing endpoints on the returned spec."""
    import base64

    from facetta.concept import ConceptInvalid, originate_concept

    try:
        image, read, spec, corrections = originate_concept(
            request.brief, request.model, request.variant)
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    except ConceptInvalid as exc:
        return JSONResponse(status_code=422, content={
            "detail": [issue.as_detail() for issue in exc.issues],
            "corrections": exc.corrections,
            "note": "the generated concept could not be made physically real",
        })
    return {
        "concept_image_b64": stamp_b64(image),
        "media_type": _sniff_media_type(image),
        "read": read.model_dump(),
        "spec": spec.model_dump(mode="json"),
        "corrections": corrections,
    }


class AgentSheetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    notes: Annotated[str, Field(max_length=2000)] = ""
    mode: str | None = None                # None → the agent routes it
    region: str = "DUAL"
    spec: Spec | None = None               # validated → authoritative dims
    legibility: bool = False               # one extra text-repair pass
    facetta_template: bool = False         # official frame, lettered by code
    house: str | None = None               # branding for the official frame
    signature: str | None = None
    piece_name: Annotated[str, Field(max_length=48)] | None = None  # optional title
    # the ballpark designer's assist: with NO spec, Grok vision-reads the
    # render and code letters the panel as ESTIMATED (never painted text)
    assist_specs: bool = False
    variant: int = 0  # regenerate: force a fresh Grok drawing, not the cached one


@router.post("/technical-drawing")
@router.post("/agent-sheet")               # legacy alias, same handler
def technical_drawing(request: AgentSheetRequest):
    """The user-facing jewelry manufacturing technical drawing, drawn by the
    AGENT: Grok vision classifies and inspects the designer's render, then a
    controlled image-to-image edit turns it into black-line orthographic
    documentation. Deterministic code never draws this artifact — when a spec
    is supplied it is validated first and its numbers ride along in the
    prompt as designer-authoritative dimensions; everything else is TBD on
    the drawing.

    facetta_template=true is the official-template mode: the model is told to
    leave clean margins (no title block, no names, no dates) and the response
    carries framed_svg — the drawing wrapped in the Facetta frame, lettered
    by code from the validated spec and the ?house=/?signature= branding.
    (The parametric CAD/DXF sheet remains /specs/sheet.svg — a separate,
    explicit handoff.)"""
    import base64 as b64
    import binascii

    try:
        image_bytes = b64.b64decode(request.image_base64, validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=422,
                            content={"detail": "image_base64 is not valid base64"})

    validated = None
    if request.spec is not None:
        # the assistance numbers must be REAL — an invalid spec never
        # letters a factory sheet
        result = validate_spec(request.spec, get_vocabulary())
        if not result.ok:
            return JSONResponse(
                status_code=422,
                content={"detail": [issue.as_detail() for issue in result.issues]},
            )
        validated = result.spec

    try:
        sheet, summary, cached = generate_spec_sheet(
            image_bytes, notes=request.notes, mode=request.mode,
            region=request.region, spec=validated,
            legibility=request.legibility,
            templated=request.facetta_template, variant=request.variant)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    # the assist read: no record to letter the panel from, so Grok estimates
    # from the DESIGNER'S RENDER (not the drawing) and code letters it as
    # ESTIMATED. A validated spec always wins; assist is skipped then.
    estimates = None
    if (request.facetta_template and request.assist_specs
            and validated is None):
        from facetta.specagent import read_sheet_specs
        try:
            estimates = read_sheet_specs(image_bytes)
        except RenderUnavailable as exc:
            status = 503 if "_KEY" in str(exc) else 502
            return JSONResponse(status_code=status, content={"detail": str(exc)})

    framed_svg = None
    if request.facetta_template:
        framed_svg = frame_technical_drawing(
            sheet, spec=validated,
            branding=_branding(request.house, request.signature),
            piece_name=request.piece_name, estimates=estimates)
    return {
        "sheet_b64": b64.b64encode(sheet).decode(),
        "media_type": _sniff_media_type(sheet),
        # Section 5 rename: summary["mode"] is now the CAPABILITY; the
        # piece-type key the drawing was compiled from lives in piece_type —
        # which is what this response's "mode" field has always meant
        "mode": summary.get("piece_type"),
        "region": summary.get("region"),
        "summary": summary,
        "cached": cached,
        "framed_svg": framed_svg,
        # the same estimates prefill the designer's spec form — the on-ramp
        # from ballpark to a confirmed record
        "estimated_specs": estimates,
    }


class RenderModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    piece_description: Annotated[str, Field(min_length=3, max_length=600)]
    metal: str = ""
    stones: str = ""
    setting_details: str = ""
    view_angle: str = "three-quarter product view"
    variant: int = 0  # >0 asks for a genuinely fresh take, not the cached one


@router.post("/jewelry-render")
def jewelry_render_endpoint(request: RenderModeRequest):
    """MODE A — JEWELRY_RENDER: photorealistic product visualization from the
    Section 4A prompt body (presentation and design approval, never factory
    line art — that is /specs/technical-drawing). The compiled prompt rides
    back so the app can show exactly what was asked of the engine."""
    import base64 as b64

    prompt = compile_render_instruction(
        request.piece_description, metal=request.metal, stones=request.stones,
        setting_details=request.setting_details,
        view_angle=request.view_angle)
    try:
        image, _cached = generate_image(prompt, variant=request.variant)
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return {
        "image_b64": stamp_b64(image),
        "media_type": _sniff_media_type(image),
        "capability": "JEWELRY_RENDER",
        "prompt": prompt,
    }


class LocalizedEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    region_description: Annotated[str, Field(min_length=1, max_length=500)]
    change_instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    mask_base64: str | None = None      # white = edit, black = preserve
    kind: Literal["render", "technical"] = "render"


@router.post("/localized-edit")
def localized_edit_endpoint(request: LocalizedEditRequest):
    """MODE C — LOCALIZED_EDIT: apply the change ONLY inside the highlighted
    region, freeze everything outside it. The preservation contract rides in
    every edit prompt; with a mask the result is drift-checked and retried
    once with stronger preserve language when it moved outside the region."""
    import base64 as b64
    import binascii

    try:
        image_bytes = b64.b64decode(request.image_base64, validate=True)
        mask_bytes = (b64.b64decode(request.mask_base64, validate=True)
                      if request.mask_base64 else None)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=422,
                            content={"detail": "image payload is not valid base64"})
    try:
        result = localized_edit(
            image_bytes, region_description=request.region_description,
            change_instruction=request.change_instruction,
            mask_bytes=mask_bytes, kind=request.kind)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return {
        "image_b64": (stamp_b64(result["image"]) if request.kind == "render"
                      else b64.b64encode(result["image"]).decode()),
        "media_type": _sniff_media_type(result["image"]),
        "changed": result["changed"],
        "frozen": result["frozen"],
        "retried": result["retried"],
        "drift": result["drift"],
        "cached": result["cached"],
        "capability": "LOCALIZED_EDIT",
    }


class InferCapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=4000)]


@router.post("/infer-capability")
def infer_capability_endpoint(request: InferCapabilityRequest):
    """The app's router hook: Section 1's mode-inference rules over the
    user's message — localized-edit signals win, then technical-drawing,
    then render; the default journey starts at JEWELRY_RENDER."""
    return {"capability": infer_capability(request.text)}


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: Annotated[str, Field(min_length=3, max_length=600)]
    output: Literal["render", "sheet", "both"] = "both"
    model: str = "grok_direct"
    variant: int = 0
    include_cad_sheet: bool = False   # explicit CAD handoff: parametric sheet_svg
                                      # + render-matched sheet (legacy math module)
    blueprint: bool = False           # also paint the graphite blueprint twin
                                      # (explicit request, like the CAD handoff)
    house: str | None = None
    signature: str | None = None
    piece_name: Annotated[str, Field(max_length=48)] | None = None  # optional title
    persist: bool = False             # save as a design so it can be annotated/edited
    created_by: str = "usr_pending"


@router.post("/build")
def build(request: BuildRequest, db: DbSession):
    """One call, the whole piece: Grok invents the design, the validator makes
    it real, and we return the concept image, the validated spec, the
    manufacturing technical drawing, and a client render together — the
    assistant's `output` choice decides which visual layers come back. The
    user-facing jewelry manufacturing technical drawing (technical_drawing_b64)
    is drawn by the AGENT from the render with the validated spec's numbers
    injected as designer-authoritative dimensions; the agent draws it templated
    (clean margins, no invented names) and technical_drawing_framed_svg wraps it
    in the official Facetta frame, lettered by code from the record and the
    house/signature branding. Per the pack's Section H hard rule the agent
    pipeline never calls the legacy math spec module in the same transaction,
    so the parametric CAD/DXF artifacts (sheet_svg and the render-matched
    sheet_over_render_svg) are drawn only on the explicit
    include_cad_sheet=true request — a separate, explicit handoff. Concept
    failure is fatal (503/502) and an unbuildable concept is 422; a downstream
    drawing/render hiccup is a warning, not a failure, so the spec always
    ships. With persist=true the piece is saved as a design (v1) and its
    design_id returned, ready for surgical annotation edits."""
    import base64

    from facetta.concept import ConceptInvalid, originate_concept

    try:
        image, read, spec, corrections = originate_concept(
            request.brief, request.model, request.variant)
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    except ConceptInvalid as exc:
        return JSONResponse(status_code=422, content={
            "detail": [issue.as_detail() for issue in exc.issues],
            "corrections": exc.corrections,
            "note": "the generated concept could not be made physically real",
        })

    branding = _branding(request.house, request.signature)
    warnings: list[str] = []
    sheet_svg = sheet_over_render_svg = blueprint_svg = None
    client_render_b64 = render_media_type = None

    # the accurate render: built straight from the VALIDATED spec, so Grok stays
    # in the design's lane (exact families, cuts, mm, counts). This is the piece
    # the render-matched sheet draws and the client render shows.
    spec_render = None
    try:
        spec_render, _ = render_from_spec(spec, variant=request.variant)
    except RenderUnavailable as exc:
        warnings.append(f"spec render unavailable: {exc}")

    if request.output in ("render", "both") and spec_render is not None:
        client_render_b64 = stamp_b64(spec_render)
        render_media_type = "image/png"

    technical_drawing_b64 = manufacturing_summary = None
    technical_drawing_framed_svg = None
    if request.output in ("sheet", "both"):
        # the USER-FACING manufacturing technical drawing: the agent draws it
        # from the accurate render (or the concept image) with the validated
        # spec's numbers riding along as designer-authoritative dimensions —
        # templated, so the model leaves clean margins and the official
        # Facetta frame (code, from the record) letters all identity
        try:
            drawing, manufacturing_summary, _ = generate_spec_sheet(
                spec_render if spec_render is not None else image,
                spec=spec, region="DUAL", templated=True,
                variant=request.variant)
            technical_drawing_framed_svg = frame_technical_drawing(
                drawing, spec=spec, branding=branding,
                piece_name=request.piece_name)
            technical_drawing_b64 = base64.b64encode(drawing).decode()
        except (RenderUnavailable, ValueError, OSError) as exc:
            manufacturing_summary = technical_drawing_framed_svg = None
            warnings.append(f"agent spec sheet unavailable: {exc}")

    # the parametric CAD/DXF artifacts come from the LEGACY MATH spec module.
    # Section H hard rule: the agent pipeline (steps 4-6 above) never calls it
    # in the same transaction unless the designer EXPLICITLY asks for the CAD
    # handoff — so these are gated on include_cad_sheet, never on output alone.
    if request.include_cad_sheet:
        try:
            sheet_svg = render_sheet(spec, branding=branding)
        except SheetUnsupported as exc:
            warnings.append(f"factory sheet unavailable: {exc}")
        # the render-matched sheet: the accurate spec render IS the drawing (or
        # the concept image if the spec render was unavailable), code letters the
        # validated dimensions on it — so the sheet matches the render
        try:
            sheet_over_render_svg = render_annotated_artwork(
                spec, spec_render or image)
        except (OverlayUnsupported, ValueError, OSError) as exc:
            warnings.append(f"render-matched sheet unavailable: {exc}")
    if request.blueprint:
        from facetta.blueprint import render_blueprint_sheet
        try:
            blueprint_svg, _ = render_blueprint_sheet(spec, branding=branding)
        except (SheetUnsupported, RenderUnavailable) as exc:
            warnings.append(f"blueprint unavailable: {exc}")

    spec_out = spec.model_dump(mode="json")
    response: dict = {
        "brief": request.brief,
        "output": request.output,
        "concept_image_b64": stamp_b64(image),
        "media_type": _sniff_media_type(image),
        "read": read.model_dump(),
        "spec": spec_out,
        "corrections": corrections,
        "spec_render_b64": (stamp_b64(spec_render)
                            if spec_render is not None else None),
        "sheet_svg": sheet_svg,
        "technical_drawing_b64": technical_drawing_b64,
        "manufacturing_summary": manufacturing_summary,
        "technical_drawing_framed_svg": technical_drawing_framed_svg,
        "sheet_over_render_svg": sheet_over_render_svg,
        "blueprint_svg": blueprint_svg,
        "client_render_b64": client_render_b64,
        "render_media_type": render_media_type,
        "warnings": warnings,
    }

    if request.persist:
        from facetta.api.designs import _store_version
        from facetta.db import Design, new_id

        design = Design(id=new_id("dsn"), created_by=request.created_by,
                        collection=None)
        db.add(design)
        response["spec"] = _store_version(db, design, spec, 1, request.created_by)
        response["design_id"] = design.id
        response["version"] = 1

    return response


@router.post("/blueprint-sheet.svg")
def blueprint_sheet(spec: Spec, model: str = "grok_imagine",
                    house: str | None = None, signature: str | None = None):
    """The presentation twin of the technical sheet: an image model paints the
    views into a graphite blueprint, code letters every dimension on top. The
    crisp master stays at /sheet.svg. Rings only for now. ?house=/?signature=
    stamp the designer's studio mark (presentation only)."""
    from facetta.blueprint import render_blueprint_sheet

    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        svg, cached = render_blueprint_sheet(
            result.spec, model, branding=_branding(house, signature))
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"X-Render-Cache": "hit" if cached else "miss"})


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


@router.post("/render.png")
def render_png(body: FinishRequestBody, model: str = "flux_kontext"):
    """The one-button photoreal render: control image + finish instruction
    sent to the image provider, result cached by content — an unchanged
    design renders once, ever. ?model= picks the engine: flux_kontext or
    grok_imagine (fal key), or grok_direct (xAI key)."""
    result = validate_spec(body.spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        png, cached = render_finished_image(result.spec, body.style,
                                            body.lighting, model)
    except SceneUnsupported as exc:
        return JSONResponse(status_code=422,
                            content={"detail": str(exc), "valid_options": exc.valid})
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    from facetta.disclaimer import stamp_image
    return Response(content=stamp_image(png), media_type="image/png",
                    headers={"X-Render-Cache": "hit" if cached else "miss"})


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


class ArtworkRestyleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    media_type: Annotated[str, Field(pattern=r"^image/(jpeg|png|webp)$")] = "image/jpeg"
    style: str = "rendered_color"


@router.post("/artwork-restyle.png")
def artwork_restyle(body: ArtworkRestyleBody, model: str = "grok_imagine"):
    """Restyle the designer's artwork page IN PLACE — rendered color or ink
    line art. The page IS the composition: nothing is added, removed, moved,
    or lettered. Numbers belong to /specs/annotated-artwork.svg, where code
    draws them from the validated spec."""
    import binascii

    try:
        image_bytes = __import__("base64").b64decode(body.image_base64,
                                                     validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=422,
                            content={"detail": "image_base64 is not valid base64"})
    try:
        image, cached = restyle_artwork(image_bytes, body.media_type,
                                        body.style, model)
    except SceneUnsupported as exc:
        return JSONResponse(status_code=422,
                            content={"detail": str(exc), "valid_options": exc.valid})
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return Response(content=image, media_type=_sniff_media_type(image),
                    headers={"X-Render-Cache": "hit" if cached else "miss"})


@router.post("/artwork-restyle-request")
def artwork_restyle_request(style: str = "rendered_color"):
    """The compiled restyle instruction — for callers driving an engine
    themselves. Restyle-in-place, no re-composition, zero lettering."""
    try:
        return compile_artwork_restyle_request(style)
    except SceneUnsupported as exc:
        return JSONResponse(status_code=422,
                            content={"detail": str(exc), "valid_options": exc.valid})


class AnnotatedArtworkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    anchor_image_base64: Annotated[str, Field(max_length=14_000_000)] = ""


@router.post("/annotated-artwork.svg")
def annotated_artwork(body: AnnotatedArtworkBody):
    """The artwork (or its in-place restyle) lettered by CODE: schedule
    letters, cluster callouts, dimensions and tolerances all from the
    validated spec — image models letter fiction, so they never letter here.
    anchor_image_base64 carries the ORIGINAL artwork when the display image
    cannot be traced (ink line art has no colored stones)."""
    import base64 as b64
    import binascii

    result = validate_spec(body.spec, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    try:
        image_bytes = b64.b64decode(body.image_base64, validate=True)
        anchor = (b64.b64decode(body.anchor_image_base64, validate=True)
                  if body.anchor_image_base64 else None)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=422,
                            content={"detail": "image payload is not valid base64"})
    try:
        svg = render_annotated_artwork(result.spec, image_bytes, anchor)
    except (OverlayUnsupported, ValueError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


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
