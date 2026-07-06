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
