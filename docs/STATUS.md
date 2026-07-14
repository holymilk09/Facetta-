# Project status — read me first in a new session

Last updated: 2026-07-14 · branch `codex/facetta-integration`.
Read `CLAUDE.md` (constitution — binding), `README.md` (endpoints/layout),
`docs/DATA_WANTED.md` (open research asks). This file is the delta: what is
DONE beyond the original TASKS.md build order, and what is next.

## 2026-07-14 exact-context web workflow checkpoint

Studio Refine now invalidates every in-flight preview or decision when its
exact project, source asset, or design version changes. Instructions, markup,
component choices, design-fact review, and temporary candidates are cleared on
that boundary. Late Preview, Apply, Discard, Save as Variation, markup-read,
or fact-save responses are ignored even across an A -> B -> A switch or
unmount, so an old request cannot reappear against a familiar-looking source.

Visual-only Restore now closes its pre-specification concurrency gap with an
explicit compare-and-set on the expected active asset. The byte-identical
child, copied component map, provenance record, and active pointer still share
one transaction; a competing Apply or Restore causes the entire proposed
restore to roll back instead of leaving an accepted sibling or last-writer-wins
pointer. Exact-specification projects continue to serialize through immutable
DesignVersion history.

Protected Studio images now use an authenticated same-origin fetch on web,
validate a successful nonempty image response, and render a revocable object
URL without placing bearer credentials in the display source. Replacement,
unmount, and stale requests abort or revoke their bytes; failures expose only
a bounded, generic retry. Native clients retain their authenticated image
headers. This repairs the two-direction Create review path without relaxing
the existing origin or sign-in fail-closed behavior.

The authenticated shell now owns the full viewport on every route, eliminating
the black root exposed beneath short light workspaces while preserving the dark
Studio home. New accounts no longer see an invented "Continue saved work"
choice: that action appears only after a one-shot family read confirms saved
work. Confirmed-empty Collections offers a direct "Start a design" action back
to canonical Create; unknown or unavailable family state makes no claim.

Local validation is green: 1,785 backend tests; all 36 mobile Jest suites (300
tests); 77 Studio contract tests; TypeScript; Ruff; Expo web export; diff
hygiene; and the complete ten-project production TypeScript-client -> HTTP ->
FastAPI acceptance run with no Factory use. The provider-free frozen definition
still covers 144 integrity sources, 58 ring-quality sources, and 1,044 planned
evaluation sequences with zero execution-ready sequences and zero provider
calls. The credential-free staging probe exits `77` with
`secrets_logged: false`. The signed live corpus, independent designer/GIA
review, founder approval, authority enrollment, and live two-principal HTTPS
staging evidence remain unmet external-beta gates.

## 2026-07-14 selection-order, source-provenance, and legacy-discovery checkpoint

Studio project hydration now treats every Collections or Activity open as an
ordered designer selection. A slower response from an earlier selection can no
longer replace the latest family variation, open the wrong revision, or surface
an obsolete recovery error. Signing out also invalidates any in-flight project
open before authenticated UI state is cleared.

`ImageAsset.source_kind` is now part of the canonical immutability boundary.
Persisted drawing, photograph, finished-render, or legacy unknown provenance
cannot be relabeled in place after the asset has entered revision history;
pinning remains the deliberately mutable presentation exception.

The signed staging probe now checks 53 exact retired method/path pairs instead
of only the previous mutation subset. It covers every route classified as
Deprecated compatibility or Dead/conflicting, including provider-triggering
GET renders, raw prompt/compiler operations, design edit/annotation adapters,
and token-share reads. Tests bind every probe template to a real development
route, prove every one is absent from production OpenAPI and method discovery,
and require every production mutation to remain classified Canonical.

Local validation is green: 1,784 backend tests; all 36 mobile Jest suites (284
tests); 77 Studio contract tests; TypeScript; Ruff; Expo web export; diff
hygiene; and the complete ten-project production TypeScript-client -> HTTP ->
FastAPI acceptance run with no Factory use. The frozen definition still covers
144 integrity sources, 58 quality sources, and 1,044 logical sequences with
zero provider calls. The credential-free staging probe exits `77` with
`secrets_logged: false`. The signed corpus run, reviewed assignment bundle,
independent designer/GIA review, founder approval, authority enrollment, and
live two-principal staging evidence remain unmet external-beta gates.

## 2026-07-14 Studio lineage, destination, and staging-isolation checkpoint

Studio Refine now binds annotations to the exact source asset rather than its
temporary URL. Refreshing the URL for the same asset preserves the designer's
marks, while switching to another immutable revision clears stale markup and
disables Preview until the new source is annotated. A mark from one revision
can no longer be silently rebound to another.

A QA-approved catalog Apply now appends its immutable
`ProjectRevisionRecord` in the same transaction as the canonical image asset,
design version, accepted image run, and active pointer. The record retains the
exact instruction, region, source and output hashes, image-run identity,
source and target specification hashes, operation, summarized change, and
non-factory authority. Failed QA and database rollback leave no revision or
partial canonical state.

The production TypeScript client -> HTTP -> FastAPI acceptance matrix now
reopens Library and creates an exact-revision Client or Marketing derivative
for each of ten mixed-source projects. It proves five Client and five Marketing
saves, ten non-mutating Library reopens, ten atomically charged presentation
jobs, and zero Factory use. Staging isolation v4 also inspects read-only
`OPTIONS` responses and fails closed when any of the 29 operations in the
canonical production-hidden mutation inventory is mounted; a proxy-stripped
method inventory also fails closed.

Local validation is green: 1,772 backend tests; all 36 mobile Jest suites (280
tests); 77 Studio contract tests; TypeScript; Ruff; Expo web export; diff
hygiene; the complete ten-project production-client acceptance run; and frozen
workload validation for 144 integrity sources, 58 quality sources, and 1,044
planned sequences with zero provider calls. The signed corpus run, independent
designer/GIA review, founder approval, six-role authority enrollment, and live
two-principal PostgreSQL staging evidence remain unmet external-beta gates.

## 2026-07-14 restore authority and canonical presentation checkpoint

