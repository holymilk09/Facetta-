# Design Spec Object — Schema v1

The hub of the whole system. Stored as JSONB, validated with pydantic, immutable per
version. All linear dimensions mm, weights ct.

## Example
```json
{
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
  "metal": {
    "material": "gold", "karat": 18, "color": "yellow",
    "finish": "high_polish"
  },
  "band": {"profile": "half_round", "width_mm": 1.8, "thickness_mm": 1.6},
  "ring_size": {"system": "US", "value": 6.5, "inner_diameter_mm": 16.9},
  "side_stones": [],
  "notes_to_factory": "Slightly higher gallery to clear a future wedding band."
}
```

## Validation rules
| Rule | Behavior on failure |
|---|---|
| species/cut/color.trade/clarity.grade ∈ vocabulary | 422 + list of valid options for that stone |
| carat ↔ dimensions_mm within ±12% of density model for species+cut | 422 + computed expected mm (or expected ct) |
| phenomena allowed for species (per vocabulary `phenomena` map) | 422 |
| clarity.system must match species (Type I/II/III, jade, pearl, opal) | 422 |
| ring inner_diameter_mm consistent with size system value | auto-derive if absent, reject if contradictory |
| band.width_mm ∈ [1.2, 8.0]; prong_tip_mm ∈ [0.6, 1.5] | 422, manufacturability bounds |

## Density model (carat ↔ mm)
`carat ≈ L × W × D × SG × shape_factor / 200` — SG (specific gravity) and per-cut
shape factors live in the vocabulary file (add `sg` per species: diamond 3.52,
corundum 4.00, emerald 2.72, spinel 3.60, tourmaline 3.06, topaz 3.53, zircon 4.65,
garnet 3.6–4.3 by variety, chrysoberyl 3.73, quartz 2.65).

## Additive extensions (v1, multi-stone archetypes)

All optional — existing specs are unaffected; `schema_version` stays 1.

| Field | Meaning |
|---|---|
| `stone.count` (default 1) | Number of identical stones in the group; `carat` is per stone |
| `stone.position` | Placement of a group: `"halo"`/`"surround"` (around the center), `"stations"` (spaced on a bangle), `"under_center"`/`"drop"` (below the cluster) |
| `bracelet` | Oval bangle: `inner_length_mm`, `inner_width_mm`, `width_mm` ∈ [3, 12], `thickness_mm` ∈ [1.5, 4] |
| `pendant` | `bail_inner_diameter_mm`, `bail_height_mm`, `drop_mm` (derived when absent: bail + 1 mm link + cluster + 1 mm link + drop stone) |

Templates: `solitaire_prong` and `halo_prong` (rings — require `band` + `ring_size`),
`love_bangle` (requires `bracelet`), `cluster_pendant` (requires `pendant`).

### Physical-fit rules (422 with the feasible maximum)

| Rule | Model |
|---|---|
| Surround/halo stones fit around the center | `count × (stone width + 0.2 mm gap) ≤ halo centerline perimeter` (Ramanujan ellipse approximation, 0.3 mm off the center girdle) |
| Bangle stations fit on the band | `count × (stone width + 1 mm) ≤ band centerline perimeter`; stone width ≤ band width − 1 mm |

## Versioning
| Action | Result |
|---|---|
| Any edit | New row, version+1, prior versions untouched |
| Share link | Points to (design_id, version) — never "latest" implicitly |
| Comment | Anchored to (design_id, version, x%, y%, view) on the sheet |
