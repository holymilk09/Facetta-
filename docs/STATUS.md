# Project status — read me first in a new session

Last updated: 2026-07-13 · branch `codex/facetta-integration`.
Read `CLAUDE.md` (constitution — binding), `README.md` (endpoints/layout),
`docs/DATA_WANTED.md` (open research asks). This file is the delta: what is
DONE beyond the original TASKS.md build order, and what is next.

## 2026-07-13 resumed Studio integration checkpoint

The canceled Codex tracking record did not remove the recovered work. The
trusted recovery branch remains independently preserved, and the unified
Studio integration continues on `codex/facetta-integration`.

This checkpoint closes two review-state hazards. A stale pre-spec visual
candidate is now terminalized together with its exact uncharged Refine job,
clears temporary bytes, and cannot create a revision or review decision.
Generic Activity cancellation now fails closed once a job reaches `reviewing`;
candidate-specific Apply, Save as Variation, and Discard remain the atomic
decision boundary.

The production Studio shell also removes avoidable navigation repetition:
action workspaces use one compact return control, returning designers can open
saved work directly from Studio, and Activity polls only while work is queued
or running. Ring-only fact confirmation is no longer presented as a universal
primary action. It is explicitly labeled `Ring facts` under More. Factory
language remains absent until the backend reports that the exact revision is
both entitled and eligible; the older readiness registry entry is retained
internally during migration but is not visible.

Local validation at this checkpoint: 1,439 backend tests, 230 Jest tests, 61
Studio contract tests, TypeScript, Ruff, Expo web export, and the ten-project
production TypeScript-client -> HTTP -> FastAPI acceptance all pass. The
acceptance reports no canonical mutation before acceptance, no canonical
asset/revision or charge from failed QA, and no Factory use. These local
results do not satisfy the two external gates: the signed frozen 144-image
corpus with founder/GIA review and live two-principal HTTPS staging isolation
remain `not_run` / `unmet` in `STUDIO_EXTERNAL_BETA_GATES.md`.

## 2026-07-12 AI-first studio architecture direction

The target product architecture is now recorded in
[`ai-first-studio-architecture.md`](ai-first-studio-architecture.md). Facetta is an AI-first jewelry studio
organized around `Create -> Explore -> Organize`; factory handoff is an
optional promotion lane for a selected immutable revision. The target hierarchy
is Design Family -> Variation -> Revision, with a current `Project` serving as
the persisted variation container until an additive family model exists.

The integrated Studio shell now uses global Studio, Collections, Activity, and
Learn navigation with contextual Create, Vary, Refine, Views, Present, and
optional Factory actions. First-class Design Family records, sibling
Variations, immutable Revision history, comparison/restore, role-labeled
references, temporary preview decisions, durable Studio jobs, and
Client/Marketing presentation destinations are implemented through one typed
Studio gateway. Create candidates are durable review directions rather than
fake sequential revisions; the selected direction becomes the Original and
other useful candidates can be kept explicitly as sibling Variations.

The real-process Studio acceptance now runs ten deterministic projects through
the production TypeScript client/gateway, HTTP, uvicorn/FastAPI, and disposable
SQLite. It covers sentence, drawing, photograph, finished-render, and every
secondary reference role; each case saves, reopens, branches, previews without
canonical mutation, applies, compares bytes, and restores append-only without
entering Factory. Live provider quality and two-principal staging isolation
remain separate external gates.

Remaining product/reliability work includes a calibrated production component
mapper for initially unmapped creative candidates, broader cross-category
component graphs, a complete instant masked configurator, design-derived
factory discussion views, and the external beta evidence in
`STUDIO_EXTERNAL_BETA_GATES.md`. Generic deterministic jewelry schematics remain
internal/non-authoritative until their documented replacement and deletion
gates pass.

The engineering invariant is stricter than the legacy implementation: AI
creates jewelry geometry and vision checks it; deterministic code records,
masks, measures, validates, versions, and lays out evidence. Existing generic
SVG/DXF jewelry geometry remains compatibility/internal and non-authoritative
until design-derived replacements pass structural QA, diverse live review, and
the documented deletion gates. No compatibility code was declared complete or
removed by this architecture update.

## 2026-07-12 localized-edit trust audit

The heterogeneous live evidence is now summarized without pretending it is one
release run in `docs/evals/live-image-agent-scorecard-v1-2026-07-12/report.md`.
Center identity/color, background-only presentation, exact halo addition, and
several drawing/prompt render paths are promising. Band geometry, exact
setting/prong topology, material identity, and exact repeated inventory remain
the weak competitive operations.