Studio Restore now carries an existing immutable component map across the
byte-identical appended revision. A mapped ring therefore remains available
for component-aware Refine after Restore instead of becoming inexplicably
unmapped. The copy revalidates the historical map hash and raster binding,
records the exact source and copied-map hash in the new immutable revision,
and commits the image, specification version, active pointer, map, and revision
record together. Corrupt evidence fails with no partial revision or pointer
change; a genuinely unmapped source stays explicitly unmapped and never gains
invented component authority.

The active Studio presentation gateway no longer shares the hidden trusted
workflow's conditional beauty-render and product-photo methods. It calls
explicit Studio-only client methods that always use the accounted
`/studio/projects/...` review routes and force presentation-only behavior.
Deprecated project-render methods remain isolated for compatibility until the
founder, OpenAPI, and historical-readability deletion gates pass. A source
policy test prevents the active gateway from regaining those fallbacks.

Create copy now matches its actual authority contract: sentence-led creation
with material/style, construction/detail, or brand-direction references no
longer displays a contradictory master-geometry warning. Supporting references
without either a design sentence or a visual source remain disabled and explain
what is missing without implying that an advisory image can define the jewelry.

Local validation is green: 1,768 backend tests; all 36 mobile Jest suites (279
tests); 77 Studio contract tests; TypeScript; Ruff; Python byte-compilation;
Expo web export; diff hygiene; and the complete ten-project production
TypeScript-client -> HTTP -> FastAPI acceptance run. That run again used no
Factory path, and failed QA created zero canonical projects, revisions,
accepted outputs, or charges. The external 144-image run, independent
designer/GIA review, founder approval, authority enrollment, and live staging
evidence remain unmet external-beta gates.

## 2026-07-14 sentence-led references and bound release authority checkpoint

Studio Create now accepts up to three unique supporting images—material/style,
construction/detail, and brand direction—after the designer supplies a design
sentence. A supporting image is never promoted to master geometry. Without a
master image, the written direction remains the sole geometry and identity
authority; supporting images may influence only their labeled advisory role.
An advisory-only setup with neither a sentence nor a master remains disabled.

The backend composes a deterministic role-labeled advisory board, binds its
exact hash and role contract to `CREATIVE_GENERATE`, and uses an image-backed
provider route without enabling source-geometry fidelity checks. The original
reference bytes, roles, hashes, board, provider runs, and candidate lineage are
persisted in one transaction. The candidates remain pre-spec, and failed QA
retains attempt evidence without creating a Project, image revision, Design, or
DesignVersion. The production TypeScript-client -> HTTP -> FastAPI acceptance
matrix now includes sentence-plus-material/brand guidance as one of ten
mixed-source projects; all ten save, reopen, branch, and refine without using
Factory.

The external-beta authority verifier now binds every operational signer—the
executor, canonical API runner, GIA reviewer, founder, independent designer,
and staging reviewer—to the exact enrolled role key ID and normalized Ed25519
digest. A valid but unused enrollment can no longer mask an unrelated gate
signer. The staging reviewer approval must also bind the exact tested fixture
set, in addition to origin and deployment revision. Frozen implementation pins
were advanced to these verifier bytes without changing either external gate's
`not_run` / `unmet` status.

Local validation is green: 1,764 backend tests; all 36 mobile Jest suites (278
tests); 77 Studio contract tests; TypeScript; Ruff; Python byte-compilation;
Expo web export; diff hygiene; 176 focused release-integrity tests; frozen
definition validation; and the complete production client-to-API acceptance
run. The credential-free staging probe still exits `77` with
`secrets_logged: false`.

The available corpus source directory was independently checked against the
manifest: all 144 images match their hashes, byte sizes, dimensions, and
formats, with no missing or extra files. Execution remains correctly blocked:
all 1,044 rows lack the reviewed, hash-pinned assignment bundle, no executor
authority or `corpus_run_id` is enrolled, and zero rows are execution-ready.
The repository intentionally consumes externally generated execution and
persistence bundles instead of containing a paid live runner. No provider call,
human review, founder approval, authority enrollment, or live staging run was
performed by this checkpoint.

## 2026-07-14 synchronized comparison and Activity-truth checkpoint

Refine, Views, unsaved Present candidates, and Collections revision comparison
now use one shared before/after decision surface. Phones keep source and
candidate in a single toggleable viewport instead of stacking them into a
memory test; larger screens use a split view. The full inspector applies one
shared 1x/2x/4x zoom and one scroll coordinate system to both images. Only the
compact source and candidate loads can authorize Apply or Save; loading or
zooming detail images cannot satisfy the review gate. Immutable source and
temporary-candidate labels remain visible throughout inspection.

Refine's visible Stone color action now fails closed until the exact,
lineage-checked specification contains a stone species. The species is passed
to the scoped catalog request, invalid or unavailable palettes remain
unselectable, and designer copy no longer exposes provider terminology.

Activity now reconciles expired temporary Catalog, Visual, Markup, Views, and
Present candidates before returning job list or detail state. Each domain
retains authority for its own row-locked expiration and billing settlement.
Expired bytes are cleared, zero accepted outputs remain free, accepted Present
subsets charge exactly the saved outputs, repeated reads are idempotent, and an
owner's read cannot settle another owner's work. Durable Create directions are
intentionally excluded because they are saved directions rather than temporary
review pixels.

Local validation for this checkpoint is green: 1,754 backend tests; all 36
mobile Jest suites (276 tests); 76 Studio contract tests; TypeScript; Ruff;
Python byte-compilation; Expo web export; diff hygiene; and the complete
ten-project production TypeScript-client -> HTTP -> FastAPI acceptance run.
That run used no Factory path and failed QA produced zero canonical revisions,
accepted outputs, or charges.

The frozen 144-image provider corpus, independent designer/GIA review, founder
approval, enrolled external authority, and live two-principal HTTPS staging
evidence remain external beta gates and were not performed by this local
checkpoint.

## 2026-07-14 historical Refine variation checkpoint

Activity can now preserve a useful Refine result even after the source project
has advanced. Catalog, visual-only, and marked-region candidates may be saved
as a new sibling Variation from the exact immutable revision they were created
from. Apply remains active-source-only, so a stale candidate can never silently
replace the designer's current work.

