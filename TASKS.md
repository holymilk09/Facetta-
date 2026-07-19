# First Sessions — Ordered Tasks

> **Historical work ledger.** This file records completed foundations, acceptance work,
> and remaining gates across many sessions. It is not the current sprint plan and its
> checkboxes are not proof that the present checkout, configured providers, or live
> 8000 → 8081 path is green. Start with `README.md` and
> `docs/REPOSITORY_MAP.md`; use the nearest tests and a real product walkthrough for
> current verification.

## Session 1 — Skeleton + spec truth
- [x] Scaffold FastAPI project (poetry or uv), /health route, pytest wired
- [x] Pydantic models for Spec Schema v1 (docs/SPEC_SCHEMA.md)
- [x] Vocabulary loader for data/gemology_vocabulary.json with typed accessors
- [x] Carat↔mm density validator + unit tests (use SG table in SPEC_SCHEMA.md)
- [x] POST /specs/validate — returns spec or structured 422 with valid options

## Session 2 — Cascading options API
- [x] GET /vocabulary/stones
- [x] GET /vocabulary/stones/{species}/options → colors (trade+gia), clarity system+grades, allowed cuts, phenomena
- [x] Tests: ruby returns Pigeon's Blood set; pearl/opal return their own parameter sets. Jadeite is NOT in the vocabulary yet (open item in CLAUDE.md — needs a grading source before it can be added as data); it 404s with the valid stone list.

## Session 3 — The money feature: SVG sheet
- [x] svg_sheet.py: round + oval solitaire, top view and side profile
- [x] Dimension callouts: stone L×W, band width, gallery height, inner diameter
- [x] Pencil-style rendering (thin strokes, light hatching), title block: design_id, version, date, designer
- [x] Golden-file tests: spec fixture → SVG snapshot, exact dimension text asserted
- [x] GET /designs/{id}/versions/{v}/sheet.svg (+ stateless POST /specs/sheet.svg preview)

## Session 4 — Persistence + collaboration
- [x] Postgres schema: users(role), designs, design_versions(spec JSONB, immutable), comments(version, x%, y%, view, body), share_links(design, version, scope)
- [x] Immutability enforced at API layer (no PUT on versions)
- [x] Share link opens read-only sheet + comment thread

## Session 5 — Claude API layer
- [x] POST /specs/from-prose — Claude API, system prompt embeds vocabulary constraints, must return JSON matching Schema v1, then re-validated server-side
- [x] Property: invalid model output never reaches the DB

## Later (do not start until 1–5 green)
- [ ] CAD/master attachment and viewer for designer- or factory-supplied
  tolerance-bearing geometry; deterministic code must not procedurally invent
  jewelry geometry as the product design.
- [ ] Photo enhance/background-swap via external API
- [ ] Photoreal ControlNet pipeline

## Trusted ring workspace — internal acceptance

- [x] Atomic project creation from a confirmed image.
- [x] QA-gated brief pipeline: concept → read/physicalize → reference-backed
  spec render → Grok correction/FLUX fallback.
- [x] Exact `ImageAsset.design_version` provenance and primary-only visual
  revision numbering.
- [x] Append-only image runs/attempts, structured QA, errors, hashes, latency,
  cache, routing, and optional usage/cost evidence.
- [x] Version-checked markup apply with image/spec atomicity; visual-only edits
  inherit the spec; warnings and failures never promote an asset.
- [x] Exact-revision checklist, auto-pin, project state, and deterministic
  hashed factory pack.
- [x] Feature-flagged, typed desktop/tablet trusted client with mobile review
  behavior, reference draft extraction, warning review, version-aware mobile
  comments, and Jest/React Native Testing Library coverage.
- [x] OpenAPI route/import inventory and staged deprecation metadata.
- [x] Ring golden-set preflight and release-gate harness.
- [x] Designer-common-edit matrix with deterministic edit domains, frozen
  facts, domain-specific prompts, and independent Grok Vision QA gates.
