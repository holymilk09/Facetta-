# Facetta repository map

This map answers two questions: **how does a product action travel through the system?**
and **where should a change be made?** It intentionally points to stable boundaries
instead of listing every module in a large, evolving codebase.

## Request path

```text
Expo screen or workspace
  → StudioGateway method
  → authenticated HTTP request
  → FastAPI router
  → domain service / workflow
  → SQLAlchemy transaction and/or image provider
  → QA + explicit designer decision
  → immutable canonical revision or temporary candidate response
```

The normal direction is client → gateway → router → domain service → persistence or
provider. Avoid importing API/router concerns into domain modules or duplicating server
business rules in React components.

## Top-level directories

| Path | Contents |
|---|---|
| `src/facetta/` | Python application and domain logic |
| `src/facetta/api/` | FastAPI HTTP boundary |
| `src/facetta/image_agent/` | Provider-neutral image planning, execution, QA, and correction |
| `mobile/` | Expo/React Native application and TypeScript clients |
| `tests/` | Python tests, including route and workflow acceptance coverage |
| `scripts/` | Deliberate operator, eval, and acceptance commands |
| `data/` | Controlled vocabulary, facet diagrams, references, and local render cache |
| `docs/` | Architecture, contracts, operations, and retained evidence |

## Backend entry points and boundaries

| Concern | Start here | Responsibility |
|---|---|---|
| App startup and public surface | `src/facetta/main.py` | Environment loading, auth validation, router wiring, CORS, health, production allowlists |
| Configuration | `src/facetta/config.py`, `.env.example` | `.env.local`/`.env` precedence and documented settings |
| Authentication and ownership | `src/facetta/auth.py` | Principal validation and canonical owner boundaries |
| Persistence model | `src/facetta/db.py` | SQLAlchemy models, SQLite/PostgreSQL engine, durable relationships |
| HTTP operations | `src/facetta/api/` | Request parsing, dependencies, response mapping; keep business logic thin |
| Studio job/control plane | `src/facetta/api/studio.py` | Studio jobs, candidates, history, restore, variations, presentations |
| Families and Collections | `src/facetta/api/organization.py` | Flat collection membership, favorites, and tags on design families |
| Creative intake | `src/facetta/api/projects.py`, `src/facetta/creative_workflow.py` | Prompt/drawing projects and temporary creative candidates |
| Refine/markup | `src/facetta/api/assets.py`, `src/facetta/markup_snapshot.py` | Markup reads, previews, explicit apply, and exact-raster evidence |
| Visual candidates | `src/facetta/studio_visual_candidates.py`, `src/facetta/studio_markup_candidates.py`, `src/facetta/studio_preview_candidates.py` | Temporary candidate storage and decision boundaries |
| Lineage/history | `src/facetta/project_backbone.py`, `src/facetta/studio_history.py`, `src/facetta/trusted_revision.py` | Project/variation roots and immutable revision persistence |
| Jewelry specification | `src/facetta/spec.py`, `src/facetta/validation.py`, `src/facetta/vocabulary.py` | Typed facts, physical validation, controlled vocabulary |
| Image orchestration | `src/facetta/image_agent/` | Provider routing, planning, generation/editing, QA, retry, evidence |
| Provider adapters | `src/facetta/image_agent/providers.py`, `src/facetta/image_agent/openai_provider.py`, `src/facetta/grokedit.py` | External-provider boundary and normalized errors |
| Factory eligibility | `src/facetta/factory_scope.py`, `src/facetta/factory_pack.py`, `src/facetta/factory_sheet_plan.py` | Exact-revision blockers, fact schedules, and review archives |
| External-beta authority | `src/facetta/external_beta_release.py`, `src/facetta/frozen_*`, `scripts/verify_*` | Retained evidence validation and fail-closed release decisions |

`src/facetta/main.py` is the source of truth for which operations are public in
production. A router existing in development does not mean it is a supported public
Studio route.

## Mobile entry points and boundaries

