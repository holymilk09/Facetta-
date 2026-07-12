# SVG → DXF transform and curve parity v1

Date: 2026-07-12

The previous regex converter recognized only untransformed `M/L/A/Z` paths.
That silently misplaced rotated station/leaf geometry and dropped quadratic or
cubic segments from leaf-shoulder and drop-earring sheets.

The replacement walks the XML tree, composes nested matrix/translate/scale/
rotate transforms, retains exact circles where the transform permits, and
samples quadratic, cubic, smooth, and rotated-arc segments into deterministic
R12 polylines. Rounded rectangle/link corners are likewise retained rather than
collapsed into sharp boxes. Unknown transforms or malformed paths fail instead
of returning a partially wrong exchange file.

| Template | DXF entities | Polyline vertices | SVG transforms | Path commands |
|---|---:|---:|---:|---|
| solitaire_prong | 160 | 310 | 0 | — |
| halo_prong | 194 | 374 | 0 | — |
| leaf_shoulder_prong | 1,556 | 10,738 | 66 | M/Q/Z |
| love_bangle | 75 | 185 | 8 | — |
| cuff | 77 | 143 | 5 | A/L/M/Z |
| link_bracelet | 82 | 688 | 22 | — |
| cluster_pendant | 257 | 935 | 0 | — |
| loose_stone | 137 | 375 | 0 | — |
| leaf_spray_brooch | 1,067 | 5,861 | 24 | — |
| deco_drop_earring | 117 | 467 | 0 | A/C/M/Q/Z |

Visual inspection compared the authoritative SVG against a reconstruction of
DXF edge/annotation entities for the leaf-shoulder ring and drop earring. The
rotated leaf topology, stone placements, ring profiles, marquise outline, pear
drop, hook, link run, and dimension witnesses aligned. SVG text and hatch fills
were intentionally excluded from the reconstruction preview; the DXF itself
still contains text entities.

DXF remains explicitly non-authoritative. R12 curve sampling is appropriate for
a 2D CAD underlay, but it is not solid geometry and does not encode production
tolerances, stone seats, wall construction, or a manufacturable 3D model.
