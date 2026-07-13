# Facetta AI-first studio architecture

Status: active product architecture with an integrated Studio shell and trusted
control-plane foundation. Target-only capabilities are identified explicitly;
the document does not imply that every destination or reliability gate has
shipped.
Current implementation evidence remains in
[`STATUS.md`](STATUS.md) and the narrower persisted workflow is documented in
[`trusted-workflow-architecture.md`](trusted-workflow-architecture.md).

## Product thesis

Facetta is an AI-first jewelry studio. Its primary job is to help a designer
create, explore, refine, compare, and organize jewelry ideas. Factory handoff is
an optional promotion lane for a selected revision, not the mandatory ending
of every creative session.

The global loop is:

```text
Create -> Explore -> Organize
   ^                    |
   +--------------------+
```

- **Create** starts from a prompt, drawing, photograph, design plate, component
  choice, or existing revision and returns reviewable visual candidates.
- **Explore** branches candidates, compares revisions, changes components,
  tests materials and presentation, and keeps useful alternatives without
  forcing premature manufacturing facts.
- **Organize** groups related work, records provenance, names variations,
  preserves immutable revisions, and sends selected outputs to the right
  destination.

The loop can repeat indefinitely. A designer may create a client presentation,
save a reusable component, or publish ecommerce imagery without ever opening a
factory checklist.

## Studio hierarchy

The target product hierarchy is:

```text
Design Family
  -> Variation (persisted today as a Project)
      -> immutable Revision
          -> optional derived visual twins and destination assets
```

### Design Family

A Design Family is the creative identity shared by related alternatives: for
example, one floral ring idea explored in several center stones, settings, and
metals. First-class family records, variations, immutable revisions, comparison,
and restore-as-new are implemented in the trusted project control plane. The
unified Collections interface is the presentation layer for these records.

### Variation

A Variation is one coherent branch of the family. The existing `Project`
aggregate is the current persisted variation container and remains the
canonical storage term until an additive family migration is designed and
tested. A variation may be visual-only or may later acquire a validated
specification.

### Immutable Revision

A Revision is an exact point in a variation's history. Where a structured
record exists, the revision binds the primary image to one immutable
`DesignVersion`. Presentation derivatives inherit that exact revision rather
than silently advancing it. Branching creates a new revision or variation; it
never rewrites historical pixels, specification facts, approvals, or evidence.

## Visual twin on demand

A visual twin is a generated depiction of a selected revision for a defined
purpose. It is requested when useful, not generated as compulsory ceremony.
Examples include:

- a photoreal client render;
- a faithful line or colored design illustration;
- an alternate approved view;
- a clean ecommerce product photograph;
- a marketing scene; or
- a proposed mounting or technical discussion view.

Every twin must record its source revision, operation, prompt-contract version,
provider attempt evidence, QA result, and authority status. A presentation-only
twin inherits the same specification version. A twin that proposes structural
change cannot become the active revision until the image and validated record
advance together. A raster twin never proves exact dimensions, hidden
construction, alloy, manufacturability, or factory readiness.

A single unified visual-twin product boundary is target work. Current project
render, reference-render, line-art, product-photo, and marketing operations are
real foundations but are not yet one cross-category studio command surface.

## Component-aware edit engine

The edit engine should reason about stable jewelry components rather than a
flat prompt and a whole image. A component record may carry:

- stable identity and role;
- parent/child and connection relationships;
- source and active-revision hashes;
- one or more view-aware masks;
- visual and structured facts;
- frozen neighbors and protected regions;
- authority and dimension provenance; and
- catalog, custom drawing, sample, or supplier references when applicable.

The current component catalogs, edit domains, saved masks, structured design
forms, source-component coverage, and exact-version revision machinery are
foundations for this model. A unified cross-category component graph and
studio-wide component library are not yet implemented.

### Instant masked configurator

Use the instant lane when geometry and component topology stay fixed. Examples
include previewing an approved metal color, stone color, finish, background, or
another appearance option within an exact saved mask.

The instant lane may apply cached, pre-approved visual layers or bounded pixel
transformations inside recorded masks. Deterministic code may select, mask,
composite, and record pixels; it must not invent a new shank, stone, prong,
setting, link, or other jewelry geometry. An instant preview is not a new
factory fact. If an exact catalog selection also changes the specification,
that delta is compiled from the catalog and committed only through the normal
versioned acceptance boundary.

