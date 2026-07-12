# Trusted ring evaluation — designer-halo-count-atomic-inventory-live-v3-2026-07-12

## Scope

Focused live diagnostic of one designer request: reduce an emerald ring's
19-stone halo to exactly 18 while freezing the center stone, setting, band,
metal, camera, lighting, and background. The source is the operator-reviewed
`emerald-halo-rose-4-exact.png` image with SHA-256
`68cb3b2be9888d30b6e0542a8bd413374f9d6f08a2d4db764058b844231bb4ec`.
This source override makes the run diagnostic-only; it is not a release gate.

## Result

The requested edit is not reliable under the current three-attempt policy.

- Grok attempt 1 failed: the blind audit counted 20 side stones, not 18.
- Grok attempt 2 failed: the blind audit again counted 20 and also found the
  wrong visible center-prong count.
- OpenAI fallback remained a warning candidate because neither independent
  count could prove the complete target inventory. The harness comparison
  found no credible visible count change, so it was not eligible for designer
  promotion and was not applied.
- No candidate became a project asset.

The primary and blind vision readers disagreed materially across attempts.
That disagreement is evidence against acceptance, not evidence that one of the
readers must be right. Exact inventory edits now carry a structured 19-to-18
source/target contract, a separate blind count with count-completeness state,
and a hard failure when a complete blind count contradicts the target. An
unresolved exact count is capped below pass-level scoring and remains explicit
designer review only.

See `results.json` for prompts, routes, hashes, latency, corrective
instructions, and every QA check. The full release gates remain unevaluated.
