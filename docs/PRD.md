# Facetta — Product Requirements

> **Historical foundation, not the active Studio product contract.** This document
> records the original specification-first milestone and remains useful for trusted
> factory-review constraints. Current product hierarchy, navigation, authority, and
> acceptance requirements live in `docs/ai-first-studio-architecture.md`, `TASKS.md`,
> and `docs/STUDIO_EXTERNAL_BETA_GATES.md`. In particular, Factory is optional and
> deterministic jewelry geometry is never design or production authority.

## Problem
Jewelry designers hand-draw dimensioned technical sheets for factories and separately
mock up visuals for clients. Text-to-image AI cannot do this job: it hallucinates
geometry and cannot hold dimensions. Factories need millimeter truth; clients need
beauty; today those are two manual workflows.

## Solution
One structured spec drives both. Designers assemble a design from controlled
gemological vocabulary (GIA language + everyday trade terms), and the platform emits:
1. An annotated, dimensioned technical sheet (factory)
2. An interactive, physically-scaled 3D preview (designer + client)
3. Photoreal renders compiled from the same spec (client, Phase 2+)

## Users
| User | Needs |
|---|---|
| Designer (primary; founder's wife is user #1) | Fast spec entry, trade-term vocabulary, factory-ready sheets, versioning |
| Manufacturer | Unambiguous dimensions, stable referenced versions, comment/annotation |
| End client (via designer) | Beautiful accurate preview, on-hand scale reference |

## Input modes
| Mode | Phase |
|---|---|
| Parameter builder — Basic (stone, shape, color, carat, jewelry type, metal) | 1 |
| Parameter builder — Pro (adds clarity, exact mm, setting style, band width, finish, origin) | 1 |
| Natural language → spec via Claude API | 1.5 |
| Photo → isolate/enhance/background swap | 2 |
| Photo → spec extraction | 3 |

## Color model (two layers, both stored)
Surface: everyday trade term the buyer/seller uses (Pigeon's Blood, Royal Blue,
Paraiba, Muzo Green, D-Z for diamonds...).
Compiler: GIA formal hue/tone/saturation translation used in prompts and sheets.
Cascading: choosing a stone swaps the color, clarity, and grading vocabularies
(jadeite ≠ diamond ≠ tanzanite systems). Pearls and opals use their own parameter
sets entirely (see vocabulary file).

## Phase plan
| Phase | Deliverables |
|---|---|
| 1 MVP | Spec builder → validated spec → SVG technical sheet (top+side, mm callouts) → immutable versions → share link + pinned comments |
| 1.5 | Prose → spec (Claude API); carat↔mm validator UX |
| 2 | CadQuery solitaire template → GLB → three.js viewer (rotate/zoom/lighting environments/dimension overlay); scaled hand model with ring-size selector; photo enhance/background swap (API-based) |
| 2.5 | Photoreal renders: 3D views as ControlNet skeletons + compiled prompt; lighting toggle demos pleochroic/color-change stones |
| 3 | Template library growth (halo, bezel, three-stone, pendants); AR try-on (USDZ); photo→spec |

## MVP success criteria
| # | Criterion |
|---|---|
| 1 | Designer produces a factory-acceptable dimensioned sheet from dropdowns in under 3 minutes |
| 2 | Same spec always renders an identical sheet (byte-stable SVG modulo metadata) |
| 3 | Impossible carat/mm combos are rejected with a corrective suggestion |
| 4 | A factory can open a share link, see one unambiguous version, and pin a comment to a region of the sketch |
| 5 | Founder's wife signs off that the sheet matches or beats her hand-drawn format |

## Explicit non-goals
Freeform CAD; casting/production files (STL prep, shrinkage, sprues); marketplace;
payments; synthetic-stone detection.
