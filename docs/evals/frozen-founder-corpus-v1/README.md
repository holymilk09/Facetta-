# Frozen founder corpus v1

This directory defines a provider-free release gate. It is **not** a quality
result and contains no release authority.

- `manifest.json` pins the exact 144 founder-supplied source hashes and marks
  the 58-reference advisory ring slice.
- `workload.json` binds all 144 sources to integrity scope and expands the 58
  ring sources into seven render and eleven edit evaluations: 1,044 logical
  sequences. The other 86 sources have an explicit null quality assignment.
- `config.json` pins the 90/85/90 thresholds, three-attempt ceiling, `0.18`
  outside-mask drift threshold, routing contract, workload, capture/replay,
  blind-review, authority-enrollment, release, and staging implementations.

The production config intentionally has no assignment bundle, executor key,
canonical API-runner key, GIA key, founder key, independent-designer key,
staging-reviewer key, or six-role authority bundle. All 1,044 quality rows are
unresolved, so the executable provider budget is zero and release status is
`not_run`.

## 1. Validate and resolve before provider work

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-definition

PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out /secure/path/to/evidence-root/provider-call-plan.json plan
```

The 3,132-attempt number is only the logical maximum at three attempts per
sequence. It is not an executable budget. Independently review and hash-pin a
source-specific assignment/applicability bundle first. Every row must declare
`execute` or `not_applicable`, concrete regions/references, a canonical
`resolved_inputs_sha256`, and the preassigned `corpus_run_id`.

Before capture, enroll six independent authorities—executor, canonical API
runner, GIA reviewer, founder, jewelry designer, and staging reviewer—and pin a
`facetta-release-authority-bundle-config.v1`. Each role needs proof-of-key
control, separately verified qualification, an active signed status entry, and
unique key material. Private keys remain outside the repository and evidence
root. Enrollment artifacts use opaque identifiers and exclude raw personal or
credential data.

## 2. Produce and validate the signed capture

The fail-closed producer consumes an already hash-bound execution bundle and
canonical persistence observations. Its default adapter makes zero provider
calls; a secured deployment may replace the executor seam, but not its
preflight, attempt limit, artifact confinement, or signatures.

```bash
set +x
umask 077
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_capture.py \
  --evidence-root /secure/path/to/evidence-root \
  --source-dir /secure/path/to/evidence-root/founder-reference-directory \
  --execution-bundle /secure/path/to/evidence-root/execution-bundle.json \
  --persistence-observations /secure/path/to/evidence-root/persistence-observations.json \
  --output-dir /secure/path/to/evidence-root/signed-capture \
  --executor-private-key /separate/secret/path/executor.key \
  --canonical-api-private-key /separate/secret/path/api-runner.key \
  --commit-sha <exact-40-or-64-character-commit-sha> \
  --attestation-id <operator-issued-attestation-id>

PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-capture \
  --capture /secure/path/to/evidence-root/frozen-capture.json \
  --capture-public-key /secure/path/to/evidence-root/keys/executor.pub \
  --capture-key-id secured-executor-v1
```

`facetta-frozen-capture.v2` binds the exact plan, run ID, manifest, config,
workload, assignments, resolved inputs, all source/candidate/mask hashes, and a
separately signed canonical-persistence attestation. Every sequence has one to
three attempts; an accepted attempt must be final; exhausted sequences are
retained with zero accepted attempts. Output is staged atomically and every
reference is root-relative and hash indexed.

Passing capture validation proves provenance and completeness only. It does
not prove image quality or human acceptance.

## 3. Prepare blind human-review packets

The compatibility `replay-v1` packet remains available for machine replay,
but its scores and Boolean review data can never authorize release. External
human authority requires `blind-v2`.

Use separately controlled 32-byte seeds, represented as 64 lowercase hex
characters, for the two roles:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --packet-format blind-v2 \
  --review-seed <64-lowercase-hex-characters> \
  --reviewer-role gia_visual_fidelity_reviewer \
  --evidence-root /secure/path/to/evidence-root \
  --source-dir /secure/path/to/evidence-root/founder-reference-directory \
  --capture /secure/path/to/evidence-root/frozen-capture.json \
  --capture-public-key /secure/path/to/evidence-root/keys/executor.pub \
  --capture-key-id secured-executor-v1 \
  --out /secure/path/to/evidence-root/review/gia-packet.json

PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --packet-format blind-v2 \
  --review-seed <different-64-lowercase-hex-characters> \
  --reviewer-role independent_jewelry_designer \
  --evidence-root /secure/path/to/evidence-root \
  --source-dir /secure/path/to/evidence-root/founder-reference-directory \
  --capture /secure/path/to/evidence-root/frozen-capture.json \
  --capture-public-key /secure/path/to/evidence-root/keys/executor.pub \
  --capture-key-id secured-executor-v1 \
  --out /secure/path/to/evidence-root/review/designer-packet.json
```