The trusted-ring harness now recognizes either FAL or OpenAI as the configured
third-attempt fallback and records the provider it actually used. OpenAI also
runs after two Grok provider failures, not only after QA failures. Its fallback
default is medium quality because it is reached only after two failed Grok
attempts; low remains available for explicit inexpensive comparisons. A named
`--edit-source` option permits one focused diagnostic to reuse a hashed,
operator-reviewed source without repeatedly spending credits to rebuild it;
such a run remains ineligible for full release-gate calculation.

A live band-width run exposed a severe evaluator false positive: a visually
attractive result changed camera, crop, scale, and composition but had been
reported as 100-fidelity. Deterministic evidence already said
`framing_stable=false`; the evaluator was incorrectly allowing the vision pass
to override it. Band silhouette evidence is now authoritative and a hard
`band_edit_presentation_lock` rejects camera/crop/scale drift. The replayed
three-attempt policy correctly rejected two Grok candidates and one OpenAI
candidate; the fallback also changed a six-prong setting to four. No candidate
was persisted. Evidence:
`docs/evals/designer-band-width-presentation-lock-live-v4-2026-07-12/`.

The next localization experiment derived a front-facing shank suggestion only
when a chromatic center provided a reliable center boundary. It protects the
stone plus low-saturation prong/setting components, edits a narrow side-shank
corridor, excludes floor reflections, declines ambiguous/colorless centers,
and records its mask hash, normalized protected region, editable fraction, and
provenance in the image plan. Persisted designer markup remains authoritative
and is labeled separately from caller-supplied or automatic masks. OpenAI uses
the native alpha mask plus inward-only feathering, with exact source pixels
outside the original mask. Live v6 held framing, six prongs, and zero
outside-mask drift but still failed for insufficient widening and blend
artifacts; no asset was created. Evidence:
`docs/evals/designer-band-width-auto-localized-live-v6-2026-07-12/`.

## 2026-07-11 trusted low-information E2E v7

A synthetic low-information designer source completed the real workflow:
blind source audit, explicit designer resolution of only inconclusive facts,
persisted reference project, Grok yellow-to-rose isolated edit, independent QA
disagreement surfaced as a warning, operator visual acceptance, immutable spec
v2, exact checklist/pin, and deterministic factory ZIP. The accepted image
preserved the emerald, four prongs, six primary shoulder diamonds, composition,
and camera. Factory truth remained split correctly: material/stone/setting
facts confirmed; 12 reference-derived dimensions labeled EST. with a
non-measurement warning. The final project reloaded as `factory_ready`.
Artifacts: `docs/evals/low-information-rose-edit-factory-e2e-live-v7-2026-07-11/`.

Two visual-QA defects found during the run were fixed: long reviewer IDs no
longer overflow the sheet title block and the schedule disclaimer wraps rather
than clipping. Source evidence advances only through an unbroken chain of
accepted image-agent runs whose exact source/target visual-spec hashes match;
failed, missing, unresolved, and off-branch evidence still fails closed.

## 2026-07-12 creative-first trusted UI

Free-form “Describe an idea” is now a category-neutral pre-spec workflow rather
than an alias for the structured ring brief. `POST /projects/from-prompt` runs
one to four independently versioned `CREATIVE_GENERATE` plans through Grok-first
coherence, prompt-adherence, and output-hygiene QA. It persists only reviewable
`CREATIVE_RENDER` candidates—no fake source asset, Design, DesignVersion,
measurement, or factory claim. The first candidate safely serves as the chain
root, and root or alternate candidates promote through the same exact audited
spec-v1 boundary. The old ring brief remains available as “Structured ring
brief.”

Live evidence exposed and fixed a real evaluator false positive. Grok's first
necklace candidate was visually strong but drew more than the requested five
emerald leaves; the original judge noted “5+” and still passed it. Prompt
contract `creative-generate.v2` now treats written or numeric quantities as
exact visual constraints, and count mismatch is a hard QA failure. A repeated
live run rejected two over-count Grok candidates, issued a count-specific retry,
then used the configured OpenAI image adapter because FAL is unavailable. The
fallback produced exactly five emerald leaves and one tapered drop and scored
92 automatically, but human review rejected its wrong diamond shapes and
cropped chain. It remained review-only with no product/spec/factory
persistence. Evidence:
`docs/evals/creative-prompt-necklace-live-v3-2026-07-12/`.

