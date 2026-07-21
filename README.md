# Facetta

Facetta Studio is an AI jewelry-design workspace built around a reversible loop:
**create → choose → refine → compare → keep**. Designers can begin with text,
drawings, photographs, renders, or role-labeled references, then preserve useful
directions as variations and immutable revisions.

An exact revision may later produce client, marketing, view, or optional
factory-review material. Factory is a destination, not a required design stage.
AI imagery and deterministic diagrams are never production authority by themselves.

## Start here

| Need | Read |
|---|---|
| Understand the product and non-negotiable rules | [Project constitution](CLAUDE.md) |
| Find code, tests, and request paths | [Repository map](docs/REPOSITORY_MAP.md) |
| Understand lineage and Studio behavior | [AI-first Studio architecture](docs/ai-first-studio-architecture.md) |
| Understand persistence, QA, and promotion boundaries | [Trusted workflow architecture](docs/trusted-workflow-architecture.md) |
| Find an API operation | [Route inventory](docs/trusted-workflow-route-inventory.md) or development `/docs` |
| Navigate the rest of the documentation | [Documentation index](docs/README.md) |
| Review historical work and evidence | [Task ledger](TASKS.md) and [status log](docs/STATUS.md) |

`TASKS.md` and `docs/STATUS.md` are historical ledgers, not proof that the current
checkout or live product path is green. Re-run the relevant tests and the real local
workflow before making a current-status claim.

## Product and data model

Facetta separates permanent design history from flexible organization:

```text
Design Family
└── Variation
    └── immutable Revision

Collections and tags organize Design Families without rewriting lineage.
```

- Candidate images are temporary until the designer explicitly accepts them.
- Apply and Restore append revisions; they do not mutate prior revisions.
- Client, marketing, view, and factory-review outputs remain pinned to the exact
  revision that produced them.
- Failed or discarded candidates do not become canonical assets.
- Factory preparation requires confirmed facts, provenance, approvals, and any
  required designer-supplied drawing or CAD/master reference.

## Local setup

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js, and npm.

```sh
uv sync
cp .env.example .env
cd mobile
npm ci
```

Both `.env` and `.env.local` are gitignored. When both exist, `.env.local` wins;
exported environment variables override either file. Never commit provider keys,
database credentials, access tokens, or Supabase service-role credentials.

### Start the complete local preview

Use the supervised runner from the repository root. It supplies the required
local auth settings, waits for API readiness before starting Studio, and stops
both services if either one fails. This prevents a cached browser bundle from
looking healthy after its API or Metro process has exited.

```sh
uv run python scripts/run_local_preview.py
```

Facetta is ready when the runner prints `http://127.0.0.1:8081/`. Check an
already-running stack with:

```sh
uv run python scripts/run_local_preview.py --check
```

The two-terminal commands below remain useful when debugging one service.

### 1. Start only the API

From the repository root:

```sh
FACETTA_ENV=development FACETTA_AUTH_MODE=test \
  PYTHONPATH=src uv run uvicorn facetta.main:app --reload --port 8000
```

Then verify the process you actually reached:

```sh
curl http://127.0.0.1:8000/health
```

Development OpenAPI documentation is available at
`http://127.0.0.1:8000/docs`. Production deliberately hides it and exposes only
the allowlisted Studio surface in `src/facetta/main.py`.

### 2. Start only the Studio preview

In a second terminal:

```sh
cd mobile
npm run preview:bypass
```

This starts the Expo web preview on `http://127.0.0.1:8081` and points it at the
local API on port 8000. The bypass skips login only for local preview work. Never
use it as a production or shared-staging configuration.

For the normal Expo flow instead:

```sh
cd mobile
npm start
```

Set `EXPO_PUBLIC_API_URL` when the API is not at `http://localhost:8000`.

## Tests

Run backend and frontend checks from their respective directories:

```sh
# Repository root
PYTHONPATH=src uv run pytest -q

# mobile/
npm test -- --runInBand
npm run test:studio
npm run test:studio-client-api
```

`test:studio-client-api` starts a disposable FastAPI process with temporary SQLite
and deterministic offline image providers, then exercises the production TypeScript
gateway over HTTP. It does not replace live provider QA or a browser walkthrough on
ports 8000 and 8081.

For a focused backend change, run the nearest test module first, for example:

```sh
PYTHONPATH=src uv run pytest tests/test_studio_jobs_api.py -q
```

## Architecture at a glance

```text
mobile/App.tsx
  → mobile/src/studio/*Workspace.tsx
  → mobile/src/studio/gateway.ts
  → src/facetta/main.py + src/facetta/api/*
  → domain services in src/facetta/*
  → SQLAlchemy persistence and configured image/vision providers
```

The typed Studio gateway is the client/server seam. FastAPI routers should translate
HTTP input and ownership context, while domain modules own business rules and atomic
persistence. Provider output must pass the relevant jewelry QA and explicit review
boundary before it can enter immutable history.

See [the repository map](docs/REPOSITORY_MAP.md) for the files to change for Create,
Refine, Collections, lineage/history, destinations, Factory, auth, providers, and
release evidence.

## Configuration

The complete commented template is [.env.example](.env.example). Common settings:

| Key | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL/Supabase connection; unset uses local `./facetta.db` |
| `FACETTA_ENV` | `development`, `test`, or `production` |
| `FACETTA_AUTH_MODE` | Local/test mode during development; production requires `supabase` |
| `FACETTA_SUPABASE_URL` | Supabase issuer used for production JWT verification |
| `FACETTA_DEPLOYMENT_REVISION` | Immutable deployed revision reported by `/health` |
| `FACETTA_CORS_ORIGINS` | Exact comma-separated production web origins; wildcard is rejected |
| `XAI_KEY` | Grok image/vision paths when configured |
| `OPENAI_API_KEY` | Task-safe image/vision fallback paths when configured |
| `FAL_KEY` | fal.ai rendering paths when configured |
| `ANTHROPIC_API_KEY` | Legacy prose-to-spec and edit-agent paths |

Local SQLite requires no database configuration. Production uses PostgreSQL and
refuses to start without Supabase authentication. The app verifies asymmetric Supabase
access JWTs locally; it does not expose the Supabase service role to the client.
See [Studio authentication](docs/STUDIO_AUTH.md) before changing auth or ownership.

## Important boundaries

- Facetta is a design communication and review workspace, not a CAD or casting system.
- SVG/DXF outputs are schematic unless backed by the required design-derived,
  tolerance-bearing authority.
- Creative text and model-inferred details do not silently become factory facts.
- Dimensions are millimeters; weights are carats; controlled gemological facts come
  from `data/gemology_vocabulary.json`.
- External-beta readiness is separate from code completion. The frozen corpus,
  independent review, and two-principal staging checks are documented in
  [Studio external beta gates](docs/STUDIO_EXTERNAL_BETA_GATES.md).

## Repository layout

| Path | Purpose |
|---|---|
| `src/facetta/` | FastAPI application, domain services, persistence, QA, and providers |
| `src/facetta/api/` | HTTP routers and request/response boundary |
| `mobile/` | Expo/React Native Studio application |
| `tests/` | Backend unit, API, integration, and acceptance tests |
| `scripts/` | Explicit eval, release, and local acceptance entry points |
| `data/` | Controlled vocabulary, reference data, and local ignored render cache |
| `docs/` | Architecture, contracts, operations, status, and retained eval evidence |

For a change-oriented map rather than a directory dump, use
[docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md).