- [x] Atomic full side-stone inventory edits and coupled center-shape/setting
  edits with stale-version and rollback coverage.
- [x] Per-field reference-dimension provenance, `EST.` sheet labels, factory
  manifest disclaimer, and designer-adjustment promotion.
- [x] Generic component-catalog contract and typed chain-style catalog; exact
  cable/curb/etc. selections freeze every unselected necklace fact.
- [x] Persisted ring catalog-selection endpoint with active-version guards,
  deterministic-only spec authorship, option-specific image isolation, atomic
  image/spec/run commit, and temporary warning review.
- [x] Stable-ID design-form contract and saved-mask Art Deco → smooth shoulder
  workflow: normalized form intent, exact one-element scope, QA, atomic
  image/spec version, accepted-byte hash binding, warning review, and explicit
  visual-reference factory blockers.
- [x] Source-component coverage contract for imported design plates and
  finished-jewelry photos. Every represented component receives a stable
  mapping; the blind audit adds anything missed. Unresolved, unaudited, failed,
  and inconclusive coverage blocks spec-aligned rendering and factory release
  while legacy history remains readable. Mappings to paths removed by a later
  spec edit fail closed before re-audit, rendering, or handoff.
- [x] Blind-first independent source audit: expectation-free component
  inventory, bidirectional mapping, explicit unmapped-component records, and
  content-addressed evidence with no dimension/CAD inference.
- [x] Trusted desktop/tablet action for a QA-checked beauty render from a
  designer-confirmed imported reference; phone remains review-only.
- [x] Necklace chain-style routing with construction-specific factory fields,
  explicit target stock/custom references, whole-chain QA, optimistic version
  guards, atomic pass persistence, and temporary warning review.
- [x] Server-side normalized source-region isolation for multi-view plates,
  exact crop propagation through retry, and strict confirmed/colored line-art
  QA that rejects count, geometry, output-hygiene, and presentation drift.
- [x] Staged canonical prompt-to-project harness with provider-free preflight,
  offline pass/warning/failure matrix, explicit test-only warning acceptance,
  image-run evidence, and terminal atomicity assertions.
- [x] Strict necklace live harness with complete component audit for a clean
  single-design control and a fail-closed unresolved multi-design negative
  control.
- [x] Neutral drawing/image creative intake with one-to-four QA-gated render
  candidates, explicit candidate promotion, and no pre-spec factory authority.
- [x] Category-neutral free-form prompt intake with one-to-four QA-gated visual
  directions; prompt projects create no fake source, spec, or factory authority
  and reuse the exact selected-candidate promotion path.
- [x] Live category-neutral necklace prompt proved Grok-first count rejection,
  targeted correction, and OpenAI fallback. The 92-scored fallback remained
  review-only and was human-rejected for wrong diamond shapes/cropped chain;
  a later Grok-first candidate preserved the complete piece, exactly five
  marquise emeralds, round diamond accents, and one tapered drop.
- [x] Exact prompt-candidate necklace factory-gate E2E: corrected category and
  custom-form spec, blind re-audit with bounded invalid-contract retry,
  explicit confirmation of raster-inconclusive facts, immutable promotion,
  checklist/pin, preliminary review SVG, and 409 DXF/factory-pack refusal for
  unresolved dimensioned vine geometry and chain production reference.
- [x] Inconclusive source-component confirmation bound to exact source bytes;
  failed/missing audits remain non-overridable. Accepted QA edit runs provide
  an exact hash-to-hash evidence lineage instead of rewriting old audits.
- [x] Live low-information ring proof through isolated yellow-to-rose edit,
  warning review, immutable spec v2, checklist, pin, and deterministic factory
  ZIP. Factory schedule pages paginate without truncation and estimates remain
  visibly non-measurements.
- [x] Review-only ecommerce marketing packs with partial-failure isolation and
  no effect on the approved primary revision.
