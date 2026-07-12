# Live image-agent scorecard v1 — 2026-07-12

This is a curated diagnostic inventory of real provider evidence. It is not a
release-gate result: the runs were collected under different prompt/evaluator
versions, several are intentionally superseded by stricter re-audits, the
complete golden matrix has not run under one frozen configuration, and the
GIA-trained cofounder review is still outstanding.

## Measured strengths

| Designer operation | Best current live evidence | Current reading |
| --- | --- | --- |
| Center species/color | `designer-live-center-identity-2026-07-11` | Applied on the first attempt with no reported drift. |
| Background-only presentation | `trusted-ring-grok-only-v3-2026-07-11` | Applied on the first attempt while retaining the spec. |
| Add exact halo inventory | `designer-live-halo-add-crossaudit-2026-07-11` | Exact 12-stone halo passed the independent edit audit. |
| Remove complete halo | `designer-live-halo-remove-2026-07-11` | Applied on the first attempt; remains a single-case diagnostic. |
| Prompt-to-necklace concept | `creative-prompt-necklace-live-v5-2026-07-12` | First-attempt review candidate retained exact named stones/counts and complete-piece framing; no factory authority. |
| Professional drawing to beauty render | `professional-multiview-ring-region-render-live-v3-2026-07-12` | A source-topology failure was caught and converted into a targeted Grok retry; final candidate remains designer-review-only. |

## Weak or inconsistent operations

| Designer operation | Evidence | Finding |
| --- | --- | --- |
| Band width / shank geometry | `designer-band-width-presentation-lock-live-v4-2026-07-12` | All three attempts failed. Two Grok candidates changed framing/scale. OpenAI medium widened the silhouette more closely but changed the six-prong setting to four and still shifted framing. Terminal quality failure was correct. |
| Metal material identity | `designer-live-metal-material-crossaudit-2026-07-11` | Two Grok attempts failed the requested material/spec-domain checks; no accepted edit. |
| Exact halo count decrement | `designer-halo-count-atomic-inventory-live-v3-2026-07-12` | Current prompt/evaluator rerun failed safely. Two Grok attempts produced blind counts of 20 against the target 18; OpenAI could not prove the complete count and the harness found no credible visible decrement. No candidate was applied. |
| Center cut with frozen setting | `designer-live-center-shape-crossaudit-2026-07-11` | The edit itself can pass, but reference preparation exposed wrong metal/prong/component identity. Current source preparation and edit results must be scored separately. |
| Prong-setting change | `designer-live-prong-setting-2026-07-11` versus later blind/cross audits | Earlier apparent success is not sufficient evidence because blind counting later exposed expectation-biased prong judgments. Rerun required. |
| Repeated motif reshaping | `designer-live-leaf-motif-crossaudit-2026-07-11` | Warning rather than accepted result; exact repeated-shape preservation still needs designer review. |

## False-positive incident and correction

`designer-band-width-openai-fallback-live-v2-2026-07-12` was automatically
reported as a 100-fidelity, first-attempt band-width success. Direct visual
inspection showed a different camera angle, crop, ring scale, center-stone
presentation, and shank composition. The deterministic band evidence had
already measured `framing_stable=false`, `height_ratio=1.688`, and
`change_visible=false`, but the evaluator incorrectly allowed the vision pass
to override those facts.

The current evaluator makes deterministic silhouette evidence authoritative
for band geometry and adds a hard `band_edit_presentation_lock`. Replaying the
same source rejected the old candidate, produced targeted camera/framing
corrections, and rejected all three new attempts rather than persisting a
beautiful wrong edit. This improves trust, but it does not make band-width
editing reliable yet.

A later auto-localized diagnostic,
`designer-band-width-auto-localized-live-v6-2026-07-12`, improved the failure
mode: OpenAI held framing exactly, preserved six prongs/components, and changed
zero outside-mask pixels. It still failed because the visible width delta was
too small and the blend contained vertical artifacts. The automatic localizer
now declines ambiguous/colorless centers, protects detected low-saturation
setting components, and records its mask provenance/evidence. This is progress
on isolation, not a pass for band geometry.

The exact halo-count rerun exposed a second expectation-bias problem: one
vision reader could report the requested 18 while an expectation-free reader
counted 20 or 21. The current contract records complete versus occluded counts,
hard-fails a complete blind count that contradicts the target, and caps an
unresolved exact-count warning below pass-level scoring. This correction makes
the failure honest; exact count editing itself remains unreliable.

## Current competitive conclusion

Facetta's strongest wedge is not claiming that every image edit works. It is a
designer-controlled image loop that can produce strong candidates while
refusing silent structural drift and keeping factory facts separate from
pixels. The immediate reliability focus remains localized structural editing:
band geometry first, then setting/prong topology, exact stone inventory, and
material identity. Model/provider additions are useful only when they improve
these frozen-workload results.

## Release boundary

Do not calculate the stated 90/85/90 release gates from this heterogeneous
inventory. The next release-quality result must run the complete canonical set
under one frozen prompt/evaluator/routing version, include named canonical API
persistence evidence, record the configured fallback, and receive the
GIA-trained cofounder false-positive/false-negative review.
