# Trusted ring evaluation — designer-band-width-auto-localized-live-v6-2026-07-12

Focused, non-release diagnostic using the named source hash in `results.json`.
The agent derived a conservative chromatic-center shank mask, recorded its
normalized evidence in the plan, and exercised Grok → corrected Grok → OpenAI
medium under the normal three-attempt policy.

Results:

1. Grok changed the overall presentation (`height_ratio=1.584`) despite the
   guide and failed the presentation lock.
2. Corrected Grok again re-framed the piece (`height_ratio=1.672`) and failed.
3. OpenAI's native-mask path held framing (`height_ratio=1.0`), preserved all
   six prongs and every major component, and had zero outside-mask drift. The
   measured median shank width increased only 6.5%, below the visible-change
   threshold, and both vision audits found vertical blending artifacts.

Final outcome: terminal quality failure and no project asset. This run proves
that native localization materially improves preservation, not that the band
edit is ready. Subsequent code changes replace the rectangular protected-box
cutout with a shape-following center-component mask, protect low-saturation
prongs, and feather only inward while keeping outside-mask pixels exact; those
changes are unit-tested but have not been claimed as a successful live result.