- [x] Trusted desktop/tablet creative-first UI: any valid drawing/image can
  request one to four faithful candidates without source grading; the chosen
  server-held candidate can be drafted, mapped, audited, explicitly confirmed,
  and promoted without re-uploading bytes. Pre-spec candidates cannot enter
  approval or factory phases.
- [x] Trusted multi-preset ecommerce UI discloses the attempt multiplier,
  handles partial failures independently, and saves accepted outputs only as
  derived presentation assets.
- [x] Added `TrustedWorkspaceEntry` as the one-import redesign integration seam;
  no redesign-owned file was modified while its worktree remains dirty.
- [x] Designer-confirmed dimensioned full-assembly profile variant for
  freeform metal contours: explicit millimeter paths/thickness/datum,
  supplied-vs-estimated status, deterministic custom sheet substitution,
  manifest/fact-plan disclosure, and profile-only DXF conversion. Partial
  profiles and visual-reference-only definitions remain factory blockers;
  uploaded native CAD assets are still deferred.
- [x] Pre-promotion custom-profile confirmation route and typed client: binds
  designer-entered millimeter geometry to exact server-held creative candidate
  bytes/actor/time, changes the visual-spec hash when geometry changes, and
  requires source re-audit before the updated draft may promote.
- [x] Professional multi-view necklace plate compiler and live regression:
  inventories one finished piece across repeated views, preserves physical
  stone-group roles/count status/handwritten labels, retains assembly-named
  omitted gem groups as blockers, and never treats generic `white metal` as a
  confirmed 18k white-gold factory fact.
- [x] Exact multi-view drawing source isolation for creative beauty renders:
  retains the full plate plus an immutable crop asset, binds candidate/run
  provenance to the crop hash, and uses two prompt-diverse region-by-region QA
  audits. Live proof caught an attractive topology/cut false negative, converted
  it into a targeted Grok correction, and returned the improved image for
  designer review without manufacturing authority.
- [x] Typed Factory Facts draft editor replaces raw JSON as the primary
  confirmation interaction for essential stone, count, dimension, metal,
  setting, ring, and necklace fields. Measured versus estimated dimension
  provenance drives the dynamic sheet/fact-plan authority and any edit makes
  the previous source audit stale; JSON remains available only as Advanced.
- [x] Controlled draft component selections reuse the canonical backend
  catalogs for center cut, complete alloy/color, center setting, and chain
  style. Coupled and derived fields compile together without provider work;
  invalid, category-incompatible, and no-op selections fail before mutation.
- [x] Cascading center-gemstone draft selection uses controlled vocabulary
  species and per-species trade colors, clears incompatible grading/origin
  claims, freezes geometry/count/cut, and recalculates modeled carat. Unknown
  species and cross-species colors fail before draft mutation.
- [x] Provider-free dimensional-diagram preview in creative candidate review:
  renders the exact unpersisted Factory Facts through the canonical SVG
  compiler, remains visibly schematic/not-production geometry, and becomes
  stale after any draft change. Generic circles/outlines are never promoted as
  a factory-acceptable drawing.
- [x] Complete non-dimensional factory fact schedule and release gate: stone
  mount/grading/treatment, band profile, ring-size system, chain construction/
  production reference, component counts, custom-form authority, and factory
  instructions remain typed, losslessly paginated, explicitly approved, and
  block pack generation while pending.
- [x] Transform- and curve-aware DXF R12 exchange: nested transforms plus
  quadratic/cubic/arc sheet paths convert deterministically across all ten
  current templates; unsupported SVG fails closed. Representative geometry was
  visually compared, while DXF remains correctly non-authoritative.
- [x] Honest live image-agent scorecard plus localized-edit false-positive
  correction: the harness records its actual FAL/OpenAI fallback, focused
  diagnostics can reuse a hashed reviewed source, and deterministic band
  silhouette/framing evidence can veto vision judges. Current band-width live
  evidence still fails after three attempts rather than accepting camera,
  scale, prong, or composition drift.