The variation response now names its source project and source asset. The
mobile gateway first verifies that exact revision still exists, then verifies
the response provenance and rereads the source project after the branch. Any
change to its active asset, design version, specification, revision history, or
selection fails closed. Ownership, source and output hashes, specification and
component-map lineage, target mask, provider run, QA evidence, and durable job
binding remain mandatory. Catalog Activity resume also retains a valid stale
candidate instead of expiring it merely because a newer revision is active.

Local validation for this checkpoint is green: 1,747 backend tests; all 35
mobile Jest suites (269 tests); 76 Studio contract tests; TypeScript; Ruff;
Python byte-compilation; Expo web export; diff hygiene; and the complete
ten-project production TypeScript-client -> HTTP -> FastAPI acceptance run.
The end-to-end run caught and closed a child-revision lineage regression before
this checkpoint: candidate images remain reviewable when the design bridge is
canonically held by the project root. The run used no Factory path and failed
QA produced zero canonical revisions, accepted outputs, or charges.

The frozen 144-image provider corpus, independent designer/GIA review, founder
approval, enrolled external authority, and live two-principal HTTPS staging
evidence remain external beta gates and were not performed by this local
checkpoint.

## 2026-07-14 exact-revision destination checkpoint

Collections now keeps the selected immutable revision in context through the
next designer decision. An active family exposes one compact destination card:
Present is the primary action for client or marketing material, while Factory
appears only when the existing typed action gate verifies that the same active
revision is exact, entitled, and eligible. Collections does not duplicate the
Factory rules and does not add Factory to mandatory progress.

Restoring an older revision still appends a new immutable revision. Collections
now refetches history when the active asset or design version changes within the
same family, so the newly appended revision, active badge, revision count, and
subsequent Present handoff cannot remain locally stale. Routing tests prove that
Present receives the exact active asset and that Factory is absent for a
visual-only revision but becomes available after exact design confirmation.

Local validation for this checkpoint is green: 1,733 backend tests; all 35
mobile Jest suites (269 tests); 76 Studio contract tests; TypeScript; Ruff;
Python byte-compilation; Expo web export; diff hygiene; and the complete
ten-project production TypeScript-client -> HTTP -> FastAPI acceptance run.
That run used no Factory path and preserved zero canonical revisions, accepted
outputs, or charges for failed-QA work. The frozen 144-image provider corpus,
independent designer/GIA review, founder approval, enrolled external authority,
and live two-principal HTTPS staging evidence remain external beta gates and
were not performed by this local checkpoint.

## 2026-07-13 blind external-evidence authority checkpoint

The corpus and external-beta release boundary now uses two separate
`facetta-blind-jewelry-review-packet.v2` / signed-ledger workflows. The GIA
visual-fidelity reviewer and independent jewelry designer receive opaque,
HMAC-randomized item IDs and role-specific criterion rubrics. Their packets do
not expose provider identity, machine scores, retry counts, machine verdicts,
or another reviewer's decisions. Acceptance is derived by the verifier from
the signed criterion rows; a reviewer cannot supply a trusted top-level
Boolean. Each ledger binds the exact manifest, config, workload, signed
capture, corpus run, selected source/candidate/mask artifacts, reviewer role,
reviewer-profile hash, key ID, and timezone-qualified completion time.

The founder finalizer no longer trusts retained `results.json` as sufficient
evidence. It requires the raw manifest, source directory, replay, evidence
root, workload, and GIA packet/ledger; reruns the provider-free compiler; and
requires the recomputed result to byte-match the retained result. The combined
external-beta controller repeats that verification, validates a separate
designer packet/ledger over the exact quick-appearance selections, derives the
configured acceptance rate, and preserves the live staging-isolation gate.
Compatibility replay-v1 and legacy Boolean approval artifacts remain readable
but cannot authorize a release.

Release approval now also requires a privacy-safe six-role authority bundle.
Executor, canonical API runner, GIA reviewer, founder, independent jewelry
designer, and staging reviewer must each have hash-pinned enrollment,
qualification, active-status, and key-custody evidence at one decision time.
Role/key reuse, expiration, suspension, revocation, or unacknowledged rotation
fails closed. The production config intentionally leaves this bundle and all
public keys unenrolled, so local fixtures cannot impersonate external custody.

Validation for this checkpoint is green: 1,709 backend tests; 135 focused
blind-review, corpus, founder-finalizer, authority-enrollment, and
external-beta tests; all 35 mobile Jest suites (248 tests); 70 Studio contract
tests; TypeScript; Expo web export; Ruff; Python byte-compilation; diff hygiene;
and frozen-definition validation.

The production frozen definition still represents 144 integrity sources, 58
ring-quality sources, and 1,044 logical evaluation sequences. No provider
corpus run, human review, founder approval, credential enrollment, or live
two-principal staging run was performed; both external gates remain
`not_run` / `unmet`.

## 2026-07-13 external-evidence authority checkpoint (superseded contract)

The remaining beta gates now bind the code and deployment they claim to test.
The frozen corpus configuration hash-pins the capture producer and its CLI,
and producer preflight verifies those bytes before executor preflight or any
provider activity. A drifted producer therefore cannot spend calls or create a
capture that only fails later during release verification.

Release approval also enforces cryptographic role separation. Executor,
canonical API runner, GIA reviewer, founder, independent jewelry designer, and
staging reviewer must use unique key IDs and unique Ed25519 public-key bytes.
The corpus compiler, founder finalizer, and combined external-beta verifier all
recompute that audit. This proves distinct enrolled signing identities; the
real-world people, qualifications, and independence still require external
enrollment records and human verification.

The live staging probe is now `facetta-staging-isolation.v4`. It calls the exact
HTTPS origin's `/health`, requires Facetta to report the operator-selected
immutable deployment revision, and requires the initialized persistence engine
to be PostgreSQL before checking both principals in both directions. A caller
can no longer relabel evidence from a different deployment or pass the gate on
the local SQLite fallback. The same read-only probe now checks the deployed
method inventory for every mutating operation the production surface classifies
as hidden. A missing `Allow` header fails closed, and an accidental registry-
listed legacy POST route fails the staging gate without being invoked.

Validation at this checkpoint is green: 1,650 backend tests, the six production
surface/route checks, all 35 mobile Jest suites (248 tests), TypeScript, Expo web
export, Ruff, Python byte-compilation, and frozen-definition validation. The
credential-free staging command exits `77` with `secrets_logged: false`, as
required, instead of fabricating live evidence.

