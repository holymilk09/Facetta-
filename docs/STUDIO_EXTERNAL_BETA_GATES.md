# Studio external beta gates

Only the two gates below remain external. Local unit, integration, export, and
mock-transport tests do **not** satisfy either gate.

| Gate | Current execution status | External-beta status |
|---|---|---|
| Signed frozen 144-image corpus, blind GIA/founder review, and blind designer acceptance | `not_run` | `unmet` |
| Live two-principal staging isolation | `not_run` | `unmet` |

Do not change either status from local test output. Retain every command exit
code, raw evidence artifact, signed decision, and generated JSON together.

## Shared release-authority prerequisite

Before capture, enroll six independently controlled roles: secured executor,
canonical API runner, GIA visual-fidelity reviewer, founder, independent
jewelry designer, and staging reviewer. The frozen config must contain a
strict `facetta-release-authority-bundle-config.v1` value that hash-pins, for
all six roles:

- a proof-of-possession enrollment artifact;
- a separately signed qualification artifact;
- the role public key and key ID;
- one fresh signed status list covering active, revoked, suspended, expired,
  and rotated state; and
- distinct qualification-verifier and status-signer public keys.

The combined decision checks all six roles at one UTC decision time. Missing,
expired, suspended, revoked, or stale records fail closed. Role/key reuse,
duplicate subjects, invalid qualification scope, status rollback, or
unacknowledged rotation also fail. Artifacts use opaque tokens and must not
contain names, email addresses, government identifiers, credential numbers,
or private keys. The public key and key ID used by each operational gate must
exactly match that role's enrolled key; an unrelated signer cannot borrow the
authority of a valid but unused enrollment. The production config deliberately
keeps `release_authority_bundle` and all release keys `null` until real external
enrollment is retained.

## Gate 1: signed frozen 144-image corpus

### Required inputs

- The source directory contains the exact 144 files and SHA-256 values pinned
  by `docs/evals/frozen-founder-corpus-v1/manifest.json`.
- `config.json` matches the manifest and every frozen implementation pin.
- The independently reviewed assignment bundle resolves the 1,044 logical
  ring-quality rows to source-specific `execute` or `not_applicable`
  assignments and preassigns one `corpus_run_id`. Unresolved rows make zero
  provider calls and cannot enter capture.
- A signed `facetta-frozen-capture.v2` binds the manifest, config, workload,
  assignments, source/candidate/mask hashes, selected result set, executor,
  canonical API persistence attestation, and exact run ID.
- A complete `facetta-frozen-replay.v1` supplies all raw machine evidence. It
  remains machine evidence, not human review authority.
- A separate GIA `facetta-blind-jewelry-review-packet.v2` and
  `facetta-blind-jewelry-review-ledger.v2` cover the exact selected artifacts.
  Replay-v1 Boolean review fields remain compatibility data and cannot pass
  this gate.

### Plan and validate the signed capture

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-definition

PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out /secure/path/to/evidence-root/provider-call-plan.json plan

PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-capture \
  --capture /secure/path/to/evidence-root/frozen-capture.json \
  --capture-public-key /secure/path/to/evidence-root/keys/executor.pub \
  --capture-key-id secured-executor-v1
```

The repository production definition reports 144 integrity sources, 58 ring
quality sources, 1,044 logical evaluation sequences, and zero execution-ready
rows until assignments and keys are enrolled. Planning and validation make
zero provider calls.

### Secured execution handoff

The repository does not contain a paid live executor. A separately secured
operator must resolve and pin every assignment, preassign the `corpus_run_id`,
enroll the executor authority, mount the verified source directory beneath the
evidence root, and enforce an account-level dollar budget before provider work.
The `3,132` maximum is an image-attempt ceiling, not a total request or dollar
ceiling. The operator must also review and pin one exact fallback contract;
the frozen routing label must not be used to infer a different live-runner
fallback silently.

After the secured executor produces the complete execution bundle and the
canonical API produces persistence observations, the local CLI revalidates and
signs them without calling an image provider:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_capture.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --execution-bundle "$EVIDENCE_ROOT/execution-bundle.json" \
  --persistence-observations "$EVIDENCE_ROOT/persistence-observations.json" \
  --output-dir "$EVIDENCE_ROOT/signed-capture" \
  --executor-private-key /separate/secret/path/executor.key \
  --canonical-api-private-key /separate/secret/path/api-runner.key \
  --commit-sha "$(git rev-parse HEAD)" \
  --attestation-id <operator-issued-attestation-id>
```

