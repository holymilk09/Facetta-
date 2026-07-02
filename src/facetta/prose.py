"""Prose → spec via the Claude API.

The model's only job is translating language into a Spec Schema v1 object
drawn from the controlled vocabulary — it never draws geometry and never
invents trade terms. Whatever comes back is re-validated server-side with
the exact same vocabulary + density rules as hand-built specs, so invalid
model output can never reach the DB.
"""

from __future__ import annotations

import os
from functools import lru_cache

from facetta.spec import Spec
from facetta.vocabulary import Vocabulary, get_vocabulary

DEFAULT_MODEL = "claude-opus-4-8"

PROSE_SYSTEM_PROMPT = """\
You are the spec compiler for Facetta, a jewelry design-to-manufacturing platform.
Translate the designer's prose into a single Design Spec Object (Schema v1) as JSON.

Hard rules:
- You only translate language into numbers and controlled-vocabulary values. You never
  invent trade terms, species, cuts, or grades that are not listed below.
- All linear dimensions in mm, all weights in ct, as JSON numbers, never strings.
- The carat and dimensions must be physically consistent:
  carat ≈ length × width × depth × SG × shape_factor / 200 (within ±12%).
  If the prose gives carat but not dimensions, derive plausible dimensions from that
  formula (typical proportions: round length=width, depth ≈ 0.61×diameter; oval
  length/width ≈ 1.35, depth ≈ 0.64×width). If it gives dimensions but not carat,
  compute the carat.
- Ring sizes are US; inner_diameter_mm = 11.63 + 0.8128 × size. Omit
  inner_diameter_mm if unsure — the server derives it.
- Store BOTH the trade term and its GIA translation on the stone color, exactly as
  given in the vocabulary below.
- Clarity is OPTIONAL. Pieces are designed before stones are sourced — omit clarity
  entirely unless the designer explicitly states a grade (finest available is assumed).
  When given, the clarity system must be one listed for that species.
- Use placeholders for identity fields: design_id "dsn_pending", version 1,
  created_by "usr_pending", created_at "1970-01-01T00:00:00Z" — the server assigns
  the real values.
- template must be "solitaire_prong" and jewelry_type "ring" unless the prose
  clearly asks otherwise. mode is "pro" when the prose gives precise measurements,
  otherwise "basic".
- If the prose is missing a required value, choose the most conventional option
  (e.g. 4-prong basket, half_round band 1.8 mm wide × 1.6 mm thick, prong tips
  0.9 mm, gallery 4.5 mm, 18k yellow gold high polish, US size 6.5) and mention
  nothing — the designer reviews the spec before saving.

{vocabulary}
"""


def vocabulary_digest(vocab: Vocabulary) -> str:
    """A compact, deterministic rendering of the controlled vocabulary for the
    system prompt."""
    lines = ["Controlled vocabulary:", "", "Species (id | SG | clarity systems | trade color terms | phenomena):"]
    for sid in vocab.species_ids():
        sp = vocab.species(sid)
        colors = "; ".join(
            f"{t.term} => {t.gia}" for t in vocab.trade_color_terms(sid)
        ) or "(no trade term list — describe with GIA hue/tone/saturation)"
        phenomena = ", ".join(sp.allowed_phenomena) or "none"
        lines.append(
            f"- {sid} | SG {sp.sg} | {', '.join(sp.clarity_systems)} | {colors} | {phenomena}"
        )
    lines.append("")
    lines.append("Cuts (id | shape_factor):")
    for cid in vocab.cut_ids():
        cut = vocab.cut(cid)
        lines.append(f"- {cid} | {cut.shape_factor}")
    lines.append("")
    systems = sorted({s for sid in vocab.species_ids() for s in vocab.species(sid).clarity_systems})
    lines.append("Clarity grades per system:")
    for system in systems:
        lines.append(f"- {system}: {', '.join(vocab.clarity_grades(system))}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return PROSE_SYSTEM_PROMPT.format(vocabulary=vocabulary_digest(get_vocabulary()))


class ProseUnavailable(Exception):
    """The Claude API is not configured (no ANTHROPIC_API_KEY)."""


def generate_spec(prose: str) -> Spec:
    """One Claude API call: prose in, schema-validated Spec out.

    Uses structured outputs (messages.parse) so the response is guaranteed to
    match the pydantic schema; vocabulary and density rules are enforced by the
    caller via facetta.validation afterwards.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ProseUnavailable(
            "ANTHROPIC_API_KEY is not set; POST /specs/from-prose needs a Claude API key"
        )
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=os.environ.get("FACETTA_CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=16000,
        system=system_prompt(),
        messages=[{"role": "user", "content": prose}],
        output_format=Spec,
    )
    return response.parsed_output