The production frozen definition still passes provider-free validation at 144
integrity sources, 58 ring-quality sources, and 1,044 logical evaluation
sequences, with zero provider calls and `corpus_gate_ready: false`. The reviewed
assignment bundle, six separately controlled signing identities, source files,
secured execution, completed reviews, founder approval, and live staging
fixtures remain external and unenrolled.

The blind criterion-level review and authority-enrollment contracts described
in the checkpoint above supersede this snapshot. They are implemented and
locally verified, but remain unexercised with real enrolled reviewers and
external evidence.

## 2026-07-13 inspectable inputs, canonical orchestration, and honest corpus checkpoint

Studio Create now treats every role-labeled reference as a consequential
visual input. Master geometry, material/style, construction/detail, and brand
direction thumbnails open the authenticated 1x/2x/4x detail inspector with the
role and source label visible. Creation remains disabled until every attached
compact preview has rendered; a failed reference asks the designer to replace
or remove it. Opening or zooming the detail modal cannot satisfy that gate or
change the role sent to the backend.

The canonical Studio action manifest now owns orchestration as well as labels,
inputs, pricing, output type, and authority. Typed `execution_mode` and
`review_authority` values are generated into the mobile registry and loaded by
the backend. Vary is an atomic transaction and cannot create an orphan Activity
job. Create, Refine, Views, and Present are candidate-decision jobs; generic
success/failure transitions cannot settle them after review begins. Factory is
the declared terminal job. The mobile gateway mirrors a backend-owned candidate
transition before validating its response, so malformed lineage cannot trigger
a false generic failure against a durable reviewing candidate.

The frozen corpus producer now records legitimate terminal exhaustion instead
of aborting it. A sequence may have zero or one accepted attempt; when accepted,
that attempt must be final, and early or multiple acceptance still fails the
atomic capture. Three-attempt render and edit exhaustion is persisted, signed,
replayed from the final attempt, and counted as a reliability failure. This
removes survivorship bias from the 90% acceptance and structural gates.

Local validation for this checkpoint: 1,639 backend tests, 248 Jest tests, 70
Studio contract tests, TypeScript, Ruff, Python compilation, Expo web export,
six exact production-surface tests, generated-manifest parity, and the complete
ten-project production TypeScript-client -> HTTP -> FastAPI acceptance pass.
The frozen 144-image corpus has not been executed with enrolled provider and
reviewer identities; independent designer/GIA review, founder approval, and
live two-principal HTTPS staging evidence remain external beta gates.

## 2026-07-13 inspectable and candidate-owned Studio review checkpoint

Every consequential Studio visual can now be inspected at jewelry-detail
scale before a designer decides. Create directions, Refine source/candidate
pairs, Technical-view source/candidate pairs, Present source/outputs, and
Collection revision comparisons share one authenticated full-screen inspector
with 1x, 2x, and 4x zoom plus two-axis panning. The inspector explicitly calls
out prongs, stone outlines, pave spacing, edges, and unintended drift. Its
detail image deliberately owns no render-readiness callback: opening or zooming
the modal cannot authorize Apply, Save, or selection; only the compact image in
the actual decision surface can satisfy the existing fail-closed render gate.

Create, Refine, Views, and Present jobs are now candidate-owned once they enter
`reviewing`. The public generic lifecycle endpoint can no longer mark those
jobs succeeded or failed, strand a durable candidate, or fabricate completion
outside its candidate transaction. Apply, Save as Variation, Save
presentation/view, and Discard remain the canonical settlement authorities;
pre-review provider failure is still allowed and remains zero-charge. Tests
also preserve malformed historical bindings as fail-closed compatibility cases
rather than recreating them through the public API.

The public production beta no longer mounts any stateless `/specs/*` adapter.
Those routes and their historical clients remain intact, authenticated, and
tested in development for compatibility and the eventual Advanced
Specifications escape hatch. The production surface now exposes only persisted
Studio/project/asset/candidate services, while legacy state remains readable
without becoming a second visible workflow.

Local validation for this checkpoint: 1,633 backend tests, 247 Jest tests, 68
Studio contract tests, TypeScript, Ruff, Python compilation, Expo web export,
the exact production route-surface tests, and the complete ten-project
production TypeScript-client -> HTTP -> FastAPI acceptance pass. The rendered
unauthenticated entry and six-step tour were inspected locally; authenticated
candidate inspection still requires a configured Supabase session. The frozen
144-image corpus, independent designer/GIA review, founder approval, and live
two-principal HTTPS staging evidence remain the external beta gates.

## 2026-07-13 exact Studio context and Views reservation checkpoint

Every saved-design Studio action now keeps the exact working context visible.
Vary, Refine, Technical views, and Present show the authenticated design image,
project title, and immutable revision number in one compact strip, with direct
access to History. Activity review shows its exact source revision rather than
silently substituting the latest project state, and successful decisions advance
the strip to the newly active revision. Create remains intentionally free of a
false saved-design context.

One-output Technical views jobs now have one durable candidate authority. A
short-lived reservation binds the exact job and revision before provider work,
puts the job in review, and is cleared atomically when the candidate is stored
or the attempt fails. A partial unique database index prevents new duplicate
job bindings; additive migration preserves historical duplicates but leaves
them fail-closed. Accept and Discard reject ambiguous historical bindings with
no asset, revision, review, or charge, and abandoned reservations expire to a
zero-output, zero-charge failure. Generic job transitions cannot bypass the
candidate decision while a Views job is under review.

Local validation for this checkpoint: 1,629 backend tests, 245 Jest tests, 68
Studio contract tests, TypeScript, Ruff, Expo web export, and the complete
ten-project production TypeScript-client -> HTTP -> FastAPI acceptance pass.
The rendered unauthenticated shell was also inspected locally; authenticated
visual review remains unavailable without a configured Supabase session. The
frozen 144-image corpus, independent designer/GIA review, founder approval, and
live two-principal HTTPS staging evidence remain the external beta gates.

## 2026-07-13 atomic Create authority checkpoint

