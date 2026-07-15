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
canonical API-runner key, assignment-reviewer key, GIA key, founder key,
independent-designer key, staging-reviewer key, or seven-role authority bundle.
All 1,044 quality rows are unresolved, so the executable provider budget is
zero and release status is `not_run`.

## Retained run-directory safety

Preassign a fresh opaque `CORPUS_RUN_ID` in the release ticket before capture.
It must exactly equal the `corpus_run_id` in the reviewed assignment bundle,
capture, and replay. The staging and combined-release operators likewise
preassign fresh `STAGING_RUN_ID` and `EXTERNAL_RELEASE_RUN_ID` values before
their commands run. None of these identifiers may be generated after execution
starts.

Provision only parent directories ahead of time. Create each leaf run directory
with plain `mkdir`, never `mkdir -p`, so a repeated identifier or stale directory
fails immediately. Enable shell noclobber with `set -C` before every redirect
that retains command output or an exit code. A retry receives a new run ID and a
new directory; it never deletes, empties, or reuses the earlier evidence.
Artifacts are installed atomically one file at a time, so an interrupted batch
may leave an incomplete directory. It is not valid evidence and must never be
resumed; only the complete artifact set plus its retained zero exit code passes.

## 1. Validate and resolve before provider work

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-definition

PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out /secure/path/to/evidence-root/provider-call-plan.json plan
```

The 3,132-attempt number is only the logical maximum at three attempts per
sequence. It is not an executable budget. Independently review and hash-pin a
source-specific assignment/applicability bundle first. The human reviewer does
not author executable prompts or `resolved_inputs_sha256`; the provider-free
compiler derives those values from the frozen workload, validated source spec,
raster-bound component map, and retained review/region evidence. Every edit row
must end as `execute` or reviewed `not_applicable`. Render coverage is mandatory.
Reviewer IDs are opaque `rvr_` tokens followed by 64 lowercase hex characters;
N/A evidence uses versioned reason/detail codes and contains no free prose.
`source_component_absent` is available only when every required semantic kind
is unresolved under a repository-pinned mapper contract whose retained
calibration covers at least 144 sources with zero false-absence results. It
also requires a separately enrolled Ed25519 mapper key in
`component_mapper_public_key` and a signed, retained
`facetta-frozen-component-map-attestation.v1` for the exact map. The
attestation binds the source SHA-256, canonical component-map SHA-256, mapper
contract, calibration-evidence SHA-256, frozen corpus run ID, and an opaque
`maprun_` token. Unsigned, forged, cross-run, or mismatched attestations fail
before the row can become N/A. The canonical component map and its exact signed
attestation are embedded in the signed assignment binding; installation and
planning independently reverify its mapper signature, pinned mapper contract,
calibration digest, corpus run, component-map hash, and workload source hash.
Planning also rejects the N/A claim if any semantic kind required by that edit
is resolved in the embedded map. The mapper key must not reuse the
assignment reviewer's key ID or public-key bytes; its private key stays outside
both the repository and retained evidence. The production config intentionally
leaves this enrollment `null` until a real mapper authority is enrolled, so
component-absence N/A claims currently fail closed.
`canonical_delta_inapplicable` embeds the source hash, canonical source spec,
and deterministic edit issues. Installation recomputes the named canonical
edit and accepts N/A only when it still produces no target and the exact same
non-empty issue set. Unknown reason strings and every render N/A fail at the
signed-contract boundary. Without those proofs the row must remain unresolved
and provider work stays blocked.

After the assignment reviewer is enrolled in the config, create the locked
blank workbook inside a fresh retained-evidence directory. The reviewer works
on a separate private working copy outside both the repository and retained
evidence root, completes only the exposed review fields and evidence
references, and never alters frozen bindings or row identities. The completed
working file is hash-verified, canonically parsed, and atomically submitted as
a new retained artifact; it is never copied into evidence with a general file
copy command.

```bash
set +x
umask 077
EVIDENCE_ROOT=/secure/path/to/evidence-root
CORPUS_RUN_ID=<preassigned-opaque-run-id>
REVIEW_WORK_ROOT=/separate/private/reviewer-working-directory
COMPLETED_WORKBOOK="$REVIEW_WORK_ROOT/completed-workbook.json"

