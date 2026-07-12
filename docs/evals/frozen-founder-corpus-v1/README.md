# Frozen founder corpus v1

This is a provider-free release-gate definition, not a quality result.

- `manifest.json` pins the exact 144 founder-supplied source hashes and declares
  the 58-reference advisory ring slice plus the canonical ring render/edit
  workload.
- `config.json` pins the current 90/85/90 gate, three-attempt limit, calibrated
  `0.18` outside-mask drift threshold, routing contract, and implementation
  hashes.
- Neither file contains generated candidates, visual scores, designer
  acceptance, or factory authority.

Run the integrity-only gate with:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --source-dir /path/to/founder-reference-directory \
  --outdir /tmp/facetta-frozen-corpus-gate
```

The command intentionally exits nonzero with image quality `not_run` until
`--evidence` points to a complete `facetta-frozen-replay.v1` JSON capture. A
replay pins the manifest/config hashes and contains:

- at least one artifact-verified attempt for every one of the 144 manifest
  sources, plus a signed filename/hash-bound coverage row whose evaluation IDs
  exactly match the attempts the gate observed for that source;
- one or more attempts for every declared render and edit evaluation;
- hash-bound source and candidate artifacts for every attempt, plus a
  hash-bound mask for every edit attempt;
- captured render conformance and edit-fidelity results;
- named canonical API persistence evidence, including the count of rejected
  candidates that became active assets;
- completed GIA-trained false-positive/false-negative review.

Scores, persistence assertions, source coverage, artifact declarations, and
review assertions are one canonical JSON payload signed with Ed25519. The
reviewer public-key file is configured outside the evidence and its SHA-256 is
pinned in `config.json`. The production key is intentionally unconfigured
until the reviewer enrollment step is complete; no key or unsigned evidence
can become release-ready.

The offline replay verifies artifact hashes and recalculates outside-mask drift
from the captured pixels. Coverage counts come from verified attempts, never
from signed summary claims alone. Absent source coverage, unsigned or tampered
evidence, missing captures, changed configuration, more than three attempts,
failed metrics, rejected-candidate persistence, or missing review all fail
closed.
