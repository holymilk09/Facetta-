"""Extract exact, visually countable component claims from creative briefs.

This is intentionally category-neutral.  It does not attempt to turn prose
into a jewelry specification; it only records explicit numeric constraints
that a single review image can independently count.  Measurements, alloy
marks, carat weights, and top-level product categories are excluded.
"""

from __future__ import annotations

import re

from facetta.json_types import JsonObject


_SMALL_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?)"
)
_NUMBER_RE = re.compile(
    rf"(?<![\w.])(?P<number>\d{{1,3}}(?![\w.])|{_NUMBER_WORD})(?![\w])",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z]+(?:-[a-z]+)?", re.IGNORECASE)

# Boundaries end the noun phrase associated with the count.  ``of`` is a
# boundary so "four rows of diamonds" records four rows rather than silently
# changing the claim into four diamonds.
_PHRASE_BOUNDARIES = frozenset({
    "and", "with", "plus", "featuring", "using", "of", "in", "on",
    "around", "along", "across", "at", "by", "for", "from", "to",
    "per", "each", "mounted", "holding",
})

# These are visible, countable jewelry components or motifs.  Product classes
# such as ring/necklace and material/measurement words are deliberately absent.
# The phrase supplied to vision retains all modifiers (for example ``halo
# diamonds`` or ``marquise emerald leaves``); the canonical head is routing
# metadata only.
_COUNTABLE_HEADS = frozenset({
    "arm", "arms", "bar", "bars", "bead", "beads", "branch", "branches",
    "charm", "charms", "claw", "claws", "coil", "coils", "diamond",
    "diamonds", "drop", "drops", "emerald", "emeralds", "gem", "gems",
    "gemstone", "gemstones", "leaf", "leaves", "link", "links", "loop",
    "loops", "motif", "motifs", "opal", "opals", "panel", "panels",
    "pearl", "pearls", "petal", "petals", "prong", "prongs", "row",
    "rows", "ruby", "rubies", "sapphire", "sapphires", "spike", "spikes",
    "stone", "stones", "strand", "strands", "stud", "studs", "tassel",
    "tassels", "teardrop", "teardrops",
})
_PRONG_HEADS = frozenset({"prong", "prongs", "claw", "claws"})
_SIDE_SETTING_MARKERS = frozenset({
    "halo", "side", "melee", "pave", "pavé", "accent",
})
_MEASUREMENT_UNITS = frozenset({
    "mm", "millimeter", "millimeters", "cm", "centimeter", "centimeters",
    "in", "inch", "inches", "ct", "carat", "carats", "g", "gram",
    "grams", "ga", "gauge",
})


def _parse_number(value: str) -> int | None:
    normalized = value.lower().replace("-", " ")
    if normalized.isdigit():
        parsed = int(normalized)
        return parsed if parsed <= 512 else None
    words = normalized.split()
    if len(words) == 1:
        return _SMALL_NUMBERS.get(words[0], _TENS.get(words[0]))
    if len(words) == 2 and words[0] in _TENS and words[1] in _SMALL_NUMBERS:
        return _TENS[words[0]] + _SMALL_NUMBERS[words[1]]
    return None


def _claim_kind(head: str, phrase_tokens: list[str]) -> str:
    if head in _PRONG_HEADS and not (
        _SIDE_SETTING_MARKERS & {token.lower() for token in phrase_tokens}
    ):
        return "center_prongs"
    return "named_visible_component"


def extract_explicit_component_counts(intent: str) -> tuple[JsonObject, ...]:
    """Return explicit visual count locks without inferring unstated facts.

    The extractor accepts digits and ordinary English number words.  A claim is
    emitted only when the following short noun phrase contains a known visible
    component head.  This avoids treating ``18k``, ``2 mm``, ``1.5 carat``, or
    a product category as a component count.
    """

    normalized = intent.replace("–", "-").replace("—", "-")
    claims: list[JsonObject] = []
    seen: set[tuple[int, str]] = set()
    for match in _NUMBER_RE.finditer(normalized):
        expected = _parse_number(match.group("number"))
        if expected is None:
            continue
        tail = normalized[match.end():]
        separator = re.match(r"[\s-]+", tail)
        if separator is None:
            continue
        tail = tail[separator.end():]
        phrase_tokens: list[str] = []
        selected_head: str | None = None
        selected_length = 0
        for word_match in _WORD_RE.finditer(tail):
            # Stop at punctuation or a long gap before this word.
            between = tail[
                (0 if not phrase_tokens else previous_end):word_match.start()
            ]
            if any(char in between for char in ",;:.!?()[]{}"):
                break
            token = word_match.group(0).lower()
            if token in _PHRASE_BOUNDARIES:
                break
            phrase_tokens.append(token)
            previous_end = word_match.end()
            if len(phrase_tokens) == 1 and token in _MEASUREMENT_UNITS:
                # ``2 mm stones`` states a size, not a two-stone inventory.
                selected_head = None
                break
            if token in _COUNTABLE_HEADS:
                selected_head = token
                selected_length = len(phrase_tokens)
            if len(phrase_tokens) >= 6:
                break
        if selected_head is None:
            continue
        selected_tokens = phrase_tokens[:selected_length]
        phrase = " ".join(selected_tokens)
        dedupe_key = (expected, phrase)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        claims.append({
            "claim_id": f"count_{len(claims) + 1}",
            "component": phrase,
            "component_head": selected_head,
            "kind": _claim_kind(selected_head, selected_tokens),
            "expected_count": expected,
        })
    return tuple(claims)
