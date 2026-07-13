# Trusted workflow route inventory

Generated from `facetta.main.app.openapi()` on the trusted-workflow branch.
The inventory tracks the currently supported and compatibility HTTP operations. “Tests”
means a direct `TestClient` call exists; it does not make the route a supported
product boundary.

Caller abbreviations:

- **Trusted client**: `mobile/src/trusted/client.ts`.
- **Live script**: `scripts/live_verify_approval_markup.py`.

## Operational and trusted project routes

| Method and path | Class | Observed caller evidence | Replacement or disposition |
|---|---|---|---|
| `GET /health` | Canonical | Operational probes; `test_validate_api.py` | Retain as operational health check. |
| `POST /projects/from-brief` | Deprecated compatibility | Hidden trusted-workflow screen; prompt-brief evaluation harness; `test_project_backbone.py` | Retained outside production for historical structured-ring evaluation and warning-review fixtures. Active Studio sentence creation uses `POST /projects/from-prompt`; this route must not return to the public allowlist. |
| `POST /projects/from-prompt` | Canonical | Trusted client; `test_creative_project_api.py` | Category-neutral designer prompt entry. Runs one to four `CREATIVE_GENERATE` variants through direction/coherence QA, atomically persists no source/spec/version, and requires explicit selected-candidate promotion before approval or factory work. |
| `POST /projects/from-drawing` | Canonical | `test_creative_project_api.py` | Neutral drawing/image entry. Runs one to four explicit `REFERENCE_RENDER` variants through source-fidelity QA, persists no partial project on hard failure, and creates no specification or factory authority. |
| `POST /studio/projects/import-confirmed` | Canonical | Studio trusted client; four exact-reference live harnesses; `test_confirmed_import_studio_api.py` | Authenticated designer-confirmed image entry. Requires the independent component audit to name the exact uploaded source SHA-256, then atomically creates the project, immutable Design v1, and byte-identical imported reference. |
| `POST /projects/from-image` | Deprecated compatibility | Historical trusted-workflow tests | Retained outside production for historical development callers. Delegates the same confirmed-import service under the legacy source-audit policy; it must not return to the public allowlist. |
| `POST /projects/{project_id}/creative-candidates/{candidate_id}/draft` | Canonical | Trusted client; `test_creative_project_api.py` | Reads the exact selected pre-spec candidate into a non-persisted, independently audited draft using server-held candidate bytes; no duplicate base64 upload and no specification authority is created. |
| `POST /projects/{project_id}/creative-candidates/{candidate_id}/confirm-design` | Canonical | Studio gateway; `test_creative_project_api.py` | Projects ring facts from the exact selected candidate and issues a short-lived, one-time opaque confirmation token. The server retains the audited specification and binds it to owner, project, candidate bytes, and expiry; no design revision is created until explicit promotion. |
| `POST /projects/{project_id}/creative-candidates/{candidate_id}/select` | Canonical | Studio Create workspace; Trusted client; `test_creative_project_api.py` | Persists which pre-spec visual direction the owner chose and makes it the project cover/active creative candidate without creating a specification, design version, approval, or factory authority. |
| `POST /projects/{project_id}/creative-directions/commit` | Canonical | Studio Create workspace; `test_creative_project_api.py` | Atomically chooses one pre-spec candidate as Original, retains up to three other reviewed candidates as named sibling Variations, and settles the bound Create job exactly once. A project-scoped durable decision makes exact retries idempotent; incomplete or mismatched prior state fails closed without partial selection, branching, family creation, or charging. |
| `POST /projects/{project_id}/creative-candidates/{candidate_id}/dimensioned-profile/confirm` | Canonical | Trusted client; `test_creative_project_api.py` | Binds designer-entered full-assembly millimeter paths/thickness to the exact server-held candidate hash and server confirmation actor/time. It is a non-persisted draft step, derives no geometry from pixels, invalidates stale visual-spec audit evidence, and still requires re-audit plus candidate promotion. |
| `POST /projects/{project_id}/creative-candidates/{candidate_id}/source-coverage/resolve` | Canonical | Trusted client; `test_creative_project_api.py` | Corrects stable component mappings and optionally re-runs the independent audit against the exact stored candidate bytes. |
| `POST /projects/{project_id}/creative-candidates/{candidate_id}/source-coverage/confirm` | Canonical | Trusted client; `test_creative_project_api.py` | Allows only explicit inconclusive-fact confirmation, bound to the exact stored candidate and visual spec; failed or missing audits remain non-overridable. |
| `POST /projects/{project_id}/creative-candidates/{candidate_id}/promote` | Canonical | Studio Confirm; `test_creative_project_api.py` | The owner promotes one exact, acknowledged candidate into immutable Design v1 while retaining every pre-spec variant. Unresolved source questions remain attached as explicit Factory blockers but do not prevent ordinary Studio preservation and refinement. |
| `POST /studio/projects/{root_id}/beauty-render` | Canonical | Studio Present; Trusted client; `designer-reference-e2e-2026-07-11`; project render tests | QA-gated Client beauty preview from a confirmed exact revision. The route requires `presentation_only=true` and an accounted Studio job, preserves the active revision, and delegates to the trusted render transaction so accepted bytes remain `CLIENT_BEAUTY_RENDER` derivatives. |
| `POST /studio/projects/{root_id}/product-photo` | Canonical | Studio Present; Trusted client; product-photo compiler/project tests; `designer-product-photo-live-2026-07-11` | QA-gated ecommerce preview from an exact revision. The route requires `presentation_only=true` and an accounted Studio job, rejects physical redesign instructions, and delegates to the trusted product-photo transaction so accepted bytes remain `CLIENT_PRODUCT_PHOTO` derivatives. |
| `POST /projects/{root_id}/render` | Deprecated compatibility | Hidden trusted-workflow screen; project render acceptance tests | Retained outside production while historical callers migrate. It still supports the older primary-revision behavior and must not be restored to the public allowlist. |
| `POST /projects/{root_id}/product-photo` | Deprecated compatibility | Hidden trusted-workflow screen; project product-photo acceptance tests | Retained outside production while historical callers migrate. It still supports the older `PRODUCT_PHOTO` primary-revision behavior and must not be restored to the public allowlist. |
| `POST /projects/{root_id}/marketing-pack` | Canonical | `test_marketing_pack_api.py` | Generates one to four presentation-only background candidates from the exact active image/spec. Every output requires designer selection; accepted outputs persist as derived `MARKETING_IMAGE` assets and never replace the active design revision or invalidate factory approval. Partial provider/quality failures retain run evidence without product bytes. |
| `POST /projects/{root_id}/visual-twin/views` | Internal primitive | `test_visual_twin_api.py` | Retained for historical development/evaluation callers but not mounted in production because it has no durable StudioJob contract. Active Studio Views uses the exact-revision, job-bound line-art candidate workflow. |
| `POST /projects/{root_id}/line-art` | Canonical | Drawing workflow/project tests; canonical live line-art eval | Creates a temporary geometry-only drawing from the active revision. QA pass still requires explicit designer confirmation before `LINE_ART` becomes a derived asset. |
| `POST /projects/{root_id}/line-art/{line_art_asset_id}/colorize` | Canonical | Drawing workflow/project/material-drift tests; `designer-corrected-full-e2e-2026-07-11` | Colors only a confirmed line drawing from the exact spec. Keeps the active revision/spec unchanged, sends corroborated material loss through targeted correction/hard failure, and holds conflicting raster/vision evidence for explicit review. |
| `GET /projects/from-brief/candidates/{candidate_id}/image` | Deprecated compatibility | Hidden trusted-workflow warning review; prompt-brief evaluation harness; `test_project_backbone.py` | Retained outside production so historical structured-ring warning candidates can still be inspected; never a project asset. |
| `POST /projects/from-brief/candidates/{candidate_id}/accept` | Deprecated compatibility | Hidden trusted-workflow warning review; prompt-brief evaluation harness; `test_project_backbone.py` | Retained outside production to preserve the historical continue-or-persist transaction after explicit review. Active Studio uses the category-neutral Create candidate decision flow. |
| `GET /projects/{root_id}` | Canonical | Trusted client; project/library tests | Canonical project read model. |
| `GET /studio/families/{family_id}` | Canonical | `test_studio_domain_models.py` | Returns one Design Family and its ordered, independently versioned project variations without collapsing their histories. |
| `GET /studio/families` | Canonical | Studio Collections workspace; Trusted client; `test_studio_domain_models.py` | Lists canonical Design Families, optionally owner-filtered, while retaining each variation's independent project identity and branch provenance. |
| `GET /studio/projects/{project_root_id}/history` | Canonical | Studio history tests; immutable revision model tests | Returns append-only primary revision history, raw designer intent, interpretation, change summary, lineage, and exact image/spec references for one variation. |
| `POST /studio/projects/{project_root_id}/variations` | Canonical | Studio branching and domain model tests | Save as Variation forks the exact current asset/spec into a sibling project within the same Design Family with stale-version protection. |
| `POST /studio/projects/{project_root_id}/creative-candidates/{candidate_id}/variations` | Canonical | Studio Create comparison; pre-spec journey tests | Saves an explicitly kept, unselected Create candidate as a named sibling Variation after the Original direction is fixed. Candidate alternatives remain durable review records, never masquerade as sequential revisions, and the exact raster/component map is copied without inventing authority. |
| `POST /studio/projects/{project_root_id}/revisions/{asset_id}/restore` | Canonical | Studio restoration and immutable revision model tests | Restores historical content by appending a new primary revision; it never rewrites or deletes the original history. |
| `POST /studio/projects/{project_id}/visual-previews` | Canonical | Studio Refine; Trusted client; `test_studio_visual_preview_api.py` | Generates a temporary appearance-only or exact-marked-region preview from the selected pre-spec visual. Persists ImageRun evidence but no ImageAsset, Design, DesignVersion, or factory authority. Structural scope is rejected. |
| `GET /studio/projects/{project_root_id}/visual-candidates` | Canonical | Studio Refine resume; Trusted client; `test_studio_visual_preview_api.py` | Reopens durable owner-scoped visual previews after refresh. Every decision remains bound to the exact selected source asset and hash; stale or terminal candidates fail closed. |
| `GET /studio/image-runs/{run_id}/visual-candidates/{candidate_id}/image` | Canonical | Studio Refine; Trusted client; `test_studio_visual_preview_api.py` | Returns private, no-store bytes for one temporary pre-spec visual candidate. Applied, discarded, and expired candidates are unavailable. |
| `POST /studio/image-runs/{run_id}/visual-candidates/{candidate_id}/accept` | Canonical | Studio Refine; Trusted client; `test_studio_visual_preview_api.py` | Rechecks exact owner, project, selected source, source hash, and run lineage; atomically appends a null-spec `GLOBAL_RESTYLE` or `LOCALIZED_EDIT` revision and advances the selected visual with compare-and-set semantics. It does not rerun the provider or create specification/factory authority. |
| `POST /studio/image-runs/{run_id}/visual-candidates/{candidate_id}/discard` | Canonical | Studio Refine; Trusted client; `test_studio_visual_preview_api.py` | Records a terminal designer discard, removes temporary candidate bytes, and leaves canonical project history unchanged while retaining durable run/review evidence. |
| `POST /studio/image-runs/{run_id}/visual-candidates/{candidate_id}/save-as-variation` | Canonical | Studio Refine; Trusted client; `test_studio_visual_preview_api.py` | Atomically saves a reviewed visual candidate as a sibling pre-spec project in the same Design Family. The source remains unchanged; the sibling retains exact candidate bytes and run provenance with no specification or Factory authority. |
| `GET /studio/projects/{project_root_id}/markup-candidates` | Canonical | Studio Refine resume; Trusted client; `test_studio_markup_candidate_durability.py` | Reopens durable exact-revision Describe/Mark-up previews after app or worker restart. Only owner-scoped, review-pending candidates bound to the selected source asset/spec are returned. |
| `GET /studio/markup-candidates/{run_id}/{candidate_id}/image` | Canonical | Studio Refine; Trusted client; `test_studio_markup_candidate_durability.py` | Returns private, no-store bytes for one unresolved exact Refine candidate. Terminal, expired, foreign, and stale candidates fail closed. |
| `POST /studio/markup-candidates/{run_id}/{candidate_id}/accept` | Canonical | Studio Refine; Trusted client; `test_studio_markup_candidate_durability.py` | Revalidates exact project/source/spec hashes and QA, then atomically appends an immutable revision, resolves the candidate, and settles its Studio job charge once. |
| `POST /studio/markup-candidates/{run_id}/{candidate_id}/discard` | Canonical | Studio Refine; Trusted client; `test_studio_markup_candidate_durability.py` | Atomically records a terminal discard, settles the linked Studio job with zero accepted outputs, removes temporary bytes, and leaves canonical history unchanged. |
| `POST /studio/markup-candidates/{run_id}/{candidate_id}/save-as-variation` | Canonical | Studio Refine; Trusted client; `test_studio_markup_candidate_durability.py` | Atomically saves the exact reviewed candidate as a sibling Design Family variation, preserves source history, retains generation provenance, and settles the linked Studio job once. |
| `GET /studio/view-candidates` | Canonical | Studio Views resume; Trusted client; `test_studio_exact_candidate_durability.py` | Lists durable owner-scoped exact-spec line-art View candidates after refresh or worker restart. |
| `GET /studio/view-candidates/{run_id}/{candidate_id}/image` | Canonical | Studio Views; Trusted client; `test_studio_exact_candidate_durability.py` | Returns private, no-store bytes for one unresolved exact View candidate; terminal and foreign candidates fail closed. |
| `POST /studio/view-candidates/{run_id}/{candidate_id}/accept` | Canonical | Studio Views; Trusted client; `test_studio_exact_candidate_durability.py` | Rechecks owner, active source asset and hash, immutable design version, image-run lineage, output hash, and QA before atomically saving a derived `LINE_ART` asset without advancing the active revision. |
| `POST /studio/view-candidates/{run_id}/{candidate_id}/discard` | Canonical | Studio Views; Trusted client; `test_studio_exact_candidate_durability.py` | Persists a terminal exact View rejection with no derived asset, revision mutation, or hidden charge. |
| `POST /studio/projects/{project_root_id}/facts/revise` | Canonical | Studio fact revision API; `test_studio_facts_api.py` | Applies authenticated allowlisted designer facts against an exact active asset/spec version. A valid change atomically appends a byte-identical visual revision, immutable DesignVersion, designer-confirmed dimension provenance, and hash-bound history with zero provider use or credits. |
| `POST /studio/projects/{project_id}/presentation-previews` | Canonical | Studio Present; Trusted client; `test_studio_pre_spec_presentation_api.py` | Generates one review-only Client or Marketing image from the exact selected pre-spec visual. Uses source-faithful reference rendering without creating a specification, revision, approval, or factory authority. |
| `GET /studio/presentation-candidates` | Canonical | Studio Present resume; Trusted client; `test_studio_pre_spec_presentation_api.py` | Lists one owner's durable review-pending pre-spec presentation candidates, optionally scoped to an exact project, so refreshes and API worker changes do not lose a decision. |
| `GET /studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/image` | Canonical | Studio Present; Trusted client; `test_studio_pre_spec_presentation_api.py` | Returns private, no-store bytes for one temporary pre-spec presentation candidate. Saved, discarded, and expired candidates are unavailable. |
| `POST /studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/accept` | Canonical | Studio Present; Trusted client; `test_studio_pre_spec_presentation_api.py` | Rechecks owner, selected source asset, source SHA-256, run lineage, and null-spec authority before saving a derived Client or Marketing asset. The active visual remains unchanged. |
| `POST /studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/discard` | Canonical | Studio Present; Trusted client; `test_studio_pre_spec_presentation_api.py` | Records a durable terminal rejection against the exact source hash, removes temporary bytes, and creates no asset or charged output. |
| `POST /studio/presentation-candidates/{run_id}/{candidate_id}/accept` | Canonical | Studio Present; Trusted client; `test_marketing_pack_api.py`, `test_project_backbone.py` | Rechecks owner plus exact project, source asset, design version, hashes, operation, and active state before saving a presentation-only candidate as a derived asset. The active design revision and specification do not change. |
| `POST /studio/presentation-candidates/{run_id}/{candidate_id}/discard` | Canonical | Studio Present; Trusted client; `test_marketing_pack_api.py` | Records a durable terminal discard for one exact-lineage presentation candidate without creating an asset or changing the active design revision. |
| `GET /studio/capabilities` | Canonical | Authenticated Studio shell and gateway; `test_auth_boundary.py` | Returns server-owned, fail-closed optional destination capabilities for the exact principal. It explicitly reports that durable workspace entitlements are not yet available. |
| `POST /studio/jobs` | Canonical | Studio gateway and Activity workspace; `test_studio_jobs_api.py` | Creates the persistent designer-facing record before generation starts. Stores action, lane, exact design/revision lineage, requested outputs, and the upfront per-output estimate without provider or retry internals. |
| `GET /studio/jobs` | Canonical | Studio Activity workspace; Trusted client; `test_studio_jobs_api.py` | Owner-scoped Activity feed with optional lifecycle filter. Another owner's job identity fails closed. |
| `GET /studio/jobs/{job_id}` | Canonical | Trusted client; `test_studio_jobs_api.py` | Reads one owner-scoped persistent job. |
| `PATCH /studio/jobs/{job_id}` | Canonical | Studio gateway; Trusted client; `test_studio_jobs_api.py` | Enforces monotonic queued, running, reviewing, succeeded, failed, or canceled transitions. Only successfully completed requested outputs become charged outputs. |
| `POST /studio/jobs/{job_id}/cancel` | Canonical | Studio gateway; Activity workspace; `test_studio_jobs_api.py` | Cancels eligible queued or running work with zero charged outputs; terminal and review states fail closed. |
| `GET /projects/{project_id}/factory-pack` | Canonical | Trusted client; `test_trusted_handoff.py` | Retain; exact approved manifest. |
| `POST /projects/{project_id}/factory-pack` | Canonical | Studio Factory workspace; `test_studio_jobs_api.py` | Revalidates a queued Factory job against the locked exact revision and approval generation, builds the deterministic review pack, and atomically settles one accepted output. Pack failures and stale context terminate with zero charge. |
| `GET /projects/{project_id}/factory-pack.zip` | Canonical | Trusted client; `test_trusted_handoff.py`; corrected designer E2E; ten-template DXF parity suite | Retain; exact approved archive. Validated JSON and deterministic SVG are factory truth. Transform-aware DXF remains a bundled non-authoritative R12 underlay because sampled 2D curves are not solid/tolerance-bearing fabrication geometry; an exact-version confirmed line drawing is included only as manifest-labeled, non-authoritative discussion context. |
| `GET /image-runs/{run_id}` | Internal primitive | Trusted compatibility client; `test_trusted_handoff.py` | Retain append-only QA/routing evidence for evaluation and operations, but exclude raw provider/model/QA metadata from the production Studio router. |
| `POST /image-runs/{run_id}/feedback` | Internal primitive | Trusted compatibility client; image-run feedback tests | Retain evaluation feedback outside the production Studio router; designer decisions use owner-scoped candidate endpoints instead. |
| `GET /image-runs/{run_id}/candidates/{candidate_id}/image` | Canonical | Trusted warning review; `test_markup_api.py` | Temporary preview only; bytes are not a project asset. |
| `POST /image-runs/{run_id}/candidates/{candidate_id}/accept` | Canonical | Trusted client; `test_markup_api.py` | Explicit designer promotion of a QA-warning candidate with stale-version protection. |
| `POST /image-runs/{run_id}/candidates/{candidate_id}/discard` | Canonical | Studio Refine; Trusted client; `test_markup_api.py` | Terminally discards a temporary markup candidate while preserving append-only ImageRun evidence; it can no longer be accepted. |
| `GET /image-runs/{run_id}/catalog-candidates/{candidate_id}/image` | Canonical | Trusted catalog preview; `test_catalog_revision_api.py` | Returns private, no-store bytes for one temporary pass-or-warning catalog preview; never a product asset. |
| `POST /image-runs/{run_id}/catalog-candidates/{candidate_id}/accept` | Canonical | Trusted catalog preview; `test_catalog_revision_api.py` | Applies the already evaluated candidate without rerunning the provider, after exact active-asset, design-version, source-hash, and source/target spec-hash checks. Image, immutable spec, and append-only review persist atomically. |
| `POST /image-runs/{run_id}/catalog-candidates/{candidate_id}/save-as-variation` | Canonical | Studio Refine; Trusted client; `test_catalog_revision_api.py` | Atomically saves the reviewed candidate and its exact proposed specification as Design v1 of a sibling project in the same family, without first applying it to or advancing the source project. |
| `DELETE /image-runs/{run_id}/catalog-candidates/{candidate_id}` | Canonical | Trusted catalog preview; `test_catalog_revision_api.py` | Discards temporary candidate bytes while retaining append-only ImageRun evidence. |