### Prepare the blind GIA packet

Generate a fresh secret 32-byte review seed outside the repository, record its
custody in the release ticket, and pass its lowercase 64-character hex form.
The packet uses it only to produce a reproducible HMAC order and opaque IDs.

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
```

The GIA packet exposes the review image triplet and role-specific rubric, but
not provider/model identity, prompt text, machine scores, machine acceptance,
retry count, another reviewer's verdict, or release status. The reviewer must
complete every required criterion; non-pass ratings require a rationale. The
signed ledger binds the packet's canonical SHA-256, exact criterion rows, reviewer
profile hash, key ID, and timezone-qualified completion time. The verifier
derives each item decision from those criteria; it ignores any asserted
top-level approval.

All sources, capture, public keys, replay, candidates, masks, packets, ledgers,
and gate outputs must be confined to the explicit evidence root. Absolute
references, traversal, symlink escape, omitted index entries, or hash drift
invalidate the run.

### Compile the corpus gate

```bash
set +x
umask 077
EVIDENCE_ROOT=/secure/path/to/evidence-root
CORPUS_DIR="$EVIDENCE_ROOT/gate-artifacts/frozen-founder-corpus-v1"
mkdir -p "$CORPUS_DIR"
set +e
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v1.json" \
  --gia-review-packet "$EVIDENCE_ROOT/review/gia-packet.json" \
  --gia-review-ledger "$EVIDENCE_ROOT/review/signed-gia-ledger.json" \
  --outdir "$CORPUS_DIR" > "$CORPUS_DIR/command-result.json"
GATE_EXIT=$?
set -e
printf '%s\n' "$GATE_EXIT" > "$CORPUS_DIR/exit-code.txt"
test "$GATE_EXIT" -eq 0
```

After the founder reviews `results.json`, they sign a
`facetta-founder-approval.v1` bound to its exact bytes. Finalization must
receive the raw evidence again; it reruns the provider-free corpus compiler
and requires the recomputed result to byte-match the retained result.

```bash
set +e
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
  --outdir "$CORPUS_DIR" > "$CORPUS_DIR/final-command-result.json"
FINAL_EXIT=$?
set -e
printf '%s\n' "$FINAL_EXIT" > "$CORPUS_DIR/final-exit-code.txt"
test "$FINAL_EXIT" -eq 0
```

### Corpus pass criteria

- Source integrity is `144/144`; the exact 58-source ring workload and 1,044
  logical rows are covered without missing or extra assignments.
- Every accepted attempt is the final attempt; every sequence has zero or one
  accepted attempt and uses no more than three attempts.
- Render hard-gate pass rate is at least `0.90`; mean render conformance is at
  least `85`; mean edit fidelity is at least `90`; outside-mask drift is at
  most `0.18`.
- Every edit has replayable source, candidate, and mask bytes. Component maps
  exist or explicitly fail closed as unmapped. Failed-QA candidates never
  become canonical assets.
- Every GIA criterion assignment validates and every selected item derives an
  accepted visual-fidelity decision. The quick and structural classes retain
  their frozen fidelity and drift requirements.
- The canonical persistence attestation proves atomic image/specification
  persistence, stale-write rejection, and zero rejected candidates becoming
  active assets.
- The fresh recomputation byte-matches retained `results.json`, founder
  approval binds those exact bytes, every signature verifies, and both
  commands exit `0`.

`final-decision.json.corpus_gate_ready: true` satisfies this gate only. It
cannot emit `external_beta_ready`.

## Gate 2: live two-principal staging isolation

Use two already-seeded, distinct Supabase principals. Each must own a different
canonical project, Design Family, and image asset in the deployed
production-filtered staging API. Recycle every API replica after seeding, then
run the probe read-only.

The secret manager must inject:

```text
FACETTA_STAGING_BASE_URL
FACETTA_STAGING_DEPLOYMENT_REVISION
FACETTA_STAGING_USER_A_ACCESS_TOKEN
FACETTA_STAGING_USER_A_PROJECT_ID
FACETTA_STAGING_USER_A_FAMILY_ID
FACETTA_STAGING_USER_A_ASSET_ID
FACETTA_STAGING_USER_B_ACCESS_TOKEN
FACETTA_STAGING_USER_B_PROJECT_ID
FACETTA_STAGING_USER_B_FAMILY_ID
FACETTA_STAGING_USER_B_ASSET_ID
```

The base URL must be an exact HTTPS origin. The live `/health` response must
report the same immutable deployment revision and the initialized PostgreSQL
persistence engine. The local SQLite fallback cannot pass.

```bash
set +x
umask 077
STAGING_DIR=/secure/path/to/gate-artifacts/staging-two-principal
mkdir -p "$STAGING_DIR"
set +e
.venv/bin/python scripts/run_staging_two_user_isolation.py \
  > "$STAGING_DIR/results.json"
