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
        "an haute joaillerie designer's presentation sketch, hand-drawn in "
        "colored pencil, soft graphite and fine white gouache on warm ivory "
        "paper; confident varied line weight — loose expressive strokes for "
        "the metal, precise rendering of every stone facet; composed like a "
        "couture atelier plate with three views on one page (face-on large, "
        "three-quarter, and profile smaller beside it); translucent "
        "watercolor wash giving each gem its color and inner glow, hatched "
        "graphite shadow anchoring each view to the paper, faint construction "
        "and symmetry lines left visible around the drawing, generous empty "
        "margins, refined gallery-quality presentation"
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


def compile_finish_request(spec, style: str = "photo",
                           lighting: str = "studio") -> dict:
    """Have an image model FINISH our control image, not imagine a piece.

    The division of labor the product is built on: deterministic code draws
    the control image — every stone position, count, mount and silhouette
    exact — and the image model paints realism over that scaffold. The
    instruction is written for an image-editing model (Grok Imagine's edit
    mode, FLUX Kontext class): trace, don't redesign."""
    from facetta.prototype import stone_manifest

    if style not in STYLES:
        raise SceneUnsupported(f"unknown style '{style}'", sorted(STYLES))
    if lighting not in LIGHTING:
        raise SceneUnsupported(f"unknown lighting '{lighting}'", sorted(LIGHTING))

    piece, _ = prompt_core(spec)
    manifest = "; ".join(stone_manifest(spec))
    if style == "atelier_sketch":
        look = ("repaint it as " + STYLES["atelier_sketch"])
    else:
        look = ("repaint it as an ultra-realistic studio product photograph, "
                + LIGHTING[lighting] + ", polished metal with true "
                "reflections, gems with real depth, fire and internal light")
    instruction = (
        f"The attached image is an exact engineering control drawing of a "
        f"{piece} ({manifest}). Every stone's position, size, count, and "
        f"silhouette, and every piece of metal hardware — claws, beads, "
        f"bezel rims, gallery rails, caps, jump rings — is drawn where it "
        f"truly belongs and MUST be preserved exactly. {look}. Render the "
        f"metalwork as real three-dimensional goldsmithing following the "
        f"drawn hardware precisely. Do NOT add, remove, move, or resize any "
        f"stone or component; do not change the viewpoint or composition of "
        f"either view; no text, numbers, watermarks, or signatures anywhere."
    )
    return {
        "instruction": instruction,
        "negative_prompt": ", ".join(
            ["extra stones", "missing stones", "moved stones",
             "different proportions", "text", "handwriting", "numbers",
             "watermark", "logo", "brand names", "hands", "skin"]),
        "control": {
            "image": "POST /specs/control-image.svg, rasterized — the edit input",
            "role": "geometry scaffold: the model paints over it, never redraws it",
        },
        "provider_payload": {  # instruction-editing model defaults
            "guidance_scale": 3.0,
            "num_inference_steps": 28,
        },
        "fidelity_checklist": fidelity_checklist(spec),
    }


def compile_restage_request(jewelry_type: str = "ring", lighting: str = "studio",
                            worn_on: str = "product") -> dict:
    """Re-stage a photograph of a FINISHED piece into a new scene.

    No spec required: the uploaded photo IS the geometry. The instruction is
    written for an image-editing model (FLUX Kontext class) that preserves the
    pictured piece exactly and only changes the setting around it.
    """
    if lighting not in LIGHTING:
        raise SceneUnsupported(f"unknown lighting '{lighting}'", sorted(LIGHTING))
    allowed = WORN_FOR_TYPE.get(jewelry_type, ("product",))
    if worn_on not in allowed:
        raise SceneUnsupported(
            f"'{worn_on}' does not fit a {jewelry_type}", list(allowed))

    scene_bits = [LIGHTING[lighting]]
    if WORN_ON[worn_on]:
        scene_bits.append(WORN_ON[worn_on])
    instruction = (
        "Keep the pictured piece of jewelry EXACTLY as it is — identical stones, "
        "stone count, metal color, proportions and construction; do not redesign, "
        "add or remove any element. Re-stage it: " + ", ".join(scene_bits) + "."
    )
    return {
        "instruction": instruction,
        "scene": {"lighting": lighting, "worn_on": worn_on},
        "provider_payload": {  # drop-in for an instruction-editing endpoint
            "guidance_scale": 2.5,
            "num_inference_steps": 28,
        },
        "control": {"image": "the uploaded photograph, sent as the edit input"},
        "consistency": (
            "image-editing models preserve the input piece; only the scene "
            "described in the instruction changes between renders"
        ),
    }


def fidelity_checklist(spec: Spec) -> list[str]:
    """Ten-second grading list for a generated image — the exact points image
    models drift on: stone counts, relative melee scale, cut identity,
    invented components. Every item is checkable by eye against the render."""
    stone = spec.stone
    d = stone.dimensions_mm
    checks = [
        f"center stone is a {stone.cut.replace('_', ' ')} "
        f"({d.length} x {d.width} mm) — verify the cut, not just the color",
    ]
    for side in spec.side_stones:
        w = side.dimensions_mm.width
        rel = w / d.width
        checks.append(
            f"EXACTLY {side.count} {side.species} stones at {side.position or 'accent'} "
            f"— each {w} mm (about {rel:.0%} of the center's width"
            + ("; small accent points, not feature stones)" if rel < 0.45 else ")"))
        if side.cut != "cabochon":
            checks.append(
                f"the {side.position or 'accent'} {side.species} is FACETED "
                f"({side.cut.replace('_', ' ')}) — reject smooth domes")
    if spec.chain is None and spec.jewelry_type in ("pendant", "necklace"):
        checks.append("NO chain — the spec has none; reject renders that add one")
    if spec.template == "leaf_spray_brooch":
        from facetta.validation import spray_cluster_row
        checks.insert(0, (
            f"EXACTLY {len(spray_cluster_row(spec))} quatrefoil clusters on ONE "
            "curved branch, the largest at the tip — reject a mirrored second "
            "branch or extra clusters"))
    if spec.metal:
        karat = f"{spec.metal.karat}k " if spec.metal.karat else ""
        color = f"{spec.metal.color} " if spec.metal.color else ""
        checks.append(f"metal reads as {karat}{color}{spec.metal.material}")
    checks.append("no text, hallmark letters, or logos anywhere on the metal")
    return checks


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
    if spec.brooch:
        geo["brooch"] = [spec.brooch.length_mm, spec.brooch.width_mm,
                         spec.brooch.sweep_deg]
    if spec.composition:
        geo["composition"] = [spec.composition.clusters, spec.composition.vein]
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
        "fidelity_checklist": fidelity_checklist(spec),
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
