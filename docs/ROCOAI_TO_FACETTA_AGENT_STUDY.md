# RocoAI study → Facetta Agent Studio brief

**Purpose:** implementation and product brief for agents working on Facetta's
AI-agent surface. It records what was visibly observed in RocoAI during a
signed-out browser study on 2026-07-12, then makes explicit product decisions
for Facetta.

**Evidence boundary:** the RocoAI features below are UI-visible claims and
screens only. We did not log in, upload files, run generation, or verify its
model/provider behavior. Do not infer implementation details or output
fidelity from its labels.

## The decision

Facetta **does need a first-class AI agent**. The positioning is not “no
generative AI”; it is:

> An AI jewelry-design agent that turns an approved idea into a validated,
> versioned factory handoff.

RocoAI is a useful reference for the creative surface: it makes the user pick
an outcome, collects only the parameters for that outcome, and generates a
visual. Facetta must use that approachable interaction model while retaining
the distinction that makes its factory package trustworthy.

```text
intent / references
        ↓
Atelier agent → proposed structured spec → validation
        ↓
visual draft → controlled visual revisions → approved visual
        ↓
Spec vN + approved visual asset vM → factory package
        ↓
technical sheet + DXF + factory comments + immutable history
```

Generated visuals are drafts or presentation assets. The factory package is
the canonical record and is derived from an approved, validated spec.

## RocoAI feature inventory (visible UI)

### Product navigation

The mobile navigation exposes:

- Home
- **AI Design**
- **AI Visual**
- **AI Video** (label visible; workflow not inspected)
- Toolbox
- **AI Modeling** (label visible; workflow not inspected)
- Inspiration/creative gallery
- Research area

### AI Design

Visible creation modes:

| RocoAI mode | UI-visible behavior |
|---|---|
| Smart design | Optional text brief, optional reference upload, structured design parameters, generate a visual concept. |
| Extended design | A separate variation/extension mode; detailed fields were not inspected. |
| Sketch colorization | A sketch-to-colour/design mode; detailed fields were not inspected. |
| Multi-image reference | Separate slots for a **subject/master reference** and a **style reference**. The helper text describes retaining the first image's structure while transferring material/atmosphere from the second. |
| Style modification | Upload an existing style, choose 1K/2K/4K and one to four outputs. The upload accepts JPG/PNG/WebP/AVIF up to 10 MB. |
| Free design | A required free-text prompt, optional reference image, count, resolution, and aspect controls. |

The Smart-design screen is a useful interaction reference:

- The design prompt is explicitly **optional**: a user can direct the result
  through text, a reference image, or structured parameters.
- Quick controls expose an inspiration-prompt helper, output count, preview
  quality, automatic aspect ratio, and a freehand/brush control.
- Its beta parameter taxonomy is: product category, material, image style,
  design style, craft, silhouette/layout, decorative elements, setting/inlay,
  and components/accessories.
- Selected values become compact chips beneath the category strip.
- The primary CTA is fixed at the bottom and visibly names its compute cost.

### AI Visual

Visible top-level visual operations:

1. Smart all-in-one visual generation
2. Model wearing / virtual try-on
3. One-click scene replacement
4. HD upscaling
5. Viewpoint/angle change
6. One-click retouching

The all-in-one screen shows ten visual deliverables:

| Deliverable | UI-visible purpose |
|---|---|
| Ecommerce detail page | Long-form jewelry product-detail imagery for ecommerce. |
| Xiaohongshu seeding image | Social cover image. |
| OEM sampling brief | Jewelry OEM/factory sampling instruction image. |
| Holiday marketing image | Holiday campaign poster. |
| Product packaging image | High-end jewelry packaging presentation. |
| Product selling-point breakdown | Product benefit infographic. |
| Visual storyboard | Artistic jewelry storyboard. |
| Brand visual asset | Brand assets generated from an uploaded logo. |
| Ecommerce promotion poster | Jewelry promotion poster. |
| New-product launch poster | New-product/key-visual poster. |

Common visual generation controls observed:

- One reference-image slot (`0/1`) with paste, drag/drop, or click-to-upload.
- JPG/PNG/WebP accepted; 10 MB single-file limit.
- 2K and 4K choices; the UI describes 4K as better for image-and-text detail.
- A fixed generation CTA with a displayed credit cost.