## Asset and approval routes

| Method and path | Class | Observed caller evidence | Replacement or disposition |
|---|---|---|---|
| `POST /assets/render` | Deprecated compatibility | Asset/library/checklist tests; live script | Replace sentence creation with `POST /projects/from-prompt`; keep exact confirmed imports on `POST /studio/projects/import-confirmed`. |
| `GET /assets/{asset_id}` | Internal primitive | Asset/checklist tests | Retain as a narrow asset read until all consumers use `ProjectDetail`. |
| `GET /assets/{asset_id}/image` | Canonical | Trusted client constructs this URL; project payloads return it | Retain; image bytes stay out of project JSON. |
| `GET /assets/{asset_id}/component-map` | Canonical | Trusted component-aware editing | Returns the accepted revision's stable semantic component IDs and normalized regions without exposing provider internals. |
| `GET /assets/{asset_id}/studio-component-targeting` | Canonical | Studio Refine capability gate; `test_catalog_revision_api.py` | Returns designer-safe targetability states, stable component IDs, and exact revision hashes for released catalog paths. It never exposes raw polygons or treats the raster map as jewelry geometry. |
| `POST /assets/{asset_id}/studio-component-map` | Canonical | Studio Refine automatic ring preparation; Trusted client; `test_catalog_revision_api.py` | Idempotently prepares the exact ring revision's image-space component map only when the fixed mapper contract, verified external calibration digest, released path, and runtime readiness are active. It consumes no generation credit, creates no revision, and carries no Factory authority. |
| `GET /assets/{asset_id}/components/{component_id}/mask` | Canonical | Trusted component-aware editing | Returns the normalized mask for one stable component on the exact accepted revision; used as deterministic targeting input, never as jewelry geometry. |
| `GET /assets/{asset_id}/history` | Internal primitive | `test_assets.py` | Project revisions are canonical; retain compare/history primitive while client migration completes. |
| `POST /assets/{asset_id}/markup/read` | Canonical | Trusted client; markup and design-form acceptance tests; live script | Retain; read-only interpretation with stable design-form element IDs when an organic component is targeted. |
| `POST /assets/{asset_id}/markup/apply` | Canonical | Trusted client; markup tests; live script | Retain; canonical confirmed, version-checked mutation. |
| `POST /assets/{active_asset_id}/catalog/preview` | Canonical | Trusted client; `test_catalog_revision_api.py` | Runs the exact catalog compiler, provider routing, and jewelry QA before any product persistence. Pass and warning candidates remain temporary until explicit Apply; hard failures retain evidence only. |
| `GET /assets/{active_asset_id}/catalog/previews` | Canonical | Studio Refine resume; Trusted client; `test_catalog_revision_api.py` | Reopens durable owner-scoped catalog previews for the exact active revision. The proposed specification, candidate bytes, and hashes remain non-canonical until an explicit terminal decision. |
| `POST /assets/{active_asset_id}/catalog/apply` | Deprecated compatibility | `test_catalog_revision_api.py` | Existing direct-apply boundary retained while callers migrate to Preview then explicit Apply. Uses the same catalog compiler and image-agent plan; remove only after no production caller remains. |
| `POST /assets/{asset_id}/checklist` | Canonical | Trusted client; checklist/handoff tests; live script | Retain; bind exact asset/spec. |
| `GET /assets/{asset_id}/checklist` | Canonical | Trusted client; checklist tests | Retain approval read model. |
| `POST /assets/{asset_id}/checklist/respond` | Canonical | Trusted client; checklist/handoff tests; live script | Retain; completed checklist pins the exact pair. |
| `POST /assets/{asset_id}/feedback` | Canonical | `test_feedback.py` | Retain Accepted/Regenerated/Rejected evidence; wire trusted UI. |
| `GET /assets/insights/instruction-stats` | Internal primitive | `test_feedback.py` | Internal evaluation/operations read model. |
| `PATCH /assets/{asset_id}/organize` | Internal primitive | `test_library.py` | Move project metadata mutation behind a project service before making it canonical. |
| `PATCH /assets/{asset_id}/link-design` | Internal primitive | Asset/markup tests | Migration primitive for legacy chains; new projects link atomically. |
| `POST /assets/{asset_id}/pin` | Canonical | Trusted approval client; asset/checklist tests; live script | Retain as the explicit final approval action for an eligible exact revision. It is serialized with checklist generation and Factory CAS, and cannot change approval truth while Factory consumes that generation. |
| `POST /assets/{asset_id}/localized-edit` | Deprecated compatibility | Asset/library/checklist tests | Replace with confirmed markup apply through the image agent. |
| `POST /assets/{asset_id}/views` | Deprecated compatibility | `test_assets.py` | Reintroduce only through observed derived-asset execution. |
| `POST /assets/{asset_id}/global-restyle` | Deprecated compatibility | `test_assets.py` | Route future presentation-only work through `VISUAL_ONLY_EDIT`. |
| `POST /assets/{asset_id}/video` | Deprecated compatibility | `test_assets.py` | Deferred feature; migrate through observed derived-asset execution. |
| `POST /assets/{asset_id}/technical-drawing` | Deprecated compatibility | Asset/checklist tests; live script | Factory truth comes from the approved project pack; optional AI drawing must be non-authoritative. |

