# Facetta

Facetta Studio is an AI jewelry-design workspace built around a short, reversible loop:
start from a sentence or reference, choose a direction, refine it without unrelated
drift, and keep every useful variation and revision. An exact saved revision can become
a client image, marketing asset, or optional factory-review package when the designer
chooses. Factory is a destination, not a required stage of design.

Read `CLAUDE.md` for the project constitution, `docs/PRD.md` for product requirements,
`docs/SPEC_SCHEMA.md` for the spec object schema, and `TASKS.md` for the build order.

## Trusted Studio workflow

The primary product loop is **Create → choose → refine → compare → keep**. A
category-neutral designer prompt, drawing, photograph, render, or set of role-labeled
references can create one to four review-only visual candidates through
`POST /projects/from-prompt` or `POST /projects/from-drawing`. Structural and material
edits remain temporary until the designer explicitly applies them or saves them as a
variation. Apply and Restore append immutable revisions; they never overwrite the
active revision in place.

Client, marketing, and view outputs stay attached to the exact revision that produced
them. Factory preparation is optional and appears only for an eligible revision. It
uses the trusted specification, approval, provenance, and review services behind the
simpler Studio interface. The deterministic SVG/DXF are explicitly schematic
dimensional diagrams—not production drawings or buildable jewelry geometry.
Production handoff still requires a designer-approved, design-derived technical
drawing and/or tolerance-bearing CAD/master geometry.

Grok is primary for image work. Every trusted candidate passes structured
jewelry QA, receives one failure-specific Grok correction when needed, and may
use one task-safe fallback: FLUX when configured, otherwise the OpenAI image
adapter when its credential is available. Warnings require designer review and failed
candidates never become project assets. A reviewed warning remains immutable
in its original image-run evidence; explicit acceptance writes a separate
review decision and the exact revision atomically. See
[`docs/trusted-workflow-architecture.md`](docs/trusted-workflow-architecture.md)
and the OpenAPI-checked
[`route inventory`](docs/trusted-workflow-route-inventory.md).

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Configuration

All secrets live in one place: a gitignored `.env` at the repo root. Copy the
template and fill in what you need:

```sh
cp .env.example .env
```