Prompt contract `creative-generate.v3` now also hard-checks stone species,
color, cut/shape, role, complete-piece framing, and invented branding. A later
position-anchored Grok attempt produced a complete clasp-to-drop necklace with
exactly five marquise emerald leaves, round diamond accents, and one tapered
metal drop on its first attempt; it remains a human-review candidate rather
than automatic product truth. Evidence:
`docs/evals/creative-prompt-necklace-live-v5-2026-07-12/`.

That exact candidate then completed the persisted prompt-candidate workflow:
category-correct necklace read, designer-corrected spec, blind source audit,
explicit confirmation of three raster-inconclusive facts, immutable spec-v1
promotion, checklist, and pin. Release correctly stopped with only
`visual_reference_not_dimensioned` and
`chain_production_reference_missing`; the factory pack and DXF both returned
409. The standalone SVG is now explicitly `PRELIMINARY — NOT FOR PRODUCTION`,
hides the misleading generic pendant geometry, and explains the missing
dimensioned form/chain evidence in designer language. One bounded retry is
allowed only when the vision provider violates the audit response contract;
valid failed or inconclusive judgments remain blocking. Evidence and rendered
sheet preview:
`docs/evals/creative-prompt-necklace-factory-e2e-live-v3-2026-07-12/`.

The factory-sheet path now has an explicit resolution for custom visual form:
`dimensioned_profile` accepts one complete designer-supplied or
designer-confirmed-estimate front assembly in millimeter coordinates, including
closed outlines/open width-bearing centerlines, thickness, datum, source hash,
confirmation actor/time, and manufacturing notes. It never derives this record
from image pixels. The deterministic SVG replaces generic template geometry,
writes the actual scale and overall callouts, and discloses every estimated
coordinate/width/thickness in the fact plan and manifest. DXF conversion
selects only that custom profile group, preventing hidden catalog geometry from
reappearing in CAD. A real factory ZIP integration test passes; synthetic
render/visual evidence is in
`docs/evals/dimensioned-form-sheet-v1-2026-07-12/`. Partial profiles and native
CAD upload remain deferred rather than guessed.

Professional multi-view necklace plates now use a one-finished-piece inventory
contract: detail, side, and enlarged construction views clarify the design but
cannot multiply the physical stone schedule. Stone groups retain their physical
role, source views, count status, and nearby handwritten labels through draft
compilation and blind coverage audit. A paid regression on the founder-supplied
emerald collar plate retained the center drop once, separated two flanking from
four outer drops, and again scored 100 for jewelry type, expected materials,
group coverage, and transcription. It correctly remained `review_required`:
setting construction, exact articulated collar/chain production, ambiguous
buff-top geometry/counts, and missing structured diamond clusters are not
factory facts. Generic `white metal` is now explicitly unresolved instead of
being silently promoted to the compiler's valid 18k-white-gold preview
placeholder. Evidence:
`docs/evals/designer-emerald-necklace-coverage-live-v3-2026-07-12/`.

Professional multi-view drawing-to-beauty intake now supports an exact
designer-selected normalized source region. Facetta retains the original full
plate, persists the exact crop as `CREATIVE_SOURCE_REGION`, and binds candidate
parentage plus image-run source hash/ID to that crop. The trusted client carries
the typed contract without changing the parallel redesign. A live geometric
emerald-ring plate regression exposed a real evaluator false negative: an
attractive first render scored 92 despite replacing source step facets and
panel/shank topology. Region-specific QA now audits local contours, repeated
element count/shape/order/spacing, and stone shape/cut family with an independent
skeptical comparison. On the same cached candidate the stricter audit scored 42
and named each drift. In the full closed loop, cached attempt 1 failed, those
exact checks became the correction prompt, and Grok attempt 2 produced a better
step-cut/panel-faithful 92-scored candidate. It remains designer-review-only and
establishes no factory fact. Evidence:
`docs/evals/professional-multiview-ring-region-render-live-v1-2026-07-12/`,
`docs/evals/professional-multiview-ring-region-render-live-v3-2026-07-12/`.

Creative candidates can now enter that contract before persistence through a
typed confirmation route/client. The server binds submitted paths to the exact
stored candidate SHA-256 and server confirmation actor/time; callers cannot
substitute source bytes or manufacture provenance fields. The result remains a
non-persisted draft and changing profile coordinates changes the visual-spec
hash, making prior source-audit evidence stale until the exact updated draft is
re-audited. Repeated/partial targets are rejected, and no Design or
DesignVersion is created until normal candidate promotion.