This unified configurator experience is target work. Existing masks, catalog
selections, visual-only edits, and exact outside-mask compositing demonstrate
parts of the contract, but do not yet constitute a complete instant studio
configurator.

### Structural AI edit

Use the structural lane when the request changes shape, topology, count, or
physical construction. Examples include:

- changing center-stone shape or setting;
- adding or removing stones;
- changing prongs, gallery, shoulders, or shank form;
- changing chain or clasp construction; or
- changing a custom design element's outline or attachment.

The image model creates the revised jewelry pixels. Vision systems compare the
candidate with the exact source, requested component delta, frozen neighbors,
and validated target facts. Observed drift is a hard failure and becomes a
targeted correction; unassessable evidence is held for designer review. A
successful structural change advances image and specification atomically.

The product chooses instant versus structural execution from the component and
delta contract. Designers choose the change they want, not a provider or model.

Structural component-map continuity now has a ring-first production adapter,
but remains disabled until externally reviewed calibration evidence is mounted
and explicitly activated. The first release contract supports center-stone cut
changes only. It maps the source revision on demand, treats the center stone,
prongs, and setting as one coupled edit scope, and maps the generated child
while it is still a temporary PreviewCandidate. Structural warnings are never
accept-capable. Apply and Save as Variation only revalidate and atomically
persist the already reviewed map; they do not make a late provider call.

Activation requires the fixed mapper contract, the verified SHA-256 of an
external calibration artifact, the exact supported catalog path, and a passing
runtime readiness probe. Capability discovery is path-specific, `/health`
reports `unconfigured`, `unhealthy`, or `ready`, and both source and child maps
carry the activated evidence digest. Revocation, evidence drift, an unhealthy
mapper, uncovered changed pixels, outside-target drift, missing semantic
inventory, or a contract mismatch fails closed and settles the linked Refine
job with zero charged outputs. Component maps remain exact-revision raster edit
evidence only; they are never CAD, measurement, manufacturability, or Factory
authority. Setting-style mapping and additional jewelry categories remain
gated work.

## Division of labor

The core invariant is:

> AI creates jewelry geometry and vision checks it. Deterministic code records,
> masks, measures, validates, versions, and lays out evidence; it never designs
> or draws jewelry geometry.

| Owner | Owns | Must not claim |
|---|---|---|
| Image AI | New jewelry concepts, structural visual edits, faithful visual twins, proposed unseen visual construction | Exact measurements, approval, validated specification authorship, or factory authority |
| Vision AI | Source inventory, candidate comparison, component/count/topology checks, uncertainty evidence | Measurement proof, approval, or silent promotion |
| Deterministic control plane | IDs, hashes, masks, exact deltas, physical validation, provenance, measurements supplied by people/records, immutable revisions, page layout, callouts, manifests, and transaction boundaries | Aesthetic invention or jewelry geometry |
| Designer | Direction, clarification, component selection, warning review, supplied/adjusted facts, revision approval, and optional factory promotion | Responsibility for errors hidden by the system |

Deterministic layout may place an approved AI/designer drawing and letter
confirmed facts around it. It may draw masks, crop guides, measurement leaders,
page rules, comparison overlays, and other interface evidence. It may not draw
the ring, necklace, stone, prong, gallery, link, clasp, or setting that it is
supposed to describe.

The repository still contains deterministic generic jewelry schematics and DXF
reference geometry. They remain compatibility/internal primitives and are
explicitly non-authoritative. They are not the target visual architecture and
must not be presented as the actual design or buildable geometry.

## Optional factory promotion lane

Factory promotion begins from one selected immutable revision:

```text
Selected Revision
  -> confirm factory facts and provenance
  -> resolve dimensions and construction evidence
  -> approve exact image/spec pair
  -> generate deterministic records and optional discussion visuals
  -> factory review package
```

Entering this lane is optional. It requires more than visual approval:

- an exact validated record;
- confirmed versus estimated versus pending fact status;
- source-component and revision provenance;
- required dimensions and production references;
- design-derived mounting/section evidence where relevant;
- exact-revision designer approval; and
- an explicit production-authority boundary.

AI-derived technical or mounting views are editable discussion proposals until
the designer confirms them. Even after confirmation, production-ready claims
require tolerance-bearing CAD or a verified master where the manufacturing
process demands it. The current deterministic pack and readiness gates remain
the implemented handoff foundation; replacing generic visual schematics with
design-derived discussion views is still open work.