PYTHONPATH=src .venv/bin/python scripts/author_frozen_assignment_bundle.py \
  template \
  --evidence-root "$EVIDENCE_ROOT" \
  --corpus-run-id "$CORPUS_RUN_ID" \
  --out assignment-review/blank-workbook.json

# Copy the trusted blank workbook OUT to the private working directory. The
# reviewer edits only the working copy and uses Save As for the completed file.
# Never edit blank-workbook.json or any retained artifact in place.
test ! -e "$COMPLETED_WORKBOOK"
cp "$EVIDENCE_ROOT/assignment-review/blank-workbook.json" \
  "$COMPLETED_WORKBOOK"

# After human completion, calculate the hash from the closed working file and
# use the provider-free submit command. Submit reads the file once, verifies
# that exact hash, parses one JSON object, renders canonical JSON, and creates
# the retained destination atomically without replacement.
COMPLETED_SHA256=$(shasum -a 256 "$COMPLETED_WORKBOOK" | awk '{print $1}')
PYTHONPATH=src .venv/bin/python scripts/author_frozen_assignment_bundle.py \
  submit \
  --evidence-root "$EVIDENCE_ROOT" \
  --completed-input "$COMPLETED_WORKBOOK" \
  --expected-sha256 "$COMPLETED_SHA256" \
  --out assignment-review/completed-workbook.json

# Validate the newly submitted retained workbook:
PYTHONPATH=src .venv/bin/python scripts/author_frozen_assignment_bundle.py \
  validate \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir founder-reference-directory \
  --template assignment-review/completed-workbook.json \
  --out assignment-review/provider-free-validation.json
```

Before capture, enroll seven independent authorities—executor, canonical API
runner, frozen-assignment reviewer, GIA reviewer, founder, jewelry designer,
and staging reviewer—and pin a
`facetta-release-authority-bundle-config.v2`. The assignment reviewer must hold
the `frozen_assignment_reviewer` qualification and use the exact operational
key configured as `assignment_reviewer_public_key`. Each role needs
proof-of-key control, separately verified qualification, an active signed
status entry, and unique key material. Private keys remain outside the
repository and evidence root. Enrollment artifacts use opaque identifiers and
exclude raw personal or credential data.

Once the active seven-role authority bundle is installed, finalize with the
assignment reviewer's Ed25519 private key kept outside both the repository and
evidence root. Finalization reopens and re-hashes every compiled evidence file
immediately before signing, writes the bundle, validation, and pin proposal as
one fresh atomic batch, and still makes zero provider calls.

```bash
PYTHONPATH=src .venv/bin/python scripts/author_frozen_assignment_bundle.py \
  finalize \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir founder-reference-directory \
  --template assignment-review/completed-workbook.json \
  --private-key /separate/secret/path/assignment-reviewer.key \
  --decision-time <explicit-ISO-8601-UTC-time> \
  --bundle-out assignment-review/signed-assignment-bundle.json \
  --validation-out assignment-review/final-validation.json \
  --pin-out assignment-review/pin-proposal.json
```

The finalization pin proposal identifies the retained source artifact and its
exact file SHA-256, but deliberately does **not** emit a planner pin: the
planner resolves frozen-component paths relative to the repository, while the
signed source still lives in external retained evidence. Review the proposal,
then use the provider-free `install` command to verify the exact source hash,
canonical JSON encoding, reviewer signature, and authority binding before an
atomic no-clobber copy into the config-adjacent repository
`assignment-bundles` directory. Do not manually copy the signed bundle.

```bash
PIN_PROPOSAL="$EVIDENCE_ROOT/assignment-review/pin-proposal.json"
BUNDLE_SHA256=$(PYTHONPATH=src .venv/bin/python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["source_file_sha256"])' \
  "$PIN_PROPOSAL")
INSTALL_DIR=docs/evals/frozen-founder-corpus-v1/assignment-bundles
test -d "$INSTALL_DIR" || mkdir "$INSTALL_DIR"
INSTALL_PATH="$INSTALL_DIR/$CORPUS_RUN_ID.json"
test ! -e "$INSTALL_PATH"

