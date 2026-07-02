# CLAUDE.md — Project Constitution

## Product name
**Facetta** — use for repo (`facetta`), Python package (`facetta`), API title, and all
user-facing copy. Pronounced fa-SET-ta.

## What this is
A design-to-manufacturing platform for the jewelry industry. Designers describe a piece
via structured parameters (assembly-line dropdowns, Basic/Pro modes). The system compiles
that into an immutable spec object, which drives every output: an annotated technical
sheet for factories, an interactive 3D preview, and (later) photoreal client renders.

Founder context: co-founded with a GIA-graduate jewelry designer who currently hand-draws
dimensioned sheets for factories. She is the domain expert and first user. Her manual
drawing workflow is the thing Phase 1 replaces.

## Non-negotiable principles
1. **Dimensional truth.** Every output derives from exact mm values in the spec. The AI
   never draws geometry; it only translates language into numbers. Deterministic code
   draws from those numbers. Same spec in, same output out, every time.
2. **Version immutability.** A design version is never mutated. Edits create a new
   version. Designer, factory, and client must always be able to reference an
   unambiguous, permanent state.
3. **Controlled vocabulary.** All stone, color, clarity, cut, and metal values come from
   `data/gemology_vocabulary.json`. Never free-text these fields. Never invent trade
   terms. The vocabulary is the single source of gemological truth — extend it via data,
   not code.
4. **We are not CAD.** Parametric templates for known jewelry archetypes only
   (solitaire, halo, bezel, three-stone...). No freeform modeling. No casting/STL
   production prep — that stays with the factory. Output = communication layer, exactly
   the role of the designer's current hand drawings.
5. **Physically possible or rejected.** Cross-validate carat ↔ mm using stone density.
   A spec that describes an impossible stone fails loudly with a helpful message.

## Stack
| Layer | Choice |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| Geometry | CadQuery (3D templates), svgwrite or raw SVG (2D sheets) |
| LLM | Claude API — natural language → spec object only |
| DB | PostgreSQL, JSONB for spec objects |
| Frontend | React Native (Expo) |
| 3D viewer | three.js (web) / GLB export; USDZ for iOS AR later |

## Architecture in one line
`user parameters → spec object (JSON, validated) → [SVG technical sheet | CadQuery 3D model | compiled AI prompt]`

The spec object is the hub. Everything else is a spoke. No spoke may talk to another
spoke directly.

## Build order (do not reorder)
1. Spec schema + validation (pydantic) incl. carat↔mm density checks
2. Vocabulary loader + cascading option API (stone → its colors, its clarity system)
3. SVG technical sheet generator: round solitaire, top + side views, mm annotations
4. Versioned design records API (immutable), share links, pinned comments
5. Claude API layer: prose → spec (strict JSON out, validated by #1)
6. ONE 3D template (round solitaire, 4-prong) in CadQuery → GLB
7. three.js viewer: rotate/zoom, lighting environments, dimension overlay

Ship 1–4 before touching 5–7. The founder's wife must be able to produce a
factory-acceptable sheet from dropdowns alone — that is the MVP bar.

## Conventions
- All dimensions in mm, all weights in ct, stored as numbers, never strings.
- Spec objects carry `schema_version`. Migrations are additive only.
- Trade term + GIA translation are BOTH stored on every stone color
  (e.g. `"trade": "Pigeon's Blood", "gia": "vivid red, slightly purplish, tone 5-6"`).
- Tests for every geometry function: given spec X, assert exact dimension Y in output.
- When the vocabulary lacks a stone/term the user needs, add it to the JSON with the
  same field shape — do not special-case in code.

## Known open items (do not silently resolve — ask)
- Jadeite grading (translucency/texture/Type A-B-C) not yet in vocabulary
- Manufacturer onboarding flow undefined
- Permission model beyond share-link granularity undefined
