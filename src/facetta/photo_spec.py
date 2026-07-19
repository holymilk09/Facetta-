"""Imported jewelry photograph -> designer-reviewable draft specification.

A configured vision service performs only the visual read. Facetta's
deterministic completion and validation layers remain responsible for
converting that sparse read into physically consistent draft dimensions.
Nothing from this module is persisted until the designer confirms the
resulting specification.
"""

from __future__ import annotations

import base64
import binascii
from facetta.concept import complete_design, read_design
from facetta.dimension_provenance import with_reference_dimension_estimates
from facetta.render import RenderUnavailable
from facetta.source_component_seed import seed_imported_reference_coverage
from facetta.spec import Spec


class PhotoSpecInvalid(ValueError):
    """The supplied reference is not valid base64 image content."""


class PhotoSpecUnavailable(RuntimeError):
    """No configured vision reader could safely read the reference."""


def generate_spec_from_photo(
    image_base64: str,
    media_type: str,
    notes: str = "",
) -> Spec:
    """Read one reference image and return a physically consistent draft spec.

    ``media_type`` is accepted as part of the public request contract; provider
    input labeling is derived from image magic bytes in ``read_design`` so a
    mislabeled upload cannot silently change how the image is interpreted.
    """
    del media_type
    try:
        image = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PhotoSpecInvalid("image_base64 is not valid base64") from exc
    if not image:
        raise PhotoSpecInvalid("image_base64 decodes to an empty image")

    context = (
        "Imported finished-jewelry reference. Return only visible facts. "
        "Exact dimensions remain designer-confirmed. Designer notes: "
        f"{notes.strip() or 'none'}"
    )
    try:
        visual_read = read_design(image, context)
        spec, _corrections = complete_design(visual_read, context)
    except RenderUnavailable as exc:
        # Provider names and credential details are internal configuration,
        # not designer-facing recovery instructions. Preserve the original
        # exception as chained diagnostic evidence while returning one stable
        # fail-closed public contract.
        raise PhotoSpecUnavailable(
            "reference understanding is temporarily unavailable; try again"
        ) from exc
    draft = with_reference_dimension_estimates(
        spec,
        source="imported finished-jewelry reference",
        method="reference_vision",
        confidence=0.45,
    )
    return draft.model_copy(update={
        "source_component_coverage": seed_imported_reference_coverage(draft),
    })