PYTHONPATH=src .venv/bin/python scripts/author_frozen_assignment_bundle.py \
  install \
  --evidence-root "$EVIDENCE_ROOT" \
  --bundle assignment-review/signed-assignment-bundle.json \
  --expected-sha256 "$BUNDLE_SHA256" \
  --out "$INSTALL_PATH"
```

Only the install command emits the planner-installable, repository-relative
`resolved_assignment_bundle_pin` in exact
`repository/path.json@sha256:installed_file_sha256` form. Independently review
that output and set it as `frozen_components.resolved_assignment_bundle` in
`config.json`; the installer never edits config. Then rerun both definition
validation and a fresh provider-free plan into a new retained path:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-definition

POST_INSTALL_PLAN="$EVIDENCE_ROOT/provider-plans/$CORPUS_RUN_ID.json"
test -d "$EVIDENCE_ROOT/provider-plans"
test ! -e "$POST_INSTALL_PLAN"
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out "$POST_INSTALL_PLAN" plan
```

Until the explicit config change and successful post-install validation, the
production plan remains unresolved with a zero provider budget. Submission,
validation, finalization, installation, and planning make zero provider calls;
private keys and private reviewer working paths remain outside the repository
and retained evidence.

## 2. Produce and validate the signed capture

The fail-closed producer consumes an already hash-bound execution bundle and
canonical persistence observations. Its default adapter makes zero provider
calls; a secured deployment may replace the executor seam, but not its
preflight, attempt limit, artifact confinement, or signatures.

```bash
set +x
umask 077
EVIDENCE_ROOT=/secure/path/to/evidence-root
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_capture.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --execution-bundle "$EVIDENCE_ROOT/execution-bundle.json" \
  --persistence-observations "$EVIDENCE_ROOT/persistence-observations.json" \
  --output-dir "$EVIDENCE_ROOT/signed-capture" \
  --executor-private-key /separate/secret/path/executor.key \
  --canonical-api-private-key /separate/secret/path/api-runner.key \
  --commit-sha <exact-40-or-64-character-commit-sha> \
  --attestation-id <operator-issued-attestation-id>

CAPTURE_PATH="$EVIDENCE_ROOT/signed-capture/capture.json"
REPLAY_PATH="$EVIDENCE_ROOT/signed-facetta-frozen-replay.v2.json"
test -f "$CAPTURE_PATH"

PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-capture \
  --capture "$CAPTURE_PATH" \
  --capture-public-key "$EVIDENCE_ROOT/keys/executor.pub" \
  --capture-key-id secured-executor-v1

PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --packet-format replay-v1 \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --capture "$CAPTURE_PATH" \
  --capture-public-key "$EVIDENCE_ROOT/keys/executor.pub" \
  --capture-key-id secured-executor-v1 \
  --out "$REPLAY_PATH"
```

`facetta-frozen-capture.v3` binds the exact plan, run ID, manifest, config,
workload, assignments, resolved inputs, all source/candidate/mask hashes, one
retained evaluator report for every candidate-producing attempt, and a
separately signed canonical-persistence attestation. Capture validation and
release replay both recompute scores, QA outcomes, acceptance, edit fidelity,
and hard-gate decisions from the retained observations. Every sequence has one
to three attempts; an accepted attempt must be final; exhausted sequences are
retained with zero accepted attempts. Output is staged atomically and every
reference is root-relative and hash indexed.

Passing capture validation proves provenance, completeness, and deterministic
agreement between retained evaluator observations and their machine
projections. The reports are executor-attested observations, not independent
provider receipts; capture validation does not prove human acceptance.

## 3. Prepare blind human-review packets

Legacy `replay-v1` packets are rejected. The `replay-v2` packet remains machine
evidence and cannot authorize release through Boolean review data. External
human authority requires `blind-v2`.

