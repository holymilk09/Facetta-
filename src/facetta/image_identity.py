"""Provider-neutral content identities for visual specification work."""

from __future__ import annotations

import hashlib
import json

from facetta.spec import Spec


_NONVISUAL_SPEC_FIELDS = {
    "design_id",
    "version",
    "created_by",
    "created_at",
    "schema_version",
    "mode",
    "notes_to_factory",
    "dimension_provenance",
    "source_component_coverage",
}


def spec_visual_hash(spec: Spec) -> str:
    """Fingerprint every specification fact that can affect the image."""
    data = {
        key: value
        for key, value in spec.model_dump(mode="json").items()
        if key not in _NONVISUAL_SPEC_FIELDS
    }
    # A design-form reference pins provenance to immutable asset bytes, but
    # those storage identifiers are not instructions for how the jewelry must
    # look.  Keeping them out of the visual fingerprint lets a plan reserve its
    # output identity before the provider call and bind the final SHA afterward
    # without changing the plan/cache identity.  Description, symmetry, count,
    # and normalized regions remain fingerprinted.
    design_form = data.get("design_form")
    if isinstance(design_form, dict):
        elements = design_form.get("elements")
        if isinstance(elements, list):
            for element in elements:
                if not isinstance(element, dict):
                    continue
                definition = element.get("definition")
                if isinstance(definition, dict):
                    if definition.get("kind") == "dimensioned_profile":
                        # Unlike a pinned raster identity, confirmed profile
                        # coordinates and thickness change the actual custom
                        # form. They must invalidate image-agent cache and
                        # audit evidence. Actor/time/source identifiers and
                        # manufacturing prose remain non-visual provenance.
                        element["definition"] = {
                            key: definition.get(key)
                            for key in (
                                "kind",
                                "scope",
                                "view",
                                "coordinate_system",
                                "paths",
                                "profile_thickness_mm",
                            )
                        }
                    else:
                        element["definition"] = {
                            "kind": definition.get("kind"),
                        }
    chain = data.get("chain")
    if isinstance(chain, dict):
        # Supplier SKUs, approved-sample IDs, and CAD references establish
        # manufacturing provenance but cannot change visible pixels.
        chain.pop("production", None)
    encoded = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]
