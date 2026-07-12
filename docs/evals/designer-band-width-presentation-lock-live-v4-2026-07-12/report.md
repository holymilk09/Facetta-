# Trusted ring evaluation — designer-band-width-presentation-lock-live-v4-2026-07-12

Focused live diagnostic using the named, operator-reviewed source hash recorded
in `results.json`. This result set did not regenerate the source and is not
eligible for full release-gate calculation.

The canonical 3.2 mm to 3.8 mm lower-shank edit exhausted the configured policy:

1. Cached Grok candidate: rejected because camera/framing changed materially
   (`height_ratio=1.688`) even though the vision judges had called it a pass.
2. Corrected Grok candidate: rejected; framing improved but scale remained
   materially changed (`height_ratio=1.568`).
3. OpenAI medium-quality fallback: rejected; the lower-band silhouette moved in
   the requested direction, but framing still missed the lock and the six-prong
   setting became four prongs.

Final outcome: terminal quality failure. No candidate was written as a project
asset. The result proves the presentation-lock false-positive fix, not reliable
band-width editing.
