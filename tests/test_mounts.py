"""Mounting techniques: vocabulary-driven, validated, and actually drawn.

The complaint that motivated this: surround stones floating with no metal
holding them, a drop 'just dangling'. Every stone now gets a mount — a
default per position, swappable per stone — and the validator rejects a
mount that cannot physically hold its stone.
"""

from facetta.plate import PAPERS, render_presentation_plate
from facetta.prototype import render_color_preview
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def _validated(raw):
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return result.spec


def _issues(raw):
    return validate_spec(Spec.model_validate(raw), get_vocabulary()).issues


def test_vocabulary_has_the_technique_library(vocab):
    ids = [t["id"] for t in vocab.setting_techniques()]
    for expected in ("prong_4", "prong_6", "v_prong", "bezel", "shared_prong",
                     "pave", "channel", "flush", "tension", "drop_cap"):
        assert expected in ids


def test_unknown_mount_rejected(example_spec):
    example_spec["stone"]["mount"] = "superglue"
    issues = _issues(example_spec)
    assert any(i.type == "vocabulary" and "superglue" in i.msg for i in issues)


def test_mount_must_hold_its_role(pendant_spec):
    # a drop cap cannot hold a center stone
    pendant_spec["stone"]["mount"] = "drop_cap"
    issues = _issues(pendant_spec)
    assert any("cannot hold a center stone" in i.msg for i in issues)
    # and the valid alternatives offered all genuinely hold centers
    issue = next(i for i in issues if "cannot hold" in i.msg)
    assert "prong_4" in issue.valid_options and "drop_cap" not in issue.valid_options


def test_mount_size_bounds(pendant_spec):
    # 6 mm surround stones are too big for micro-pave (max 1.2 mm)
    surround = next(s for s in pendant_spec["side_stones"]
                    if s["position"] in ("halo", "surround"))
    surround["mount"] = "micro_pave"
    issues = _issues(pendant_spec)
    assert any("workable range" in i.msg for i in issues)


def test_nothing_floats_by_default(pendant_spec):
    """Surrounds get shared-prong beads, the center gets claws, the drop
    gets a cap — with no mount specified at all."""
    spec = _validated(pendant_spec)
    svg = render_color_preview(spec)
    surround = next(s for s in spec.side_stones
                    if s.position in ("halo", "surround"))
    # one shared bead per surround stone (midpoint claws around the ring)
    beads = svg.count('opacity="0.75"')
    assert beads >= surround.count  # every gap between stones carries a claw
    assert "Q" in svg  # the drop cap's dome path exists


def test_swapping_a_mount_changes_the_drawing(pendant_spec):
    plain = render_color_preview(_validated(pendant_spec))
    for s in pendant_spec["side_stones"]:
        if s["position"] in ("under_center", "drop"):
            s["mount"] = "bezel"
    bezeled = render_color_preview(_validated(pendant_spec))
    assert plain != bezeled  # the swap is visible, not just recorded


def test_plate_papers(example_spec):
    spec = _validated(example_spec)
    svgs = {p: render_presentation_plate(spec, paper=p) for p in PAPERS}
    assert len(set(svgs.values())) == len(PAPERS)  # each paper distinct
    assert PAPERS["black"]["paper"] in svgs["black"]
    assert PAPERS["grey"]["paper"] in svgs["grey"]
    # re-inking never touches geometry: strip colors (and the grain matrix,
    # which is computed from the ink) — the drawing itself is identical
    import re

    def strip(s: str) -> str:
        s = re.sub(r"#[0-9a-fA-F]{6}", "", s)
        return re.sub(r"<feColorMatrix[^/]*/>", "", s)

    assert strip(svgs["ivory"]) == strip(svgs["black"])


def test_unknown_paper_fails_loudly(example_spec):
    spec = _validated(example_spec)
    try:
        render_presentation_plate(spec, paper="chartreuse")
        raise AssertionError("should have rejected the paper")
    except ValueError as exc:
        assert "ivory" in str(exc)
