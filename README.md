# Facetta

A design-to-manufacturing platform for the jewelry industry. Designers describe a piece
via structured parameters drawn from a controlled gemological vocabulary; the system
compiles that into an immutable spec object which drives every output — an annotated
technical sheet for factories, an interactive 3D preview, and (later) photoreal client
renders.

Read `CLAUDE.md` for the project constitution, `docs/PRD.md` for product requirements,
`docs/SPEC_SCHEMA.md` for the spec object schema, and `TASKS.md` for the build order.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Run the tests

```sh
uv run pytest
```

## Run the API

```sh
uv run uvicorn facetta.main:app --reload
```

### Health check

```sh
curl http://127.0.0.1:8000/health
```

### Validate a spec

`POST /specs/validate` takes a Spec Schema v1 object (see `docs/SPEC_SCHEMA.md`) and
returns it validated — with the ring inner diameter auto-derived from the size when
absent — or a structured 422 listing every failed rule with its valid options or
computed expected values.

```sh
curl -s -X POST http://127.0.0.1:8000/specs/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 1,
    "design_id": "dsn_8Kx2",
    "version": 3,
    "created_by": "usr_ana",
    "created_at": "2026-07-02T18:40:00Z",
    "jewelry_type": "ring",
    "template": "solitaire_prong",
    "mode": "pro",
    "stone": {
      "species": "sapphire",
      "cut": "oval_brilliant",
      "carat": 2.0,
      "dimensions_mm": {"length": 8.6, "width": 6.4, "depth": 4.1},
      "color": {
        "trade": "Royal Blue",
        "gia": "vivid violetish blue, tone 6, saturation 6",
        "hue_code": "vB", "tone": 6, "saturation": 6
      },
      "clarity": {"system": "gia_type_ii", "grade": "VS", "eye_clean": true},
      "origin": "Sri Lanka",
      "treatment": "heated",
      "phenomena": []
    },
    "setting": {
      "style": "4_prong_basket",
      "prong_count": 4,
      "prong_tip_mm": 0.9,
      "gallery_height_mm": 4.5
    },
    "metal": {"material": "gold", "karat": 18, "color": "yellow", "finish": "high_polish"},
    "band": {"profile": "half_round", "width_mm": 1.8, "thickness_mm": 1.6},
    "ring_size": {"system": "US", "value": 6.5, "inner_diameter_mm": 16.9},
    "side_stones": [],
    "notes_to_factory": "Slightly higher gallery to clear a future wedding band."
  }'
```

Change `"carat": 2.0` to `"carat": 5.0` in the payload above to see the density check
reject a physically impossible stone with the computed expected carat and depth. Change
`"trade": "Royal Blue"` to anything unknown to get back the list of valid sapphire trade
terms.

## Layout

| Path | Purpose |
|---|---|
| `data/gemology_vocabulary.json` | Controlled vocabulary — the single source of gemological truth |
| `src/facetta/spec.py` | Pydantic models for Spec Schema v1 |
| `src/facetta/vocabulary.py` | Vocabulary loader + typed accessors |
| `src/facetta/density.py` | Carat ↔ mm density model (`carat = L × W × D × SG × shape_factor / 200`) |
| `src/facetta/validation.py` | Vocabulary + physical-consistency rules with structured issues |
| `src/facetta/main.py` | FastAPI app: `GET /health`, `POST /specs/validate` |
