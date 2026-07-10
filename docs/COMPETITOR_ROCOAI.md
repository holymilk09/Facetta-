# Competitor analysis — RocoAI (兔可AI)

*Written 2026-07-10, from five founder-supplied screenshots of RocoAI v0.8.3 (Beta),
a jewelry-focused AI visual tool popular in China. This doc records every feature
visible in the screenshots, cross-references each against Facetta's shipped state
(see `docs/STATUS.md`), and ends with the wedge and a concrete adoption list.*

---

## 1. What RocoAI is

A **post-production AI marketing suite for jewelry photos**. Input is always a
photograph of a piece that already exists; output is prettier photographs.
Dark-luxury UI (near-black surfaces, gold accent, serif English subtitles),
the same design language as mainstream AI photo/video tools. Monetized via a
credit economy ("算力" / compute points): every generation shows its credit
cost on the button, balance and top-up live in the header.

### Top-level navigation (left rail)

| Module | Chinese | What it is |
|---|---|---|
| AI Design | AI 设计 | Design-generation module (not shown in detail) |
| AI Visual | AI 视觉 | The photo suite — the module demoed |
| AI Video | AI 视频 | Video generation from product imagery |
| AI Chat | AI 对话 | Assistant/chat surface |
| Creative Gallery | 创意廊 | Community gallery; generations can be shared into it |
| Academy | 研学屋 | Tutorials / learning content |

### AI Visual sub-tools (the six-pack)

| Tool | Chinese | What it does | Commodity? |
|---|---|---|---|
| Smart full package | 智能全案 | One click → a full marketing asset set | No — bundling is the value |
| Model try-on | 模特佩戴 | Renders the piece worn on an AI model | Semi |
| **AI Scene Swap** | 一键换场景 | Flagship: white-background product photo → styled e-commerce scene | Semi |
| HD upscale | 高清放大 | Upscaling | Yes |
| Change angle | 修改角度 | Novel view synthesis from one photo | Semi |
| One-click retouch | 一键精修 | Auto retouching | Yes |

## 2. The Scene Swap workflow, step by step

This is the feature the demo video walks through, and it is well designed:

1. **Upload** — drag / paste / click a product photo into the left panel
   (their demo: a gold ring with star-set diamonds on a plain white background).
2. **Mode choice** — 智能换背景 (smart auto background) vs 自定义背景 (custom
   background). Auto mode has an 自动场景 toggle: *"automatically matches an
   e-commerce scene to the product's theme / elements / style"* (智能适配产品
   气质与元素). This is their headline claim.
3. **Or pick a curated preset** — a scene library organized as taste-category
   tabs, each preset a thumbnail card with an evocative two-to-four-character
   name:
   - 简约INS (minimal Instagram): 瓷园暖影, 木影留白, 奶油石韵, 暖笺留光
   - 禅意古风 (Zen / classical Chinese)
   - 红色主题 (red theme — CN gifting market)
   - 品牌摄影 (brand photography): 简约几何, 白棉花语, 白素紫韵, 黑胶旧梦
4. **Quality tier** — 1K (fast) / 2K (HD) / 4K (ultra) plus aspect-ratio presets
   (3:4 portrait etc.). Cheap fast preview, expensive final.
5. **Generate** — button states the credit cost up front ("开始 AI 生成 (15 算力)";
   18 for the ring). Result lands on a **work canvas** (工作画布) with a
   **history tab** (历史记录) and a layers icon.
6. **Output actions** — 分享到创意廊 (share to gallery), **添加水印 (add
   watermark)**, 下载图片 (download). Toast confirms completion; a feedback
   button (问题反馈) is always visible.

Demo results: the plain necklace shot became a flat-lay on cream linen with
lisianthus and lavender; the ring became a moody dark-slate hero shot.
Marketing tags on the feature page: 多维场景 (multi-scene), 氛围营造
(atmosphere), 光影融合 (light/shadow fusion).

## 3. Feature-by-feature cross-reference against Facetta