The **parameters are not static**. Selecting a deliverable swaps in the
relevant form. Examples observed:

- Packaging image: brand name, product category, packaging style.
- Promotion poster: promotion information and selling price.
- New-product launch: brand name and product name.
- Holiday image: holiday name.

This is the important pattern to adopt: a stable shell plus a
**selected-action parameter schema**, not one generic form for every visual
job.

### Toolbox

Visible utility operations:

- Smart cutout/background isolation
- Watermark removal
- Raster image to vector
- Image stitching/compositing

## Facetta product decisions

### Keep: an agent-led, outcome-first creative surface

Build **Atelier** as the primary AI surface, not a generic chat pane and not
a static builder form. It begins with a brief or references and offers
outcome-led actions:

| Atelier action | Facetta behavior |
|---|---|
| Create concept | Generate a new jewelry concept from a brief and/or references. Return the visual, the agent's design read, a proposed structured spec, and validation corrections before saving. |
| Create variation | Preserve stated design DNA while exploring materials, setting, scale, silhouette, or collection variants. |
| Combine references | Make each reference role explicit: master design/geometry, style/material, detail, and optional brand asset. |
| Refine selected area | Require a region/mask and a change instruction. Preserve everything outside it. Show parent/child comparison and the change summary. |
| Wear it / place it | Generate controlled worn-on or scene visuals from an approved visual/design. |
| New view | Generate a declared camera angle from the current approved visual; retain asset lineage. |
| Presentation pack | Later: derive client-facing product, campaign, and detail visuals from an approved design. |
| Prepare for factory | Convert an approved idea into the validated spec/version and create the factory package. |

Use RocoAI's optional prompt model. Facetta users should be able to direct the
agent through any combination of:

1. A rough sentence or conversation
2. A master reference, sketch, or existing render
3. Structured design-intent controls

The agent should populate controls from what it understood and ask only the
next high-value question. It should not demand a fully engineered prompt.

### Separate design truth from visual direction

Design values can become proposed spec fields and therefore require
controlled vocabulary and validation:

- Jewelry type/template
- Stone species, cut, colour, carat/dimensions
- Metal and finish
- Setting and construction intent
- Proportion/silhouette

Visual values only affect a render request and must never silently mutate the
factory record:

- Studio/worn/editorial scene
- Model direction and pose
- Camera angle, crop, aspect ratio
- Lighting and presentation styling
- Preview versus print-quality output

Do **not** copy nine RocoAI parameter categories directly onto the first
Facetta screen. Start with six high-signal design-intent controls, let the
agent infer the rest, and reveal “Advanced design details” only when asked.

### Adopt dynamic parameter schemas

Each Atelier action must declare its fields instead of reusing a static form.
An implementation can use a registry shaped like this:

```ts
type AtelierAction = {
  id: string;
  family: 'create' | 'visualize' | 'refine' | 'factory';
  label: string;
  requires: Array<'brief' | 'spec' | 'asset' | 'mask' | 'brand_asset'>;
  fields: Array<{
    id: string;
    label: string;
    required: boolean;
    source: 'user' | 'prefill_from_spec' | 'prefill_from_asset';
  }>;
  output: 'visual_draft' | 'derived_visual' | 'proposed_spec' | 'factory_package';
  trust: 'presentation' | 'canonical';
};
```

Examples:

| Selected action | Required/prefilled context |
|---|---|
| Wear it | Approved visual; piece dimensions/ring size if available; body location; model direction. |
| New view | Source visual; desired angle; crop/background. |
| Scene | Source visual; intended use; scene; optional brand mood. |
| Local edit | Source visual; selected region/mask; exact change request. |
| Presentation pack | Approved design; desired outputs; brand assets; factual copy inputs. |
| Factory package | Exact spec version; approved visual; unresolved/TBD data; regional profile. |

### Utility decisions

| RocoAI utility | Facetta decision |
|---|---|
| Smart cutout | **Add.** Useful for clean source assets, masks, and scene work. Preserve the source and create a derived child asset. |
| Watermark removal | **Do not add.** It is a rights risk and is not required for Facetta's value proposition. |
| Image to vector | **Add later as “Trace silhouette” or “Vector reference.”** It must be labelled visual/reference-only, never CAD or trusted manufacturing geometry. |
| Image stitching | **Add as “Reference board.”** It should combine master, material/style, detail, and brand references for the agent; retain the individual source assets. |