- [x] Conservative band-localization foundation: designer masks carry explicit
  provenance; eligible chromatic-center front views can derive a hashed shank
  suggestion that protects center components and excludes reflections; OpenAI
  composites with inward-only feathering and exact outside-mask pixels. Live
  evidence improved preservation but still failed width/artifact gates, so band
  geometry is not marked reliable.
- [x] Atomic exact side-stone inventory contract and skeptical count gate:
  add/remove/count operations carry exact source/target groups, the primary
  comparison reports complete versus occluded counts, and an independent blind
  count can veto expectation-biased agreement. The focused 19-to-18 halo live
  run failed safely across Grok and OpenAI and persisted no candidate; exact
  inventory editing remains a model-reliability gap, not a claimed success.
- [ ] Replace the final visual factory-sheet role with a design-derived
  technical illustration workflow that shows the actual piece's setting,
  seats, prongs, gallery, joints, thickness transitions, hidden construction,
  sections, and assembly—not generic template geometry. Keep confirmed facts
  code-lettered; require designer review and a CAD/master reference before any
  production-ready claim.
- [x] Integrate the trusted contracts into the redesign through the typed
  Studio gateway and four-destination navigation without transplanting the
  large trusted screen or overwriting redesign-owned presentation files.
- [ ] Run the complete frozen ring matrix with the configured OpenAI fallback
  (or FAL when added), named canonical-API persistence evidence, and no source
  overrides. Focused OpenAI fallback is live; band geometry still fails safely.
- [ ] GIA-trained cofounder review of evaluator false positives/negatives.
- [ ] Founder acceptance scenario, then remove only compatibility code whose
  callers and replacement coverage satisfy the documented deletion gates.

## AI-first studio convergence — target work

Architecture: `docs/ai-first-studio-architecture.md`. These items extend the
verified trusted foundation; unchecked items are not implemented claims.

- [x] Document the AI-first product loop, hierarchy, authority boundaries,
  optional factory lane, destinations, and legacy removal criteria without
  rewriting current evidence.
- [x] Add an additive `DesignFamily` grouping model and APIs. Treat existing
  Projects as variations and preserve every immutable asset/spec revision and
  historical link.
- [x] Wire the redesign around global Studio, Collections, Activity, and Learn
  navigation with contextual Create, Vary, Refine, Views, Present, and More;
  keep Factory as an eligible optional exact-revision destination.
- [ ] Unify current render, reference-render, line-art, product-photo, and
  marketing operations behind an on-demand visual-twin contract with exact
  source-revision provenance and category-safe QA.
- [ ] Build the cross-category component graph: stable component IDs,
  relationships, view-aware masks, frozen neighbors, authority, and catalog or
  custom references.
- [ ] Add the instant masked configurator for geometry-preserving previews.
  Deterministic code may select/mask/composite recorded pixels but may not draw
  jewelry geometry or convert a preview into factory truth.
- [ ] Route shape, topology, count, setting, mounting, shank, and chain changes
  through structural AI edits with source/candidate vision comparison and
  atomic image/spec revisions.
- [x] Add explicit Client, Marketing/Ecommerce, Library, and optional Factory
  destinations. Preserve exact-revision provenance, require review before Save,
  and fetch protected exports only after an authenticated user action.
- [ ] Integrate and live-test design-derived mounting/section QA before any AI
  technical view can be retained as a designer-confirmed discussion artifact.
- [ ] Remove generic deterministic jewelry-geometry routes only after all
  callers migrate, replacements pass stronger tests and diverse founder review,
  OpenAPI removals are approved, and historical packs/migrations remain
  readable. Retain deterministic masks, measurements, validation, schedules,
  layout, manifests, and hashes.

## Definition of done, per task
Tests pass, run instructions in README, founder can exercise it via curl or the
simplest possible page — no feature is done if only code exists.
