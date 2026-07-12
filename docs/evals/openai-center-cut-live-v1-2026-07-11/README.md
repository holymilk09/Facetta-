# GPT Image 2 masked center-cut comparison — 2026-07-11

## Disposition

This one-attempt, low-quality comparison is **rejected evaluation evidence**.
It created no Project, Design, DesignVersion, or ImageAsset and carries no
designer, founder, factory, or GIA-cofounder approval.

The provider successfully changed the oval blue center to an emerald-cut blue
center. Facetta's native-alpha-mask adapter then composited only the approved
patch over the immutable 594 x 547 source crop, producing exactly `0.0`
outside-mask drift. The request completed in 54,755 ms and reported 2,179
input tokens plus 160 output tokens.

Facetta still rejected the candidate. Independent target-spec QA observed four
center prongs and 20 halo stones, while the supplied evaluation spec claimed
six prongs and 14 halo stones. The candidate scored 95 before those hard-gate
failures; a high score never overrides a hard structural mismatch.

## What this proved

- GPT Image 2 is a credible reference-preserving localized-edit comparison
  route, especially with native masks plus Facetta's exact outside-mask
  compositing.
- The result cannot be used to claim OpenAI conformed to the full target spec.
  Later blind-first audit evidence could not independently count either the
  halo stones or center prongs, so those source facts remain review-required;
  the broad edit mask also included touching prongs and may have allowed
  structural change inside the authorized patch.
- The prior source-component audit proved path coverage but did not bind the
  exact visible facts behind those paths. That is now treated as a release
  blocker: new evidence records the exact visual-spec hash, and missing or
  stale bindings block rendering and factory handoff.
- No second paid attempt should run on this case until the visible halo and
  setting counts are designer-confirmed or proven from a clearer isolated
  source view, and the mask is narrowed to the center stone.

`results.json` is the canonical machine-readable record. `source-crop.jpg` and
`approved-edit-mask.png` preserve the exact comparison inputs. The rejected
candidate remains only in the temporary content-addressed render cache and is
not a product asset.
