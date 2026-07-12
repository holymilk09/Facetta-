# Trusted workflow architecture and consolidation boundary

Status: implementation inventory for the internal ring milestone. This is not
an instruction to delete compatibility code. The old surface remains available
until founder acceptance and the live-image release gates pass.

## Relationship to the AI-first studio

Facetta's global product direction is the AI-first studio loop
`Create -> Explore -> Organize`. The target hierarchy is Design Family ->
Variation -> immutable Revision, with client, marketing, library, and factory
destinations. That broader target, including explicit implemented-versus-
planned boundaries, is defined in
[`ai-first-studio-architecture.md`](ai-first-studio-architecture.md).

This document describes the narrower persisted workflow that exists today. A
current `Project` is the persisted variation container. A first-class Design
Family entity, unified visual-twin command surface, instant masked
configurator, and destination picker are not yet implemented. The trusted
approval/factory sequence below is therefore an optional promotion lane inside
the studio direction, not the required outcome of every creation.

## Implemented trusted promotion boundary

The current persisted workflow is:

```text
Create or promote Project -> Refine exact spec/image pair
  -> optional designer approval -> optional factory review pack
```

The authoritative aggregate for this lane is a `Project` rooted at one
`ImageAsset` chain and linked to one immutable `Design`/`DesignVersion`
history. A primary visual
revision says which exact `design_version` it represents. Derived assets do not
advance the visual revision number. The factory pack is built only from the
approved, pinned asset/spec pair. Its validated JSON and confirmed schedules
are authoritative fact records; the deterministic SVG is only a schematic
dimensional diagram and its DXF is only an exchange reference. Neither is
buildable jewelry geometry. When a confirmed line drawing exists for that exact primary
revision/spec, the pack also includes it as `discussion-line-art.*`; the
manifest marks it non-authoritative and explicitly forbids measurement or
manufacture from it. Until a designer-approved, design-derived technical
drawing or tolerance-bearing CAD/master reference is attached, the manifest
states `factory_review_only`, never production-ready.

The first-slice public boundary is intentionally small:

- Project creation and retrieval: category-neutral `POST /projects/from-prompt`,
  structured-ring `POST /projects/from-brief`, neutral
  `POST /projects/from-drawing`, designer-confirmed `POST /projects/from-image`,
  candidate promotion, persisted `POST /projects/{root_id}/render`, and
  `GET /projects/{root_id}`.
- Ecommerce presentation: `POST /projects/{root_id}/product-photo` executes a
  `VISUAL_ONLY_EDIT`, freezes the jewelry and exact spec version, stores clean
  `PRODUCT_PHOTO` bytes, and sends QA warnings through explicit review.
  `POST /projects/{root_id}/marketing-pack` creates one to four temporary scene
  candidates; accepted outputs are exact-version `MARKETING_IMAGE` derivatives,
  so the approved/pinned primary revision and factory readiness do not change.
- Confirmed drawing stages: `POST /projects/{root_id}/line-art` always pauses
  for designer geometry confirmation; colorization then runs from that exact
  `LINE_ART` asset and spec version. `LINE_ART` and `COLORED_LINE_ART` are
  derived evidence, not primary revisions or factory truth. Approved-source
  material identity is evaluated inside the image-agent loop so corroborated
  loss drives a targeted Grok correction. Cross-modality raster/vision
  disagreement is held as a temporary warning for explicit designer review.
- Brief candidates that receive a QA warning remain temporary and use the
  nested `/projects/from-brief/candidates/{candidate_id}` preview/accept loop;
  concept acceptance continues into spec extraction/rendering before any
  project row exists.
- Persisted annotation: `POST /assets/{asset_id}/markup/read` and
  `POST /assets/{asset_id}/markup/apply`.
- Deterministic component controls:
  `POST /assets/{active_asset_id}/catalog/apply` accepts one stable catalog
  option only against the exact active primary image and immutable spec. The
  catalog compiles the sole factory-spec delta; the image model executes that
  delta under the option's geometry, isolation, and frozen-fact contract.