## Project library routes

| Method and path | Class | Observed caller evidence | Replacement or disposition |
|---|---|---|---|
| `GET /library` | Internal primitive | `test_library.py` | Retain project search; move query helpers out of router modules. |
| `GET /library/collections` | Internal primitive | `test_library.py` | Retain Advanced/workspace filter primitive. |
| `GET /library/tags` | Internal primitive | `test_library.py` | Retain Advanced/workspace filter primitive. |

## Immutable design and collaboration routes

| Method and path | Class | Observed caller evidence | Replacement or disposition |
|---|---|---|---|
| `POST /designs` | Internal primitive | Legacy client; design/agent/markup tests; live script | Retain for Advanced specifications; trusted creation persists through `/projects`. |
| `GET /designs` | Internal primitive | Legacy client; design/handoff tests | Retain Advanced specifications listing during migration. |
| `GET /designs/{design_id}` | Internal primitive | Legacy client; design tests | Retain immutable spec history primitive. |
| `POST /designs/{design_id}/versions` | Internal primitive | Legacy client; design tests | Retain explicit Advanced spec version creation; trusted revisions commit atomically elsewhere. |
| `GET /designs/{design_id}/versions/{version}` | Internal primitive | Legacy client; design/agent tests | Retain exact immutable spec read. |
| `GET /designs/{design_id}/changes` | Internal primitive | `test_designs_api.py` | Retain structural diff primitive. |
| `POST /designs/{design_id}/set-field` | Internal primitive | `test_setfield.py` | Retain validated Advanced editor primitive. |
| `POST /designs/{design_id}/edit` | Deprecated compatibility | `test_agent.py` | Duplicate Claude spec orchestration; migrate to scoped project revision service. |
| `POST /designs/{design_id}/annotate` | Deprecated compatibility | `test_annotate.py` | Replace with asset markup interpretation/apply. |
| `GET /designs/{design_id}/versions/{version}/sheet.svg` | Internal primitive | Legacy client; design tests | Retain deterministic exact-version sheet. |
| `GET /designs/{design_id}/versions/{version}/sheet.dxf` | Internal primitive | Handoff/design tests | Retain deterministic exact-version DXF. |
| `GET /designs/{design_id}/versions/{version}/true_size.svg` | Internal primitive | Tests/docs | Retain deterministic Advanced preview. |
| `GET /designs/{design_id}/versions/{version}/plate.svg` | Internal primitive | Tests/docs | Retain deterministic presentation preview. |
| `GET /designs/{design_id}/versions/{version}/prototype.svg` | Internal primitive | Tests/docs | Retain deterministic presentation preview. |
| `GET /designs/{design_id}/versions/{version}/stack/{other_id}/{other_version}/sheet.svg` | Internal primitive | Stacking/design tests | Retain deterministic Advanced comparison. |
| `GET /designs/{design_id}/versions/{version}/blueprint-sheet.svg` | Deprecated compatibility | Blueprint tests/docs | It starts a provider outside the image agent; migrate or keep only as a non-authoritative internal service. |
| `GET /designs/{design_id}/versions/{version}/render.png` | Deprecated compatibility | Render/design tests/docs | Replace provider execution with a persisted `SPEC_RENDER` run. |
| `GET /designs/{design_id}/versions/{version}/comments` | Internal primitive | Legacy client; design tests | Collaboration is deferred but the exact-version record remains readable. |
| `POST /designs/{design_id}/versions/{version}/comments` | Internal primitive | Legacy client; design tests | Keep out of primary navigation until authenticated collaboration exists. |
| `GET /designs/{design_id}/messages` | Internal primitive | Trusted and legacy clients; handoff tests | Internal-studio review comments; external collaboration still requires authentication. |
| `POST /designs/{design_id}/messages` | Internal primitive | Trusted and legacy clients; handoff tests | Version-aware internal-studio comment; keep external sharing deferred. |
| `POST /designs/{design_id}/versions/{version}/share` | Deprecated compatibility | Legacy client; design tests | Remove token sharing after callers migrate; external beta requires revocable authenticated sharing. |

