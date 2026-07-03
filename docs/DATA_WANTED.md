# Data wanted — research shopping list

What Facetta still needs, in priority order. Each item says exactly what to
ask for, the format that drops into the system unchanged, and how we verify
it. Always ask for **source URLs per row** so claims can be checked, and for
CSV output with the exact column headers given.

---

## Priority 1 — plugs into existing engines immediately

### 1. Real GemCad `.ASC` files for marquise, trillion, pear, radiant
Ours are reconstructed from tier angles; genuine files would replace them
drop-in, no code.

- **Ask for:** complete `.ASC` (ASCII) file *contents* — not screenshots, not
  summaries — for one standard design each: marquise brilliant, trillion
  brilliant, pear brilliant, radiant. Round/oval/cushion upgrades welcome too.
- **Must have:** every `a` line in the form `a <angle> <distance> <index …>`
  — the **distance** (second number) is mandatory; angle-only files cannot be
  reconstructed. Also `g 96 0.` (index gear) near the top, and 90° girdle
  lines present.
- **Source + license:** only from FacetDiagrams.org's open catalog or the
  USFG public design directory, and only designs marked free to
  use/public-domain. Capture the design name, designer, and source URL —
  competition designs on The Gemology Project often carry designer copyright;
  skip anything without a clear license.
- **Verify:** we parse it; if the stone doesn't close, the file was partial.

### 2. Jadeite grading framework (draft for co-founder approval)
The one vocabulary hole we won't invent. Gemini gathers the standard
framework; the GIA-graduate co-founder approves/edits before it ships.

- **Ask for:** CSV `grade_type,id,display,definition,trade_note,source_url`
  covering three scales: **treatment type** (Type A / B / C / B+C, what each
  treatment is), **translucency** (opaque → semi-translucent → translucent,
  with the trade terms like "glassy"), **texture** (fine / medium / coarse,
  crystal-grain basis). Plus the color trade terms (Imperial Green, Apple
  Green, Lavender, Ice…) each with a plain-language color description we can
  map to hue codes.
- **Verify:** co-founder sign-off; nothing enters the vocabulary before that.

### 3. Setting-style geometry table
We only have prong baskets. Every new setting style needs numbers, not names.

- **Ask for:** CSV `style_id,display,min_metal_contact_pct,seat_depth_pct,
  wall_or_prong_thickness_mm_min,stone_protrusion_pct,suits_cuts,
  suits_stone_mm_range,note,source_url` for: **bezel** (full + half),
  **channel**, **pavé** (incl. micro-pavé bead sizes), **flush/gypsy**,
  **tension**, **bar**, **cathedral shoulders**, **east-west**.
  Example row: `bezel_full,Full Bezel,100,10,0.35,55,"round,oval,cushion",
  3-12,"wall wraps girdle fully; adds ~0.5 mm to face-up size",<url>`
- **Verify:** every number in mm or %, nothing qualitative-only.

### 4. Prong sizing vs stone size table
Needed so validation can reject a 0.8 mm prong on a 3 ct stone.

- **Ask for:** CSV `stone_diameter_mm_min,stone_diameter_mm_max,prong_count,
  prong_wire_diameter_mm,tip_diameter_mm,source_url` — the bench-jeweler
  standards (e.g. 4-prong 6.5 mm round → ~0.9–1.0 mm wire). Include 4-prong
  and 6-prong rows from 3 mm to 12 mm stones.

---

## Priority 2 — unlocks new features

### 5. Chain & finding physical dimensions
We have chain *styles* as vocabulary; drawings need real cross-sections.

- **Ask for:** CSV `chain_style_id,gauge_name,wire_diameter_mm,link_length_mm,
  link_width_mm,weight_g_per_cm_silver,weight_g_per_cm_14k,typical_use,
  source_url` for cable, curb, figaro, rope, box, snake, wheat, singapore in
  2–3 common gauges each. Same for clasps: `clasp_id,overall_length_mm,
  ring_inner_diameter_mm,min_chain_gauge_mm,source_url`.

### 6. Cabochon & rose cut profile standards
Our last two non-diagram cuts.

- **Ask for:** dome height as % of width for low/medium/high cabochon domes,
  base thickness minimums, girdle edge angle; for rose cut: number of facet
  rows for 12/24-facet roses, crown height %, flat-base convention. CSV
  `cut_id,variant,parameter,value,unit,source_url`.

### 7. Costing model structure (not live prices)
So estimates work offline; live prices come later via an API.

- **Ask for:** the *formula structure* factories/appraisers use: casting loss
  percentages by metal, typical labor pricing units (per-stone setting fees
  by setting type and stone size, per-piece finishing), findings cost
  categories, and typical retail markup ranges (keystone etc.). CSV
  `cost_component,basis,typical_value,unit,applies_to,source_url`.

### 8. Additional metal alloys
- **Ask for:** CSV `alloy_id,display,composition,density_g_cm3,karat_or_purity,
  colors_available,hallmark_stamp,tarnish_or_wear_note,source_url` for:
  10k gold, palladium 950, platinum 900 vs 950, argentium silver, sterling
  vs fine silver. (We have 9/14/18/22/24k gold, Pt, sterling-equivalent.)

---

## Priority 3 — later, nice to have

### 9. Pearl & opal grading scales
Luster grades, nacre thickness mm bands, surface grades (pearl); play-of-color
pattern names, body tone scale N1–N9, brightness scale (opal). CSV per scale
with `id,display,definition,source_url`.

### 10. Fancy-color diamond grading
GIA fancy grades (Faint → Fancy Vivid) with modifier structure, for when a
client asks for a fancy yellow radiant. CSV `grade_id,display,definition,
source_url`.

---

## Format rules for everything above

1. **CSV with the exact headers given**, one concept per row, no merged cells.
2. **Numbers in mm, %, or g/cm³** — never "small" or "thin" without a number.
3. **A source URL on every row.** No URL, no ingest.
4. Unknown/varies → leave the cell empty, don't guess.
5. `.ASC` files: paste full raw text, fenced, one file per design.

## Explicitly NOT needed from Gemini

- Shape factors / density data (ours are verified), ring size conversions,
  culet/girdle scales, manufacturing tolerances — already ingested.
- Live metal/stone prices (needs an API feed, not research).
- Image-generation API access (needs an account/key, e.g. fal.ai or
  Replicate — that's a signup, not a search).