STAGING_EXIT=$?
set -e
printf '%s\n' "$STAGING_EXIT" > "$STAGING_DIR/exit-code.txt"
test "$STAGING_EXIT" -eq 0
```

The owner reads must succeed, cross-owner reads and enumeration must fail with
the expected status, unauthenticated reads must return `401`, and every
legacy/admin/OpenAPI/docs surface in the probe must remain hidden. A separately
enrolled staging reviewer signs `facetta-staging-isolation-approval.v1` against
the exact result and exit-code bytes, origin, deployment revision, and fixture
set. Exit `77` (missing fixtures), `2` (invalid/unreachable), or `1` (failed
check) all leave this gate unmet.

## Blind independent-designer review

Create a second blind-v2 packet for the independent designer using a separately
controlled review seed:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --packet-format blind-v2 \
  --review-seed <different-64-lowercase-hex-characters> \
  --reviewer-role independent_jewelry_designer \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --capture "$EVIDENCE_ROOT/frozen-capture.json" \
  --capture-public-key "$EVIDENCE_ROOT/keys/executor.pub" \
  --capture-key-id secured-executor-v1 \
  --out "$EVIDENCE_ROOT/review/designer-packet.json"
```

The signed designer ledger is separate from the GIA ledger. The combined
verifier selects only the validator-derived quick-appearance items, requires
complete criterion assignments, and derives the acceptance rate. At least 90%
must be accepted, and the corresponding machine sequences must have completed
within three attempts.

## Final release decision

Only the provider-free combined controller may emit
`external_beta_ready: true`. It requires all raw corpus evidence again,
recomputes the founder decision, verifies both blind ledgers, validates the
six-role authority bundle, verifies staging, and binds both retained zero
exit-code files.

```bash
set +e
PYTHONPATH=src .venv/bin/python scripts/verify_external_beta_release.py \
  --corpus-decision "$CORPUS_DIR/final-decision.json" \
  --corpus-results "$CORPUS_DIR/results.json" \
  --corpus-approval "$EVIDENCE_ROOT/review/signed-founder-approval.json" \
  --corpus-exit-code "$CORPUS_DIR/final-exit-code.txt" \
  --corpus-manifest docs/evals/frozen-founder-corpus-v1/manifest.json \
  --corpus-source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --corpus-evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v1.json" \
  --corpus-evidence-root "$EVIDENCE_ROOT" \
  --corpus-workload docs/evals/frozen-founder-corpus-v1/workload.json \
  --gia-review-packet "$EVIDENCE_ROOT/review/gia-packet.json" \
  --gia-review-ledger "$EVIDENCE_ROOT/review/signed-gia-ledger.json" \
  --designer-review-packet "$EVIDENCE_ROOT/review/designer-packet.json" \
  --designer-review-ledger "$EVIDENCE_ROOT/review/signed-designer-ledger.json" \
  --staging-results "$STAGING_DIR/results.json" \
  --staging-approval "$EVIDENCE_ROOT/review/signed-staging-approval.json" \
  --staging-exit-code "$STAGING_DIR/exit-code.txt" \
  --outdir "$EVIDENCE_ROOT/gate-artifacts/external-beta"
COMBINED_EXIT=$?
set -e
test "$COMBINED_EXIT" -eq 0
```

`external-beta-decision.json` is a derived authority. Missing raw evidence,
v1 Boolean review data, packet/ledger mismatch, wrong reviewer profile,
incomplete criteria, authority-bundle failure, nonzero retained exit code,
staging drift, or any hash/signature mismatch leaves
`external_beta_ready: false`. Update the table only from retained external
evidence.
