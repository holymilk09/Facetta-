# Project status — read me first in a new session

Last updated: 2026-07-03 · branch `claude/new-session-ajtbwj` · 164 tests passing.
Read `CLAUDE.md` (constitution — binding), `README.md` (endpoints/layout),
`docs/DATA_WANTED.md` (open research asks). This file is the delta: what is
DONE beyond the original TASKS.md build order, and what is next.

## Built and verified (beyond TASKS.md sessions 1–5)

- 8 sheet templates (solitaire, halo, love bangle, cuff, link bracelet,
  cluster pendant, pendant necklace, loose-stone Gem ID) + stacking overlay,
  all on a shared baseline with witness-line snap tests and golden files.
- GemCad .ASC facet engine (`facetta/gemcad.py`): parses real exports (signed
  angles, interleaved names), reconstructs stones by half-space intersection,
  projects exact face-up layouts. All 10 faceted cuts have diagrams in
  `data/facet_diagrams/` — `oval_brilliant.asc` is a genuine published design
  (Robert H. Long 1991), NEVER overwrite it. Fabricated research data gets
  rejected with evidence (see commit e853dc7).
- Color prototypes with per-facet-normal lighting, sheen, gradient ground
  shadow. Sheets stay pencil-clean; KEY/legend footer; label halos.
- Mockup engine (`facetta/mockup.py`): scene-controlled render requests
  (lighting x worn-on x photo/atelier-sketch style), seed locked to a
  geometry-only fingerprint so color/metal swaps keep the composition.
  Restage + from-photo endpoints exist. NOT yet wired to a provider —
  waiting on a fal.ai API key (plan: FLUX ControlNet for hero renders,
  FLUX Kontext for single-parameter edits).
- Validation beyond density: alloy logic (silver/platinum carry no karat or
  color), halo/station fit, cuff gap, depth/table %, girdle weight
  correction, culet scale, intl ring sizes (US/UK/EU/JP/HK), gallery-vs-
  culet clearance (factory rule).
- Factory handoff: DXF R12 export (stateless + stored versions), share
  links with pinned comments, per-design designer/factory Discussion thread.
- App (Expo, `mobile/`): category builder (Basic/Pro), proportional resize
  with carat re-estimate, collections + search + category filters, mockup
  scene compiler UI, tablet two-pane layout.

## Next (in priority order, agreed with founder)

1. **Supabase accounts** — founder has a project; waiting on Project URL,
   anon key, DB connection string. Plan: DATABASE_URL -> Supabase Postgres,
   JWT verification middleware, designs owned by users, login screen in app.
   Factories stay account-less via share links.
2. **fal.ai wiring** — render.png endpoint + cache by (geometry_fingerprint,
   scene, style). Payloads are already compiled by /specs/render-request.
3. Jadeite vocabulary — BLOCKED on co-founder approval, never invent it.
4. Real .ASC files for marquise/trillion/pear/radiant (ours are angle-true
   reconstructions; genuine files drop into data/facet_diagrams/ unchanged).

## Conventions a new session must keep

- Vocabulary changes are additive, formatting-preserving, data-only.
- Golden files regenerate only for intentional visual changes, then get
  visually verified (Chromium screenshots) before committing.
- Every geometry function gets a spec-X-gives-dimension-Y test.
- Never put model identifiers in committed artifacts.
- Do not reorder or skip validation: spec -> validate -> render, always.

## Render pipeline — ready, awaiting network (2026-07-05)

Everything for photoreal rendering is built and tested (203 tests):
`POST /specs/render.png` with `?model=flux_kontext | grok_imagine | grok_direct`.
Keys are expected as env vars `FAL_KEY` and `XAI_KEY` (or a local gitignored
`.env`). The workspace network policy must allow: fal.run, fal.media, api.x.ai.

First action once network is open: render docs/examples/twilight_pendant.json
through all three models, compare against the fidelity checklist (14 surround
stones alternating, claws/cap as drawn, no invented text), send images to the
founder.

