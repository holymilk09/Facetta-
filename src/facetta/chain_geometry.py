"""Factory-readiness rules for necklace carrier chains.

Historical specs named a chain style, length, and clasp.  That is enough to
find or visualize a chain, but not enough to buy the same stock item or build
the same custom chain.  The schema remains additive so those records can still
be opened; this module prevents them from being described as factory-ready.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from facetta.spec import Spec


class ChainFactoryBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field_path: str
    message: str
    required_resolution: str


def chain_factory_blockers(spec: Spec) -> tuple[ChainFactoryBlocker, ...]:
    """Return explicit blockers without making legacy JSON unreadable."""
    if spec.chain is None:
        return ()

    blockers: list[ChainFactoryBlocker] = []
    if spec.chain.geometry is None:
        blockers.append(ChainFactoryBlocker(
            code="chain_geometry_missing",
            field_path="chain.geometry",
            message=(
                "The chain records style, length, and clasp but no physical "
                "width/profile or construction-specific dimensions. It is a "
                "visual/procurement description, not a fabrication record."
            ),
            required_resolution=(
                "Enter measured or explicitly estimated chain geometry for "
                "the selected construction family."
            ),
        ))
    if spec.chain.production is None:
        blockers.append(ChainFactoryBlocker(
            code="chain_production_reference_missing",
            field_path="chain.production",
            message=(
                "The exact stock item, approved sample, dimensioned drawing, "
                "or CAD construction record for the chain is not identified."
            ),
            required_resolution=(
                "Choose stock or custom production and attach its authoritative "
                "supplier/sample/drawing/CAD reference."
            ),
        ))
    if spec.chain.pendant_connection is None:
        blockers.append(ChainFactoryBlocker(
            code="chain_pendant_connection_missing",
            field_path="chain.pendant_connection",
            message=(
                "The specification does not say whether the chain slides "
                "through the bail, is fixed to the bail, or is split around "
                "the pendant. Bail-clearance assumptions would be unsafe."
            ),
            required_resolution=(
                "Confirm slides_through_bail, fixed_to_bail, or split_chain."
            ),
        ))
    return tuple(blockers)
