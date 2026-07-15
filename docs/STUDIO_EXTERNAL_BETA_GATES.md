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

Before capture, enroll seven independently controlled roles: secured executor,
canonical API runner, frozen-assignment reviewer, GIA visual-fidelity reviewer,
founder, independent jewelry designer, and staging reviewer. The assignment
reviewer signs the exact source-specific execute/not-applicable decisions before
provider work and must remain distinct from execution and downstream quality
review. The frozen config must contain a strict
`facetta-release-authority-bundle-config.v2` value that hash-pins, for all seven
roles:

- a proof-of-possession enrollment artifact;
- a separately signed qualification artifact;
- the role public key and key ID;
- one fresh signed status list covering active, revoked, suspended, expired,
  and rotated state; and
- distinct qualification-verifier and status-signer public keys.

The combined decision checks all seven roles at one UTC decision time. Missing,
expired, suspended, revoked, or stale records fail closed. Role/key reuse,
duplicate subjects, invalid qualification scope, status rollback, or
unacknowledged rotation also fail. Artifacts use opaque tokens and must not
contain names, email addresses, government identifiers, credential numbers,
or private keys. The public key and key ID used by each operational gate must
exactly match that role's enrolled key; an unrelated signer cannot borrow the
authority of a valid but unused enrollment. The production config deliberately
keeps `release_authority_bundle` and all release keys `null` until real external
enrollment is retained.

## Retained run-directory safety

Preassign three fresh, opaque identifiers in the release ticket before any
external execution: `CORPUS_RUN_ID`, `STAGING_RUN_ID`, and
`EXTERNAL_RELEASE_RUN_ID`. The corpus identifier must exactly equal the
`corpus_run_id` already pinned by the reviewed assignment bundle and carried by
the capture and replay. The staging and external-release identifiers must be
assigned before their commands run and bound into the operator record. Never
derive a run identifier from a clock after execution has started.

Provision only the parent directories in advance. Each command below creates
its leaf run directory with plain `mkdir`; an existing directory is a hard
collision and the operator must stop rather than reuse or clean it. Do not
replace these calls with `mkdir -p`. Every shell block that retains redirected
output enables `set -C` first so an existing file cannot be overwritten.
Artifact creation is atomic per file; a process or host failure can still leave
an incomplete run directory. Such a directory is failed evidence, never a
resume point. A valid gate requires the complete named artifact set and retained
zero exit code from one run ID.

## Gate 1: signed frozen 144-image corpus

### Required inputs

- The source directory contains the exact 144 files and SHA-256 values pinned
  by `docs/evals/frozen-founder-corpus-v1/manifest.json`.
- `config.json` matches the manifest and every frozen implementation pin.
- The independently reviewed assignment bundle resolves the 1,044 logical
  ring-quality rows to source-specific `execute` or `not_applicable`
  assignments and preassigns one `corpus_run_id`. Unresolved rows make zero
  provider calls and cannot enter capture. A reviewed `not_applicable` row
  remains in the logical scope as a signed reason/hash binding, but creates no
  execution-bundle sequence, provider request, candidate, or reviewer item.
- A signed `facetta-frozen-capture.v3` binds the manifest, config, workload,
  assignments, source/candidate/mask hashes, one retained evaluator report per
  candidate-producing attempt, selected result set, executor, canonical API
  persistence attestation, and exact run ID. Scores, QA outcomes, acceptance,
  and hard-gate decisions are recomputed from those reports during capture and
  release replay instead of being trusted as submitted scalars.
- A complete `facetta-frozen-replay.v2` supplies all raw machine evidence. It
  remains executor-attested machine observation evidence, not provider
  attestation or human review authority.
- A separate GIA `facetta-blind-jewelry-review-packet.v2` and
  `facetta-blind-jewelry-review-ledger.v2` cover the exact selected artifacts.
  Legacy replay-v1 packets are unsupported and cannot pass this gate.

### Plan the signed capture

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-definition

PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out /secure/path/to/evidence-root/provider-call-plan.json plan
```

The repository production definition reports 144 integrity sources, 58 ring
quality sources, 1,044 logical evaluation sequences, and zero execution-ready
rows until assignments and keys are enrolled. Planning and validation make
zero provider calls. Once enrolled, `planned_evaluation_sequence_count` remains
`1,044`; only `execution_ready_sequence_count` contributes to the live attempt
ceiling, while `not_applicable_sequence_count` remains hash-bound end to end.

### Secured execution handoff

The repository does not contain a paid live executor. A separately secured
operator must resolve and pin every assignment, preassign the `corpus_run_id`,
enroll the executor authority, mount the verified source directory beneath the
evidence root, and enforce an account-level dollar budget before provider work.
The `3,132` maximum is an image-attempt ceiling, not a total request or dollar
ceiling. The operator must also review and pin one exact fallback contract;
the frozen routing label must not be used to infer a different live-runner
fallback silently.

The exact contract is
`docs/evals/frozen-founder-corpus-v1/routing-contract.v1.json`, hash-pinned by
`config.json`. Attempts 1 and 2 use the `grok_edit` route through the
`grok_direct` adapter, but their signed provider identity is xAI model
`grok-imagine-image-quality` at `POST /v1/images/edits`; `grok_direct` is not a
provider model. Attempt 3 uses the `openai_edit` route through the direct
OpenAI image-provider adapter, model `gpt-image-2` at
`POST /v1/images/edits`. Both provider model identifiers are mutable aliases
because no immutable provider revision is available; the contract records that
limitation explicitly, so a later revision claim requires a new reviewed
contract and hash. Credential-driven provider substitution is forbidden.

Each execution-bundle attempt binds the contract digest, routing label, route
role, route, adapter key, provider, actual provider model, revision status,
endpoint, and provider operation before the producer copies it into the signed
capture. Route assignment also checks the task class and image operation against
the contract's applicability lists. Primary attempts must carry no fallback
reason. Attempt 3 must carry exactly one contract-declared reason:
`grok_provider_failed`, `grok_provider_failed_after_qa_failure`, or
`grok_qa_failed`, and that reason is derived from the signed prior attempt
outcomes rather than accepted as an isolated label. Definition, producer,
capture, replay, and release validation fail closed on a missing or drifted
contract, reordered routes, provider/model or endpoint substitution,
inapplicable assignment, a missing fallback reason, an undeclared reason, or a
reason contradicted by the prior outcomes. These validations remain
provider-free.

The enrolled executor's signature is the assertion boundary for provider,
model, endpoint, error, and QA-attempt identity. It proves who made those
claims and detects later mutation; it is not an independent provider receipt.
Do not describe route identity as provider-attested unless immutable provider
receipts are added to the capture contract and verified separately.

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

The capture producer installs the signed envelope at
`$EVIDENCE_ROOT/signed-capture/capture.json`. Validate that exact artifact,
then materialize the complete provider-free replay consumed by the corpus gate.
The replay builder revalidates the capture and makes zero provider calls.

```bash
EVIDENCE_ROOT="${EVIDENCE_ROOT:?set the retained evidence root}"
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

### Prepare the blind GIA packet

Generate a fresh secret 32-byte review seed outside the repository, record its
custody in the release ticket, and pass its lowercase 64-character hex form.
The packet uses it only to produce a reproducible HMAC order and opaque IDs.

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
```

After the founder reviews `results.json`, they sign a
`facetta-founder-approval.v1` bound to its exact bytes. Finalization must
receive the raw evidence again; it reruns the provider-free corpus compiler
and requires the recomputed result to byte-match the retained result.

```bash
set +x
umask 077
set -C
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

### Corpus pass criteria

- Source integrity is `144/144`; the exact 58-source ring workload and 1,044
  logical rows are covered without missing or extra assignments.
- The replay's reviewed non-applicable projection exactly matches the frozen
  assignment plan. Any omitted, rewritten, duplicated, or attempted
  non-applicable row fails closed.
- Every accepted attempt is the final attempt; every execution-ready sequence
  has zero or one accepted attempt and uses no more than three attempts.
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
canonical project, Design Family, image asset, Studio job, and one fresh,
QA-valid reviewing candidate in each of the catalog, visual, markup, view, and
presentation stores in the deployed production-filtered staging API. Each
principal also needs a separate normalized preview candidate that was already
discarded before the probe, with its exact active-asset and specification
version guards retained. The probe replays the same terminal `discard`
decision idempotently; it does not generate, accept, branch, charge, or create
a new canonical revision. Recycle
every API replica after seeding, then run the probe read-only. The candidate
fixtures must remain fresh for the whole probe so no GET performs expiry or
reconciliation writes.

The secret manager must inject:

