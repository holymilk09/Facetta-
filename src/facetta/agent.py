"""The edit-loop agent: natural-language change → validated new version.

The founder's JEWELRY-OS wanted one model to author the spec sheet, letter the
dimensions, and enforce tolerances by instruction — the exact failure this
whole product is built to prevent. So our agent keeps the LOOP they love and
routes each job to the engine that can be trusted with it:

  language → spec DELTA   ·  Claude (translation only, this module)
  is it physically real?  ·  the validator (density + vocabulary + fit)
  paint the piece         ·  Grok (render / blueprint)
  letter every number     ·  deterministic code (sheets / overlay)

Claude never writes a final number into the record unchallenged: whatever it
returns is re-validated with the same rules as a hand-built spec, and an
impossible ask (0.20 ct on a 4.5 × 2.25 mm marquise) is REJECTED with the
density correction rather than quietly saved. Multi-turn memory is the
immutable version chain itself — each accepted edit is a new version.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from facetta.prose import DEFAULT_MODEL, ProseUnavailable, system_prompt
from facetta.spec import Spec

EDIT_SYSTEM_PROMPT = """\
You are the edit planner for Facetta, a jewelry design-to-manufacturing platform.
You are given a design's CURRENT spec object (Schema v1 JSON) and one plain-language
edit instruction from the designer. Return the COMPLETE edited spec plus a short
summary of what changed.

Hard rules:
- Change ONLY what the instruction requires. Copy every other field through unchanged,
  byte for byte — same stones, counts, positions, metal, setting, everything.
- Honor every number the designer states EXPLICITLY, exactly as given, even if it looks
  physically inconsistent. Do NOT silently "fix" a contradiction — the server validates
  the result and reports any impossibility with a correction. Only derive a value the
  designer did NOT specify (e.g. if they change carat but not depth, recompute depth so
  carat ≈ length × width × depth × SG × shape_factor / 200).
- You only translate language into numbers and controlled-vocabulary values; never
  invent trade terms, species, cuts, or grades outside the vocabulary below.
- Keep the identity fields exactly as they are in the current spec — the server assigns
  the new version number and timestamps.

Also report:
- changed_fields: one short string per change, "path old → new"
  (e.g. "stone.carat 4.03 → 3.20", "stone.dimensions_mm.depth 6.3 → 5.0").
- isolate_ref: the stone-schedule letter of the stone the edit targets — "A" is the
  centre stone, "B" the first side_stones entry, "C" the second, and so on. Null if the
  edit touches metal or band rather than a specific stone.
- message: one friendly sentence for the designer describing the change.

{vocabulary}
"""


class EditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    changed_fields: list[str] = Field(default_factory=list)
    isolate_ref: str | None = None
    message: str = ""


def edit_system_prompt() -> str:
    # reuse the prose layer's vocabulary digest, swap in the edit rules
    base = system_prompt()
    vocab = base[base.index("Controlled vocabulary:"):]
    return EDIT_SYSTEM_PROMPT.format(vocabulary=vocab)


def plan_edit(instruction: str, current: Spec) -> EditResult:
    """One Claude call: current spec + instruction in, edited spec + summary
    out. The result is NOT trusted — the caller re-validates it and only then
    writes a new version."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ProseUnavailable(
            "ANTHROPIC_API_KEY is not set; the edit agent needs a Claude API key")
    import anthropic

    client = anthropic.Anthropic()
    user = (
        "CURRENT SPEC:\n"
        + current.model_dump_json(indent=2)
        + "\n\nEDIT INSTRUCTION:\n" + instruction
    )
    response = client.messages.parse(
        model=os.environ.get("FACETTA_CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=16000,
        system=edit_system_prompt(),
        messages=[{"role": "user", "content": user}],
        output_format=EditResult,
    )
    return response.parsed_output
