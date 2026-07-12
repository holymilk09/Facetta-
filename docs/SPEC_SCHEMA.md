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

| `stone.table_pct` / `depth_pct` / `girdle` / `inscription` | Gem-ID data: table and depth percentages (depth% must match the mm within ±2.5), girdle word from the vocabulary scale, laser inscription text |
| `bracelet.gap_width_mm` | Open-cuff wrist opening (its presence makes the piece a cuff; must stay smaller than the inner width) |
| `bracelet.link_count` | Articulated bracelet; link pitch = band centerline perimeter / count (derived, dimensioned on the LINK DETAIL sub-view) |
| `chain` | `style` and `clasp` from the vocabulary `findings` section, `length_mm` ∈ [300, 900] — its presence turns a pendant into a necklace. Additive `geometry` and `production` records establish physical and procurement/fabrication truth; their absence remains readable legacy data but blocks trusted factory release. |
| `design_form` | Stable designer-confirmed components: ID, role, label, declarative form, symmetry/instances, and normalized per-view isolation polygons. A definition is either exact `visual_reference_only` bytes or one explicit designer-confirmed millimeter `dimensioned_profile`; pixels are never promoted into geometry automatically. |
| `source_component_coverage` | For new imported plates and finished-jewelry photos: represented components have stable canonical mappings and the blind audit adds any visible omissions, with per-component evidence. Missing field means legacy provenance; no guessed backfill. |
| `dimension_provenance` | Per numeric field, records designer-confirmed input versus a reference estimate and its method/source/confidence. |

`setting` and `metal` are now optional at the schema level; every template except
`loose_stone` requires them via validation (a loose stone has no mount).

Templates: `solitaire_prong` and `halo_prong` (rings — require `band` + `ring_size`),
`love_bangle` / `cuff` / `link_bracelet` (require `bracelet`, plus gap or link count),
`cluster_pendant` (requires `pendant`; accepts `chain`), `loose_stone` (stone only).

### Necklace chain manufacturing record

A chain style is a catalog/visual family, not a fabrication recipe. New trusted
necklace releases carry both:

Field names follow the trade definitions in Rio Grande's
[Anatomy of a Chain](https://www.riogrande.com/knowledge-hub/articles/anatomy-of-a-chain/):
chain width, link inside dimension, end-ring outside dimension, clasp, link
thickness, and link length.

- `chain.geometry`, discriminated by construction. `open_link` records chain
  width, finished profile thickness, end-ring outside diameter, link-section
  thickness, soldered/unsoldered state, and one standard link repeat (plus a
  long repeat for Figaro) with outside length and inside length/width.
  `stranded` records the overall envelope, strand-wire diameter and strand
  count. `smooth_plate` records the overall envelope and plate thickness. Rope,
  wheat, Singapore and snake are never coerced into open-link measurements.
- `chain.production`, either a stock `supplier_sku`/`approved_sample`, or a
  custom `dimensioned_drawing`/`cad_asset`. This is required because the
  dimensions represented here do not, by themselves, define every rope,
  braided or smooth-chain fabrication operation.
- `chain.pendant_connection`: `slides_through_bail`, `fixed_to_bail`, or
  `split_chain`. The 0.2 mm bail-assembly clearance applies only when the full
  chain profile must slide through the bail; fixed and split constructions do
  not inherit that false assumption.

Every numeric leaf uses the normal exact dotted/indexed provenance paths, such
as `chain.geometry.chain_width_mm` and
`chain.geometry.links[0].inside_length_mm`. Reference-derived values remain
`estimated_from_reference` and appear as `EST.` on the deterministic sheet.
Legacy chains containing only style/length/clasp still validate and render
byte-for-byte as before, but factory-pack generation refuses to call them
manufacturing-complete.

The persisted `chain.style` catalog endpoint requires a complete target
`chain_geometry` and `chain_production` payload. It never derives dimensions
from the selected style, reuses a source-style supplier SKU/sample, or clears a
production record. Submitted target dimensions receive exact
`designer_confirmed` provenance; production identifiers persist in the
immutable spec but are excluded from image prompts and visual cache identity.

### Visual-form and source-coverage factory gates

A `design_form` element supports two deliberately separate definitions:

- `visual_reference_only` pins the accepted raster and normalized regions for
  image isolation. It establishes no spline, thickness, tolerance, or
  millimeter contour and therefore blocks factory release.
- `dimensioned_profile` records exactly one complete front-assembly geometry
  in an `x_right_y_up` millimeter datum. It contains uniquely identified closed
  outlines and/or width-bearing open construction centerlines, profile
  thickness, exact source asset/hash, confirmation actor/time, manufacturing
  notes, and either `designer_supplied` or
  `designer_confirmed_estimate` status. Partial profiles are intentionally not
  accepted yet because they cannot be positioned against unrelated template
  geometry without a shared manufacturing datum.

The dimensioned profile replaces the generic template drawing in the factory
SVG. Its actual view scale is written into the title block, overall dimensions
are called out, and every estimated coordinate/width/thickness appears in the
manifest and fact plan. DXF conversion selects only the confirmed custom
profile layer; concealed template geometry is never exported. The system does
not derive this profile from an image—the designer must supply or explicitly
confirm the millimeter record.

For a new designer plate, `source_component_coverage.components[]` uses a
stable `component_id`. Exactly one of `canonical_spec_paths` or
`unresolved_reason` must be present. Mapped components also require a passing
`independent_component_audit` before factory release. A failed or inconclusive
audit remains a blocker. Organic components may map to a stable path such as
`design_form.elements[shoulder_architecture]`; no coverage record may carry
guessed dimensions or CAD data.

### Stacking

`nesting_clearance(spec_a, spec_b)`: two bangles/cuffs → per-axis clearance
`(outer opening − inner envelope) / 2` (negative = does not nest); two rings →
combined stack height (band widths) + inner-diameter delta. Exposed as
`POST /specs/stack.svg` and
`GET /designs/{id}/versions/{v}/stack/{id2}/{v2}/sheet.svg`, both rendering the
overlay STACKING SHEET with clearance dims.

### Blueprint alignment

Every sheet draws its views centered on a shared horizontal datum (y = 105 on
the A4 landscape page, drawn as a dash-dot line), and every dimension witness
line must start exactly on a shape edge — enforced by
`tests/support.py::assert_witness_lines_snap` across all templates.

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
