"""Provider-neutral vision transport and design-consistency normalization.

xAI remains the primary visual inspector.  OpenAI is a fail-closed transport
fallback for the same JSON audit contract; it is not allowed to bypass or
weaken any downstream jewelry-quality gate.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable

from facetta.config import env_value
from facetta.media import sniff_media_type
from facetta.provider_errors import RenderUnavailable


PairInspector = Callable[[str, bytes, bytes, str], dict]

_XAI_VISION_URL = "https://api.x.ai/v1/chat/completions"
_OPENAI_VISION_URL = "https://api.openai.com/v1/chat/completions"


def _image_uri(content: bytes) -> str:
    encoded = base64.b64encode(content).decode()
    return f"data:{sniff_media_type(content)};base64,{encoded}"


def _json_object(response) -> dict:
    response.raise_for_status()
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError(f"provider returned non-object JSON: {data!r}")
    return data


def _vision_request(
    *,
    url: str,
    key: str,
    model: str,
    system: str,
    images: tuple[bytes, ...],
    user_text: str,
) -> dict:
    import httpx

    content = [
        {"type": "image_url", "image_url": {"url": _image_uri(image)}}
        for image in images
    ]
    content.append({"type": "text", "text": user_text})
    response = httpx.post(
        url,
        timeout=120.0,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
        },
    )
    return _json_object(response)


def _provider_neutral_vision_json(
    system: str,
    images: tuple[bytes, ...],
    user_text: str,
) -> dict:
    """Use xAI first and OpenAI only when the primary transport is unusable."""
    failures: list[str] = []
    xai_key = env_value("XAI_KEY")
    if xai_key:
        try:
            return _vision_request(
                url=_XAI_VISION_URL,
                key=xai_key,
                model=os.environ.get("FACETTA_XAI_VISION", "grok-4.3"),
                system=system,
                images=images,
                user_text=user_text,
            )
        except Exception as exc:
            failures.append(f"xAI: {exc}")

    openai_key = env_value("OPENAI_API_KEY")
    if openai_key:
        try:
            return _vision_request(
                url=_OPENAI_VISION_URL,
                key=openai_key,
                model=os.environ.get(
                    "FACETTA_OPENAI_VISION",
                    "gpt-4.1-mini-2025-04-14",
                ),
                system=system,
                images=images,
                user_text=user_text,
            )
        except Exception as exc:
            failures.append(f"OpenAI: {exc}")

    if not failures:
        raise RenderUnavailable(
            "no vision provider configured — set XAI_KEY or OPENAI_API_KEY"
        )
    raise RenderUnavailable(
        "all configured vision providers failed: " + "; ".join(failures)
    )


def vision_json(system: str, image_bytes: bytes, user_text: str) -> dict:
    """Run one primary-or-fallback vision request and return a JSON object."""
    try:
        return _provider_neutral_vision_json(
            system,
            (image_bytes,),
            user_text,
        )
    except RenderUnavailable:
        raise
    except Exception as exc:
        raise RenderUnavailable(f"vision inspect failed: {exc}") from exc


def vision_json_pair(
    system: str,
    image_a: bytes,
    image_b: bytes,
    user_text: str,
) -> dict:
    """Run one primary-or-fallback audit over an image pair."""
    try:
        return _provider_neutral_vision_json(
            system,
            (image_a, image_b),
            user_text,
        )
    except RenderUnavailable:
        raise
    except Exception as exc:
        raise RenderUnavailable(f"consistency check failed: {exc}") from exc


_CONSISTENCY_SYSTEM = """\
You compare TWO photos of fine jewelry for a manufacturer. The FIRST image is
the approved reference design. The SECOND is a new photo that must show the
EXACT SAME piece from a different angle or setting — not a redesign.

Judge ONLY the jewelry (ignore camera angle, background, hands, lighting).
Return JSON exactly:
{"consistent": true|false, "differences": ["..."], "severity": "none|minor|major"}

