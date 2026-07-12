# Canonical Drawing Contract Matrix v1

This internal, provider-free contract test made **0 provider calls**, generated **0 images**, live-evaluated **0 images**, and classified **0 user sources**.

All fixture policy comes from `facetta.drawing_intake.build_drawing_processing_contract`. Fixture IDs and evidence signals are internal test data and never product labels or provider judgments.

## Result

- Fixtures: 6
- Passing contracts: 6
- All contracts pass: True
- Distinct render strategies: 1
- Uniform render strategy: `faithful_best_effort`
- Factory truth from provider output: prohibited

## Internal matrix

| Fixture | Render strategy | Dimension evidence | Signals | Visual attempt |
|---|---|---|---:|---|
| `phone-capture-visibility-loss` | `faithful_best_effort` | `absent` | 2 | required |
| `open-ideation-lines` | `faithful_best_effort` | `absent` | 2 | required |
| `single-visible-line-design` | `faithful_best_effort` | `absent` | 0 | required |
| `dimensioned-multi-view-source` | `faithful_best_effort` | `designer_supplied` | 1 | required |
| `line-and-color-intent-source` | `faithful_best_effort` | `reference_estimate` | 1 | required |
| `finished-piece-photo-reference` | `faithful_best_effort` | `unresolved` | 1 | required |

Every fixture passes the same four contract dimensions: fidelity, best-result usefulness, uncertainty capture, and factory-truth non-promotion. Evidence changes factory questions or dimension handling; it never changes or pre-blocks the visual attempt.

## Evidence boundary

The founder corpus contains 144 decodable inventoried files. One existing inventory entry anchors each fixture to an advisory taxonomy and hash. Neither the 144 files nor the six linked files were pixel-inspected or live-tested by this harness.

A pass proves canonical contract consistency only. It does not prove provider image quality, geometry fidelity, or factory readiness. Those remain separate live, designer-reviewed release gates.