## Stateless specification routes

| Method and path | Class | Observed caller evidence | Replacement or disposition |
|---|---|---|---|
| `POST /specs/validate` | Internal primitive | Legacy client; validation/fit tests | Retain pure validation behind Advanced specifications and services. |
| `POST /specs/catalog/select` | Internal primitive | Trusted Factory Facts editor; draft catalog/API tests | Compile one controlled component option and its coupled/derived facts against an unpersisted draft. No provider call, persistence, or factory authority. |
| `POST /specs/stone/select` | Internal primitive | Trusted Factory Facts editor; vocabulary/stone-selection tests | Apply one vocabulary-controlled center species and trade color, clear incompatible species-specific claims, and recompute modeled carat at frozen dimensions. |
| `POST /specs/estimate-stone` | Internal primitive | `test_estimate.py` | Retain deterministic designer assist. |
| `POST /specs/sheet.svg` | Internal primitive | Legacy client; drawing tests | Retain deterministic unsaved preview; not factory authority. |
| `POST /specs/sheet.dxf` | Internal primitive | Handoff tests/docs | Retain deterministic unsaved preview; factory pack is canonical handoff. |
| `POST /specs/true-size.svg` | Internal primitive | Legacy client; true-size tests | Retain deterministic Advanced preview. |
| `POST /specs/prototype.svg` | Internal primitive | Legacy client; prototype tests | Retain deterministic Advanced preview. |
| `POST /specs/plate.svg` | Internal primitive | Legacy client; plate tests | Retain deterministic Advanced preview. |
| `POST /specs/control-image.svg` | Internal primitive | Mockup tests/docs | Keep as internal geometry scaffold, not a user-visible provider workflow. |
| `POST /specs/stack.svg` | Internal primitive | Stacking tests | Retain deterministic Advanced comparison. |
| `POST /specs/annotated-artwork.svg` | Internal primitive | `test_artwork.py` | Retain deterministic code-lettered overlay. |
| `POST /specs/from-prose` | Internal primitive | Legacy client; prose tests | Anthropic prose extraction is intentionally retained; designer validation still gates persistence. |
| `POST /specs/from-photo` | Internal primitive | Trusted reference-draft client; photo-spec/source-audit tests | Grok Vision proposes visible facts and deterministic completion; stable coverage is seeded from represented components, trusted callers run a blind-first audit, and designer confirmation gates dimensions. |
| `POST /specs/from-plate` | Internal primitive | Trusted reference-draft client; plate compiler/source-audit/hand-off tests | Plate draft with explicit major-component coverage. Trusted callers request a blind-first independent audit; unresolved, unmapped, failed, and inconclusive items remain visible blockers. |
| `POST /specs/source-coverage/resolve` | Internal primitive | Trusted reference-draft client; source-component resolution/audit tests | Pure unpersisted batch resolver for existing stable source-component mappings. Semantic changes clear prior audit evidence; the persisted project revision workflow remains the product edit boundary. |
| `POST /specs/source-coverage/confirm` | Internal primitive | `test_source_component_confirmation.py` | Pure internal-studio review boundary for an inconclusive independent audit. It changes no spec values, cannot override failed/missing audits, and binds visible-source or designer-defined-target confirmation to exact source bytes and visual-spec hash. |
| `POST /specs/assist` | Internal primitive | `test_assistant.py` | May collect a brief, but active Studio sentence creation must finish through `/projects/from-prompt`. |
| `POST /specs/swap-stone` | Internal primitive | Stone-library tests | Retain validated Advanced editor primitive. |
| `POST /specs/from-concept` | Deprecated compatibility | Concept tests/docs | Active Studio confirms and promotes an exact selected `POST /projects/from-prompt` or drawing candidate instead of creating specification authority through this adapter. |
| `POST /specs/build` | Deprecated compatibility | Build/spec-agent tests/docs | Remove mega orchestration after founder acceptance. |
| `POST /specs/jewelry-render` | Deprecated compatibility | Agent-mode tests | Replace with persisted image-agent `CONCEPT_GENERATE`/`SPEC_RENDER`. |
| `POST /specs/localized-edit` | Deprecated compatibility | Agent-mode/house-style tests | Replace with confirmed asset markup apply. |
| `POST /specs/technical-drawing` | Deprecated compatibility | Spec-agent tests | Replace public stateless drawing with approved project handoff. |
| `POST /specs/agent-sheet` | Dead/conflicting | Spec-agent tests only | Exact alias of `/specs/technical-drawing`; remove with compatibility route. |
| `POST /specs/read-plate` | Deprecated compatibility | Spec-agent tests | Provider-backed stateless flow; retain extraction internally, persist via project onboarding. |
| `POST /specs/plate-lineart` | Deprecated compatibility | Spec-agent tests | Provider-backed drawing step must become an internal image-agent capability if still needed. |
| `POST /specs/plate-colorize` | Deprecated compatibility | Spec-agent tests; live line-art/color eval | Provider-backed drawing step must become an internal image-agent capability; geometry QA rejects added/removed/moved elements before a sheet is returned. |
| `POST /specs/blueprint-sheet.svg` | Deprecated compatibility | Blueprint tests/docs | Provider-backed preview bypasses image-run QA/observability. |
| `POST /specs/render.png` | Deprecated compatibility | Render tests/docs | Replace with persisted image-agent `SPEC_RENDER`. |
| `POST /specs/artwork-restyle.png` | Deprecated compatibility | Artwork tests | Replace with observed `VISUAL_ONLY_EDIT`; geometry/spec must remain frozen. |
| `POST /specs/render-request` | Deprecated compatibility | Legacy client; mockup tests | Migrate caller; raw compiler payload/model control is not product UI. |
| `POST /specs/restage-request` | Dead/conflicting | Handoff tests only | Remove public compiler path after any useful compiler becomes internal. |
| `POST /specs/render-prompt` | Dead/conflicting | Docs/tests only | Raw prompt export conflicts with versioned prompt contracts. |
| `POST /specs/finish-request` | Dead/conflicting | Mockup tests only | Raw compiler endpoint; image agent owns execution contracts. |
| `POST /specs/artwork-restyle-request` | Dead/conflicting | Artwork tests only | Raw compiler endpoint; visual-only plan owns frozen facts. |
| `POST /specs/infer-capability` | Dead/conflicting | Agent-mode tests only | Canonical `ImageAgentPlan` normalizes operation internally. |