consistent is FALSE if the second piece differs in any of: centre stone shape/
cut, centre stone colour, number or arrangement of side/halo stones, setting or
prong style, metal colour, overall proportions, or the SIZE/SCALE of the stone
and ring. Scale matters: if the ring is worn on a hand, the centre stone must
keep the same size relative to the finger — a stone that looks noticeably bigger
or smaller than the reference (so a 2 ct would read as a different carat) is a
MAJOR difference, because the client must not be misled about how large the
finished piece is. List each real difference briefly in differences. Minor
lighting/reflection changes are NOT differences. Set severity to "major" for any
change to the design, stones, metal, or size; "minor" for trivial framing. Be
fair but honest. Output ONLY the JSON."""


def check_design_consistency(
    reference_bytes: bytes,
    candidate_bytes: bytes,
    *,
    inspect_pair: PairInspector | None = None,
) -> dict:
    """Return normalized same-design evidence, permissive on provider outage."""
    inspect = inspect_pair or vision_json_pair
    try:
        data = inspect(
            _CONSISTENCY_SYSTEM,
            reference_bytes,
            candidate_bytes,
            "Is the second the same piece as the first?",
        )
    except RenderUnavailable:
        return {
            "consistent": True,
            "differences": [],
            "severity": "none",
            "checked": False,
        }
    data.setdefault("differences", [])
    data.setdefault("severity", "none")
    data["checked"] = True
    return data


_GEOMETRY_SYSTEM = """\
You compare TWO images of the same jewelry technical drawing. The FIRST is the
designer-approved black line-art geometry. The SECOND is a colorized candidate.
Ignore all color, metal finish, lighting, background, and rendering style.
Judge only whether the silhouette, setting, stone shapes, stone count,
placement, and band/structural geometry are unchanged. Return JSON only:
{"consistent": true|false, "differences": ["..."],
 "severity": "none|minor|major"}
Any added, removed, duplicated, moved, or reshaped jewelry element is a major
difference. Do not call a material/color change a difference."""


def check_geometry_consistency(
    reference_bytes: bytes,
    candidate_bytes: bytes,
    *,
    inspect_pair: PairInspector | None = None,
) -> dict:
    """Verify colorization preserved approved geometry while ignoring color."""
    inspect = inspect_pair or vision_json_pair
    try:
        data = inspect(
            _GEOMETRY_SYSTEM,
            reference_bytes,
            candidate_bytes,
            "Did colorization preserve exactly the approved jewelry geometry?",
        )
    except RenderUnavailable:
        return {
            "consistent": True,
            "differences": [],
            "severity": "none",
            "checked": False,
        }
    data.setdefault("differences", [])
    data.setdefault("severity", "none")
    data["checked"] = True
    return data


_COLORED_LINE_ART_SYSTEM = """\
You compare TWO images in a locked jewelry drawing workflow. The FIRST is the
designer-confirmed black technical line drawing. The SECOND must be that same
technical illustration with controlled color applied inside its existing
outlines. This is deliberately NOT the later photorealistic beauty-render step.

Return JSON only:
{"linework_retained": true|false|null,
 "color_inside_existing_geometry": true|false|null,
 "technical_illustration_style": true|false|null,
 "photorealistic_replacement": true|false|null,
 "geometry_consistent": true|false|null,
 "differences": ["specific evidence"],
 "severity": "none|minor|major|unknown"}

linework_retained is true only when the source's deliberate black outer,
setting, stone, prong, band, and facet construction lines remain visibly
present as technical drawing lines. technical_illustration_style is false when
the second image has become a product photograph, 3D beauty render, or painterly
replacement even if the jewelry looks attractive. photorealistic_replacement
must be true for that prohibited transformation. color_inside_existing_geometry
is false if shading or material rendering replaces, obscures, or redraws the
confirmed line structure. geometry_consistent is false for any added, removed,
moved, duplicated, or reshaped jewelry element. A photorealistic replacement is
a major workflow-contract failure; do not excuse it as a harmless style change."""


def check_colored_line_art_contract(
    confirmed_line_art: bytes,
    colored_candidate: bytes,
    *,
    inspect_pair: PairInspector | None = None,
) -> dict:
    """Verify color was added without replacing the confirmed line drawing."""
    inspect = inspect_pair or vision_json_pair
    try:
        data = inspect(
            _COLORED_LINE_ART_SYSTEM,
            confirmed_line_art,
            colored_candidate,
            (
                "Is the second image still the exact confirmed technical line "
                "illustration, with color added inside the retained black lines?"
            ),
        )
    except RenderUnavailable:
        return {
            "checked": False,
            "linework_retained": None,
            "color_inside_existing_geometry": None,
            "technical_illustration_style": None,
            "photorealistic_replacement": None,
            "geometry_consistent": None,
            "differences": [
                "colored-line-art contract could not be independently verified"
            ],
            "severity": "unknown",
        }
    data.setdefault("differences", [])
    data.setdefault("severity", "unknown")
    data["checked"] = True
    return data


_CONFIRMED_LINE_ART_SYSTEM = """\
You are a skeptical QA reviewer for a designer drawing-to-line-art workflow.
The FIRST image is the imported designer source. The SECOND is the candidate
technical line drawing. Inspect the SECOND image absolutely, including all
corners and faint edge areas; do not excuse a caption, signature, logo,
watermark, social/platform ID, or branding merely because it existed in the
FIRST image.