The tested creative backend is now usable from the presentation-independent
trusted workspace. Desktop/tablet designers can submit any valid drawing or
jewelry image, give a designer-direction prompt, and request one to four
faithful candidates without being labeled rough/professional or being forced
through factory extraction first. Candidates remain visual-only. Selecting one
reads the exact server-held pixels into a draft; mappings can be corrected and
re-audited against those same bytes; only inconclusive facts can receive an
exact-source/spec designer confirmation; promotion then binds the chosen asset
to immutable spec v1. Approval/factory navigation stays disabled pre-promotion.

Draft correction no longer depends on manually editing JSON. The trusted
desktop/tablet workspace now exposes a typed Factory Facts editor covering
center and side stone identity/cut/count/carat/dimensions, metal, setting,
ring construction, and necklace chain/pendant construction. Optional unknown
facts can be supplied directly. A designer chooses `Measured / supplied` or
`Reference estimate` before changing dimensions; the editor writes canonical
per-field provenance, marks the prior source audit stale, and keeps raw JSON
under Advanced. A cross-layer acceptance test proves the same 2.8 mm band value
renders without `EST.` when designer-confirmed and with `EST.` when retained as
an estimate, while the factory fact plan reports the matching authority.
Supported cut, complete alloy/color, center-setting, and necklace-chain choices
now come from the canonical component catalogs. A stateless draft compiler
applies coupled fields and derived carat together, rejects invalid, category-
incompatible, and no-op selections, and removes provenance for dimensions
cleared by the choice (for example prong-tip gauge when changing to a bezel).
The editor no longer exposes free-text karat or prong count beside those coupled
controls.
Center gemstone identity now uses the same cascading gemology vocabulary as the
Builder. Selecting a species loads only its controlled trade colors; the backend
rejects cross-species color terms, clears incompatible clarity/origin/treatment/
phenomena claims, preserves the designer's cut/dimensions/count, and recomputes
modeled carat for the new species density. Jadeite remains unavailable rather
than being invented.

Candidate review now exposes the existing deterministic factory-sheet renderer
instead of making designers reason from facts alone. `Preview factory sheet`
posts the exact unpersisted draft to `/specs/sheet.svg`, embeds the returned SVG
on desktop/tablet, preserves the server authority header, and marks the image
stale immediately when any factory fact changes. Incomplete custom geometry or
source coverage remains visibly preliminary/not-for-production; even a clean
spec-derived preview is not factory authority until exact-revision approval and
factory-pack generation. This path makes no image-provider call.

The factory fact plan now covers the non-numeric manufacturing record as well
as measurements. Stone mounts and sourcing/grading facts, band profile,
ring-size system/letter sizes, bracelet/drop counts, complete chain construction
and production references, custom-form authority, and factory instructions all
receive typed paths and confirmation status. Schedule-page text continues onto
physical rows without ellipsis, and exact production references remain intact.
Factory notes are now an explicit approval/edit target, while resolved
dimensioned profiles no longer mislabel themselves as visual-reference-only.
Pack generation fails closed when any recorded fact remains pending.

The trusted UI also exposes multi-preset ecommerce packs with the maximum
provider-attempt multiplier shown before execution. Partial failures do not
discard successful candidates, and accepted scenes remain derived marketing
assets. `TrustedWorkspaceEntry` is ready as the one-import seam for the parallel
redesign, but `mobile/App.tsx` remains untouched because that worktree is still
dirty and uncommitted.

## 2026-07-10 trusted workflow milestone

- Canonical ring project creation now persists Design v1, its exact primary
  visual revision, provenance, project metadata, and image-run evidence in one
  transaction after provider work and QA finish.
- `image_agent/` owns Grok-primary execution, targeted correction, task-safe
  fallback, ring-specific QA, prompt/cache versioning, and structured failures.
- Confirmed markup uses optimistic spec-version checks; trusted edits promote
  only QA-pass candidates and commit image/spec changes atomically. Warnings
  and failures are observable but never active assets. Explicitly accepted
  warnings use temporary previews plus append-only review/feedback evidence.
- Imported-reference creation now extracts a draft before designer correction
  and confirmation; creation-stage concept/spec warnings remain reviewable
  without leaving partial Project, Design, or ImageAsset rows.
- Exact-revision approval now gates factory-review packs containing the
  validated spec, confirmed fact schedules, schematic Facetta SVG/reference
  DXF, approved image, and hashed manifest. The generic deterministic drawing
  is visibly labeled `NOT PRODUCTION GEOMETRY`, is non-authoritative in the
  manifest, and can no longer masquerade as a factory-acceptable drawing.
  Production authority remains empty until a designer-approved, design-derived
  technical drawing and/or tolerance-bearing CAD/master reference exists.
