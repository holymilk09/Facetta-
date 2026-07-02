from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

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