The deprecated single-candidate selector is no longer part of the production
API or active Studio gateway. Studio Create now has one canonical acceptance
authority: `POST /projects/{project_id}/creative-directions/commit`. That
transaction establishes the immutable Original, preserves explicitly retained
sibling directions, records the durable decision and revision provenance, and
settles the bound Create job exactly once. The older selector remains mounted
only in development/test as explicitly deprecated compatibility so historical
projects and evaluation fixtures remain readable during migration.

The real TypeScript-client -> HTTP -> FastAPI acceptance process now sends all
ten sentence, drawing, photograph, finished-render, and role-labeled-reference
projects through the atomic commit. It proves one lost-response retry is
idempotent, invalid cross-project sibling retention rolls back canonical state
and billing, each requested Create job settles once, no canonical mutation
occurs before acceptance, and Factory is never required. The structural ring
case now counts the immutable Original in its provenance history instead of
accepting the legacy selector's unrecorded state transition.

Local validation for this checkpoint: 1,624 backend tests, 244 Jest tests, 68
Studio contract tests, TypeScript, Ruff, Python compilation, Expo web export,
and the complete ten-project real-process client/API acceptance pass. Existing
non-fatal Jest warnings remain the deprecated React Native `SafeAreaView` and
overlapping `act()` diagnostics. External beta is still gated on the frozen
144-image corpus, designer/GIA review, founder approval, and live two-principal
HTTPS staging evidence.

## 2026-07-13 Studio rendered-review authority checkpoint

Create, Refine, Views, and Present now share one fail-closed visual-review
invariant: a URL is not evidence that a designer saw an image. Every image
needed for a keep, apply, or save decision must emit a successful render event
for its exact candidate and source identity. Missing, protected, expired, or
failed images keep the decision disabled and repeat the same guard inside the
handler. Discard remains available, and Present tracks each candidate
independently so loading one marketing output cannot authorize another.

Create therefore cannot establish an immutable Original or retain a sibling
direction until each selected preview is visible. Refine cannot Apply or Save
as Variation until both the exact source and temporary candidate are visible.
Views and Present likewise require a rendered side-by-side comparison before a
derived asset can be saved. Concise designer recovery copy distinguishes a
pending load from an image that failed to display without exposing provider or
authentication internals.

Local validation for this checkpoint: 1,622 backend tests, 244 Jest tests, 69
Studio contract tests, TypeScript, Ruff, Python compilation, Expo web export,
and the production TypeScript-client -> HTTP -> FastAPI acceptance pass. The
acceptance still covers ten mixed-source projects without Factory and confirms
no canonical mutation before acceptance. No real 144-image corpus run,
designer/GIA review, founder approval, or live two-principal HTTPS staging run
was performed, so external beta remains gated on those external authorities.

## 2026-07-13 Studio review-continuity and Original-provenance checkpoint

Present now separates configuration from candidate review. Once any preview is
ready—or a durable preview is resumed—the destination, output, direction, cost,
and generation controls leave the screen until every candidate has been saved
or discarded. A failed decision keeps its unresolved candidate visible, and a
designer can start another presentation only after completing the current
review. This removes the previous path where changing destination could hide a
live review decision while preserving its backend job.

The selected Create direction now receives its own immutable revision record in
the same transaction that chooses Original, creates retained sibling
variations, and settles the Create job. The record binds the exact image run,
attempt output hash, generation input hash, prompt version, source bytes, output
bytes, decision project, and Studio job. Missing, ambiguous, or mismatched
generation evidence fails with no selection, family, branch, revision, job
settlement, or user charge. Exact retries return the one stored decision and do
not append a duplicate record.

The active Studio gateway no longer exposes the deprecated structured-ring
brief method. That compatibility path remains deliberately isolated to the
hidden trusted workflow and historical evaluation harness until the documented
deletion gates pass; active sentence creation continues through the
category-neutral prompt route.

Local validation for this checkpoint: 1,622 backend tests, 243 Jest tests, 69
Studio contract tests, TypeScript, Ruff, Python compilation, Expo web export,
and the production TypeScript-client -> HTTP -> FastAPI acceptance pass. The
acceptance covers ten mixed-source projects without Factory and confirms no
canonical mutation before acceptance. No real 144-image corpus run,
designer/GIA review, founder approval, or live two-principal HTTPS staging run
was performed, so external beta remains gated on those external authorities.

## 2026-07-13 Studio review-authority and secured-capture checkpoint

The renewed Studio journey is locally implemented across its six intended steps:
mixed-source Create, one-to-four candidate selection, precise Refine, temporary
side-by-side review, Family -> Variation -> immutable Revision organization,
and a navigation-only Library choice plus Client/Marketing destinations, with
Factory remaining optional. Library currently means the exact revision already
preserved in Collections; it does not claim the future reusable component,
mask, material, palette, or reference system is complete.
Designer-facing review labels now use a closed vocabulary. Unknown evaluator,
provider, model, QA, or routing labels collapse to neutral visual-consistency
language instead of leaking backend terminology into the workspace.

Every durable temporary candidate boundary now independently revalidates its
quality evidence at storage, reopen/list/image, and decision time. Catalog,
visual, marked-region, View, pre-spec Present, and exact Present candidates all
reject missing, contradictory, or hard-failure QA. Corrupt candidates expire
without appending an asset or revision, and their exact jobs settle with zero
completed/charged output. Legitimate warning and forced-designer-review shapes
remain supported. Job settlement also rechecks action, lane, pricing, owner,
project, source revision, and output binding, so a corrupted link cannot fail
an unrelated same-owner job.

The frozen-corpus evidence path now includes a provider-free capture producer
and a pluggable secured-executor seam. It refuses unresolved assignments,
unenrolled signing identities, source/hash drift, unsafe evidence paths,
over-budget attempts, non-final acceptance, or mismatched persistence results.
Successful runs atomically publish a source/candidate/mask/persistence artifact
index, a separately signed canonical-persistence attestation, and a signed
capture envelope, then locally verify both authorities before returning. The
repository CLI consumes existing execution and persistence-observation bundles;
it does not call an image provider.

Local validation for this checkpoint: 1,619 backend tests, 242 Jest tests, 69
Studio contract tests, 101 focused external-evidence tests, TypeScript, Ruff,
Python compilation, Expo web export, and the production TypeScript-client ->
HTTP -> FastAPI acceptance pass. The production frozen plan remains deliberately
non-executable with signing/reviewer identities unenrolled. No 144-image corpus
run, designer/GIA review, founder approval, or live two-principal HTTPS staging
run was performed, so external beta remains gated on real external evidence.

