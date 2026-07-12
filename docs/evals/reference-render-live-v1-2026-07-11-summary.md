# Reference-render live evaluation v1

Date: 2026-07-11

Scope: four founder-supplied source plates passed through the canonical
`REFERENCE_RENDER` operation with Grok-primary execution and comparative Grok
Vision QA. Every output remained a review candidate. No product asset, design
specification, approval, or factory record was created.

## Aggregate result

- Reviewable candidates: 4 / 4
- First-attempt source-fidelity result: 3 / 4
- Targeted corrective retry used: 1 / 4
- Fallback used: 0 / 4
- Selected-candidate mean QA score: 91.25
- Total provider + QA latency: 109.67 seconds
- Mean latency per returned candidate: 27.42 seconds
- Accepted as factory authority: 0 / 4

## Cases

| Case | Source | Result | Attempts | Selected QA | Human review |
|---|---|---:|---:|---:|---|
| Geometric emerald ring | `image-78.jpg` | Review required | 1 | 90 | Strong identity retention: octagonal step-cut center, segmented shoulder architecture, green side stones, diamond groups, and shank silhouette survived. Suitable for designer concept review, not component-count or dimensional proof. |
| Ribbon cushion ring | `image-67.jpg` | Review required | 2 | 88 | Attempt 1 failed source-identity/component gates. The evaluator-specific retry recovered the asymmetric ribbon structure and colored stone layout. Final image is attractive and recognizably faithful, but some ribbon crossings and shank curves are smoother/more regular than the source; it should not be promoted without designer inspection. |
| Emerald drop earrings | `image-32.jpg` | Review required | 1 | 92 | Strong front-view pair render. Preserved the diamond bar, square connector, emerald drop, articulation order, pair symmetry, and visible counts. The front view cannot prove the rear clip construction shown in the source. |
| Flower lariat hand source | `image-33.jpg` | Review required | 1 | 95 | Converted a paper/cord composition into a clean product image while preserving two five-petal terminals, green centers, white accent layout, and asymmetric open cord. Removed border, paper texture, signature, captions, and platform watermark. |

## Product conclusions

1. The neutral source policy works across rings, earrings, and a necklace-like
   lariat without exposing a rough/professional classification.
2. Targeted correction produced a material improvement on the hardest ribbon
   topology case; the retry was not a generic regeneration.
3. Source-to-beauty rendering is ready for an internal designer-selection UI,
   but the final ribbon case demonstrates why explicit review and immutable
   promotion boundaries remain necessary.
4. The next live tranche should contain genuinely incomplete or ambiguous user
   drawings, background packs, and isolated physical edits. A separate labeled
   synthetic low-information case now passes visible component/count fidelity,
   but one synthetic fixture does not prove performance on the diversity of
   real user sketches.

Raw evidence and candidates:

- `reference-render-geometric-emerald-live-v1-2026-07-11/`
- `reference-render-ribbon-cushion-live-v1-2026-07-11/`
- `reference-render-emerald-earrings-live-v1-2026-07-11/`
- `reference-render-flower-lariat-hand-source-live-v1-2026-07-11/`
- `reference-render-low-information-sketch-live-v1-2026-07-11/` (synthetic)