Use separately controlled 32-byte seeds, represented as 64 lowercase hex
characters, for the two roles:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --packet-format blind-v2 \
  --review-seed <64-lowercase-hex-characters> \
  --reviewer-role gia_visual_fidelity_reviewer \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --capture "$CAPTURE_PATH" \
  --capture-public-key "$EVIDENCE_ROOT/keys/executor.pub" \
  --capture-key-id secured-executor-v1 \
  --out /secure/path/to/evidence-root/review/gia-packet.json

PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --packet-format blind-v2 \
  --review-seed <different-64-lowercase-hex-characters> \
  --reviewer-role independent_jewelry_designer \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --capture "$CAPTURE_PATH" \
  --capture-public-key "$EVIDENCE_ROOT/keys/executor.pub" \
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
set +x
umask 077
EVIDENCE_ROOT=/secure/path/to/evidence-root
CORPUS_RUN_ID="${CORPUS_RUN_ID:?preassign a fresh corpus run ID}"
CORPUS_RUN_ROOT="$EVIDENCE_ROOT/gate-artifacts/frozen-founder-corpus-v1"
CORPUS_DIR="$CORPUS_RUN_ROOT/$CORPUS_RUN_ID"
test -d "$CORPUS_RUN_ROOT"
mkdir "$CORPUS_DIR" || exit 1
set -C

set +e
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v2.json" \
  --gia-review-packet "$EVIDENCE_ROOT/review/gia-packet.json" \
  --gia-review-ledger "$EVIDENCE_ROOT/review/signed-gia-ledger.json" \
  --outdir "$CORPUS_DIR" > "$CORPUS_DIR/command-result.json"
GATE_EXIT=$?
set -e
printf '%s\n' "$GATE_EXIT" > "$CORPUS_DIR/exit-code.txt" || exit 1
test "$GATE_EXIT" -eq 0

set +e
PYTHONPATH=src .venv/bin/python scripts/verify_frozen_corpus_release.py \
  --results "$CORPUS_DIR/results.json" \
  --approval "$EVIDENCE_ROOT/review/signed-founder-approval.json" \
  --manifest docs/evals/frozen-founder-corpus-v1/manifest.json \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v2.json" \
  --evidence-root "$EVIDENCE_ROOT" \
  --workload docs/evals/frozen-founder-corpus-v1/workload.json \
  --gia-review-packet "$EVIDENCE_ROOT/review/gia-packet.json" \
  --gia-review-ledger "$EVIDENCE_ROOT/review/signed-gia-ledger.json" \
  --outdir "$CORPUS_DIR" > "$CORPUS_DIR/final-command-result.json"
FINAL_EXIT=$?
set -e
printf '%s\n' "$FINAL_EXIT" > "$CORPUS_DIR/final-exit-code.txt" || exit 1
test "$FINAL_EXIT" -eq 0
```

The founder approval signs the exact `results.json` bytes. The finalizer also
requires the raw manifest, source directory, replay, evidence root, workload,
and GIA packet/ledger. It reruns the provider-free compiler and requires the
fresh result to byte-match the retained result. A stale result, missing raw
artifact, or v1 Boolean human review fails closed.

The completed corpus decision may set `corpus_gate_ready: true`; it cannot set
`external_beta_ready`. The independent-designer ledger, live staging v4
evidence, staging signature, and complete seven-role authority bundle remain
separate requirements of `scripts/verify_external_beta_release.py`. See
`docs/STUDIO_EXTERNAL_BETA_GATES.md` for the exact combined command.

That combined command must use a separately preassigned fresh
`EXTERNAL_RELEASE_RUN_ID`, create
`$EVIDENCE_ROOT/gate-artifacts/external-beta/$EXTERNAL_RELEASE_RUN_ID` with
plain `mkdir`, enable `set -C` before retained redirects, and write its decision,
command result, and exit code only inside that new directory.

## Fail-closed summary

The offline replay recalculates artifact hashes and outside-mask drift from
captured pixels. Coverage comes from verified attempts, not summary claims.
Missing/extra assignments, non-ring quality rows, operation drift,
non-contiguous attempts, unsafe paths, non-finite scores, unusable masks,
failed GIA criteria, rejected-candidate persistence, stale writes, profile/key
mismatch, unsigned evidence, or changed configuration all fail. No verifier in
this directory calls an image provider.
