# Designer product-photo live evaluation

Source: founder-supplied `image-86.jpg`, a multi-view emerald leaf-ring design
plate.

- `accepted-product-photo.png` records the first live run. Grok QA returned
  pass, but visual inspection exposed Facetta's generic design-preview caption
  on delivery. That finding produced the dedicated clean `PRODUCT_PHOTO`
  capability; this file is retained as regression evidence, not a current
  product export.
- `warning-product-photo.png` is the current clean candidate. The second Grok
  QA read correctly returned `warn` because the source can be read as two-tone
  while the confirmed draft spec says yellow gold. It remains temporary and
  was not promoted by the test runner.
- `result.json` is the current structured run evidence, including the exact QA
  checks, attempt metadata, and provider readiness.

The variance between the two vision judgments is itself important evidence:
minor material ambiguity stays a designer-review decision. Major geometry or
component drift remains a hard rejection.
