from fastapi import APIRouter
from fastapi.responses import JSONResponse

from facetta.spec import Spec
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