```text
FACETTA_STAGING_BASE_URL
FACETTA_STAGING_DEPLOYMENT_REVISION
FACETTA_STAGING_RUN_ID
FACETTA_EXTERNAL_RELEASE_RUN_ID
FACETTA_STAGING_USER_A_ACCESS_TOKEN
FACETTA_STAGING_USER_A_PROJECT_ID
FACETTA_STAGING_USER_A_FAMILY_ID
FACETTA_STAGING_USER_A_ASSET_ID
FACETTA_STAGING_USER_A_JOB_ID
FACETTA_STAGING_USER_A_CANDIDATE_FIXTURES_JSON
FACETTA_STAGING_USER_A_NORMALIZED_DECISION_FIXTURE_JSON
FACETTA_STAGING_USER_B_ACCESS_TOKEN
FACETTA_STAGING_USER_B_PROJECT_ID
FACETTA_STAGING_USER_B_FAMILY_ID
FACETTA_STAGING_USER_B_ASSET_ID
FACETTA_STAGING_USER_B_JOB_ID
FACETTA_STAGING_USER_B_CANDIDATE_FIXTURES_JSON
FACETTA_STAGING_USER_B_NORMALIZED_DECISION_FIXTURE_JSON
```

Each candidate-fixtures value is a JSON object with exactly `catalog`,
`visual`, `markup`, `view`, and `presentation` keys. Every value contains only
the pre-seeded candidate's `run_id`, `candidate_id`, `source_asset_id`, and
`studio_job_id`. The source must equal that principal's seeded active asset;
the five candidate jobs must be distinct and present in the principal's own
Studio-job list. The probe validates and hash-binds this lineage but never
prints the JSON or access tokens.

Each normalized-decision fixture is a JSON object containing only `kind`,
`image_run_id`, `candidate_id`, `source_asset_id`, `studio_job_id`, and
`expected_design_version`. `kind` is `visual`, `catalog_revision`, or `markup`;
visual uses a null version while the exact catalog/markup kinds require a
positive version. The candidate must already be terminal `discarded`, must be
separate from all five reviewing fixtures, and its job must appear in the
principal's own Studio-job list. This precondition is an explicit readiness
blocker: without it the probe exits `77` rather than claiming decision-route
proof from a read-only or synthetic check.

The base URL must be an exact HTTPS origin. The live `/health` response must
report the same immutable deployment revision and the initialized PostgreSQL
persistence engine. The local SQLite fallback cannot pass.

```bash
set +x
umask 077
STAGING_RUN_ID="${STAGING_RUN_ID:?preassign a fresh staging run ID}"
EXTERNAL_RELEASE_RUN_ID="${EXTERNAL_RELEASE_RUN_ID:?preassign a fresh external-release run ID}"
export FACETTA_STAGING_RUN_ID="$STAGING_RUN_ID"
export FACETTA_EXTERNAL_RELEASE_RUN_ID="$EXTERNAL_RELEASE_RUN_ID"
STAGING_RUN_ROOT=/secure/path/to/gate-artifacts/staging-two-principal
STAGING_DIR="$STAGING_RUN_ROOT/$STAGING_RUN_ID"
test -d "$STAGING_RUN_ROOT"
mkdir "$STAGING_DIR" || exit 1
set -C
set +e
.venv/bin/python scripts/run_staging_two_user_isolation.py \
  > "$STAGING_DIR/results.json"
STAGING_EXIT=$?
set -e
printf '%s\n' "$STAGING_EXIT" > "$STAGING_DIR/exit-code.txt" || exit 1
test "$STAGING_EXIT" -eq 0
```