Return JSON only:
{"black_line_art_on_white": true|false|null,
 "single_assembled_view": true|false|null,
 "source_geometry_preserved": true|false|null,
 "center_prong_count_matches": true|false|null,
 "observed_center_prong_count": 0,
 "side_stone_inventory_matches": true|false|null,
 "observed_side_stone_counts": [0],
 "candidate_text_or_branding_detected": true|false|null,
 "colored_or_photorealistic": true|false|null,
 "differences": ["specific evidence"],
 "severity": "none|minor|major|unknown"}

The candidate must show one assembled jewelry view as precise black technical
linework on plain white, with no color fill or photorealistic rendering. Compare
silhouette, every stone group, setting, prong, gallery, shoulder, and band to
the source. Count the CENTER-STONE prongs separately from halo/side-stone
prongs. Count each repeated side-stone group when the complete group is visible.
Use null only when the chosen view truly prevents a complete count. Any added,
removed, duplicated, moved, or reshaped jewelry element is major. Any text or
branding in the SECOND image is an absolute major failure."""


def check_confirmed_line_art_contract(
    source: bytes,
    candidate: bytes,
    *,
    expected_facts: dict,
    focus: str,
    inspect_pair: PairInspector | None = None,
) -> dict:
    """Audit line-art geometry, counts, style, and candidate-only hygiene."""
    inspect = inspect_pair or vision_json_pair
    try:
        data = inspect(
            _CONFIRMED_LINE_ART_SYSTEM,
            source,
            candidate,
            (
                "Audit focus: " + focus + "\nEXPECTED VALIDATED FACTS: "
                + json.dumps(expected_facts, sort_keys=True, separators=(",", ":"))
            ),
        )
    except RenderUnavailable:
        return {
            "checked": False,
            "black_line_art_on_white": None,
            "single_assembled_view": None,
            "source_geometry_preserved": None,
            "center_prong_count_matches": None,
            "observed_center_prong_count": None,
            "side_stone_inventory_matches": None,
            "observed_side_stone_counts": [],
            "candidate_text_or_branding_detected": None,
            "colored_or_photorealistic": None,
            "differences": ["confirmed-line-art audit unavailable"],
            "severity": "unknown",
        }
    data.setdefault("observed_side_stone_counts", [])
    data.setdefault("differences", [])
    data.setdefault("severity", "unknown")
    data["checked"] = True
    return data


_MATERIAL_IDENTITY_SYSTEM = """\
You compare TWO depictions of the same fine-jewelry design. The FIRST is the
approved colored source/reference. The SECOND is a spec-colored technical
illustration. Ignore camera angle, crop, photorealism versus illustration,
lighting, and background. Audit MATERIAL ASSIGNMENT component by component:
which outlined shapes are gemstones versus metal, gemstone species/color,
diamond/melee placement, metal color zones, enamel, and empty/open spaces.

Return JSON only:
{"consistent": true|false, "differences": ["specific lost or changed material assignment"],
 "severity": "none|minor|major"}

Mark major if any visible gemstone group becomes metal, metal becomes a stone,
a colored center/side stone changes identity, diamond/melee groups disappear,
or a two-tone zone becomes one metal. A rendering-style difference is not a
difference. Be especially alert to leaf, halo, shoulder, and pavé outlines that
remain geometrically present but are filled as plain metal in the second image."""


def check_material_identity(
    approved_source: bytes,
    colored_candidate: bytes,
    *,
    focus: str | None = None,
    inspect_pair: PairInspector | None = None,
) -> dict:
    """Verify colorization did not erase or reassign stones/material zones."""
    inspect = inspect_pair or vision_json_pair
    try:
        data = inspect(
            _MATERIAL_IDENTITY_SYSTEM,
            approved_source,
            colored_candidate,
            "Does every visible stone and metal zone keep its approved material identity?"
            + (f" Audit focus: {focus}" if focus else ""),
        )
    except RenderUnavailable:
        return {
            "consistent": False,
            "differences": ["material identity could not be independently verified"],
            "severity": "unknown",
            "checked": False,
        }
    data.setdefault("differences", [])
    data.setdefault("severity", "none")
    data["checked"] = True
    return data
