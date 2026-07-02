# First Sessions — Ordered Tasks

## Session 1 — Skeleton + spec truth
- [x] Scaffold FastAPI project (poetry or uv), /health route, pytest wired
- [x] Pydantic models for Spec Schema v1 (docs/SPEC_SCHEMA.md)
- [x] Vocabulary loader for data/gemology_vocabulary.json with typed accessors
- [x] Carat↔mm density validator + unit tests (use SG table in SPEC_SCHEMA.md)
- [x] POST /specs/validate — returns spec or structured 422 with valid options

## Session 2 — Cascading options API
- [ ] GET /vocabulary/stones
- [ ] GET /vocabulary/stones/{species}/options → colors (trade+gia), clarity system+grades, allowed cuts, phenomena
- [ ] Tests: ruby returns Pigeon's Blood set; jadeite returns translucency/Type A-B-C; pearl/opal return their own parameter sets

## Session 3 — The money feature: SVG sheet
- [ ] svg_sheet.py: round + oval solitaire, top view and side profile
- [ ] Dimension callouts: stone L×W, band width, gallery height, inner diameter
- [ ] Pencil-style rendering (thin strokes, light hatching), title block: design_id, version, date, designer
- [ ] Golden-file tests: spec fixture → SVG snapshot, exact dimension text asserted
- [ ] GET /designs/{id}/versions/{v}/sheet.svg

## Session 4 — Persistence + collaboration
- [ ] Postgres schema: users(role), designs, design_versions(spec JSONB, immutable), comments(version, x%, y%, view, body), share_links(design, version, scope)
- [ ] Immutability enforced at API layer (no PUT on versions)
- [ ] Share link opens read-only sheet + comment thread

## Session 5 — Claude API layer
- [ ] POST /specs/from-prose — Claude API, system prompt embeds vocabulary constraints, must return JSON matching Schema v1, then re-validated server-side
- [ ] Property: invalid model output never reaches the DB

## Later (do not start until 1–5 green)
- [ ] CadQuery solitaire → GLB; three.js viewer; hand-scale view
- [ ] Photo enhance/background-swap via external API
- [ ] Photoreal ControlNet pipeline

## Definition of done, per task
Tests pass, run instructions in README, founder can exercise it via curl or the
simplest possible page — no feature is done if only code exists.
