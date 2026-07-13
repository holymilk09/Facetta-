# Frozen founder corpus v1

This is a provider-free release-gate definition, not a quality result.

- `manifest.json` pins the exact 144 founder-supplied source hashes and declares
  the 58-reference advisory ring slice plus the canonical ring render/edit
  workload.
- `workload.json` binds every manifest filename/hash to source-integrity scope
  and binds only the 58 advisory ring sources to the full ring quality matrix.
  The 86 non-ring sources have an explicit null quality assignment; their byte
  integrity cannot be misreported as jewelry-image quality.
- `config.json` pins the current 90/85/90 gate, three-attempt limit, calibrated
  `0.18` outside-mask drift threshold, routing contract, and implementation
  hashes.
- None of these definition files contains generated candidates, visual scores, designer
  acceptance, or factory authority.

Validate the frozen definition and produce its deterministic secured-executor
plan with zero provider calls:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-definition
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out /secure/path/to/provider-call-plan.json plan
```

The plan contains 1,044 logical evaluation sequences: each of the 58 ring
sources is explicitly paired with seven render cases and eleven supported edit
operations. At the frozen three-attempt cap, the secured executor must budget
for at most 3,132 provider attempts. This expansion is a workload declaration,
not proof that any call ran or passed.

The secured executor's `facetta-frozen-capture.v1` envelope must bind the exact
manifest, config, and workload hashes; every planned source/evaluation key;
relative candidate and edit-mask paths plus their hashes; and a hash-bound
canonical-persistence evidence reference. Validate its separate Ed25519
executor signature before preparing the human review packet:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-capture \
  --capture /secure/path/to/frozen-capture.json \
  --capture-public-key /secure/path/to/executor-public-key \
  --capture-key-id secured-executor-v1
```

Passing capture validation proves machine provenance and artifact completeness
only. It never substitutes for the signed GIA-trained review or founder
approval.

Run the integrity-only gate with:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --source-dir /path/to/founder-reference-directory \
  --outdir /tmp/facetta-frozen-corpus-gate
```

Validated machine captures should be converted to the review schema with
`scripts/prepare_frozen_corpus_review.py`. The packet builder hash-binds every
source, candidate, and edit mask and creates pending decision rows; it never
calls a provider, fills a human decision, or signs evidence. This removes
manual hash transcription while preserving the human review boundary.

The command intentionally exits nonzero with image quality `not_run` until
`--evidence` points to a complete `facetta-frozen-replay.v1` JSON capture. A
replay pins the manifest/config hashes and contains:

- byte/image integrity for every one of the 144 manifest sources, with
  provider-backed capture assignments governed separately by the pinned
  58-source ring workload matrix;
- one or more attempts for every declared render and edit evaluation;
- hash-bound source and candidate artifacts for every attempt, plus a
  hash-bound mask for every edit attempt;
- captured render conformance and edit-fidelity results;
- named canonical API persistence evidence, including the count of rejected
  candidates that became active assets;
- completed GIA-trained false-positive/false-negative review.

The currently pinned replay compiler predates `workload.json` and still asks
for artifact-verified quality coverage across all 144 sources. That conflicts
with the new explicit 58-source quality scope. Do not launch the secured
provider run or claim the corpus gate is runnable until the replay compiler and
review-packet builder consume this workload directly and their replacement
tests pass. Definition and plan validation intentionally leave
`corpus_gate_ready: false`.

The signed reviewer block contains one decision for every selected
`kind/evaluation_id/source_filename` result. The verifier derives confusion
counts from those decisions instead of trusting summary numbers. It also
evaluates the workload classes declared in the manifest: quick appearance
edits require at least 90% reviewer acceptance within the three-attempt cap;
structural edits must meet the frozen fidelity and outside-mask drift
thresholds. Missing, duplicate, or unclassified decisions fail closed.

Scores, persistence assertions, source coverage, artifact declarations, and
review assertions are one canonical JSON payload signed with Ed25519. The
reviewer public-key file is configured outside the evidence and its SHA-256 is
pinned in `config.json`. The production key is intentionally unconfigured
until the reviewer enrollment step is complete; no key or unsigned evidence
can become release-ready.

Founder approval is deliberately not folded into `results.json`: it must bind
the exact bytes the founder reviewed. After reviewer replay passes, enroll the
separate `founder_public_key`, create and sign a
`facetta-founder-approval.v1` record bound to the SHA-256 of `results.json`, and
run `scripts/verify_frozen_corpus_release.py`. Only its
`final-decision.json.corpus_gate_ready: true` satisfies the complete corpus
gate. It deliberately cannot claim full external-beta readiness because the
live two-principal staging-isolation gate is separate. The repository ships
with both production public keys unconfigured and contains no human sign-off.

The offline replay verifies artifact hashes and recalculates outside-mask drift
from the captured pixels. Coverage counts come from verified attempts, never
from signed summary claims alone. Absent source coverage, unsigned or tampered
evidence, missing captures, changed configuration, more than three attempts,
failed metrics, rejected-candidate persistence, or missing review all fail
closed.