The owner reads must succeed, cross-owner reads and enumeration must fail with
the expected status, unauthenticated reads must return `401`, and every
legacy/admin/OpenAPI/docs surface in the probe must remain hidden. The v7 probe
fetches each principal's own Studio-job list plus all five own candidate lists.
It also exercises the normalized Refine seam: one list, each catalog/visual/
markup discriminator and exact lineage, owner-bound detail and image reads,
cross-principal non-enumeration, spoofed-owner rejection, and an idempotent
terminal decision replay. The replay remains provider-free and leaves the
result contract at `provider_calls: 0` and `mutations: 0`.
Normalized candidate evidence is decoded with the same fail-closed semantics
as the shipped trusted client: reviewing `verdict` and `qa` must agree with
explicit acceptance flags, catalog revisions require at least one unique,
labeled specification change plus a valid canonical `next_spec`. That proposed
Spec must retain schema/design/version/creator/time identity, jewelry type,
template, mode, and a meaningful center stone with positive carat and three
dimensions plus trade and GIA color. A non-empty placeholder object is not
evidence. Markup operations are limited to `LOCAL_EDIT` or
`VISUAL_ONLY_EDIT`. Each normalized candidate must bind to its own one-output
`refine` Studio job; a shared job identifier or a multi-output/non-Refine job
cannot satisfy this evidence lane.
Each seeded job and candidate fixture must appear exactly once. Duplicate or
malformed rows, the other principal's identifiers, and mismatched project or
source-asset or candidate-job lineage fail closed before the evidence can pass.
It also uses read-only `OPTIONS` discovery to require that every operation in the
canonical production-hidden mutation inventory is absent. A `405` is acceptable
only when its non-empty `Allow` header excludes the retired method; a missing
header fails closed, while a safe collision with a retained `GET` does not.
A separately enrolled staging reviewer signs
`facetta-staging-isolation-approval.v2` against the exact result and exit-code
bytes, origin, deployment revision, fixture set, `staging_run_id`, and
`external_release_run_id`. The signed `approved_at` must follow `probed_at`; both
must be at or before the combined verifier decision time. The staging evidence
must be no more than the frozen `max_staging_evidence_age_hours` (24 hours) old.
Exit `77` (missing fixtures), `2` (invalid/unreachable), or `1` (failed check)
all leave this gate unmet.

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
  --capture "$CAPTURE_PATH" \
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
seven-role authority bundle, verifies staging, and binds both retained zero
exit-code files.

```bash
set +x
umask 077
EXTERNAL_RELEASE_RUN_ID="${EXTERNAL_RELEASE_RUN_ID:?preassign a fresh external-release run ID}"
EXTERNAL_RELEASE_RUN_ROOT="$EVIDENCE_ROOT/gate-artifacts/external-beta"
EXTERNAL_RELEASE_DIR="$EXTERNAL_RELEASE_RUN_ROOT/$EXTERNAL_RELEASE_RUN_ID"
test -d "$EXTERNAL_RELEASE_RUN_ROOT"
mkdir "$EXTERNAL_RELEASE_DIR" || exit 1
set -C
set +e
PYTHONPATH=src .venv/bin/python scripts/verify_external_beta_release.py \
  --corpus-decision "$CORPUS_DIR/final-decision.json" \
  --corpus-results "$CORPUS_DIR/results.json" \
  --corpus-approval "$EVIDENCE_ROOT/review/signed-founder-approval.json" \
  --corpus-exit-code "$CORPUS_DIR/final-exit-code.txt" \
  --corpus-manifest docs/evals/frozen-founder-corpus-v1/manifest.json \
  --corpus-source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --corpus-evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v2.json" \
  --corpus-evidence-root "$EVIDENCE_ROOT" \
  --corpus-workload docs/evals/frozen-founder-corpus-v1/workload.json \
  --gia-review-packet "$EVIDENCE_ROOT/review/gia-packet.json" \
  --gia-review-ledger "$EVIDENCE_ROOT/review/signed-gia-ledger.json" \
  --designer-review-packet "$EVIDENCE_ROOT/review/designer-packet.json" \
  --designer-review-ledger "$EVIDENCE_ROOT/review/signed-designer-ledger.json" \
  --staging-results "$STAGING_DIR/results.json" \
  --staging-approval "$EVIDENCE_ROOT/review/signed-staging-approval.json" \
  --staging-exit-code "$STAGING_DIR/exit-code.txt" \
  --staging-run-id "$STAGING_RUN_ID" \
  --external-release-run-id "$EXTERNAL_RELEASE_RUN_ID" \
  --outdir "$EXTERNAL_RELEASE_DIR" \
  > "$EXTERNAL_RELEASE_DIR/command-result.json"
COMBINED_EXIT=$?
set -e
printf '%s\n' "$COMBINED_EXIT" > "$EXTERNAL_RELEASE_DIR/exit-code.txt" || exit 1
test "$COMBINED_EXIT" -eq 0
```

The v2 `external-beta-decision.json` repeats both preassigned run IDs, the probe
and approval times, the frozen maximum age, and every signed byte hash in its
gate bindings. `external-beta-decision.json` and its retained command result and exit code
must remain together in the fresh external-release run directory.
`external-beta-decision.json` is a derived authority. Missing raw evidence,
v1 Boolean review data, packet/ledger mismatch, wrong reviewer profile,
incomplete criteria, authority-bundle failure, nonzero retained exit code,
staging drift, or any hash/signature mismatch leaves
`external_beta_ready: false`. Update the table only from retained external
evidence.