## Vocabulary, saved-stone, and local-user primitives

| Method and path | Class | Observed caller evidence | Replacement or disposition |
|---|---|---|---|
| `GET /vocabulary/stones` | Internal primitive | Legacy client; vocabulary tests | Retain controlled-vocabulary data. |
| `GET /vocabulary/stones/{stone_id}/options` | Internal primitive | Legacy client; vocabulary tests | Retain cascading controlled-vocabulary data. |
| `GET /vocabulary/findings` | Internal primitive | Legacy client; validation tests | Retain controlled-vocabulary data. |
| `GET /vocabulary/components/{component_path}` | Internal primitive | Component-catalog/vocabulary tests | Typed chain style, center cut, complete metal alloy/color, and center-setting selections compile into exact validated spec deltas with isolation, coupled-field, applicability, and frozen-fact metadata. Pointed cuts needing V-prong placement remain omitted. |
| `POST /stones` | Internal primitive | Legacy client; stone tests | Retain Advanced saved-stone primitive. |
| `GET /stones` | Internal primitive | Legacy client; stone tests | Retain Advanced saved-stone primitive. |
| `POST /users` | Internal primitive | Design tests | Internal-studio placeholder; replace before external beta authentication. |
| `GET /users` | Internal primitive | Design tests | Internal-studio placeholder; never expose as the authorization model. |

## Token-share compatibility routes

| Method and path | Class | Observed caller evidence | Replacement or disposition |
|---|---|---|---|
| `GET /share/{token}` | Deprecated compatibility | Legacy client; design tests | Remove token-paste workflow after authenticated/revocable sharing exists. |
| `GET /share/{token}/sheet.svg` | Deprecated compatibility | Legacy client; design tests | Factory pack and exact-version authenticated access replace it. |
| `POST /share/{token}/comments` | Deprecated compatibility | Legacy client; design tests | Do not expose externally without authorization, revocation, retention, and audit controls. |

## Removal ledger

For every Deprecated compatibility or Dead/conflicting row, the deletion PR
must record:

1. the last production caller removed;
2. the replacement test(s);
3. the founder-acceptance result set name;
4. the OpenAPI operations intentionally removed; and
5. confirmation that existing database history remains readable.

Routes classified Internal primitive are not automatically permanent public
API. They should move behind focused services as the Advanced specifications
client and trusted workflow converge.
