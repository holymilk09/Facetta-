# Facetta

A design-to-manufacturing platform for the jewelry industry. Designers describe a piece
via structured parameters drawn from a controlled gemological vocabulary; the system
compiles that into an immutable spec object which drives every output — an annotated
technical sheet for factories, an interactive 3D preview, and (later) photoreal client
renders.

Read `CLAUDE.md` for the project constitution, `docs/PRD.md` for product requirements,
`docs/SPEC_SCHEMA.md` for the spec object schema, and `TASKS.md` for the build order.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Run the tests

```sh
uv run pytest
```

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
| `POST /specs/sheet.svg` | Stateless technical-sheet preview from a spec |
| `POST /designs` · `POST /designs/{id}/versions` | Create a design / a new immutable version (there is no update — edits always become version+1) |
| `GET /designs/{id}/versions/{v}/sheet.svg` | The stored version's dimensioned sheet |
| `POST /designs/{id}/versions/{v}/share` → `GET /share/{token}` | Share links pinned to one exact version; `comment` scope lets a factory pin comments to a region of the sheet |
| `POST /specs/from-prose` | Claude API: designer prose → validated spec (needs `ANTHROPIC_API_KEY`) |
| `POST /specs/prototype.svg` · `GET /designs/{id}/versions/{v}/prototype.svg` | Deterministic colored prototype (vocabulary hues + metal tones) |
| `POST /specs/render-prompt` | Compiled photoreal prompt + control-image hint for external image models |
| `POST /specs/render-request` | Scene-controlled mockup request (lighting, worn-on, photo/atelier-sketch style) with a geometry-locked seed: swap stone color or metal and the composition holds; change a dimension and it reseeds |
| `POST /specs/sheet.dxf` · `GET /designs/{id}/versions/{v}/sheet.dxf` | The sheet as a DXF R12 drawing — the 2D underlay jewelry CAD (Rhino, MatrixGold) imports natively |
| `POST /specs/from-photo` | Claude vision: photo of a finished piece → draft spec (designer corrects dims; same validation gate) |
| `POST /specs/restage-request` | Scene instruction for re-staging a photo of a finished piece via an image-editing model |
| `GET/POST /designs/{id}/messages` | Designer ↔ factory discussion thread on a design (distinct from pinned sheet comments) |
| `POST /specs/stack.svg` · `GET /designs/{id}/versions/{v}/stack/{id2}/{v2}/sheet.svg` | Overlay two pieces with computed nesting clearance |
| `GET /vocabulary/findings` | Chain styles, clasp types, girdle thickness scale |

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

1. In your Supabase project, open **Project Settings → Database → Connection string**
   and copy the **URI**. It looks like:

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

## Mobile app (Expo)

`mobile/` contains the React Native app: the cascading-dropdown spec builder
(Basic/Pro), validation with corrective errors, live sheet preview, immutable
version history, and the factory share view with tap-to-pin comments.

```sh
cd mobile
npm install
npx expo start          # scan the QR with Expo Go, or press w for web
```

Point the API URL field at your running backend (defaults to
`http://localhost:8000`; set `EXPO_PUBLIC_API_URL` to override).

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
| `src/facetta/density.py` | Carat ↔ mm density model (`carat = L × W × D × SG × shape_factor / 200`) |
| `src/facetta/validation.py` | Vocabulary + physical-consistency rules with structured issues |
| `src/facetta/svg_sheet.py` | Deterministic pencil-style technical sheet renderer (byte-stable per spec) |
| `src/facetta/db.py` | SQLAlchemy models: users, designs, immutable design_versions, comments, share_links |
| `src/facetta/prose.py` | Claude API prose → spec layer |
| `src/facetta/api/` | Routers: vocabulary, specs, designs, share, users |
| `src/facetta/main.py` | FastAPI app wiring |
| `mobile/` | Expo (React Native) app: builder, designs, share views |
