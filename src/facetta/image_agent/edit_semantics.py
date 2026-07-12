"""Deterministic taxonomy for the designer changes the image agent executes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from facetta.image_agent.contracts import DesignerEditDomain
from facetta.json_types import JsonValue


_ORDER = tuple(DesignerEditDomain)


def classify_spec_delta(
    changes: Iterable[Mapping[str, JsonValue]],
) -> tuple[DesignerEditDomain, ...]:
    """Map structural spec paths to stable, observable edit families.

    This classification does not guess from prose. It derives only from the
    validated source-to-result spec delta, so routing, prompt compilation, and
    QA all describe the same accepted change.
    """

    materialized = tuple(changes)
    found: set[DesignerEditDomain] = set()
    side_inventory_lifecycle = any(
        isinstance(change.get("path"), str)
        and str(change["path"]).lower().startswith("side_stones")
        and change.get("kind") in {"added", "removed"}
        for change in materialized
    )
    for change in materialized:
        path_value = change.get("path")
        if not isinstance(path_value, str):
            continue
        path = path_value.lower()
        kind = change.get("kind")

        if path == "stone.cut" or path.startswith("stone.cut."):
            found.add(DesignerEditDomain.CENTER_STONE_SHAPE)
        elif path == "stone.species" or path.startswith("stone.phenomena"):
            found.add(DesignerEditDomain.CENTER_STONE_IDENTITY)
        elif path.startswith("stone.color"):
            found.add(DesignerEditDomain.CENTER_STONE_COLOR)

        if path.startswith("side_stones"):
            if (kind in {"added", "removed"} or path.endswith(".count")
                    or path.endswith(".position")):
                found.add(DesignerEditDomain.SIDE_STONE_INVENTORY)
            # A complete group lifecycle owns its new/removed cut and identity
            # facts as one atomic inventory operation. Shape/identity domains
            # are for mutating an already-present repeated group.
            if kind not in {"added", "removed"} and path.endswith(".cut"):
                found.add(DesignerEditDomain.SIDE_STONE_SHAPE)
            if (kind not in {"added", "removed"}
                    and (path.endswith(".species") or ".color." in path
                         or path.endswith(".color"))):
                found.add(DesignerEditDomain.SIDE_STONE_IDENTITY)

        if path.startswith("setting"):
            found.add(DesignerEditDomain.SETTING)
        elif path.startswith("metal.finish"):
            found.add(DesignerEditDomain.METAL_FINISH)
        elif path.startswith("metal"):
            found.add(DesignerEditDomain.METAL_IDENTITY)
        elif path.startswith("band"):
            found.add(DesignerEditDomain.BAND_GEOMETRY)
        elif path.startswith("ring_size"):
            found.add(DesignerEditDomain.RING_SIZE)
        elif path == "chain.style" or path.startswith("chain.geometry"):
            found.add(DesignerEditDomain.CHAIN_STYLE)
        elif (path == "template" and side_inventory_lifecycle):
            # Solitaire <-> halo template transitions are the structural
            # consequence of the exact inventory lifecycle, not a second
            # free-form design operation.
            pass
        elif (path in {"template", "jewelry_type"}
              or path.startswith("design_form")):
            found.add(DesignerEditDomain.DESIGN_FORM)

    return tuple(domain for domain in _ORDER if domain in found)