| Concern | Start here | Responsibility |
|---|---|---|
| Application shell and navigation | `mobile/App.tsx` | Auth lifecycle, primary navigation, and workspace routing |
| Runtime API configuration | `mobile/src/config.ts` | API base URL and local preview flags |
| Typed server seam | `mobile/src/studio/gateway.ts` | Studio request/response mapping and exact-lineage operations |
| Shared Studio contracts | `mobile/src/studio/contracts.ts` | Client-facing Studio types |
| Create | `mobile/src/studio/StudioCreateWorkspace.tsx` | Mixed-source intake, generation, and direction review |
| Refine | `mobile/src/studio/StudioRefineWorkspace.tsx` | Selected-revision edit workflow and temporary previews |
| Direct canvas editing | `mobile/src/studio/StudioCanvasEditPanel.tsx`, `mobile/src/trusted/AnnotationCanvas.tsx` | Mark placement, text entry, selection, drag, and deletion |
| Vary and history | `mobile/src/studio/StudioVaryWorkspace.tsx`, `mobile/src/trusted/StudioHistoryPanel.tsx` | Variation branching and immutable history interaction |
| Views | `mobile/src/studio/StudioViewsWorkspace.tsx` | Exact-revision alternate-view candidates |
| Client/marketing outputs | `mobile/src/studio/StudioPresentWorkspace.tsx` | Presentation candidates and exact-revision saves |
| Collections | `mobile/src/studio/StudioCollectionsWorkspace.tsx` | Family organization without lineage mutation |
| Factory | `mobile/src/studio/StudioFactoryWorkspace.tsx` | Eligibility and authenticated exact-revision delivery |
| Activity | `mobile/src/studio/StudioActivityWorkspace.tsx` | Job and outcome history |
| Compatibility harness | `mobile/src/trusted/` | Older trusted components still used by focused flows/tests; not a second product shell |

Keep provider names, retry policy, and persistence authority out of navigation and
workspace components. The gateway and server contracts should expose product concepts:
candidate, decision, variation, revision, collection, destination, and eligibility.

## Data and generated artifacts

| Path | Role |
|---|---|
| `data/gemology_vocabulary.json` | Canonical controlled gemological vocabulary |
| `data/facet_diagrams/` | Bundled GemCad `.ASC` facet diagrams |
| `data/reference/` | Reference datasets and their provenance notes |
| `data/style_refs/` | Style-reference inputs and documentation |
| `data/render_cache/` | Local runtime cache; ignored, not source or release evidence |
| `docs/evals/` | Retained eval inputs/outputs; preserve provenance and use new run directories |

Local `facetta.db`, `.env*`, caches, build output, `node_modules`, and Expo state are
runtime artifacts, not repository architecture.

## Tests and verification

Backend tests generally mirror domain modules under `tests/test_*.py`. Mobile component
tests sit beside the implementation as `*.test.ts` or `*.test.tsx`.

| Change | Minimum useful verification |
|---|---|
| Backend domain rule | Nearest `tests/test_<domain>.py`, then broader backend suite |
| Router or ownership rule | Route-focused test plus auth/production-surface coverage |
| Studio gateway contract | `mobile/src/studio/gateway*.test.ts` and matching backend test |
| Workspace interaction | The workspace test, Studio routing test, and browser walkthrough |
| Candidate persistence | Pass/warning/failure, accept/discard, stale decision, and zero-charge assertions |
| Factory/release logic | Exact-revision blocker tests and the documented verifier; never infer release readiness from unit tests alone |

Standard commands are in the root [README](../README.md). Scripts with provider names or
`live` in their filename may make paid external calls; inspect their arguments and the
relevant runbook before running them.

## Where to make a change

1. Start at the user-visible workspace in `mobile/src/studio/`.
2. Find the invoked method in `mobile/src/studio/gateway.ts`.
3. Find its operation in `src/facetta/api/` or the development OpenAPI page.
4. Move business-rule changes into the domain service that already owns the invariant.
5. Keep writes atomic in the server transaction and append immutable history.
6. Add the narrow backend and frontend tests, then verify the real ports 8000 → 8081 path.

If a route appears duplicated, consult
[the route inventory](trusted-workflow-route-inventory.md) before deleting or building on
it. Compatibility code has explicit deletion gates; file age or an old name is not enough
to prove that it is unused.
