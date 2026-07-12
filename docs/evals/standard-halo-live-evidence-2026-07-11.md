# Standard halo live evidence — 2026-07-11

## Verdict

The standard-halo workflow is **not founder-acceptance ready**. Eleven staged
Grok runs and one GPT Image 2 comparison exercised source coverage, line
extraction, optional line coloring, line-to-beauty rendering, localized
masking, closed-loop correction, and provider-failure paths.
No run completed approval or produced a factory pack, and no failed or warning
candidate was promoted as the active visual revision.

The runs are useful because they exposed three distinct risks that a visually
attractive image can conceal:

- structural drift: wrong center-prong or halo-stone counts;
- source drift: invented band arms or geometry outside the selected view;
- presentation substitution: a photorealistic render returned where a colored
  technical drawing was requested.

## Run record

| Run | Stopped at | Evidence and disposition |
| --- | --- | --- |
| v1 | `line_art_review_required` | Early generic QA scored the line candidate highly. Manual review found synthesized geometry; the candidate stayed temporary and motivated the confirmed-line-art evaluator. |
| v2 | `color_review_required` | The model returned an attractive photorealistic ring instead of colored line art. It was not promoted; this became the colored-line-art regression case. |
| v3 | `color_failed` | The new colored-line-art gate rejected the cached substitution and a targeted retry. No configured FAL fallback was available. |
| v4 | `source_coverage_audit_failed` | A transient source-audit failure stopped the workflow before downstream work. |
| v5 | `beauty_render_failed` | Direct line-to-beauty rendering produced an attractive ring with four prongs where the validated spec required six. QA stopped it. |
| v6 | `line_art_failed` | Two xAI provider connection resets were followed by an unavailable FAL fallback because `FAL_KEY` is not configured. |
| v7 | `beauty_render_failed` | The beauty render disagreed with the validated halo inventory; it did not become a revision. |
| v8 | `line_art_failed` | Skeptical double-audit rejected line-art shape/count drift. |
| v9 | `line_art_failed` | A front-view attempt was rejected for count, shape, output-hygiene, and invented-motif failures. |
| v10 | `line_art_failed` | Server-side source cropping improved the retry to the exact six-prong/fourteen-halo inventory and removed output text, but the model invented horizontal band arms absent from the selected crop. Protected-region/source-geometry QA correctly rejected it. |
| v11 | `line_art_failed` | A tighter selected-visible-geometry contract rejected the first candidate for count, shape, and text drift. The second candidate could not be evaluated because the vision consistency audit timed out. |
| OpenAI v1 | `comparison_failed` | GPT Image 2 applied the emerald-cut center edit with exact zero outside-mask drift. Full-spec QA observed four prongs and 20 halo stones against a supplied six-prong/14-halo spec, exposing that the earlier source audit had validated paths without binding their exact visible values. The candidate remained temporary. |
| v12 | `line_art_failed` | The first exact-fact-aware source audit reported six prongs and 14 halo stones, but its retained output did not prove those counts originated in the blind pass. The run then continued farther than intended and line-art QA failed; no candidate was promoted. This motivated a strict audit-only mode and blind-evidence retention. |
| v13 | `source_coverage_audit_failed` | Audit-only mode made no image-generation or project calls. The mapping provider was unavailable after the blind pass; the stop exposed that partial blind evidence was not yet retained on provider failure. |
| v14 | `source_coverage_review_required` | Audit-only mode retained both raw passes. Blind inventory saw a halo of “multiple” stones and a pronged head but gave neither exact count. The spec-aware mapper therefore returned `inconclusive` for halo and setting, and the workflow stopped before image generation or project APIs. |

The detailed evidence remains in
`docs/evals/designer-standard-halo-full-e2e-live-v1-2026-07-11` through
`docs/evals/designer-standard-halo-full-e2e-live-v11-2026-07-11`.
The OpenAI record is in
`docs/evals/openai-center-cut-live-v1-2026-07-11`.
The stricter blind-evidence audit record is in
`docs/evals/designer-standard-halo-blind-evidence-audit-v14-2026-07-11`.

## What changed because of the evidence

- `ConfirmedLineArtQualityEvaluator` now requires one black-on-white view,
  exact visible prong and repeated-stone counts, source-geometry preservation,
  and no candidate-only caption, signature, watermark, social ID, logo, or
  branding.
- `ColoredLineArtQualityEvaluator` now requires retained linework, bounded
  specification color, technical-illustration presentation, and no
  photorealistic replacement.
- Line-art requests can carry a normalized server-side source rectangle and a
  human-readable region description. The image model and evaluator receive the
  isolated crop rather than the full multi-view plate.
- A confirmed `LINE_ART` or `COLORED_LINE_ART` asset can feed the canonical
  spec-render endpoint directly; the colored technical-illustration stage is
  optional rather than a forced lossy hop.
- New image imports must provide audited source-component coverage and stop
  atomically on unresolved, failed, unaudited, or stale components.
- Source-component evidence now binds the exact visual-spec hash and sends
  raster-assessable spec facts—not just path names—to the independent mapping
  pass. Missing or stale exact-spec evidence blocks image rendering and factory
  release; visible repeated-stone count contradictions are also rejected
  deterministically.
- Exact repeated-stone and prong counts cannot be upgraded to `pass` by the
  spec-aware second pass unless the blind first pass independently states an
  assessable count. Missing blind count evidence becomes `inconclusive`, not a
  guessed match. Successful and partial raw-pass evidence is retained without
  source bytes for evaluator-variance analysis.
- GPT Image 2 has a dedicated internal comparison adapter using native alpha
  masks, source-aspect output sizing, content-addressed caching, safe error
  mapping, and exact outside-mask patch compositing. It does not alter the
  default Grok-primary product route.

## Release blockers and next comparison

Do not spend more provider calls on this case until a designer confirms the
halo/prong counts or a clearer isolated source view proves them. The current
evidence is conflicting, so neither six/14 nor four/20 is manufacturing truth.
After resolving that uncertainty, the next
fair comparison should use a narrower center-only mask, the same isolated crop,
validated spec, frozen-fact contract, attempt limit, and QA evaluator across:

1. Grok primary attempt and one targeted Grok correction;
2. a reference-edit fallback such as FLUX Kontext once `FAL_KEY` is configured;
3. GPT Image 2 with the native masked-edit adapter;
4. one OpenArt whole-reference edit only where lack of a native region mask is
   an acceptable comparison constraint.

OpenAI and OpenArt remain internal comparisons, not visible provider choices.
No provider is allowed to change the validated specification, and warnings
still require explicit designer review.

Before these gates become blocking release criteria, the GIA-trained cofounder
must review evaluator false positives and false negatives. All dimensions,
carats, materials, counts, and ring sizes used in this live series are editable
test-designer estimates—not measurements or manufacturing authorization.
