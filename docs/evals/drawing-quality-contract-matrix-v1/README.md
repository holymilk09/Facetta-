# Canonical Drawing Contract Matrix v1

This internal evaluation verifies six source-condition fixtures against the one
canonical drawing policy:

`facetta.drawing_intake.build_drawing_processing_contract`

The fixtures cover capture artifacts, unresolved ideation lines, a single
visible line design, a dimensioned multi-view source, line-and-color intent,
and a finished-piece photo reference. These are internal evidence scenarios,
not user-facing labels or drawing scores. No fixture name is sent to an image
provider.

Every fixture must compile `faithful_best_effort`, allow the visual attempt,
preserve supplied design evidence, avoid pre-render clarification, require
designer review, and keep provider output non-authoritative. Only concrete
internal evidence signals and dimension provenance may change. Those facts may
add factory-stage questions or change dimension handling, but they cannot alter
the visual strategy.

The deterministic evaluation dimensions are fidelity, best-result usefulness,
uncertainty capture, and factory-truth non-promotion.

Run it with:

```bash
PYTHONPATH=src uv run python scripts/run_drawing_quality_matrix.py
```

The runner reuses hashes and advisory classifications from the existing
144-image founder inventory. It does not inspect those pixels, generate an
image, call a provider, classify a user source, or score a drawing. A passing
result proves canonical contract consistency—not live image quality, geometry
fidelity, provider reliability, or factory readiness.
