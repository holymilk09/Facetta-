# Canonical line-art then color live evaluation

Source: the clean product render derived from founder-supplied `image-86.jpg`.

The line-art stage passed Grok QA and was stored only after an automated test
actor exercised the explicit confirmation endpoint. That confirmation proves
workflow mechanics, not founder/designer visual approval.

Visual inspection then found a failure the first color QA missed: the sparse
confirmed spec had no side-stone groups, so the colored candidate kept the leaf
geometry but turned its white diamond/pavé stones into gold. The file
`colored-line-art.png` is retained as the rejected counterexample.

`material-guard-result.json` proves the corrected behavior. The deterministic
source-vs-candidate raster gate measured widespread white-stone-to-gold
conversion and returned `422 approved_source_material_identity_failed`; the
candidate was not persisted as a current project artifact. Two focused Grok
material audits remain as a secondary guard when deterministic drift is not
already conclusive.