- Image-agent evidence: `GET /image-runs/{run_id}`.
- Provider routing remains invisible to the product: Grok owns attempts one
  and two; attempt three uses FLUX when configured and otherwise may use the
  OpenAI image adapter. Attempt records always name the provider/model actually
  called, and every fallback candidate passes the same operation-specific QA.
- QA-warning review: the candidate preview and explicit acceptance operations
  nested under `/image-runs/{run_id}/candidates/{candidate_id}`. Candidate
  bytes stay in a bounded temporary cache; acceptance appends a review record
  and atomically persists the exact image/spec revision.
- Designer outcomes use the existing accepted/regenerated/rejected feedback
  vocabulary through `/image-runs/{run_id}/feedback`, so temporary candidates
  contribute learning evidence without becoming product assets.
- Exact-revision approval: the three `/assets/{asset_id}/checklist` operations.
- Factory handoff: `GET /projects/{project_id}/factory-pack` and `.zip`.
- Asset bytes referenced by project payloads:
  `GET /assets/{asset_id}/image`.

The trusted client treats creative rendering and specification authority as
two distinct stages. `CREATIVE_GENERATE` creates independent concepts from a
designer prompt without assuming a ring or inventing a source asset;
`REFERENCE_RENDER` interprets a supplied image while preserving visible source
identity. Both show every persisted `CREATIVE_RENDER` candidate, but
disables approval and factory phases while `design_id` and
`active_design_version` are absent. The chosen candidate is read through a
candidate-bound draft endpoint using its server-held bytes. Mapping correction,
re-audit, and inconclusive-fact confirmation use candidate-bound endpoints too,
so the client never reconstructs or re-uploads the candidate image. Only an
exact audited draft may call the promotion endpoint.

The Advanced specifications experience may continue to use deterministic spec,
vocabulary, version, schematic SVG, and reference DXF primitives. Those endpoints are not an
alternative project workflow and must not start provider orchestration or
silently persist a second chain. Their generic template circles and outlines
must never be presented as the final factory drawing.

## AI pixels, deterministic control plane

The target invariant is that AI creates jewelry geometry and vision checks it.
Deterministic code records, masks, measures, validates, versions, and lays out
evidence; it never designs or draws jewelry geometry. A capable image model
creates and edits the jewelry pixels while deterministic services constrain,
verify, and record the work.

| Owner | Responsibilities | Never treated as |
|---|---|---|
| Image AI | Concepts, photoreal renders, localized visual execution, presentation changes | Factory measurements, approval, or a specification author |
| Deterministic control plane | Validated spec delta, scope grafting, frozen facts, physical checks, masks/drift, QA policy, immutable versions, provenance, supplied measurements, confirmed fact schedules, page layout, and manifests | An aesthetic renderer or source of jewelry geometry |
| Designer | Clarification, warning-candidate review, estimate correction, exact-revision approval | A silent rubber stamp for model-derived geometry |

The existing deterministic SVG/template and DXF geometry is a compatibility
exception, not the target architecture. It remains explicitly schematic or
non-authoritative while design-derived visual and technical-view replacements
are built and accepted. Deterministic code may letter confirmed facts, draw
masks/guides/measurement overlays, and lay out an approved drawing; it must not
draw the ring, stone, prong, gallery, chain, clasp, or setting itself.

The localized edit contract derives its edit family from the validated
source-to-result spec delta, never from marketing labels or model-selected
routes. Current factory-relevant families are center-stone shape,
species/color, side-stone inventory and gem-built motif shape, setting/prongs,
metal identity/finish, band geometry, and ring size. Each family receives its
own execution instructions and independent QA result. A mismatch in any
required family is a hard failure; an unassessable fact is a warning held for
designer review. Presentation-only edits inherit the exact spec version.

Catalog-directed changes use the same localized image-agent and warning
review primitives as confirmed markup, but they do not ask a language or image
model to interpret the requested specification. `apply_catalog_selection` is
the sole spec author. All applicability, option compatibility, no-op, active
asset, and version checks finish before provider work. A pass commits the new
primary image, immutable spec version, and append-only run evidence in one
transaction; a warning exposes the exact next spec and structural diff while
keeping candidate bytes outside the asset/version chain. A necklace chain-style
request must also submit designer-confirmed target `ChainGeometry` and an exact
stock/sample or custom drawing/CAD production record. It cannot reuse a
source-style supplier SKU, silently clear production facts, or reach a provider
when the target construction is incompatible.