| RocoAI feature | Facetta today | Gap / note |
|---|---|---|
| Scene swap from a photo | `POST /specs/mockup/from-photo` + restage endpoints exist; render pipeline proven live (FLUX / Grok) | **We already have the API**; we have no preset library or UI polish around it |
| Auto scene matching (guesses product character from pixels) | Nothing — but we hold the **spec**, so we don't need to guess | Deterministic spec→scene mapping would beat their inference (see §5) |
| Curated named scene presets w/ thumbnails | Mockup engine takes raw scene params (lighting × worn-on × style) | Presets-as-data is missing; fits our "extend via data, not code" rule |
| Model try-on | "worn-on" axis exists in the mockup scene compiler; hand-scale view planned | Validates demand; ours anchors to true mm scale |
| Change angle | Full 3D-capable spec + GemCad facet engine → we can produce **exact** angles, not hallucinated ones | Their version can invent geometry; ours cannot, by constitution |
| HD upscale / retouch | Nothing | Commodity — buy via fal.ai if ever needed, never build |
| Smart full package (one click → asset set) | All outputs already derive from one spec (sheet, blueprint, client render) but are separate calls | **"Full dossier" endpoint is our natural, stronger version** |
| Credit cost shown on the button | No cost surfacing | Adopt when fal.ai billing is wired |
| 1K/2K/4K + aspect tiers | Render cache keyed by (geometry_fingerprint, scene, style); no tiers | Cheap-preview / final-quality tiers map cleanly onto the cache |
| Work canvas + generation history | Immutable versions ≫ their history, but per-version **render history** isn't exposed | Expose the cache as history in the app |
| Watermark on export | Nothing | Strong fit: designers fear concept theft on client share links |
| Share to community gallery | Share links are private-by-design | Skip — our users share to clients/factories, not to a feed |
| AI video | Nothing, not planned | Ignore for now; revisit only post-MVP |
| Credit top-up economy | No billing at all | Note for later; their per-action pricing model is proven in-market |

## 4. What they have that we should NOT copy

- **The AI paints the product.** In a scene swap the model re-renders the
  jewelry itself — stone counts, prong shapes, and engraving can silently
  drift between the input photo and the output. For e-commerce that is a
  product-misrepresentation liability; for manufacturing it is disqualifying.
  Our constitution (dimensional truth, seed-locked geometry fingerprint) is
  the direct answer. This is a difference to *advertise*, not close.
- **Photo-first means production-blind.** No dimensions, no versioning, no
  vocabulary, no factory artifact anywhere in the product. Their history tab
  is a scroll of images; our versions are contracts.
- **Community gallery.** Wrong audience for us — a designer's unsold concept
  is a trade secret, not content.

## 5. The wedge

**RocoAI competes for the marketing dollar after a piece exists. Nobody is
competing for the moment of creation.** Their entire suite operates on
photographs, which means the piece has already been designed, made, and shot.
Facetta operates on the spec — before the piece exists — and the marketing
image falls out of the same object that the factory sheet and the 3D model do.

Pitch form: *"RocoAI makes your photo prettier. Facetta makes the piece exist
— and the pretty photo is free."*

Three concrete edges they structurally cannot follow us into:

1. **Pre-production rendering.** A designer can show a client a photoreal
   render of a ring that has never been made, with carat/mm/fit already
   validated. RocoAI needs the finished piece under a camera first.
2. **Accountable imagery.** Same spec in, same piece out, every render. When
   the client says yes, the *identical* object goes to the factory as a
   dimensioned sheet + DXF. Their output can't survive a caliper.
3. **The edit loop.** "Make the halo stones 0.2 mm larger" is a new validated
   version with every artifact regenerated in sync. Their equivalent is
   re-prompting and hoping.

Risk, honestly assessed: could RocoAI move upstream into design-to-factory?
Their DNA is image-to-image; they own no vocabulary, no validation, no
manufacturing artifact, and their credit economy monetizes volume of images,
not correctness of specs. The realistic risk is different: **designers who
only want marketing images will pick RocoAI**, and we should not fight for
that user on image quality alone — foundation models are a commodity both
sides rent. We win the user whose image must agree with a factory sheet.

## 6. Adoption list (concrete, ordered, respecting the build order)

Things RocoAI does well that translate directly, none of which violate the
constitution:

1. **Scene presets as data** — `data/scene_presets.json`: named presets
   (name, category, thumbnail, mockup-engine scene params). Same pattern as
   the gemology vocabulary: extend via data, not code. The app's scene
   compiler UI becomes thumbnail cards under category tabs instead of raw
   dropdowns. Their poetic naming (e.g. "cream stone", "wood-shadow
   negative-space") is worth imitating — the co-founder should name ours.
2. **Auto-scene from spec** — deterministic mapping from spec attributes to a
   default preset (ruby → dark moody slate; pearl → soft cream linen; red
   themes for CN-market pieces). We *know* the stone, metal, and mood from the
   spec — no pixel inference needed. This out-executes their headline feature.
3. **Quality tiers on renders** — fast-preview vs final flags on
   `/specs/render.png`, mapped to model/step settings and the existing cache.
4. **Render history in the app** — surface the render cache per design
   version (the immutable-version analog of their 历史记录 tab).
5. **Watermark toggle on share links** — protects unsold concepts in
   client-facing renders; trivially deterministic (SVG/raster overlay in our
   own code, not AI).
6. **"Full dossier" one-click** — one endpoint returning technical sheet +
   blueprint + client render (+ try-on when ready) for a version. Their
   智能全案 bundling instinct, but ours is consistent-by-construction.
7. **Cost surfacing** — when fal.ai billing lands, show the cost/credit price
   on the generate action, their way. Later concern.

Explicitly deferred: upscale/retouch (buy, don't build), AI video (post-MVP),
community gallery (wrong audience), any feature where the AI would repaint
geometry (unconstitutional).