## Non-negotiable factory guardrails

1. **The factory sheet remains deterministic and spec-derived.** An AI-made
   technical-looking image may be a discussion draft, but it must not become
   the official sheet merely because it looks plausible.
2. **No false precision.** Inferred dimensions, stone counts, and weights are
   marked proposed/TBD until validated and signed off.
3. **Freeze contracts are structural.** A selected-region edit must preserve
   all non-selected fields/visual regions; it cannot rely on prompt wording
   alone.
4. **Bind the approved visual to an immutable spec version.** A factory
   package must state `Spec vN + approved visual asset vM`. If the spec
   changes, mark prior visual assets **stale for factory use** until they are
   regenerated or explicitly re-approved.
5. **Keep provenance.** Every transform remains an asset child:
   `source → cutout/reference board/render → localized edit → approved visual`.
6. **Visual utilities never imply manufacturing readiness.** This includes
   upscaling, retouching, scene swaps, image-to-vector operations, and
   presentation packs.

## Implementation priority

### P0 — make the existing agent and asset chain visible

1. Create an **Atelier** tab/screen: persistent, structured conversation;
   brief/reference intake; agent responses; generated concept; proposed spec;
   corrections; review-and-save state.
2. Bind the existing assistant/concept APIs and show a real generated asset,
   not only a compiled image prompt.
3. Create one **Visual revision** workspace: source visual, variation or
   selected-region edit, parent/child history, side-by-side comparison, and
   “Approve visual for factory.”
4. Make **Factory package** a top-level final state: version pair, validation,
   sheet, DXF, share/comments, and stale-status handling.

### P1 — useful visual actions

1. Wear it/model views
2. Scene replacement
3. Controlled view/angle pack
4. Presentation/retouch controls
5. Spin video, as a child of an approved visual

### P2 — market-facing content and utilities

Only after P0/P1 prove useful to designers:

- Presentation packs and branded client assets
- Ecommerce/social templates
- Reference board
- Cutout and trace-silhouette utilities

Do not lead the product with social posts, festival graphics, generic
ecommerce posters, or brand-key-visual templates. Those can be child outputs
of an approved design, but they are not Facetta's center of gravity.

## Current repository audit

Facetta is not starting from zero. The backend has much of the needed
capability, while the mobile surface currently exposes only a thin slice.

| Existing capability | Pointer | Current gap |
|---|---|---|
| Assistant / spec guidance | `src/facetta/api/specs.py` | Mobile does not expose the assistant conversation. |
| Concept from brief → validated spec | `POST /specs/from-concept` | Builder has a one-shot text field rather than an agent flow. |
| Hero render, localized edit, angle views, markup, video, asset history | `src/facetta/api/assets.py` | `mobile/src/api.ts` does not bind the asset-chain endpoints. |
| Immutable versions, sheets, DXF, share links, comments | designs/spec routers and `mobile/src/DesignsScreen.tsx` | Factory handoff is not elevated as the explicit last stage. |

Known UI mismatch to fix in P0: the home screen markets model try-on, scene
swaps, ecommerce packs, spin video, and precision edits, but the cards route
to the general Builder or Designs screens. Do not market a capability as a
separate studio until it has its own functional state and API binding.

## Read before changing agent behavior

`docs/jewelry_agent_system_prompt.md` contains an instruction that technical
drawing requests should not use the legacy parametric/math spec backend. That
conflicts with this product brief and the project's dimensional-truth
constitution. Resolve this before wiring an official factory-handoff flow:

- AI can make a technical-looking **discussion draft** from a reference.
- The official factory sheet/DXF must remain generated from the validated,
  immutable spec.

## Definition of done for Agent Studio v1

- A designer can start from a sentence or reference and have an agent turn it
  into a visible concept plus a proposed, validated spec.
- A designer can create a controlled visual revision and see its parent,
  child, and change summary.
- The UI makes draft, approved visual, proposed spec, and canonical spec
  unmistakably different states.
- Factory handoff visibly binds one immutable spec version and one approved
  visual asset, and blocks/flags stale pairings.
- Existing screens do not claim an unimplemented creative capability.
