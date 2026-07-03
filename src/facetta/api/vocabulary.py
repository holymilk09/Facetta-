"""Cascading option endpoints: choosing a stone swaps the color, clarity, and
grading vocabularies. Everything served here comes straight from
data/gemology_vocabulary.json — no trade terms are invented in code."""

from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from facetta.vocabulary import get_vocabulary

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


@router.get("/stones")
def stones() -> dict:
    vocab = get_vocabulary()
    entries = [
        {"id": sid, "display": vocab.species(sid).display, "parameter_set": "gemstone"}
        for sid in vocab.species_ids()
    ]
    entries += [
        {"id": sid, "display": sid.capitalize(), "parameter_set": sid}
        for sid in vocab.ORGANIC_PARAMETER_SETS
    ]
    return {"stones": entries}


@router.get("/findings")
def findings() -> dict:
    """Metalwork vocabulary (chains, clasps) and the girdle thickness scale."""
    vocab = get_vocabulary()
    return {
        "chain_styles": vocab.chain_styles(),
        "clasp_types": vocab.clasp_types(),
        "girdle_thickness_scale": vocab.girdle_grades(),
        "metals": vocab.metals(),
    }


@router.get("/stones/{stone_id}/options")
def stone_options(stone_id: str):
    vocab = get_vocabulary()

    own = vocab.parameter_set(stone_id)
    if own is not None:
        return {
            "stone": stone_id,
            "display": stone_id.capitalize(),
            "parameter_set": stone_id,
            **own,
        }

    species = vocab.species(stone_id)
    if species is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": f"unknown stone '{stone_id}'",
                "valid_options": vocab.stone_ids(),
            },
        )

    grades = {system: vocab.clarity_grade_entries(system) for system in species.clarity_systems}
    colors = [
        {k: v for k, v in asdict(t).items() if k != "extras" and v} | t.extras
        for t in vocab.trade_color_terms(stone_id)
    ]
    return {
        "stone": stone_id,
        "display": species.display,
        "parameter_set": "gemstone",
        "sg": species.sg,
        "colors": colors,
        "clarity": {"systems": list(species.clarity_systems), "grades": grades},
        "cuts": [
            {"id": c.id, "name": c.name, "category": c.category, "shape_factor": c.shape_factor}
            for cid in vocab.cut_ids()
            if (c := vocab.cut(cid))
        ],
        "phenomena": list(species.allowed_phenomena),
    }