- The typed Expo workspace is staged behind
  `EXPO_PUBLIC_TRUSTED_WORKSPACE`; the dirty parallel redesign remains the owner
  of final presentation and app navigation wiring.
- Compatibility routes are inventoried and OpenAPI-deprecated, not deleted.
  Deletion waits for live ring gates, GIA evaluator review, founder acceptance,
  redesign merge, and caller migration.
- Ring evaluation preflight:
  `docs/evals/trusted-workflow-ring-preflight-v2-2026-07-10/`. Imported cases
  now require a real source-backed run, edits span the full matrix, and
  persistence fails closed without named canonical-API evidence. Grok-primary
  live scoring and canonical imported-reference E2E evidence now exist; FLUX
  fallback remains untested because this worktree has no `FAL_KEY`.
- The designer-edit matrix now covers center cut/shape, center species/color,
  band geometry, metal color/material, setting/prongs, halo add/remove/count,
  gem-built motif shape, background-only presentation, and impossible geometry.
  Plans carry deterministic edit-domain IDs; prompts compile domain-specific
  jewelry actions; Grok Vision audits every domain independently against the
  before/after spec, exact delta, region, and frozen facts.
- Prompt-diverse skeptical render/edit audits now sit behind the primary Grok
  QA. They can veto false passes for prong counts, component inventories,
  frozen-fact drift, or a missing requested change. Audit uncertainty holds a
  candidate for designer review instead of activating it.
- Expectation-free component counting now removes the requested count from the
  vision prompt and compares the observed result in code. It correctly found
  four visible center prongs in the known false-pass six-prong case; evidence:
  `docs/evals/designer-live-center-shape-blindcount-audit-2026-07-11/`.
  Local-edit candidates also undergo a full target-spec audit after delta QA.
- Live common-edit diagnostics remain non-release evidence: center
  species/color and halo addition passed; center cut/shape was visually strong
  but exposed the prong-count false negative now blocked above; leaf motif
  shape was safely held for review. The current exact halo-count rerun failed
  safely after two Grok attempts and OpenAI fallback: blind counts contradicted
  the requested 18 or remained incomplete, the harness found no credible
  decrement, and no candidate was applied. White-gold-to-platinum remains
  unresolved. White-metal alloy substitution is now explicitly treated
  as spec truth plus designer-review warning because pixels cannot prove it.
- Exact side-stone edits now compile one atomic source-to-target inventory
  contract rather than unrelated shape/identity domains. Primary comparative
  QA records source/candidate visible counts and count completeness; a separate
  expectation-free target audit hard-fails complete contradictory counts.
  Uncountable exact-inventory candidates remain explicit review-only and their
  score is capped below pass confidence. Evidence:
  `docs/evals/designer-halo-count-atomic-inventory-live-v3-2026-07-12/`.
- Whole side-stone inventory changes and coupled center-shape/setting changes
  are structurally scoped at the persisted API boundary. Integration tests
  prove version conflict handling, provider-free rejection, and image/spec
  rollback on database failure.
- Reference/photo/plate dimensions now carry per-field estimate provenance.
  Factory sheets label estimated values `EST.` and factory-pack manifests/API/
  mobile review list the exact fields and a “not measurements” disclaimer.
  Designer-adjusted values remain versioned and can be promoted individually.
  Whole side-stone inventory edits reindex provenance by matching physical
  groups and mark every new group's nominal dimensions as estimates, so an
  AI-added halo can never silently appear measured.
- Both designer plates and finished-jewelry photo drafts now carry stable
  source-component coverage. The finished-photo path seeds only components
  represented by the extracted spec; a separate blind-first audit adds any
  visible omissions. New imports therefore remain blocked rather than falling
  through permissive legacy provenance when an audit is unavailable or invalid.
- A general typed component-catalog control surface covers eight chain
  families plus safe ring center-cut, complete alloy/color, and center-setting
  controls. Selections produce exact validated deltas with visual geometry,
  isolation targets, applicability requirements, coupled fields, and frozen
  facts. Gold material choices are complete 14k/18k alloy presets rather than
  an under-specified bare material; setting choices keep style/count/tip
  consistent. Pointed cuts needing V-prong placement remain omitted. The
  Builder vocabulary remains compatible. Necklace chains now carry
  construction-specific dimensions, exact production references, and a
  pendant-connection mode without coercing rope/snake into open-link fields.