Structural candidates and validated spec renders also receive a prompt-diverse
skeptical second audit. The render audit independently checks center identity
and cut, metal, setting style, actual center-prong count, side-stone inventory,
and major components. The edit audit re-compares the whole source/candidate
pair against the exact authorized delta and frozen facts. A secondary observed
mismatch vetoes a primary pass and enters the targeted correction loop; an
unavailable or genuinely unassessable second audit yields a warning rather
than silent promotion. This redundancy costs another vision call, but prevents
a single confident misread from becoming an active design revision.

Component counts use an additional expectation-free pass: the counter sees the
image but not the requested count, reports only the center prongs and side
stones it can actually see, and states whether the view is complete. Code then
compares that observation to the spec. This avoids the demonstrated failure in
which a spec-aware audit confidently called a visibly four-prong ring a
six-prong basket. Every structural edit candidate is also re-audited against
the complete target spec, not only the requested delta.

Some factory facts are not raster facts. In particular, polished white gold
and platinum may be visually indistinguishable in a product image. A
white-metal material substitution therefore updates deterministic spec truth
but always returns a review warning; pixels are never allowed to “prove” the
alloy. A visible metal-color or finish change remains image-gated.

Adding or removing side stones targets the complete `side_stones` inventory,
while aliases such as `halo` still require an unambiguous group. Changing a
center-stone cut is a coupled `stone + setting` scope so the minimum physically
necessary seat/prong adaptation can travel with the new shape. Structural
scope guards discard every model-proposed change outside those allowed
subtrees before validation and persistence.

Arbitrary freeform metal contours now have a deliberately limited structured
contract. Each designer-confirmed component has a stable ID, role, symmetry,
instance count, declarative form description, normalized per-view polygons,
and an exact reference asset ID + SHA-256. For example, “make the Art Deco
shoulders smooth” must target the known shoulder element through a saved
same-raster markup mask. The text planner may normalize the requested result,
but deterministic scope keeps only that one element; the accepted image and
spec version commit atomically and the definition is rebound to the exact
accepted bytes. A warning candidate keeps its reserved asset identity through
explicit designer review.

`visual_reference_only` remains image truth, not invented CAD, so a project may
be visually approved and pinned while remaining `approved` rather than
`factory_ready`. The additive `dimensioned_profile` variant resolves that form
blocker only when a designer supplies or explicitly confirms one complete
full-assembly millimeter profile, thickness, datum, source hash, actor/time,
and manufacturing notes. Estimated profiles stay visibly estimated in the
sheet, fact plan, and manifest. The deterministic sheet substitutes that exact
profile for the generic template, and DXF conversion exports only the custom
profile layer so hidden template geometry cannot reappear in CAD. Partial
profiles and unsupported CAD payloads remain rejected rather than guessed.

Imported design plates and finished-jewelry photos also carry source-component
coverage. Every represented major stone group, setting, metal body, band, and
spatial/form assembly receives a stable exact canonical mapping. The blind
inventory then adds visible components the primary read omitted as explicit
blockers. Mapped items must retain an independent coverage audit. This prevents
a source with visible diamond leaf shoulders from silently producing
`side_stones: []`, passing image QA, and reaching a factory bundle. Legacy
versions without this additive field remain readable and keep their historical
behavior.

The trusted reference client opts into a two-pass audit. Pass one inventories every
visible major component without receiving the expected spec or coverage list.
Pass two reconciles that blind inventory bidirectionally against every stable
coverage ID and canonical path. Unmapped blind items are appended as explicit
failed `audit.unmapped.*` components; failed or inconclusive mappings remain
factory blockers. Evidence hashes bind the source bytes and both raw audit
passes. The audit contract rejects millimeter, carat, CAD, spline, or mesh
claims because component coverage is not dimensional proof.

Canonical-path existence is checked against the exact current draft and again
at project render/readiness/factory boundaries. If a designer removes or
reindexes a mapped group, the historical audit remains history but no longer
authorizes release: `source_component_path_missing` blocks the project, and
re-audit skips the provider until the mapping is corrected.