## 2026-07-13 production provider-job authority checkpoint

Every provider-backed production generation path now requires a canonical,
running `StudioJob` before provider work begins. The shared gate validates the
authenticated owner, action, lane, pricing, output count, lifecycle, and exact
design/revision lineage. Create jobs are single-use: prompt and drawing requests
bind the generated project to the job in the same persistence transaction, so
replay cannot spend twice or create an untracked second project. Existing
candidate-specific Refine, Views, and Present reservations remain the stronger
decision boundary after this common production check.

Markup Refine now stores image-run evidence, the temporary preview candidate,
and the job's move to `reviewing` atomically. A failed candidate write leaves no
orphaned provider result and the job remains safely retryable. The old direct
visual-twin Views primitive is retained for historical development/evaluation
callers but is no longer mounted in production; active Studio Views uses the
exact-revision, job-bound workflow. Internal retries and failed QA attempts
therefore remain evidence without becoming hidden user charges or canonical
design history.

Local validation for this checkpoint: 1,595 backend tests, 205 affected-route
tests, 242 Jest tests, 68 Studio contract tests, TypeScript, Ruff, Python
compilation, Expo web export, and the production TypeScript-client -> HTTP ->
FastAPI acceptance pass. The frozen 144-image corpus, designer/GIA and founder
reviews, and live two-principal HTTPS staging run remain external prerequisites
and have not been performed.

## 2026-07-13 Studio authority and external-release checkpoint

The four global Studio destinations are now an explicit accessible tab set:
`Studio`, `Collections`, `Activity`, and `Learn`. Each tab exposes its selected
state and routes to its named workspace. Tests also prove that the Studio home
does not leak legacy Builder, Share, or Factory shortcuts. Within an active
design the contextual rail remains limited to Create, Vary, Refine, Views,
Present, and More; Factory is still conditional on the exact revision being
both entitled and backend-eligible.

Durable visual previews now revalidate their stored QA authority before every
review or decision. The embedded verdict must match the durable record, hard
failures can never become reviewable, and pass/warn states must carry their
expected acceptance and review flags. Malformed or tampered QA therefore
expires the temporary candidate and cannot append an asset, revision, charge,
or canonical mutation.

External-beta readiness now has one fail-closed controller. It independently
recomputes the frozen-corpus founder decision, requires a complete designer
acceptance ledger and separate Ed25519 designer approval, verifies the live
two-principal HTTPS staging result and its separate signed approval, binds all
evidence to exact hashes, deployment revision, fixture set, reviewer identities,
and frozen implementation pins, and rejects nonzero finalizer exit records.
The production configuration deliberately leaves designer and staging reviewer
keys unenrolled. The default capture plan consequently reports zero executable
sequences, zero provider attempts/calls, and cannot emit
`external_beta_ready` without the real external evidence.

Local validation for this checkpoint: 1,577 backend tests, 242 Jest tests, 68
Studio contract tests, TypeScript, Ruff, Python compilation, Expo web export,
hash-pin verification, and the production TypeScript-client -> HTTP -> FastAPI
acceptance pass. The acceptance covers ten mixed-source projects plus one
structural edit with no Factory use, no canonical mutation before acceptance,
and no canonical output or charge from failed QA. The 144-image corpus,
designer/GIA and founder reviews, and live two-principal staging run remain
external prerequisites and have not been performed.

## 2026-07-13 Studio IA and production-surface consolidation checkpoint

The designer-facing Studio no longer presents `Starting design facts` as a
second destination under More. Fact review remains available only from the
Refine context that owns it, so the action rail does not imply a mandatory
Create -> Refine -> Confirm sequence. `Views` remains a compact rail label,
but its full action and workspace copy now say `Technical views` and identify
the output as temporary line art derived from an exact revision and confirmed
design facts. It stays absent before those facts exist; Refine explains the
optional unlock while preserving continued refinement and presentation.

The deprecated direct `POST /assets/{asset_id}/pin` compatibility handler is
no longer mounted in production. Test and development environments retain it
for historical compatibility, while production Studio pinning remains owned
by exact-version checklist completion and the atomic Factory-review flow. No
OpenAPI handler, historical reader, or trusted service was deleted. A separate
caller audit identified the old trusted screen composition as orphaned, but it
was deliberately retained because founder end-to-end acceptance and the other
documented deletion gates have not yet passed.

Active Studio Present traffic now uses canonical, authenticated
`/studio/projects/{root_id}/beauty-render` and `/product-photo` routes. Both
require an accounted Studio job and review-only presentation semantics, then
delegate to the existing trusted transactions. The older project render and
product-photo handlers remain deprecated development compatibility routes and
are absent from production. Two live catalog harnesses also moved from direct
Apply to Preview-first decisions: the ring harness requires explicit operator
Accept or Discard, while the necklace evaluation defaults to no mutation and
may explicitly Save as Variation or Discard.

Exact-reference imports now use authenticated
`POST /studio/projects/import-confirmed`. Canonical imports require the
independent source-component audit to name the SHA-256 of the exact uploaded
bytes before one transaction creates the project, immutable Design v1, and
byte-identical imported asset. The shared service keeps validation and
persistence behavior identical for the deprecated development-only
`/projects/from-image` compatibility route, while production rejects missing
or stale source-audit bindings and actor spoofing. All four live exact-reference
harnesses and the trusted client now use the Studio route.

Active sentence creation remains the category-neutral one-to-four-candidate
`POST /projects/from-prompt` journey. The older structured-ring
`/projects/from-brief` route and its warning-review endpoints are now explicitly
deprecated compatibility, remain available only to hidden development/test
fixtures and the historical evaluation harness, and stay absent from the
production Studio surface.

Local validation for these slices: 1,563 backend tests, 241 Jest tests, 68
Studio contract tests, TypeScript, and Expo export pass. This remains local
contract and interface validation; the external corpus, designer/GIA review,
founder acceptance, and staging isolation gates remain unmet.

## 2026-07-13 secured corpus execution-evidence checkpoint

