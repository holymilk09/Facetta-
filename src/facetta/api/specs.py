from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from facetta import prose as prose_layer
from facetta.db import utcnow
from facetta.spec import Spec
from facetta.svg_sheet import SheetUnsupported, render_sheet
from facetta.validation import validate_spec
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