Blind packets use opaque HMAC-randomized item IDs and role-specific jewelry
rubrics. They omit provider/model identity, prompts, scores, machine verdicts,
retry counts, other reviewers' decisions, and release state. Signed
`facetta-blind-jewelry-review-ledger.v2` artifacts contain criterion-level
answers and rationale, bind the packet canonical hash and exact evidence, and
identify the enrolled key and privacy-safe reviewer-profile hash. The verifier
derives acceptance from required criteria; an asserted approval is ignored.

The GIA ledger covers visual fidelity for all selected review items. The
independent designer ledger is separately validated, and the combined release
controller derives the quick-appearance acceptance rate from the exact
validator-selected subset. At least 90% must pass within three machine
attempts.

## 4. Compile and finalize the corpus gate

```bash
EVIDENCE_ROOT=/secure/path/to/evidence-root
CORPUS_DIR="$EVIDENCE_ROOT/gate-artifacts/frozen-founder-corpus-v1"

PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v1.json" \
  --gia-review-packet "$EVIDENCE_ROOT/review/gia-packet.json" \
  --gia-review-ledger "$EVIDENCE_ROOT/review/signed-gia-ledger.json" \
  --outdir "$CORPUS_DIR"

PYTHONPATH=src .venv/bin/python scripts/verify_frozen_corpus_release.py \
  --results "$CORPUS_DIR/results.json" \
  --approval "$EVIDENCE_ROOT/review/signed-founder-approval.json" \
  --manifest docs/evals/frozen-founder-corpus-v1/manifest.json \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v1.json" \
  --evidence-root "$EVIDENCE_ROOT" \
  --workload docs/evals/frozen-founder-corpus-v1/workload.json \
  --gia-review-packet "$EVIDENCE_ROOT/review/gia-packet.json" \
  --gia-review-ledger "$EVIDENCE_ROOT/review/signed-gia-ledger.json" \
  --outdir "$CORPUS_DIR"
```

The founder approval signs the exact `results.json` bytes. The finalizer also
requires the raw manifest, source directory, replay, evidence root, workload,
and GIA packet/ledger. It reruns the provider-free compiler and requires the
fresh result to byte-match the retained result. A stale result, missing raw
artifact, or v1 Boolean human review fails closed.

The completed corpus decision may set `corpus_gate_ready: true`; it cannot set
`external_beta_ready`. The independent-designer ledger, live staging v4
evidence, staging signature, and complete six-role authority bundle remain
separate requirements of `scripts/verify_external_beta_release.py`. See
`docs/STUDIO_EXTERNAL_BETA_GATES.md` for the exact combined command.

## Fail-closed summary

The offline replay recalculates artifact hashes and outside-mask drift from
captured pixels. Coverage comes from verified attempts, not summary claims.
Missing/extra assignments, non-ring quality rows, operation drift,
non-contiguous attempts, unsafe paths, non-finite scores, unusable masks,
failed GIA criteria, rejected-candidate persistence, stale writes, profile/key
mismatch, unsigned evidence, or changed configuration all fail. No verifier in
this directory calls an image provider.