The frozen provider-call plan and capture envelope are now v2 fail-closed
contracts. The pinned workload still declares 1,044 logical ring assignments
(58 sources x 18 evaluations) and a 3,132-attempt logical ceiling, but those
counts are not an executable provider matrix. Every assignment now requires a
reviewed, hash-pinned source-specific binding with an explicit applicability
decision and canonical `resolved_inputs_sha256`. The production configuration
deliberately has no resolved assignment bundle or enrolled executor key, so it
currently reports 0 execution-ready assignments, 0 maximum executable provider
attempts, and cannot produce an accepted live capture.

Canonical persistence is no longer accepted as an unsigned JSON assertion. A
separate Ed25519 attestation from a config-enrolled canonical API runner must
bind the exact preassigned `corpus_run_id`, commit, API schema, frozen
definition, selected result-set digest, atomic image/specification behavior,
stale-write rejection, and zero persisted rejected candidates. The production
API-runner key is intentionally unenrolled. Review-packet and replay commands
also require one explicit evidence root; all sources, captures, keys,
persistence evidence, candidates, masks, and outputs must remain inside it and
are referenced through a canonical root-relative, sorted, hash-bound artifact
index. Traversal, absolute paths, symlink escape, missing index membership, and
hash drift fail closed.

Local validation for this slice: the complete backend passes 1,534 tests, and
all 81 focused frozen capture, packet, replay, persistence, release, and
production-surface tests pass. This is contract
validation only; no provider corpus run, designer review, GIA review, founder
approval, or staging release was performed. External beta remains blocked on a
reviewed per-source assignment/applicability bundle; enrolled executor,
canonical API runner, reviewer, and founder keys; the real 144-source corpus;
measured machine scores; an independently classified 58-source ring sample; a
separate designer-acceptance signal; and the combined corpus-plus-staging
release controller.

## 2026-07-13 workload-bound corpus evidence checkpoint

The frozen external-quality gate now consumes one pinned workload from capture
through replay, review-packet compilation, and founder release. It keeps the
144-source integrity inventory separate from the exact 58-source ring quality
sample and requires all 1,044 source-by-evaluation assignments. Replay rejects
missing, extra, non-ring, discontinuous, non-finite, or out-of-range evidence;
failed GIA candidates cannot machine-pass. The review packet accepts only a
valid signed `facetta-frozen-capture.v1` artifact, preserves its signing and
capture-byte provenance, binds source/candidate/mask/persistence evidence, and
leaves every human decision blank. It cannot claim readiness.

The founder finalizer no longer trusts a shallow top-level pass. It derives the
frozen scope from the pinned workload and requires the nested definition,
workload, integrity, quality, signature, coverage, GIA, evidence-chain, and
release gates to agree before it may emit `corpus_gate_ready`. Reviewer and
founder keys must be enrolled in the frozen config before plan, capture,
replay, or result bytes are signed. Staging remains a separate authority, so
this path still cannot emit `external_beta_ready`.

Local validation at this checkpoint: 1,510 backend tests, 239 Jest tests, 67
Studio contract tests, TypeScript, Ruff, Expo web export, frozen-definition
pin validation, all 57 focused frozen-gate/production-surface tests, and the
production TypeScript-client -> HTTP -> FastAPI acceptance pass. No provider
corpus run or human review was performed. External beta remains blocked on a
fully resolved secured executor, a config-pinned executor identity, measured
rather than asserted machine scores, signed API persistence attestation, an
independently classified ring sample, a separate designer-acceptance signal,
portable evidence paths, enrolled reviewer/founder keys, and the combined
corpus-plus-staging release controller.

## 2026-07-13 atomic Create and capture-planning checkpoint

The pre-spec journey no longer dead-ends after refinement. The backend now
identifies one server-authoritative `confirmable_pre_spec` asset: it must be the
current canonical selected visual, remain without a design/version binding,
use an allowed creative or reviewed-refinement capability, and descend from a
real creative direction. Both fact-review creation and Design v1 promotion use
that same predicate. Applying a visual or marked-region child therefore keeps
`Review starting design` available for the child's exact pixels, while the
original direction and stale confirmation tokens fail closed. Promotion copies
the refined child's exact bytes and hash into immutable Design v1 provenance.

The unused legacy Builder mobile island (`BuilderScreen`, `DesignsScreen`,
`ShareScreen`, and its provider-aware API wrapper) has been removed after an
import audit. Active trusted contracts, compatibility readers, and the hidden
trusted workflow remain in place until their separate migration gates pass.
Factory copy now consistently says `factory review material`, and onboarding
asks designers to mark the extra directions they actually want to retain
instead of implying every unchosen candidate is permanently discoverable.

Create review now has one typed, transaction-owned decision boundary. Studio
submits the selected Original and up to three retained sibling directions in a
single request. The backend locks the project and candidates, creates Family
and Variation records, records exact source provenance, and settles the bound
Create job in the same transaction. A durable project-scoped decision makes an
identical lost-response retry return the same branch identities without a
second charge. A changed retry, foreign candidate, stale candidate, or partial
legacy selection fails closed. Real-HTTP acceptance also reproduces production
sessions with autoflush disabled and proves that invalid retained input leaves
selection, family, branches, revisions, and billing untouched.

Frozen-corpus output is also more honest. The technical/GIA compiler and signed
founder finalizer now emit only `corpus_gate_ready`; neither may claim
`external_beta_ready` without the separate staging authority. The finalizer
binds its decision to the versioned gate schema/run kind, exact config and
manifest hashes, corpus identity, current frozen implementation pins, and the
founder-approved result bytes. The frozen per-source workload and provider-call
planner now exist and separate 144-source integrity from the 58-source ring
quality slice. This still does not make the external gate runnable: the secured
capture executor, a signed staging attestation, and a combined release
controller still need to be built;
external sources, reviewer/founder keys, and staging principals remain
`not_run` / `unmet`.

Local validation at this checkpoint: 1,492 backend tests, 239 Jest tests, 67
Studio contract tests, TypeScript, Ruff, Expo web export, corpus-definition
pin validation, and the production TypeScript-client -> HTTP -> FastAPI
acceptance all pass. The production acceptance still covers ten mixed-source
projects plus exact ring structural refinement with no Factory use. It now also
proves atomic Original-plus-sibling retention, exact retry idempotency, full
rollback on a foreign retained candidate, refine-first Design v1 bytes/hash,
and the stale-source boundary through real FastAPI persistence. No provider
corpus run or human review was performed; the external source directory,
secured executor, signing keys, GIA review, founder approval, and staging
principals remain unavailable and therefore unmet.