Reference-derived millimeters are permitted as prototyping starts, not as
measurements. Their per-field provenance remains `estimated_from_reference`,
the sheet labels them `EST.`, and the factory manifest lists every estimated
field plus a verification disclaimer. Only a versioned designer adjustment
promotes a dimension to `designer_confirmed`.

An independent audit may return `inconclusive` for a fact that the source
visibly supports or for a manufacturing target the source never measured.
The designer may confirm only that state; missing and failed audits cannot be
overridden. Confirmation is bound to the exact source bytes and visual-spec
hash. When a later image/spec edit is accepted, Facetta does not rewrite that
historical evidence. Instead, each `ImageRun` records its source and target
visual-spec hashes, and readiness may carry hash-staleness evidence forward
only along the active asset ancestry through accepted QA runs. Any gap,
rejected candidate, hash mismatch, or alternate branch fails closed.

## Component catalogs

Common choices should bypass prose planning entirely. A catalog option owns a
stable ID, designer-facing label, visual geometry, exact factory-field
assignment, image-isolation target, and frozen facts. Selecting an option
therefore compiles directly into one leaf-level spec delta before an image
model is called.

`chain.style` is backed by the controlled findings data for cable, curb,
Figaro, rope, box, snake, wheat, and Singapore chains. A cable -> curb request
changes style plus only the explicitly submitted target geometry/production
record; chain length, clasp, connection mode, pendant, bail, stones, setting,
and metal remain byte-for-byte frozen. The existing
`/vocabulary/findings` response remains compatible.

The ring slice also exposes the most repeated, safely compilable choices:

- `stone.cut` offers round brilliant, oval brilliant, emerald cut, and
  cushion. It preserves exact face-up and depth dimensions and deterministically
  recalculates modeled carat from species SG and the selected cut factor. A
  round/oval choice is rejected when the existing dimensions do not already
  describe that outline; the catalog never invents a new diameter or aspect
  ratio. Cut selection also checks the current setting combination.
- `metal.material` offers complete 14k/18k yellow, white, and rose gold alloy
  presets plus platinum and silver. A bare `gold` option is intentionally
  absent because material alone does not specify karat and alloy color.
  `metal.color` is the smaller one-field control for an existing gold spec.
- `setting.style` couples style, actual prong count, and prong-tip gauge for
  four- and six-prong baskets, full bezel, and semi-bezel. Continuous-metal
  settings clear prong fields; prong-to-prong changes preserve the existing
  designer-confirmed gauge. A bezel-to-prong change is held until that gauge
  is supplied rather than defaulting it. Six-prong selection is limited to
  round and oval centers because corner placement for other outlines requires
  designer input.

Every option states visual geometry, the image-isolation target, exact owned
factory fields, frozen facts, and applicability requirements. Catalog
application runs the normal physical validator and returns the concrete
structural diff without persisting or calling a provider. Pear, marquise,
princess, and other pointed center shapes remain outside the catalog until the
spec can represent V-prong and point-protector placement instead of guessing.
The typed catalogs are available through
`GET /vocabulary/components/{component_path}`.

The trusted image agent's necklace slice is deliberately limited to persisted
`chain.style` localized edits. Planning accepts only style plus companion
`chain.geometry`/`chain.production` deltas, strips procurement identifiers from
prompts and visual cache identity, and applies chain-specific whole-run/drift
QA. This same typed contract can later cover clasps, bails, band profiles,
stone colors, and saved studio components without adding free-text ambiguity
back into the workflow.

## Classification rules

The route inventory uses four classifications:

- **Canonical**: a supported persisted project/revision boundary. Approval and
  factory services are optional promotion paths from an eligible exact
  revision. New product callers may depend on it.
- **Internal primitive**: a retained domain, migration, deterministic drawing,
  or Advanced specifications capability. It may still be HTTP-visible during
  consolidation, but it is not a second workflow entry point.
- **Deprecated compatibility**: has callers or test coverage, but bypasses the
  persisted project/image-agent boundary. Migrate callers, then remove it.
- **Dead/conflicting**: a duplicate alias or compiler/provider control with no
  product reason to remain public. It is still gated from deletion by the same
  acceptance and history checks as deprecated code.