| Key | Used by |
|---|---|
| `DATABASE_URL` | PostgreSQL / Supabase (unset → local SQLite). See [Database](#database). |
| `ANTHROPIC_API_KEY` | Optional legacy Claude prose → spec and edit-agent endpoints |
| `FAL_KEY` | Photoreal renders / blueprint sheets via fal.ai |
| `XAI_KEY` | Grok Imagine generation/editing and Grok Vision concept/photo extraction |
| `OPENAI_API_KEY` | Optional direct GPT Image comparison runs; never exposed as a normal user model choice |

`.env` is loaded into the process environment at app startup (`facetta.config`),
so the keys reach both Facetta's own reads and the Anthropic SDK. A real exported
environment variable always wins over the file — so a hosting platform's injected
secrets override `.env` in production with no code change.

## Run the tests

```sh
PYTHONPATH=src uv run pytest -q
cd mobile
npm test -- --runInBand
npm run test:studio
npm run test:studio-client-api
```

`test:studio-client-api` starts a disposable real uvicorn/FastAPI process and
runs the production TypeScript trusted client and Studio gateway over HTTP. It
uses temporary SQLite and deterministic offline image providers to exercise ten
projects across sentence, drawing, photograph, finished-render, and role-labeled
reference starts. Every case verifies save/reopen, exact-revision branching,
review-before-Apply, immutable comparison/Restore, source semantics, and Activity
accounting without paid-provider credentials or Factory. The same run forces one
three-attempt hard-QA failure and one stale Apply race, proving zero canonical
persistence or charge for the failed generation and unchanged history plus a
zero-charge failed Activity record for the stale decision.

## Run the API

```sh
uv run uvicorn facetta.main:app --reload
```

### Health check

```sh
curl http://127.0.0.1:8000/health
```

### Validate a spec

`POST /specs/validate` takes a Spec Schema v1 object (see `docs/SPEC_SCHEMA.md`) and
returns it validated — with the ring inner diameter auto-derived from the size when
absent — or a structured 422 listing every failed rule with its valid options or
computed expected values.

```sh
curl -s -X POST http://127.0.0.1:8000/specs/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 1,
    "design_id": "dsn_8Kx2",
    "version": 3,
    "created_by": "usr_ana",
    "created_at": "2026-07-02T18:40:00Z",
    "jewelry_type": "ring",
    "template": "solitaire_prong",
    "mode": "pro",
    "stone": {
      "species": "sapphire",
      "cut": "oval_brilliant",
      "carat": 2.0,
      "dimensions_mm": {"length": 8.6, "width": 6.4, "depth": 4.1},
      "color": {
        "trade": "Royal Blue",
        "gia": "vivid violetish blue, tone 6, saturation 6",
        "hue_code": "vB", "tone": 6, "saturation": 6
      },
      "clarity": {"system": "gia_type_ii", "grade": "VS", "eye_clean": true},
      "origin": "Sri Lanka",
      "treatment": "heated",
      "phenomena": []
    },
    "setting": {
      "style": "4_prong_basket",
      "prong_count": 4,
      "prong_tip_mm": 0.9,
      "gallery_height_mm": 4.5
    },
    "metal": {"material": "gold", "karat": 18, "color": "yellow", "finish": "high_polish"},
    "band": {"profile": "half_round", "width_mm": 1.8, "thickness_mm": 1.6},
    "ring_size": {"system": "US", "value": 6.5, "inner_diameter_mm": 16.9},
    "side_stones": [],
    "notes_to_factory": "Slightly higher gallery to clear a future wedding band."
  }'
```

Change `"carat": 2.0` to `"carat": 5.0` in the payload above to see the density check
reject a physically impossible stone with the computed expected carat and depth. Change
`"trade": "Royal Blue"` to anything unknown to get back the list of valid sapphire trade
terms.

## Other endpoints

| Endpoint | Purpose |
|---|---|
| `GET /vocabulary/stones` · `GET /vocabulary/stones/{id}/options` | Cascading dropdown data: choosing a stone swaps its colors (trade+GIA), clarity system and grades, cuts, phenomena. Pearl and opal return their own parameter sets. |
| `POST /specs/catalog/select` | Apply one controlled cut, complete alloy/color, setting, or chain choice to an unpersisted draft; coupled and derived facts compile deterministically with no provider call or persistence |
| `POST /specs/stone/select` | Apply one vocabulary-controlled center species and trade color; incompatible grading/origin claims clear and modeled carat updates at frozen dimensions |
| `POST /specs/sheet.svg` | Stateless technical-sheet preview from a spec; incomplete reference-defined geometry is visibly marked preliminary and generic template geometry is withheld |
| `POST /designs` · `POST /designs/{id}/versions` | Create a design / a new immutable version (there is no update — edits always become version+1) |
| `GET /designs/{id}/versions/{v}/sheet.svg` | The stored version's dimensioned sheet |
| `POST /designs/{id}/versions/{v}/share` → `GET /share/{token}` | Share links pinned to one exact version; `comment` scope lets a factory pin comments to a region of the sheet |
| `POST /specs/from-prose` | Claude API: designer prose → validated spec (needs `ANTHROPIC_API_KEY`) |
| `POST /specs/prototype.svg` · `GET /designs/{id}/versions/{v}/prototype.svg` | Deterministic colored prototype (vocabulary hues + metal tones) |
| `POST /specs/render-prompt` | Compiled photoreal prompt + control-image hint for external image models |
| `POST /specs/render-request` | Scene-controlled mockup request (lighting, worn-on, photo/atelier-sketch style) with a geometry-locked seed: swap stone color or metal and the composition holds; change a dimension and it reseeds |
| `POST /specs/sheet.dxf` · `GET /designs/{id}/versions/{v}/sheet.dxf` | Transform-aware DXF R12 underlay for jewelry CAD: nested rotations and quadratic/cubic/arc outlines are preserved as deterministic polylines; unsupported geometry fails instead of being dropped. It remains a non-authoritative 2D exchange reference, and unresolved custom form or chain geometry returns `409` |
| `POST /specs/from-photo` | Grok Vision: finished-piece photo → physically corrected draft with stable component coverage; trusted callers run the same blind-first audit and designers still confirm dimensions |
| `POST /specs/from-plate` | Hand-rendered plate → ring or necklace draft with explicit component coverage; multi-view plates inventory one finished piece, preserve physical stone-group roles/labels, and the trusted client runs a blind-first independent inventory/mapping audit that keeps omissions/uncertainty blocking |
| `POST /projects/{id}/render` | QA-checked beauty render from the exact designer-confirmed imported reference/spec; incomplete source-component coverage is rejected before image work |
| `POST /assets/{id}/markup/read` · `POST /assets/{id}/markup/apply` | Read/confirm one marked change, then persist a version-checked image/spec revision. Freeform form edits require a stable element ID and saved same-raster mask |
| `POST /assets/{id}/catalog/apply` | Apply one safe ring or necklace-chain catalog choice from the exact active image/spec pair. Chain style requires designer-confirmed target geometry and a new exact stock/sample or custom drawing/CAD reference; missing/incompatible facts fail before provider work. Passes persist image/spec/run atomically and warnings remain temporary until explicit review |
| `POST /projects/{id}/product-photo` | Trusted ecommerce restage: catalog, luxury studio, dark editorial, or macro presentation; ring geometry/spec stay frozen and QA-warning candidates require designer review |
| `POST /projects/{id}/marketing-pack` | Generate one to four review-only ecommerce background candidates. Designer-accepted images persist as exact-version derived assets and never replace the active design or invalidate factory approval |
| `POST /projects/from-prompt` | Turn a category-neutral designer direction into one to four QA-gated visual concepts. No source asset, specification, measurements, or factory authority is invented; every candidate waits for selection and confirmed-spec promotion |
| `POST /projects/from-drawing` | Turn any valid designer drawing or jewelry image into one to four source-faithful visual candidates without grading the source or inventing factory facts; multi-view plates may include one normalized designer-selected region while Facetta retains both the full source and exact provider/QA crop |
| `POST /projects/{id}/creative-candidates/{candidate_id}/draft` | Read the exact selected creative render into a non-persisted, independently audited draft without asking the designer to upload the candidate again |
| `POST /projects/{id}/creative-candidates/{candidate_id}/dimensioned-profile/confirm` | Bind designer-entered millimeter paths/thickness to the exact stored candidate and return a non-persisted updated draft; the server supplies source hash and confirmation metadata, then requires source re-audit before promotion |
| `POST /projects/{id}/creative-candidates/{candidate_id}/source-coverage/resolve` | Correct stable candidate-component mappings and optionally re-audit the exact stored candidate bytes |
| `POST /projects/{id}/creative-candidates/{candidate_id}/source-coverage/confirm` | Bind explicit designer decisions only to inconclusive source facts; failed or missing audits cannot be overridden |
| `POST /projects/{id}/line-art` | Geometry-only drawing candidate; even QA-pass output waits for explicit designer confirmation |
| `POST /projects/{id}/line-art/{asset_id}/colorize` | Color a confirmed line drawing from the exact spec; deterministic and dual-vision material QA hard-fails corroborated stone/metal loss and routes conflicting cross-modality evidence to explicit designer review |
| `POST /specs/restage-request` | Scene instruction for re-staging a photo of a finished piece via an image-editing model |
| `GET/POST /designs/{id}/messages` | Designer ↔ factory discussion thread on a design (distinct from pinned sheet comments) |
| `POST /specs/stack.svg` · `GET /designs/{id}/versions/{v}/stack/{id2}/{v2}/sheet.svg` | Overlay two pieces with computed nesting clearance |
| `GET /vocabulary/findings` | Chain styles, clasp types, girdle thickness scale |
| `GET /vocabulary/components/{component_path}` | Typed chain style, ring center-cut, complete metal alloy/color, and center-setting catalogs with exact/coupled factory fields, visual geometry, isolation target, applicability rules, and frozen facts |

For multi-view designer plates, the line-art request may also carry a
normalized `source_region` (`x`, `y`, `width`, `height`, each relative to the
full raster) and `source_region_description`. Facetta crops on the server
before provider work and preserves the exact selection through a corrective
retry; the original project source remains immutable. This is an isolation
control, not permission for the model to invent hidden geometry.

Creative drawing intake uses the same normalized source-region coordinate
contract. The full imported plate remains the immutable root source; an exact
`CREATIVE_SOURCE_REGION` child asset stores the provider/QA crop, coordinates,
description, media type, and hash. Candidate parentage and the image run's
source ID/hash both point to that crop, so a plate cannot merely be described
as isolated while the image model actually receives every alternate view.

Design-form references and imported-source coverage are intentionally
conservative.
`visual_reference_only` components can be visually approved but keep the
project out of `factory_ready` until a real dimensioned/CAD definition exists.
The first supported resolution is a designer-supplied or
designer-confirmed-estimate full-assembly millimeter profile. Facetta renders
that profile instead of the generic template, labels estimated geometry, and
ensures DXF conversion cannot resurrect concealed template geometry. Partial
profiles remain blocked until a shared manufacturing datum is supported.
Likewise, a new design plate or finished-photo import cannot produce a
spec-aligned render or factory pack while any visible source component is
unresolved or lacks a passing independent coverage audit. Existing immutable
versions without these additive fields remain readable; Facetta never guesses
a backfill. An old passing audit also cannot bless a mapping whose canonical
spec path was removed by a later draft edit; that becomes an explicit
`source_component_path_missing` blocker, and the vision audit is not called
again until the deterministic mapping is corrected.

## Facet diagrams (GemCad .ASC)

Face-up stone drawings are not sketches: `src/facetta/gemcad.py` parses GemCad
`.ASC` faceting blueprints — the open format used by FacetDiagrams.org, the
USFG design directory and The Gemology Project — reconstructs the cut stone as
the intersection of its facet planes, and projects the crown straight down.
The bundled designs in `data/facet_diagrams/` (standard round brilliant, oval,
cushion, princess, emerald cut, asscher) were authored with meetpoint-exact
math from published proportions by `scripts/author_facet_diagrams.py`.

To use a downloaded design, drop its `.asc` file into `data/facet_diagrams/`
named after the cut id (e.g. `pear.asc`) — sheets and color prototypes pick it
up automatically; when a spec carries a `table_pct`, the drawn table is
remapped to the spec's number. Cuts without a diagram fall back to a
procedural pattern.

## Database

SQLite (`./facetta.db`) out of the box for zero-setup dev — no config needed. Point
`DATABASE_URL` at any PostgreSQL instance to switch; spec objects are stored as JSONB and
the immutable-version model is identical on both.

```sh
export DATABASE_URL="postgresql://user:password@host:5432/facetta"
```

You can also drop `DATABASE_URL=...` into a gitignored `.env` at the repo root (see
`.env.example`) — the same place the render/AI keys live — and it is picked up
automatically.

### Supabase

Supabase is managed PostgreSQL, so there is nothing to rewrite: the connection string
*is* the integration. Facetta normalizes a raw dashboard string onto its psycopg v3
driver, so you can paste it verbatim.

1. In your Supabase project, click **Connect**, choose the connection method for
   your host, and copy its **URI**. It looks like:

   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   ```

2. Set it (substituting your password) — either export it or put it in `.env`:

   ```sh
   export DATABASE_URL="postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"
   ```

3. Start the API. Facetta creates its tables (`designs`, `design_versions`, `comments`,
   …) on first boot — no manual migration step.

   ```sh
   uv run uvicorn facetta.main:app --reload
   ```

**Which connection type?** Supabase offers three, all handled automatically:

| Use | Endpoint | Notes |
|---|---|---|
| Long-running server (this API) | **Direct** `db.<ref>.supabase.co:5432` | Simplest; requires IPv6 egress |
| Server without IPv6 | **Session pooler** `…pooler.supabase.com:5432` | IPv4-friendly, one connection per client |
| Serverless / functions | **Transaction pooler** `…pooler.supabase.com:6543` | pgbouncer; Facetta disables prepared statements for you |

A bare `postgres://`/`postgresql://` scheme is routed to psycopg v3 (SQLAlchemy would
otherwise reach for psycopg2, which isn't installed). Hosted connections get
`pool_pre_ping` so Supabase's idle-connection drops are recycled rather than surfaced as
errors. Append `?sslmode=require` to force TLS if your policy demands it (psycopg
negotiates SSL with Supabase either way).

> The Supabase JS client / PostgREST auto-API is **not** used — Facetta talks to Postgres
> directly through SQLAlchemy so every write goes through the spec validator and the
> immutable-version rules. Supabase is the database, not the API layer.

> **Deployment guard:** production authentication is integrated through locally verified
> asymmetric Supabase access JWTs and canonical owner checks; see `docs/STUDIO_AUTH.md`.
> Facetta still does not use the Supabase Data API for application access. Keep direct
> table grants disabled unless a separately reviewed RLS/Data API contract is introduced.

## Mobile app (Expo)

`mobile/` contains the unified React Native Studio: mixed-source Create, temporary
candidate review, Vary, Refine, Views, Present, Collections, immutable history,
Activity, Learn, and an entitlement-gated optional Factory destination.

```sh
cd mobile
npm install
npx expo start          # scan the QR with Expo Go, or press w for web
```

Point the API URL field at your running backend (defaults to
`http://localhost:8000`; set `EXPO_PUBLIC_API_URL` to override).

The production shell integrates trusted contracts through the typed Studio gateway;
provider/model internals never enter designer navigation. The older comprehensive
trusted screen remains an internal diagnostic surface behind
`EXPO_PUBLIC_TRUSTED_WORKSPACE=true` and is not a competing product entry. Keep that
diagnostic flag off in normal Studio builds. The trusted module includes category-neutral prompt and
creative-first drawing/image intake with one to four candidates,
candidate-to-audited-spec promotion,
candidate-bound source correction/confirmation, and multi-preset ecommerce
packs. Extracted reference and creative-candidate drafts open in a typed
Factory Facts editor for stones, counts, dimensions, metal, setting, and
ring/necklace construction. Designers explicitly mark changed dimensions as
measured/supplied or reference estimates; raw JSON remains available under
Advanced rather than being the primary correction workflow. Center gemstone
species and trade colors cascade from the gemology vocabulary; cross-species
colors and unsupported species cannot enter the draft. The same candidate
review now renders the current facts through the canonical deterministic sheet
compiler on demand. The preview becomes visibly stale after any fact change and
is explicitly labeled either spec-derived or preliminary/not-for-production;
it never bypasses exact-revision approval or factory-pack release gates.

Factory-pack continuation pages are not dimension-only tables. The typed fact
plan also carries non-numeric manufacturing records: stone mount and grading/
treatment details, band profile, ring-size system, chain style/clasp/link roles/
soldering/production reference, pendant connection, bracelet and drop link
counts, custom-form authority, and designer factory instructions. Long values
continue onto additional visible rows instead of being ellipsized. A pack fails
closed if any recorded fact remains pending confirmation.

## Layout

| Path | Purpose |
|---|---|
| `data/gemology_vocabulary.json` | Controlled vocabulary — the single source of gemological truth |
| `data/facet_diagrams/` | Cached GemCad .ASC faceting blueprints, keyed by cut id |
| `data/reference/` | Research datasets as Excel-ready CSVs (facet blueprints, culet/girdle grading, weight formulas, international ring sizes, factory tolerances) |
| `src/facetta/gemcad.py` | .ASC parser + 3D reconstruction + exact face-up projection |
| `scripts/author_facet_diagrams.py` | Authors the bundled diagrams from published proportions |
| `src/facetta/spec.py` | Pydantic models for Spec Schema v1 |
| `src/facetta/vocabulary.py` | Vocabulary loader + typed accessors |
| `src/facetta/component_catalog.py` | Stable component choices compiled into one exact spec delta plus image-isolation controls |
| `src/facetta/creative_workflow.py` | Category-neutral prompt → visual concepts and input-agnostic drawing/image → source-faithful beauty renders through the closed-loop image agent |
| `src/facetta/density.py` | Carat ↔ mm density model (`carat = L × W × D × SG × shape_factor / 200`) |
| `src/facetta/validation.py` | Vocabulary + physical-consistency rules with structured issues |
| `src/facetta/svg_sheet.py` | Deterministic pencil-style technical sheet renderer (byte-stable per spec) |
| `src/facetta/db.py` | SQLAlchemy models including immutable design versions, exact-provenance assets, projects, approvals, image runs, and attempts |
| `src/facetta/image_agent/` | Grok-primary plan/execute/evaluate/correct orchestration and ring QA |
| `src/facetta/project_backbone.py` · `src/facetta/trusted_revision.py` | Atomic project creation plus accepted image/spec/run revision and warning-review persistence |
| `src/facetta/factory_pack.py` | Exact approved-revision manifest and deterministic factory archive |
| `src/facetta/factory_sheet_plan.py` | Deterministic material/stone/setting/dimension schedule with confirmed, estimated, and pending statuses |
| `src/facetta/factory_schedule_pages.py` | Byte-stable A4 continuation pages so dense fact schedules are never truncated |
| `src/facetta/prose.py` | Claude API prose → spec layer |
| `src/facetta/photo_spec.py` | Grok Vision reference-photo read → deterministic draft spec |
| `src/facetta/api/` | Routers including canonical projects, persisted markup/approval, image-run evidence, and factory handoff |
| `src/facetta/main.py` | FastAPI app wiring |
| `mobile/` | Expo (React Native) app: builder, designs, share views |