- Safe ring and necklace-chain catalog selections now share a persisted
  canonical endpoint. It rejects stale, incompatible, unknown, no-op, and
  incomplete target-manufacturing choices
  before provider work; sends the exact deterministic source/target spec,
  visual geometry, isolation target, and frozen facts through localized image
  QA; and atomically commits a passed image/spec/ImageRun. Warning candidates
  retain the exact proposed spec/diff only in temporary review storage.
- Line-art extraction now accepts an optional normalized source rectangle and
  region description. The server crops before provider work and skeptical QA,
  so one selected view from a multi-view plate cannot silently authorize
  hidden geometry from the rest of the plate. The typed mobile client preserves
  the exact selection across a corrective retry.
- Confirmed-line and colored-line evaluators now explicitly reject wrong
  prong/stone counts, source-shape drift, candidate-only captions or branding,
  photorealistic substitution, and coloring that no longer retains technical
  linework. A confirmed line drawing can feed the spec-render stage directly;
  colored technical illustration remains optional.
- Eleven staged live standard-halo runs correctly refused attractive but
  structurally wrong candidates. No run reached approval or factory pack;
  the honest release verdict and per-run failure record are in
  `docs/evals/standard-halo-live-evidence-2026-07-11.md`.
- The first GPT Image 2 native-mask comparison applied the requested
  oval-to-emerald center edit with exact zero outside-mask drift, then correctly
  failed full-spec QA because candidate QA reported four prongs and 20 halo
  stones while the old test spec claimed six and 14. A later audit-only pass
  could independently see the halo and pronged head but could not count either;
  both facts remain review-required rather than proving either side of the
  disagreement. This exposed a deeper audit flaw: path coverage was not
  exact-value coverage. Source audits now
  receive raster-visible spec facts, bind the exact visual-spec hash, reject
  assessable repeated-stone/prong conflicts deterministically, require exact
  counts to originate in the blind first pass, retain partial evidence on pass
  two failures, and block stale or missing bindings at import, render,
  project-detail, and factory-pack boundaries. Evidence:
  `docs/evals/openai-center-cut-live-v1-2026-07-11/` and
  `docs/evals/designer-standard-halo-blind-evidence-audit-v14-2026-07-11/`.
- GPT Image 2 is implemented only as an internal comparison route. Its adapter
  uses native alpha masks, source-aspect API sizing, exact outside-mask patch
  compositing, content-addressed caching, and safe provider errors. Default
  product routing remains Grok, targeted Grok retry, then task-safe FAL where
  configured; OpenArt remains a whole-reference comparison without native
  region masking.
- Drawing intake no longer classifies, scores, or labels a designer's source as
  rough, poor, clean, or professional. Every valid image/drawing condition
  compiles the same `faithful_best_effort` strategy: always attempt a visual
  candidate, preserve supplied visible geometry, allow presentation cleanup,
  and defer only concrete physical uncertainties to the later factory-spec
  review. Internal evidence signals never block rendering or draft creation and
  never become user-facing judgments. Designer-supplied dimensions are retained
  exactly; reference estimates remain `EST.`. The provider-free six-fixture
  matrix proves this contract consistently but deliberately makes no live image
  quality claim. Evidence: `docs/evals/drawing-quality-contract-matrix-v1/`.
- The canonical pre-spec `REFERENCE_RENDER` path is now live-tested across a
  geometric emerald ring, a complex ribbon ring, emerald drop earrings, and a
  flower lariat hand source. All four returned review candidates; three passed
  source-fidelity gates on attempt one and the ribbon topology recovered from a
  35-point hard failure to an 88-point review candidate through evaluator-
  specific Grok correction. No fallback or product/factory persistence was
  used. Selected mean QA was 91.25. Human review still notes minor ribbon
  regularization and the limits of unseen earring hardware. Evidence:
  `docs/evals/reference-render-live-v1-2026-07-11-summary.md`.
- A separately labeled synthetic low-information ring sketch also returned a
  92-point review candidate in one live attempt, retaining the green oval,
  four claws, and exactly three shoulder stones per side. Human review records
  the model-proposed unseen gallery as review-only and notes that one synthetic
  fixture cannot stand in for real-world sketch diversity. Evidence:
  `docs/evals/reference-render-low-information-sketch-live-v1-2026-07-11/`.