## Destinations

Organize sends an exact revision or derivative to a declared destination. A
destination changes packaging and permissions, not historical truth.

### Client

- clean candidates, comparisons, comments, and selected visual twins;
- no provider names or internal confidence jargon;
- no factory claims unless the revision actually completed that lane.

### Marketing and ecommerce

- product photographs, backgrounds, campaign scenes, crops, and bundles;
- always bound to the exact source revision and specification version;
- presentation derivatives do not invalidate or advance the primary revision.

### Library

- reusable designer-approved components, masks, palettes, materials, reference
  images, and family/variation exemplars;
- searchable provenance, rights, scope, and quality evidence;
- no training or cross-user reuse without an explicit authorization contract.

### Factory

- optional exact-revision promotion only;
- validated facts, provenance, approvals, hashes, and clearly labeled files;
- no visual guess or generic template presented as production geometry.

The current client, marketing-pack, project/library, and factory endpoints
provide destination foundations. The Studio shell exposes Collections and
contextual Present actions; a fully dynamic destination form remains open work.

## Unified Studio shell

The primary application surface is now one outcome-first shell:

- global navigation: **Studio**, **Collections**, **Activity**, and **Learn**;
- active-revision actions: **Create**, **Vary**, **Refine**, **Views**,
  **Present**, and **More**;
- Factory appears only inside **More** after explicit backend enablement and
  exact-revision eligibility;
- Guided creation shows the brief, one optional presentation direction,
  collection, and save; detailed jewelry controls are hidden behind
  **Advanced specifications**; and
- the previous feature-flagged trusted workspace remains an internal module,
  not a competing top-level product entry.

`StudioActionDefinition`, `StudioJob`, role-labeled references, and temporary
`PreviewCandidate` decisions form the typed UI boundary. Provider selection,
raw prompts, base64 payloads, and QA internals stay below that boundary.

## State and authority

Creative state and factory state must not be collapsed into one status. A
variation can be useful and complete for a client while remaining ineligible
for manufacturing.

Suggested product-level states are:

- **exploring**: candidates or revisions are still being compared;
- **organized**: a revision is selected and stored in its family/variation;
- **client-ready**: the selected visual destination is approved;
- **factory-eligible**: required structured evidence exists;
- **factory-approved**: the exact eligible revision completed approval; and
- **factory-review package available**: the package was generated and hashed.

These names are target product language, not a claim that the current database
or APIs expose this exact state machine. Existing derived project states remain
the implemented contract until an additive migration is approved.

## Legacy deterministic geometry removal

Remove deterministic jewelry-geometry code only after the replacement is real,
not merely planned. A route, renderer, adapter, or template is deletable when
all applicable gates pass:

1. No production client, canonical API, acceptance script, or test imports it.
2. The AI/design-derived replacement covers every still-supported caller and
   has equal or stronger unit, integration, and visual QA.
3. Structural QA blocks missing views/sections, center or component drift,
   count/topology errors, disconnected hardware, interpenetration, crop, text,
   false authority, and rejected-output persistence.
4. Founder/designer acceptance passes on diverse real references, not only
   synthetic controls or one attractive result.
5. Factory packages remain readable and honest for historical revisions; no
   migration, immutable version, provenance, evidence, or golden evaluation is
   deleted.
6. OpenAPI and import diffs contain only reviewed removals, and compatibility
   callers have completed a deprecation window.
7. The replacement preserves deterministic measurement, validation, masks,
   record layout, fact schedules, manifests, and hashes. Only jewelry-geometry
   invention is removed from deterministic code.
8. Documentation and normal UI expose only the canonical studio path.

Until then, generic schematics remain clearly labeled internal/reference
artifacts, hidden from normal creative flow, and ineligible to claim the actual
design or production geometry.

## Delivery sequence

1. Keep the integrated trusted project/revision and image-agent evidence stable.
2. Connect the Studio action gateway to the trusted project APIs without
   exposing the legacy trusted screen.
3. Complete Collections over the implemented Design Family and variation
   records without rewriting history.
4. Unify on-demand visual twins and component-aware edit routing.
5. Add the instant masked configurator for geometry-preserving previews.
6. Add destination packaging for Client, Marketing, Library, and optional
   Factory promotion.
7. Live-test design-derived mounting/section QA and factory discussion views.
8. Apply the legacy removal gates only after founder acceptance.
