"""Consistent photoreal mockups: spec + scene -> a provider-ready render request.

Chat image-gen gets ~75% of the way and then drifts: ask twice and you get two
different rings. This layer pins the design down with three locks, so the same
design renders the same way over and over, and a single-parameter edit changes
only that parameter:

1. **Control image** — the deterministic prototype/sheet SVG carries the exact
   geometry into a ControlNet channel; the model cannot reinvent proportions.
2. **Seed** — derived from the spec's GEOMETRY ONLY. Swap blue sapphire for
   yellow sapphire, or yellow gold for white, and the seed (and control image
   outline) are identical, so the composition holds; change a dimension and it
   reseeds, because it is a different piece.
3. **Prompt** — compiled from the spec's numbers plus a controlled scene
   vocabulary (lighting, worn-on). No free text reaches the image model.
"""

from __future__ import annotations

import hashlib
import json

from facetta.prototype import prompt_core
from facetta.spec import Spec

LIGHTING = {
    "studio": "macro jewelry photography, softbox studio lighting, neutral seamless background",
    "natural": "soft natural window light, shallow depth of field, warm neutral surface",
    "outdoor": "golden-hour outdoor daylight, softly blurred garden background",
    "editorial": "dramatic single-source editorial lighting, deep charcoal backdrop",
}

# atelier sketch: the hand-drawn presentation style high-jewelry houses show
# clients — distilled from reference boards (colored pencil on ivory paper,
# several views per page, hatched drop shadows, faint construction lines)
STYLES = {
    "photo": None,  # photoreal, composed from the lighting/worn-on scene
    "atelier_sketch": (
        "hand-drawn atelier jewelry design sketch, colored pencil and graphite "
        "on warm ivory sketchbook paper, presented in three views on one page "
        "(face-on, three-quarter, and profile), faint construction lines, "
        "hatched graphite drop shadow under each view, gouache-like highlights "
        "on the stones, refined couture presentation"
    ),
}

WORN_ON = {
    "product": None,  # product-only hero shot, no model
    "finger": ("worn on a model's ring finger, elegant natural hand, "
               "manicured, macro focus on the ring"),
    "neck": ("worn at the collarbone of a model, focus on the pendant, "
             "soft skin tones, chain draping naturally"),
    "wrist": ("worn on a model's wrist, relaxed pose, "
              "focus on the bracelet"),
}

# which worn-on placements make sense for each jewelry type — anything else is
# rejected loudly so an impossible scene never reaches the image model
WORN_FOR_TYPE = {
    "ring": ("product", "finger"),
    "bracelet": ("product", "wrist"),
    "pendant": ("product", "neck"),
    "necklace": ("product", "neck"),
    "loose_stone": ("product",),
}


class SceneUnsupported(ValueError):
    def __init__(self, msg: str, valid: list[str]):
        super().__init__(msg)
        self.valid = valid


def geometry_fingerprint(spec: Spec) -> str:
    """Canonical hash of the spec's shape — everything that affects WHERE metal
    and stones sit, nothing that only affects what they look like (species,
    color, clarity, metal, finish are all excluded on purpose)."""

    def stone_geo(stone) -> dict:
        d = stone.dimensions_mm
        return {"cut": stone.cut, "mm": [d.length, d.width, d.depth],
                "count": stone.count, "position": stone.position}

    geo: dict = {
        "template": spec.template,
        "stone": stone_geo(spec.stone),
        "side_stones": [stone_geo(s) for s in spec.side_stones],
    }
    if spec.setting:
        geo["setting"] = [spec.setting.style, spec.setting.prong_count,
                          spec.setting.gallery_height_mm]
    if spec.band:
        geo["band"] = [spec.band.profile, spec.band.width_mm, spec.band.thickness_mm]
    if spec.ring_size:
        geo["ring"] = spec.ring_size.inner_diameter_mm
    if spec.bracelet:
        b = spec.bracelet
        geo["bracelet"] = [b.inner_length_mm, b.inner_width_mm, b.width_mm,
                           b.thickness_mm, b.gap_width_mm, b.link_count]
    if spec.pendant:
        geo["pendant"] = [spec.pendant.bail_inner_diameter_mm, spec.pendant.bail_height_mm]
    if spec.chain:
        geo["chain"] = [spec.chain.style, spec.chain.length_mm, spec.chain.clasp]
    return hashlib.sha256(json.dumps(geo, sort_keys=True).encode()).hexdigest()


def compile_render_request(spec: Spec, lighting: str = "studio",
                           worn_on: str = "product",
                           style: str = "photo") -> dict:
    """Everything an image provider needs to render this design consistently."""
    if style not in STYLES:
        raise SceneUnsupported(f"unknown style '{style}'", sorted(STYLES))
    if lighting not in LIGHTING:
        raise SceneUnsupported(f"unknown lighting '{lighting}'", sorted(LIGHTING))
    allowed = WORN_FOR_TYPE.get(spec.jewelry_type, ("product",))
    if style == "atelier_sketch":
        allowed = ("product",)  # sketch pages present the piece, not a model
    if worn_on not in allowed:
        raise SceneUnsupported(
            f"'{worn_on}' does not fit a {spec.jewelry_type}"
            + (" in atelier-sketch style" if style == "atelier_sketch" else ""),
            list(allowed))

    piece, details = prompt_core(spec)
    if style == "atelier_sketch":
        prompt = (
            f"{STYLES['atelier_sketch']}, depicting a {piece}: "
            + "; ".join(details)
            + ". Physically accurate proportions exactly as specified, "
            "no exaggeration of stone size."
        )
        negative = ["wrong number of stones", "extra prongs", "photorealistic",
                    "photograph", "3d render", "text", "handwriting",
                    "signature", "watermark", "brand names", "logos",
                    "hands", "skin"]
    else:
        scene_bits = [LIGHTING[lighting]]
        if WORN_ON[worn_on]:
            scene_bits.append(WORN_ON[worn_on])
        shot = "photograph" if worn_on == "product" else "lifestyle photograph"
        prompt = (
            f"Ultra-realistic {shot} of a {piece}: "
            + "; ".join(details)
            + ". " + ", ".join(scene_bits)
            + ", sharp focus on the piece, physically accurate proportions exactly "
            "as specified, no exaggeration of stone size."
        )
        negative = ["wrong number of stones", "extra prongs", "deformed metal",
                    "text", "watermark", "blurry", "cartoon", "painting",
                    "exaggerated sparkle"]
        if worn_on == "product":
            negative += ["hands", "skin"]
        else:
            negative += ["extra fingers", "deformed hands", "second piece of jewelry"]

    fingerprint = geometry_fingerprint(spec)
    seed = int(fingerprint[:8], 16)
    return {
        "prompt": prompt,
        "negative_prompt": ", ".join(negative),
        "seed": seed,
        "geometry_fingerprint": fingerprint,
        "scene": {"lighting": lighting, "worn_on": worn_on, "style": style},
        "control": {
            "image": "rasterize this spec's /specs/prototype.svg (or sheet.svg) to PNG",
            "mode": "canny",
            "strength": 0.65,
        },
        "provider_payload": {  # drop-in body for a Flux/SDXL ControlNet endpoint
            "seed": seed,
            "guidance_scale": 3.5,
            "num_inference_steps": 28,
            "control_mode": "canny",
            "controlnet_conditioning_scale": 0.65,
        },
        "consistency": (
            "seed and control image derive from geometry only — re-render with a "
            "different stone color, species or metal and the composition is "
            "unchanged; change any dimension and the request reseeds"
        ),
    }