2026-07-06 v7 — GROK-PAINTED BLUEPRINT SHEET + EDIT-LOOP AGENT (founder:
"ours looks unfinished, are we even using Grok/an agent?" — answer was no
on both; the sheet was the one output the engine never touched). The fusion,
finally applied to the sheet itself:
- Ring views (svg_sheet) split into geometry/annotation layers via a `mode`
  param; mode=full is byte-identical so every golden held. render_sheet_
  geometry() = the piece, zero lettering; render_blueprint_frame() letters
  the dims/key/title over a background image (_frame gained a `background`
  arg). ARTWORK_STYLES['blueprint'] = graphite technical illustration.
  blueprint.py: geometry raster → Grok blueprint restyle → full-bleed image
  behind the code-drawn numbers. POST /specs/blueprint-sheet.svg + versioned
  route. The crisp master stays /sheet.svg (instant, offline, DXF-exact).
  Verified live: Grok shaded the ruby ring's three views, our numbers
  lettered on top and aligned. Note: geometry control is monochrome line-art,
  so Grok paints a graphite (colorless) rendering — correct for a blueprint.
- agent.py: plan_edit(instruction, current_spec) → EditResult via Claude
  (translation only; reuses prose.py vocabulary digest). POST
  /designs/{id}/edit — Claude edits, the VALIDATOR gates, a real edit becomes
  a new immutable version, an impossible one (0.20 ct marquise) is REJECTED
  422 with the density correction and NOTHING is saved. Multi-turn memory =
  the version chain. Isolate highlight: render_sheet(spec, highlight_ref) and
  ?highlight= ring the changed stone in red ("ISOLATED · A"). Constitution
  held: Claude never letters a number into the record; the validator does.
  LIVE agent needs ANTHROPIC_API_KEY (like FAL/XAI); without it the endpoint
  returns a clean 503. 262 tests.

2026-07-06 v6 — TECHNICAL SHEET FORMAT v2 (founder audit vs an AI restyle
of our own sheet: better format, fictional data — adopted the format,
kept the record). Ring renderers rebuilt: halo top view draws EVERY
surround group cut-true and interleaved (marquise sunburst petals radial,
rounds nested; per-stone radial seat by cut); front view carries the
shoulder-pavé column and side profile the pavé arcs (count-true per
side), comfort-fit pointer; GEMSTONE KEY & PRODUCTION NOTES table with
circled refs Ⓐ–Ⓓ matching in-view annotation pointers, per-entry and
grand carat totals; drafting-grid paper (in <defs>, zero DXF pollution —
guarded by test), pavé KEY sample, CONFIDENTIAL footer. All sheet goldens
regenerated and visually verified. Deferred, next milestones: users/roles;
builder–designer chat; chat image-annotation toolbar (arrows/boxes/
labels/mm) — annotations must be structured DATA re-letterable by the
overlay engine, never baked pixels; and the Grok-style edit loop.

2026-07-06 v5 — BRANDED FACTORY SHEET FROM ANY RENDER (founder test:
deco drop earring, docs/examples/deco_drop_earring.json). The annotated
sheet is now template-agnostic with a FACETTA masthead: generic stone
tracer (trace.trace_stones — green/blue color classes, fragment
containment filter), callouts matched per schedule entry by traced size
scaled through the center stone, side-exiting labels, dimensions box
driven by whatever sections the spec carries ("pending designer" when
none), graceful degrade when an image can't be traced (strict only when
an anchor image is explicitly supplied). Mount validator earned its keep:
rejected pavé for 2.2–3.1 mm stones. NOTE the founder's Grok "JEWELRY-OS
agent" proposal: adopt the EDIT-LOOP idea (isolate + adjust + re-render
with the prior render as edit input) — but never LLM-generated spec
sheets or model-lettered dimensions; that is the exact failure the
overlay exists to prevent.

2026-07-06 v4 — ARTWORK-FIRST RENDERING. Founder benchmark: Grok Imagine
CHAT restyled the artwork page more faithfully than our pipeline — because
chat restyles IN PLACE (no re-composition), while its annotations are pure
fiction (garbled words, invented mm, wrong gemology). New split, per the
constitution: engines restyle pixels in place; code letters every number.
- POST /specs/artwork-restyle.png (+ /artwork-restyle-request):
  ARTWORK_STYLES = rendered_color | ink_lineart; instruction forbids
  re-composition and ALL lettering; cached by (image bytes, instruction,
  model). Verified live on the designer's sheet: all three studies in
  place, counts intact, zero text, both styles, both Grok routes.
