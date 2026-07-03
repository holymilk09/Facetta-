# Reference datasets

Research-sourced tables in clean CSV form — open directly in Excel/Sheets.
These are the canonical copies; the parts the system enforces are mirrored
additively into `data/gemology_vocabulary.json` (culet scale, girdle detail,
girdle weight corrections, ring size conversions, manufacturing tolerances)
and `data/facet_diagrams/` (tier angles for pear, marquise, trillion,
radiant). Facetta's own shape factors were cross-checked against
`weight_formulas.csv` and agree within ~5%; ours remain the source of truth
because they keep specific gravity as a separate, species-correct term.