## 2026-07-13 resumed Studio integration checkpoint

The canceled Codex tracking record did not remove the recovered work. The
trusted recovery branch remains independently preserved, and the unified
Studio integration continues on `codex/facetta-integration`.

Refine now opens on the lowest-friction truthful route: one plain-language
appearance change. Mark up remains beside it, while Component appears only
after the exact revision reports at least one usable mapped path. Component
catalog data is deferred until the designer chooses that route, and the
starting-design prompt is absent when there is no eligible review action. This
removes disabled and actionless choices without weakening temporary preview,
Apply, Save as Variation, Discard, or immutable specification authority.

The first instant configurator slice is now available only where its evidence
is exact: a mapped ring's controlled yellow-, white-, or rose-gold color. The
backend declares that capability in the component catalog; Studio never infers
it from a label. The quick path performs a deterministic chroma transform
inside the exact revision mask, preserves decoded pixels outside the mask,
alpha, dimensions, luminance, and eligible RGB color-profile semantics, and
creates a temporary candidate with no provider attempt, Studio job, or credit.
Apply and Save as Variation reuse the existing atomic candidate decisions;
Discard leaves canonical history untouched. A provider fallback is allowed
only for explicit transform-version skew, is shown as a 20-credit standard
preview before acceptance, and remains uncharged unless the designer applies
or saves it. Raster, orientation, profile, mask, QA, stale-lineage, integrity,
authorization, decode, and network failures never trigger paid fallback.

Instant provenance is fail-closed across independent run, candidate, source,
mask, output, option, target-spec, transform-contract, and prompt-version
markers. The combined input hash is recomputed at decision time, any provider
attempt or injected Studio job invalidates the candidate, and compressed or
oversized rasters are rejected before pixel materialization. These controls are
image-edit evidence only and carry no Factory or production authority.

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
primary action. Pre-spec Refine links directly to `Review starting design`,
and the same ring-truthful workflow is labeled `Starting design facts` under More. Factory
language remains absent until the backend reports that the exact revision is
both entitled and eligible. The duplicate legacy readiness entry is removed
from the public Studio action contract; compatibility readers remain internal.

Local validation at this checkpoint: 1,733 backend tests, 265 Jest tests, 76
Studio contract tests, TypeScript, Ruff, Python bytecode compilation, Expo web
export, and the production TypeScript-client -> HTTP -> FastAPI acceptance all
pass. The acceptance covers ten mixed-source projects plus a confirmed ring
`stone.cut` preview/Apply journey; it reports no canonical mutation before
acceptance, no canonical asset/revision or charge from failed QA, and no
Factory use. The instant path additionally has focused raster, provenance,
tamper, fallback, decision, and client-decoder coverage inside those full
suites. These local results do not satisfy the two external gates: the signed
frozen 144-image corpus with founder/GIA review and live two-principal HTTPS
staging isolation remain `not_run` / `unmet` in
`STUDIO_EXTERNAL_BETA_GATES.md`.

## 2026-07-13 ring structural preview boundary

The ring-first structural seam is now implemented behind explicit operational
activation. A fixed Grok vision adapter can prepare semantic source maps and
reconcile one reviewed child map for the released `stone.cut` path. The edit
scope is deliberately coupled across center stone, prongs, and setting. It
requires a verified external calibration artifact digest and runtime readiness;
without those facts Studio stays fail-closed and offers Describe or Mark up.
The mobile Refine workspace attempts eligible ring source-map preparation once
in the background, without exposing provider controls or another workflow step.

Structural mapping and full QA now finish before a PreviewCandidate becomes
accept-capable. Structural warnings, mapper failures, stale sources, tampered
candidate bytes, or activation/evidence drift terminalize the candidate or run
and settle its linked Refine job with zero charged outputs. Apply and Save as
Variation are database-only acceptance boundaries: they append the exact image,
specification, component-map evidence, immutable revision or sibling variation,
and provenance atomically without a late vision call. Component-map evidence is
explicitly image-edit targeting only, never CAD or Factory authority. Broader
setting edits and categories remain gated, and the external corpus/founder/GIA
release evidence is still not run.

Collections now chooses the most recently active variation for each family card
and uses that variation's cover and open target, with deterministic
tie-breaking. This is intentionally described as project activity—not the
newest immutable design revision—because presentation and marketing work can
also advance a variation's `updated_at` timestamp.

Local validation for this checkpoint: 1,478 backend tests, 236 Jest tests, 64
Studio contract tests, TypeScript, Ruff, production OpenAPI surface equality,
Expo web export, the ten-project production client-to-HTTP matrix, and its
confirmed ring structural preview/Apply journey all pass. The structural
mapper's deterministic contract and catalog lifecycle are covered locally; the
external 144-image corpus and founder/GIA review remain explicit release gates
rather than inferred from unit tests.

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
Studio gateway. The zero-credit Library destination navigates to the exact
revision already held in Collections without copying an asset, appending a
revision, starting a job, or charging a credit. Create candidates are durable
review directions rather than fake sequential revisions; the selected direction
becomes the Original and other useful candidates can be kept explicitly as
sibling Variations.

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

Validation for the Collections and destination simplification checkpoint:
1,709 backend tests, 252 Jest tests, 73 Studio contract tests, TypeScript, Ruff,
Python compilation, Expo web export, the five-test production-surface gate, and
the ten-project production TypeScript-client -> HTTP -> FastAPI acceptance all
pass. The reusable component Library and external beta evidence remain outside
this checkpoint.

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
spec-v1 boundary. The old “Structured ring brief” route and warning-review loop
remain hidden development/test compatibility for historical evaluation; they
are not mounted on the production Studio surface.

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

The compatibility trusted UI also exposes multi-preset ecommerce packs with
the maximum provider-attempt multiplier shown before execution. Partial
failures do not discard successful candidates, and accepted scenes remain
derived marketing assets. This paragraph describes the retained hidden
workflow, not the active presentation: `mobile/App.tsx` now mounts the unified
Studio shell, while `TrustedWorkspaceEntry` remains compatibility-only pending
its separate migration gates.

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