The complete, OpenAPI-checked list is in
[`trusted-workflow-route-inventory.md`](trusted-workflow-route-inventory.md).

The Internet-facing production asset surface exposes only exact revision image
reads, confirmed markup read/apply, and the four approval operations: create or
read the newest checklist, append a response, and explicitly pin. Checklist
creation, response append, and pin all acquire the same Project row lock as
Factory job compare-and-swap. A queued, running, or reviewing Factory job makes
that approval generation immutable; the next generation can begin only after
the job is terminal.

## Canonical service/import direction

Dependencies should point inward in this order:

```text
api/projects.py       api/assets.py       api/trusted.py
        |                    |                    |
        +--------- project/revision services ----+
                             |
                image_agent orchestrator
                  | plan | execute | QA | correct
                             |
             provider transports and cache adapters

factory_pack.py -> immutable project/spec records -> svg_sheet.py + dxf.py
```

The intended import ownership is:

| Path | Classification | Owns | Must not own |
|---|---|---|---|
| `api/projects.py` | Canonical | Project request/response contracts and project HTTP handlers | Provider prompts, transport, or low-level cache logic |
| `api/assets.py` | Canonical shell plus compatibility handlers | Persisted asset reads, markup confirmation, revision/approval HTTP handlers | Direct model routing in canonical handlers |
| `api/trusted.py` | Canonical | Image-run read model and factory-pack HTTP delivery | Image generation or spec mutation |
| `project_backbone.py` | Canonical | Atomic project/spec/asset persistence and primary-revision rules | HTTP responses or provider calls inside DB transactions |
| `image_agent/` | Canonical | Typed plan, versioned prompts, attempt routing, QA, targeted correction | Product approval or database commits |
| `creative_workflow.py` | Canonical | Pre-spec category-neutral `CREATIVE_GENERATE` and source-led `REFERENCE_RENDER` planning/execution | Source-quality labels, factory-spec invention, or persistence |
| `image_run_store.py` | Canonical | Append-only run/attempt persistence without rejected image bytes | Provider calls or project-state decisions |
| `factory_pack.py` | Canonical | Exact approved revision lookup, deterministic files, manifest hashes | AI-authored dimensions or mutable “latest” lookups |
| `factory_sheet_plan.py` | Internal primitive | Structured material, stone, setting, and dimension facts with confirmation/estimate status | Image inference, provider calls, or silent estimate promotion |
| `factory_schedule_pages.py` | Internal primitive | Deterministic paginated schedule SVGs derived only from the approved fact plan | AI-authored facts or fixed-capacity truncation |
| `spec.py`, `validation.py`, `vocabulary.py`, `estimate.py`, `specdiff.py` | Internal primitive | Pure specification facts and validation | Provider-specific behavior |
| `svg_sheet.py`, `dxf.py`, `plate.py`, `prototype.py`, `overlay.py` | Internal primitive | Deterministic or explicitly non-authoritative presentation artifacts | Canonical image-agent routing |
| `prose.py` | Internal primitive | Intentionally retained legacy Claude prose extraction | Photo or localized image-edit orchestration |
| `photo_spec.py` | Internal primitive | Grok Vision imported-reference read followed by deterministic spec completion | Persistence or designer approval |
| `plate_spec.py` | Internal primitive | Rich hand-plate read compiled into a ring draft while preserving stone groups and uncertainty | Factory truth, guessed measurements, or approval |
| `render.py` | Deprecated compatibility adapter | Existing provider HTTP/cache primitives during migration | Product routing, QA policy, or UI-visible model selection |
| `specagent.py` | Deprecated compatibility mega-module | Existing markup, view, drawing, and legacy orchestration until callers migrate; focused vision/prompt/drift helpers are now compatibility re-exports | Continued growth or use by the canonical image agent |
| `agent.py`, `grokedit.py` | Deprecated compatibility | Existing Claude/Grok edit behavior while callers migrate | A second persisted-edit orchestrator |
| `mockup.py`, `blueprint.py`, `drawing_frame.py` | Internal primitive with provider-facing edges to extract | Scene/drawing compilation and presentation | Public provider selection |