- Factory handoff now rejects known jewelry-type/template mismatches. The pack
  still bundles DXF for exchange, but its manifest correctly marks it
  non-authoritative: nested transforms and current curve commands are now
  regression-tested, but sampled R12 polylines remain a 2D underlay rather than
  solid or tolerance-bearing fabrication geometry. Validated JSON and
  deterministic SVG remain the declared factory records.
  Approved packs now include a typed material/stone/setting/dimension fact plan
  plus deterministic `facetta-schedule-N.svg` continuation pages. Dense
  schedules paginate without truncation, and every row visibly remains
  CONFIRMED, EST., or PENDING.
- Prompt-created projects now have a canonical staged evaluation harness.
  Preflight compiles `concept-generate.v1` and `spec-render.v2`; the offline
  contract matrix proves pass, concept-warning, spec-warning, and terminal
  hard-failure behavior through the real API with zero provider calls/cost and
  zero partial product rows. Evidence:
  `docs/evals/prompt-brief-contract-2026-07-11/`.
- The necklace catalog live harness now audits every expected source component
  before persistence. Its clean single-necklace generated control can proceed
  only with zero blockers; the founder multi-design plate is an intentional
  negative control whose unresolved second assembly stops before project
  creation.
- Full validation on 2026-07-11: 1,033 backend tests, Ruff, TypeScript, and 57
  mobile Jest tests passed. A centralized macOS Cairo loader also restored the
  documented no-extra-environment pytest command for factory drawing tests.
- Ecommerce background bundles now use
  `POST /projects/{root_id}/marketing-pack`: one to four exact-source/spec
  scenes, an explicit three-attempt-per-scene ceiling, temporary previews even
  after QA pass, and partial-failure evidence without rejected product bytes.
  Designer acceptance persists `MARKETING_IMAGE` as a derived exact-version
  asset. Tests prove the active/pinned revision, approval checklist,
  `factory_ready` state, and immutable spec version all remain unchanged.

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
  Restage + from-photo endpoints exist. Grok Vision is now wired for imported
  references, and the trusted project render persists a QA-approved
  spec-aligned image. fal.ai remains an unconfigured quality-fallback path
  (plan: FLUX ControlNet for hero renders, FLUX Kontext for single-parameter
  edits).
- Validation beyond density: alloy logic (silver/platinum carry no karat or
  color), halo/station fit, cuff gap, depth/table %, girdle weight
  correction, culet scale, intl ring sizes (US/UK/EU/JP/HK), gallery-vs-
  culet clearance (factory rule).
- Factory handoff: DXF R12 export (stateless + stored versions), share
  links with pinned comments, per-design designer/factory Discussion thread.
- Trusted ecommerce presentation: persisted `PRODUCT_PHOTO` revisions use
  Grok visual-only editing with frozen jewelry/spec facts, explicit warning
  review, and clean unstamped delivery bytes for catalog use.
- Trusted drawing stages: project-bound line art always requires designer
  geometry confirmation before spec-driven colorization. Confirmed drawings
  remain derived assets. Material loss is hard-failed when semantic and raster
  evidence corroborate it; photo-to-illustration pixel disagreement becomes a
  designer-review warning instead of a false automatic rejection.
- Corrected designer-reference live proof:
  `docs/evals/designer-corrected-full-e2e-2026-07-11/` records a founder-supplied
  leaf ring with an explicit 36-diamond shoulder specification, confirmed line
  art, spec-colored warning review, derived colored art, seven-item approval,
  and a deterministic factory pack with an explicitly non-authoritative
  discussion line drawing. The automated review actor proves
  mechanics only; founder/GIA acceptance is still outstanding.
- Blind source-coverage live proof:
  `docs/evals/designer-source-coverage-leaf-live-v2-2026-07-11/` re-runs the
  founder leaf-ring plate through an expectation-free inventory plus exact
  mapping audit. It correctly blocks the coarse `100`-scoring draft after
  finding unmapped emerald, baguette/channel, and leaf/pavé components plus
  unresolved assembly/setting evidence. No product/factory asset was promoted.
- App (Expo, `mobile/`): category builder (Basic/Pro), proportional resize
  with carat re-estimate, collections + search + category filters, mockup
  scene compiler UI, tablet two-pane layout.

## Historical priorities (superseded by the 2026-07-12 Studio direction above)

The numbered list below is retained as a chronology of the trusted-workflow build. It is
not the current execution queue; references to pending redesign wiring, authentication,
or Supabase setup have since been superseded. Current remaining gates are summarized at
the top of this file and in `STUDIO_EXTERNAL_BETA_GATES.md`.

