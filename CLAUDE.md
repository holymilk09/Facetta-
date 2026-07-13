# CLAUDE.md — Project Constitution

## Product name
**Facetta** — use for repo (`facetta`), Python package (`facetta`), API title, and all
user-facing copy. Pronounced fa-SET-ta.

## What this is
An AI jewelry-design workspace for moving quickly from a sentence, drawing, photograph,
render, or role-labeled references to strong visual directions. Designers choose and
refine a direction without unrelated drift, retain every useful variation and immutable
revision, and may turn an exact revision into client, marketing, or honest factory-review
material. Factory is an optional destination, never a required stage of creation.

Founder context: co-founded with a GIA-graduate jewelry designer who is the domain expert
and first user. Her design judgment, client work, and factory-review workflow define the
acceptance bar.

## Non-negotiable principles
1. **Authority is explicit.** Visual AI may explore and refine jewelry form, but a render,
   inferred measurement, or deterministic schematic is never production authority.
   Confirmed specification facts, designer-supplied CAD/master geometry, approvals, and
   provenance must remain distinguishable and fail closed when missing.
2. **Version immutability.** A design version is never mutated. Edits create a new
   version. Designer, factory, and client must always be able to reference an
   unambiguous, permanent state.
3. **Controlled facts, flexible briefs.** Designers may use natural language for creative
   direction. Confirmed stone, color, clarity, cut, metal, and construction facts use the
   controlled vocabulary. Never invent trade terms or silently promote creative text into
   factory truth.
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
`mixed-source brief → temporary candidates → accepted immutable revision → [Library | Client | Marketing | optional Factory review]`

The Studio gateway is the typed integration seam. Canonical projects, assets, immutable
revisions, specifications, provenance, QA evidence, and approvals remain server-owned.
Temporary candidates cannot mutate canonical history before explicit acceptance.

## Legacy build order (historical; do not use for Studio prioritization)
1. Spec schema + validation (pydantic) incl. carat↔mm density checks
2. Vocabulary loader + cascading option API (stone → its colors, its clarity system)
3. SVG technical sheet generator: round solitaire, top + side views, mm annotations
4. Versioned design records API (immutable), share links, pinned comments
5. Claude API layer: prose → spec (strict JSON out, validated by #1)
6. ONE 3D template (round solitaire, 4-prong) in CadQuery → GLB
7. three.js viewer: rotate/zoom, lighting environments, dimension overlay

These milestones explain the trusted foundation already present in the repository. The
current Studio execution order is defined by `TASKS.md` and
`docs/ai-first-studio-architecture.md`: protect immutable design truth first, simplify
the designer journey second, and expose Factory only when an exact revision is eligible.

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
