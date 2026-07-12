"""Deterministic, role-labeled boards for pre-spec creative references.

The image-agent's trusted creative seam deliberately accepts one raster source.
This module composes the untouched master geometry and any advisory references
into that one source without pretending the secondary images are specifications
or manufacturing evidence.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageDraw, ImageFont, ImageOps


CreativeReferenceRole = Literal[
    "material_style",
    "construction_detail",
    "brand_direction",
]

ROLE_ORDER: tuple[CreativeReferenceRole, ...] = (
    "material_style",
    "construction_detail",
    "brand_direction",
)

ROLE_TITLES: dict[str, str] = {
    "master_geometry": "MASTER GEOMETRY",
    "material_style": "MATERIAL & STYLE",
    "construction_detail": "CONSTRUCTION DETAIL",
    "brand_direction": "BRAND DIRECTION",
}


@dataclass(frozen=True)
class CreativeReferenceImage:
    role: CreativeReferenceRole
    image: bytes
    media_type: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.image).hexdigest()


@dataclass(frozen=True)
class CreativeReferenceBoard:
    image: bytes
    instruction: str
    references: tuple[CreativeReferenceImage, ...]


def _decoded_image(raw: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            if opened.width * opened.height > 25_000_000:
                raise ValueError(
                    "creative reference images must not exceed 25 megapixels")
            return ImageOps.exif_transpose(opened).convert("RGB")
    except Image.DecompressionBombError as exc:
        raise ValueError("creative reference image dimensions are unsafe") from exc


def _fit_tile(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    contained = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
    tile = Image.new("RGB", size, "white")
    tile.paste(
        contained,
        ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2),
    )
    return tile


def _role_contract(
    role: str,
    image_number: int,
    sha256: str,
) -> str:
    prefix = f"IMAGE {image_number} — {ROLE_TITLES[role]} — SHA-256 {sha256}:"
    if role == "master_geometry":
        return (
            f"{prefix} the sole authority for the jewelry's identity, silhouette, "
            "component count, placement, and proportions. Preserve its geometry."
        )
    if role == "material_style":
        return (
            f"{prefix} surface-only guidance for material response, visible color, "
            "finish, and rendering style. Never copy its jewelry geometry, stones, "
            "settings, motifs, or component arrangement."
        )
    if role == "construction_detail":
        return (
            f"{prefix} visual guidance for the requested clasp, setting, joint, or "
            "detail only. It is not a confirmed construction fact, measurement, CAD "
            "model, or proof of manufacturability; do not infer hidden geometry."
        )
    return (
        f"{prefix} visual-language guidance for mood, composition, and presentation "
        "only. Never copy branding, logos, text, product geometry, stones, settings, "
        "or motifs."
    )


def build_creative_reference_board(
    master_geometry: bytes,
    references: tuple[CreativeReferenceImage, ...],
) -> CreativeReferenceBoard:
    """Return a stable 2x2 PNG board and its exact role-handling contract."""
    by_role = {reference.role: reference for reference in references}
    if len(by_role) != len(references):
        raise ValueError("creative reference roles must be unique")
    ordered = tuple(by_role[role] for role in ROLE_ORDER if role in by_role)
    if len(ordered) > 3:
        raise ValueError("at most three secondary creative references are allowed")

    entries: list[tuple[str, bytes, str]] = [(
        "master_geometry",
        master_geometry,
        hashlib.sha256(master_geometry).hexdigest(),
    )]
    entries.extend((item.role, item.image, item.sha256) for item in ordered)

    width, height = 1600, 1600
    gutter = 24
    outer = 32
    header = 92
    tile_width = (width - 2 * outer - gutter) // 2
    tile_height = (height - 2 * outer - gutter) // 2
    board = Image.new("RGB", (width, height), "#ececf1")
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default()

    for index, (role, raw, sha256) in enumerate(entries):
        column = index % 2
        row = index // 2
        left = outer + column * (tile_width + gutter)
        top = outer + row * (tile_height + gutter)
        draw.rectangle(
            (left, top, left + tile_width, top + tile_height),
            fill="white",
            outline="#22242a",
            width=3,
        )
        draw.rectangle(
            (left, top, left + tile_width, top + header),
            fill="#22242a",
        )
        label = f"IMAGE {index + 1}  |  {ROLE_TITLES[role]}"
        draw.text((left + 22, top + 20), label, fill="white", font=font)
        draw.text(
            (left + 22, top + 52),
            f"SHA-256 {sha256}",
            fill="#c8cad2",
            font=font,
        )
        image_area = (tile_width - 44, tile_height - header - 44)
        fitted = _fit_tile(_decoded_image(raw), image_area)
        board.paste(fitted, (left + 22, top + header + 22))

    output = io.BytesIO()
    board.save(output, format="PNG", optimize=False, compress_level=9)
    role_contracts = [
        _role_contract(role, index + 1, sha256)
        for index, (role, _raw, sha256) in enumerate(entries)
    ]
    instruction = (
        "ROLE-LABELED REFERENCE BOARD. Treat each panel only according to its "
        "declared role. The master is the sole geometry authority; secondary "
        "references are advisory and never establish dimensions, hidden structure, "
        "material identity, or production readiness.\n- "
        + "\n- ".join(role_contracts)
    )
    return CreativeReferenceBoard(
        image=output.getvalue(),
        instruction=instruction,
        references=ordered,
    )