- POST /specs/annotated-artwork.svg: facetta/overlay.py embeds the artwork
  (or its restyle) and letters it from the VALIDATED SPEC — schedule refs
  shared with the technical sheet, cluster callouts on traced pixel
  anchors (trace_spray_detailed), dimensions box, tolerance from the new
  vocabulary key general_linear_tolerance_mm. Cluster-count mismatch
  refuses to letter ("cannot be lettered honestly").
- render.py: _call_engine extracted; restyle path reuses the engine table.
Note for ink_lineart annotation: pass the ORIGINAL artwork as
anchor_image_base64 (line art has no green ink to trace).

2026-07-06 v3 — ARTWORK TRACING (founder audit: "we have the mathematics but
we are ruining the designer's design"). Root cause found: the drawing's own
vector geometry never entered the system — stages control→engines were
provably faithful, but spec→layout re-synthesized composition from taste
constants. New `facetta/trace.py`: deterministic tracer (no AI) — color
segmentation finds the drawn quatrefoils, picks the master study, walks the
chain terminal-first, infers the diamond cluster's slot from its double gap,
measures reach from the gold foliage. Output = normalized anchors stored in
the spec's new `composition` section (immutable, versioned with the design).
The renderer anchors to it; parametric layout is now only the untraced
fallback. Tracing the artwork CORRECTED the extraction: 6 clusters (not 5),
true graduation ratios, the real ~48° rake (width 62 mm, not 32). Also per
founder: leaves are pointed lenses, dense, both sides; quatrefoil frames hug
each petal's silhouette (NEVER a ring — the drawn circle on the sheet is a
dashed construction envelope only); factory STONE SCHEDULE on the sheet:
each stone definition once, lettered A–K, repeats by reference.

2026-07-06 later — leaf-spray v2 after founder review ("not matching"): the
lesson is COMPOSITION IS SPEC DATA. v1 hardcoded layout taste (bare wire
stem, sparse one-sided leaves, dangling clusters) and the engines faithfully
rendered the wrong drawing. v2: `brooch.sweep_deg` (plume curvature) in the
schema; barbs on BOTH sides of a tapering vein, slot count from vein length
(a plume is continuous foliage — never derive it from stone count);
quatrefoil garland chained frame-to-frame along the concave edge, terminal
past the tip; petals on the diagonals with beaded frames, as drawn;
graduation carried by four separate station entries in the spec. Extraction
corrected pavé to 190. All three engines now match the artwork.

2026-07-06 — NEW TEMPLATE: `leaf_spray_brooch` (first brooch archetype),
built from the designer's hand-drawn artwork. Additive `brooch` spec section
(length/width), quatrefoil cluster rules (petals in fours, one center per
cluster, row-fits-spray), shared `_spray_layout` driving the ink sheet,
color prototype, control image, and presentation plate; 21 tests + golden.
Cluster order along the branch = side_stones order (designer intent).
Example: docs/examples/leaf_spray_brooch.json — dimensions are DRAFT
proposals from the artwork, pending the designer's corrections. Live
three-engine renders off the control image held all 5 clusters exactly
(direct artwork-as-control renders had each engine inventing elements —
the control-image pipeline is the product, confirmed).

2026-07-05 update — first live renders done, all three engines. Providers now
return images inline (fal `sync_mode`, xAI `response_format: b64_json`) so no
CDN hosts (v3.fal.media, imgen.x.ai) need network allowances — only fal.run
and api.x.ai. Checklist results: grok_direct and grok_imagine pass (both drift
the tanzanite bluer than vB 6/6); flux_kontext keeps the 14-stone surround but
painted the topaz drop as solid metal, duplicated the front view in place of
the side view, and invented a chain. Note: xAI returns JPEG bytes even though
the endpoint is named render.png.
