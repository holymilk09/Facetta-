"""The house style set: the designer's approved renders, used as style
anchors so every generated image converges on the house's visual language
instead of the engine's generic output.

The set is DATA — image files in data/style_refs/ — curated by the designer
(bootstrapped from the strongest early renders). Code only loads and hashes;
it never draws. The style reference rides as a second input image on the
multi-image edit route with a strict style-only rule (render.STYLE_REF_RULE):
style, lighting and finish come from the reference, the DESIGN never does.
"""

from __future__ import annotations

import os
from pathlib import Path

STYLE_DIR = Path(os.environ.get(
    "FACETTA_STYLE_REFS",
    Path(__file__).resolve().parents[2] / "data" / "style_refs"))

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def list_style_refs() -> list[Path]:
    """The curated set, stable order (name-sorted)."""
    if not STYLE_DIR.is_dir():
        return []
    return sorted(p for p in STYLE_DIR.iterdir()
                  if p.suffix.lower() in _IMAGE_SUFFIXES)


def default_style_ref() -> bytes | None:
    """The first image of the curated set — the house anchor used when a
    request asks for house style without naming a specific reference.
    None when the set is empty (callers fail loudly, never silently skip)."""
    refs = list_style_refs()
    return refs[0].read_bytes() if refs else None