1. **Finish and live-test the input-agnostic creative loop** — the backend now
   exposes neutral `POST /projects/from-drawing`, runs one to four explicit
   source-faithful `REFERENCE_RENDER` variants through Grok-primary corrective
   routing, and persists the source/candidates/ImageRuns atomically without
   inventing a spec. A selected candidate can be promoted exactly once through
   designer-confirmed, source-audited spec v1; pre-spec candidates cannot be
   approved, pinned, or factory-exported. Remaining work is redesign wiring,
   explicit ecommerce/marketing background packs, and diverse live testing
   across the reference corpus. No source-quality classification belongs in UI
   or provider prompts.
2. **Deepen the factory-sheet fact plan** — add a structured plan between spec
   and output with confirmed/estimated/pending status, full materials/stone/
   setting/dimension schedules, adaptive fact overflow pages, readiness
   preflight, and SVG/DXF geometry parity before restoring DXF authority. The
   first part is now implemented: every approved pack manifest includes a typed
   `facetta.factory-sheet-plan.v1`; checklist-confirmed facts are explicit and
   reference-derived dimensions remain estimates after approval. The factory
   archive now adds as many deterministic `facetta-schedule-N.svg` continuation
   pages as required, with no fact truncation and visible CONFIRMED/EST./PENDING
   status. The DXF converter now preserves nested rotations and samples all
   current quadratic/cubic/arc sheet geometry, with ten-template regression and
   representative visual parity evidence. DXF remains a non-authoritative R12
   underlay because sampled 2D curves are not solid/tolerance-bearing CAD.
3. **Resolve the standard-halo counts before another paid image call** — the
   blind audit could not independently count halo stones or prongs, while
   candidate QA disagreed with the test spec. Obtain designer confirmation or a
   clearer isolated view, then compare Grok, GPT Image 2, FAL if configured,
   and OpenArt where its
   whole-reference constraint is fair. Keep the same source crop, frozen facts,
   QA, and three-attempt ceiling. Do not accept a provider because its image is
   merely attractive.
4. **Supabase accounts** — founder has a project; waiting on Project URL,
   anon key, DB connection string. Plan: DATABASE_URL -> Supabase Postgres,
   JWT verification middleware, designs owned by users, login screen in app.
   Factories stay account-less via share links.
5. **fal.ai wiring** — render.png endpoint + cache by (geometry_fingerprint,
   scene, style). Payloads are already compiled by /specs/render-request.
6. **Founder/GIA design-form acceptance** — the structured stable-element,
   saved-mask, exact-reference-hash, atomic revision, approval, and factory
   blocker path is implemented and covered by the Art Deco → smooth shoulder
   acceptance suite. Run it on founder artwork and review evaluator misses.
7. **Independent source-coverage acceptance** — new plate drafts explicitly
   account for visible components and block incomplete/unaudited factory
   release. Exercise the independent audit on the leaf-shoulder failure case
   before treating the gate as founder-approved.
8. Jadeite vocabulary — BLOCKED on co-founder approval, never invent it.
9. Real .ASC files for marquise/trillion/pear/radiant (ours are angle-true
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

2026-07-06 v8 — CONCEPT ORIGINATION: Grok invents, Facetta makes it real.
Full chain proven LIVE on FAL/XAI keys only (no Anthropic needed):
- render.py generate_image() + GENERATION_MODELS (xAI /v1/images/generations,
  fal flux) — Grok creates an ENTIRELY NEW design from a text brief, cached
  by (prompt, model).
- concept.py: read_design() (xAI vision, structured JSON constrained to the
  controlled vocabulary) → sparse DesignRead; complete_design() = the
  real-life-logic engine — builds a full spec, sets depth+carat by the
  density model, sizes the halo to _surround_fit, sets gallery to the
  culet-clearance rule, then runs validate_spec and auto-applies any
  remaining `expected` correction, returning the valid spec + a plain-English
  corrections list. SUPPORTED_CUTS gained emerald_cut + cushion so step-cut
  centres render.
- POST /specs/from-concept {brief} → {concept_image, read, spec, corrections}.
  Every profile (line-art master, Grok-painted blueprint w/ dims, photoreal
  client render) derives from the ONE spec, so they are consistent by
  construction. 269 tests. Live demo: "art deco emerald-and-diamond halo
  cocktail ring, platinum" → Grok concept → vision(emerald_cut 10×7, halo,
  platinum) → validator(2.14 ct at 4.5 mm depth, 19-stone halo that fits,
  3.7 mm gallery) → sheet + hand-drawn blueprint + client render.
Note: the vision→spec extractor now uses xAI directly. Grok reports visible
facts while Facetta's deterministic completion and validator own every physical
number; imported references still require designer confirmation.

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
