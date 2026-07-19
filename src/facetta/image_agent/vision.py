"""Focused Grok vision transport and design-consistency normalization."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable

from facetta.config import env_value
from facetta.media import sniff_media_type
from facetta.provider_errors import RenderUnavailable


PairInspector = Callable[[str, bytes, bytes, str], dict]


class VisionProviderUnavailable(RenderUnavailable):
    """A vision request could not run because its provider was unavailable.

    This is intentionally narrower than ``RenderUnavailable``. Invalid JSON,
    response-shape drift, and other evaluator-contract failures must stay on
    the original provider path and fail closed instead of being reinterpreted
    by a second reviewer.
    """


def _is_provider_unavailability(exc: Exception) -> bool:
    """Classify only authentication, authorization, and availability errors."""

    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status in {401, 403, 408, 429} or status >= 500
    return isinstance(exc, httpx.TransportError)


def _image_uri(content: bytes) -> str:
    encoded = base64.b64encode(content).decode()
    return f"data:{sniff_media_type(content)};base64,{encoded}"


def _response_output_text(payload: object) -> str:
    """Extract the first assistant text block from a Responses API payload."""
    if not isinstance(payload, dict):
        raise ValueError("OpenAI returned a non-object response")
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    if not isinstance(output, list):
        raise ValueError("OpenAI response did not contain output items")
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (isinstance(block, dict)
                    and block.get("type") == "output_text"
                    and isinstance(block.get("text"), str)):
                return block["text"]
    raise ValueError("OpenAI response did not contain output text")


def _openai_text_format(response_schema: dict | None) -> dict:
    """Build a Responses API text format without mutating caller schema.

    Pydantic emits ``default`` keywords and omits defaulted properties from
    ``required``. OpenAI strict Structured Outputs does not support defaults
    and requires every object property to be listed as required; nullable
    values stay expressible through Pydantic's ``anyOf`` string/null form.
    """

    if response_schema is None:
        return {"type": "json_object"}
    if not isinstance(response_schema, dict):
        raise TypeError("response_schema must be a JSON Schema object")

    # JSON round-trip both deep-copies and proves the schema is transport-safe.
    schema = json.loads(json.dumps(response_schema))

    def normalize(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                normalize(item)
            return
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        # Structured Outputs does not accept these JSON Schema string bounds.
        # Pydantic still enforces them after transport, so removing them here
        # broadens provider compatibility without weakening local validation.
        node.pop("minLength", None)
        node.pop("maxLength", None)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
            node["additionalProperties"] = False
        for value in node.values():
            normalize(value)

    normalize(schema)
    return {
        "type": "json_schema",
        "name": "facetta_vision_contract",
        "description": "One strict Facetta visual-reading contract.",
        "strict": True,
        "schema": schema,
    }


def openai_vision_json(system: str, image_bytes: bytes,
                       user_text: str,
                       response_schema: dict | None = None) -> dict:
    """Run one OpenAI vision request and return one JSON object.

    This is the OpenAI-only QA fallback for prompt-created concepts. It keeps
    the same fail-closed evaluator contract as Grok instead of treating a
    generated image as accepted merely because the primary QA provider is not
    configured.
    """
    key = env_value("OPENAI_API_KEY")
    if not key:
        raise RenderUnavailable(
            "no OPENAI_API_KEY configured — validation needs a vision key")

    import httpx

    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get(
                    "FACETTA_OPENAI_VISION", "gpt-5.4-mini"),
                "store": False,
                "input": [
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": system}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": _image_uri(image_bytes),
                                "detail": "high",
                            },
                            {"type": "input_text", "text": user_text},
                        ],
                    },
                ],
                "text": {"format": _openai_text_format(response_schema)},
                # Motif-level necklace audits can legitimately contain several
                # paired components and six-leaf inventories. The former cap
                # could truncate otherwise valid JSON before Pydantic saw it.
                "max_output_tokens": 4000,
            },
        )
        response.raise_for_status()
        data = json.loads(_response_output_text(response.json()))
        if not isinstance(data, dict):
            raise ValueError(f"provider returned non-object JSON: {data!r}")
        return data
    except Exception as exc:
        raise RenderUnavailable(
            f"OpenAI vision inspect failed: {exc}") from exc


def openai_vision_json_pair(
    system: str,
    image_a: bytes,
    image_b: bytes,
    user_text: str,
) -> dict:
    """Run one fail-closed OpenAI vision comparison over two images."""
    key = env_value("OPENAI_API_KEY")
    if not key:
        raise RenderUnavailable(
            "no OPENAI_API_KEY configured — validation needs a vision key")

    import httpx

    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get(
                    "FACETTA_OPENAI_VISION", "gpt-5.4-mini"),
                "store": False,
                "input": [
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": system}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": _image_uri(image_a),
                                "detail": "high",
                            },
                            {
                                "type": "input_image",
                                "image_url": _image_uri(image_b),
                                "detail": "high",
                            },
                            {"type": "input_text", "text": user_text},
                        ],
                    },
                ],
                "text": {"format": {"type": "json_object"}},
                "max_output_tokens": 1800,
            },
        )
        response.raise_for_status()
        data = json.loads(_response_output_text(response.json()))
        if not isinstance(data, dict):
            raise ValueError(f"provider returned non-object JSON: {data!r}")
        return data
    except Exception as exc:
        raise RenderUnavailable(
            f"OpenAI vision comparison failed: {exc}") from exc


def vision_json(system: str, image_bytes: bytes, user_text: str) -> dict:
    """Run one Grok vision request and return one JSON object."""
    key = env_value("XAI_KEY")
    if not key:
        raise VisionProviderUnavailable(
            "no XAI_KEY configured — the spec agent needs a vision key")

    import httpx

    try:
        response = httpx.post(
            "https://api.x.ai/v1/chat/completions",
            timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get("FACETTA_XAI_VISION", "grok-4.3"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": _image_uri(image_bytes)}},
                        {"type": "text", "text": user_text},
                    ]},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(data, dict):
            raise ValueError(f"provider returned non-object JSON: {data!r}")
        return data
    except Exception as exc:
        error_type = (
            VisionProviderUnavailable
            if _is_provider_unavailability(exc)
            else RenderUnavailable
        )
        raise error_type(f"vision inspect failed: {exc}") from exc


def vision_json_pair(
    system: str,
    image_a: bytes,
    image_b: bytes,
    user_text: str,
) -> dict:
    """Run one Grok vision request over a reference/candidate image pair."""
    key = env_value("XAI_KEY")
    if not key:
        raise VisionProviderUnavailable(
            "no XAI_KEY configured — validation needs a key")

    import httpx

    try:
        response = httpx.post(
            "https://api.x.ai/v1/chat/completions",
            timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get("FACETTA_XAI_VISION", "grok-4.3"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": _image_uri(image_a)}},
                        {"type": "image_url",
                         "image_url": {"url": _image_uri(image_b)}},
                        {"type": "text", "text": user_text},
                    ]},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(data, dict):
            raise ValueError("non-object JSON")
        return data
    except Exception as exc:
        error_type = (
            VisionProviderUnavailable
            if _is_provider_unavailability(exc)
            else RenderUnavailable
        )
        raise error_type(f"consistency check failed: {exc}") from exc


def configured_vision_json(
    system: str,
    image_bytes: bytes,
    user_text: str,
    response_schema: dict | None = None,
) -> dict:
    """Use one configured single-image inspector with deterministic priority.

    XAI remains primary when configured. OpenAI is used only when XAI is
    absent, so a failed primary request cannot silently create a second paid
    inspection or change the evidence source mid-request.
    """

    if env_value("XAI_KEY"):
        return vision_json(system, image_bytes, user_text)
    if env_value("OPENAI_API_KEY"):
        return openai_vision_json(
            system,
            image_bytes,
            user_text,
            response_schema,
        )
    raise RenderUnavailable(
        "no configured vision service is available for this inspection"
    )


def configured_vision_json_pair(
    system: str,
    image_a: bytes,
    image_b: bytes,
    user_text: str,
) -> dict:
    """Use the configured pair inspector with a deterministic priority.

    XAI remains the primary reviewer whenever its key is configured. OpenAI is
    the configuration fallback, allowing Refine markup interpretation to use
    the same vision provider already available to image QA. We intentionally
    do not retry a failed XAI request against OpenAI here: provider errors stay
    visible and fail closed instead of silently creating a second paid audit.
    """

    if env_value("XAI_KEY"):
        return vision_json_pair(system, image_a, image_b, user_text)
    if env_value("OPENAI_API_KEY"):
        return openai_vision_json_pair(system, image_a, image_b, user_text)
    raise RenderUnavailable(
        "no XAI_KEY or OPENAI_API_KEY configured — validation needs a vision key"
    )


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