## Current coupling evidence

This snapshot exposes the exact reasons deletion is unsafe today:

- `api/specs.py` is 1,222 lines and imports validation, estimation, mockup
  compilation, provider transport, spec-agent vision/edit functions, drawing,
  overlay, SVG, and DXF code.
- `api/assets.py` is 1,642 lines and still imports direct provider and
  `specagent.py` operations for render, views, edits, markup, restyle, video,
  and technical drawings.
- `specagent.py` is 1,745 lines after extracting provider-neutral vision,
  localized-edit prompt, and drift helpers. Tests still monkeypatch its
  compatibility re-exports directly in
  `test_assets.py`, `test_markup_api.py`, `test_agent_modes.py`,
  `test_specagent.py`, `test_housestyle.py`, and `test_evals.py`.
- The canonical `image_agent` package no longer imports `specagent.py` or any
  private `render.py` helper. It owns focused prompt, drift, vision, identity,
  and QA modules. Its production provider adapter still calls the public
  `render.edit_image`/`render.generate_image` transport facade; that is the
  remaining intentional compatibility edge.
- `api/share.py` imports private comment/version helpers from
  `api/designs.py`; shared design services must replace this router-to-router
  dependency before either route family moves.
- `api/library.py` imports project-card/chain helpers from `api/projects.py`.
  Move those read models to a project query service before treating routers as
  independent.
- Provider-neutral media detection, visual-spec identity, and provider errors
  now live in `media.py`, `image_identity.py`, and `provider_errors.py`.
- Legacy mobile code in `mobile/src/api.ts` still calls direct design, share,
  stateless preview, prose, and render-request routes. The feature-flagged
  trusted client calls the canonical project, markup, checklist, image-run,
  and factory-pack boundary.

## Extraction sequence

1. **Complete:** keep the new typed `image_agent` orchestration as the only place that owns
   attempt routing, prompt versions, QA verdicts, and corrections.
2. **Complete for canonical callers:** provider-neutral image hashing, media
   inspection, shared errors, edit prompts, drift, vision transport, and image
   QA are focused modules with compatibility re-exports.
3. Extract the remaining markup parsing/masking, view generation, and technical
   drawing behavior from `specagent.py`. Preserve temporary re-exports so
   existing tests and compatibility routes remain readable.
4. Move atomic revision mutation out of router functions into a service that
   persists `ImageAsset` and `DesignVersion` in one commit after provider work.
5. Move project read models out of `api/projects.py` so `api/library.py` no
   longer imports a router.
6. Migrate the trusted client and acceptance script, then the Advanced
   specifications client, away from every deprecated route.
7. Only then remove deprecated routes, facades, direct monkeypatch seams, stale
   response types, and documentation in one OpenAPI-reviewed change.

## Deletion gates

No deprecated or conflicting path is deleted until all of these are true:

1. No production client, script, or live workflow calls it.
2. A replacement has equivalent or stronger unit/integration coverage.
3. The ring golden-set gates pass after the configured Grok retry/fallback
   policy, including zero accepted candidates with major drift.
4. The founder scenario passes end to end for brief creation, confirmed-image
   creation, targeted retry, fallback, band widening, impossible-change
   rejection, diff/QA review, approval, pinning, and pack download.
5. The before/after OpenAPI diff contains only explicitly approved removals.
6. Existing database history and nullable legacy provenance remain readable.
7. No removal touches immutable design versions, migrations, golden specs,
   image-run evidence, or evaluation artifacts.

Until then, compatibility routes should be hidden from normal UI and may be
marked deprecated in OpenAPI, but their implementations and tests remain.

Deterministic jewelry-geometry paths have additional removal gates. Their
AI/design-derived replacements must cover every supported view and caller,
block missing sections, component/count/shape/topology drift, disconnected or
interpenetrating hardware, crop, model-authored text, and false authority, and
pass founder review on diverse real designs. Removal must preserve the useful
deterministic control plane: measurements, physical validation, masks, page
layout, schedules, manifests, hashes, migrations, and immutable history. See
the full criteria in
[`ai-first-studio-architecture.md`](ai-first-studio-architecture.md#legacy-deterministic-geometry-removal).
