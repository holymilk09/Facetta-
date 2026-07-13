# Studio external beta gates

Only the two gates below remain external. Local unit, integration, export, and
mock-transport tests do **not** satisfy either gate.

| Gate | Current execution status | External-beta status |
|---|---|---|
| Signed frozen 144-image corpus and founder/GIA review | `not_run` | `unmet` |
| Live two-principal staging isolation | `not_run` | `unmet` |

Do not change either status to met from a local test result. Retain the command
exit code and the generated JSON alongside the human sign-off.

## Gate 1: signed frozen 144-image corpus

### Required inputs

- The founder source directory must contain the exact 144 files and SHA-256
  hashes pinned by
  `docs/evals/frozen-founder-corpus-v1/manifest.json`.
- `docs/evals/frozen-founder-corpus-v1/config.json` must still match its pinned
  manifest and implementation hashes. Its current
  `current_evidence_status` is `not_run`; its executor, canonical API runner,
  reviewer, and founder keys are unenrolled; and it has no resolved assignment
  bundle, so the gate cannot pass yet.
- **Resolve the workload before capture.** The 1,044 rows are a logical review
  scope, not 1,044 executable jobs. Independently review and hash-pin one
  source-specific assignment/applicability bundle with concrete regions and
  references, a canonical resolved-input hash for every logical row, and a
  preassigned `corpus_run_id`. Do not make provider calls for unresolved or
  `not_applicable` rows; revise the workload if an operation is not applicable.
  The production plan currently reports zero execution-ready rows and zero
  maximum executable attempts.
- **Freeze key enrollment before capture.** Configure the executor, canonical
  API runner, GIA reviewer, and founder Ed25519 public keys by key ID, path, and
  SHA-256 in `config.json` before generating the final provider-call plan,
  capture, replay, or `results.json`.
  The capture and replay bind the exact config hash, so adding the founder key
  after execution would invalidate that evidence. Keep all private signing
  keys outside the repository and outside the run artifacts. The executor
  signs capture, the API runner signs persistence, the reviewer signs the
  completed replay, and the founder signs only the already-generated result
  bytes later. Public-key enrollment is not approval.
- The replay passed to `--evidence` must be one complete
  `facetta-frozen-replay.v1` JSON payload signed by that enrolled key. It must
  bind its manifest/config hashes, all source/candidate/mask artifact hashes,
  the canonical API runner's signed persistence attestation, source coverage,
  scores, and the completed named GIA-trained false-positive/false-negative
  review.
  That review must include one boolean decision for every selected
  `kind/evaluation_id/source_filename` result; the verifier recomputes the
  false-positive and false-negative counts from those decisions.
- `docs/evals/frozen-founder-corpus-v1/workload.json` must pass definition
  validation. It explicitly separates 144-source integrity from the 58-source
  ring quality slice and expands the latter into 1,044 source/evaluation
  logical sequences. A plan file, including a synthetically complete plan, is
  not capture evidence.

### Prepare the review packet

Before secured execution, generate the deterministic provider-call plan:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out /secure/path/to/provider-call-plan.json plan
```

This performs zero provider calls and leaves `corpus_gate_ready: false`. With
the repository's production config it must also report zero execution-ready
assignments. Only after assignment and key enrollment may the secured live
executor write a `facetta-frozen-capture.v2` object with its
attempt rows and canonical persistence result. Each attempt names the frozen
`source_filename`, kind, evaluation ID, attempt number, machine acceptance and
scores, plus relative candidate path and (for edits) mask path with hashes. The
envelope also pins the preassigned `corpus_run_id`, manifest/config/workload,
assignment and resolved-input hashes, and a separately signed canonical API
persistence attestation, then receives an Ed25519 executor signature. Validate
that machine envelope before review packet construction; this signature is not
the later GIA reviewer signature:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-capture \
  --capture /secure/path/to/frozen-capture.json \
  --capture-public-key /secure/path/to/executor-public-key \
  --capture-key-id secured-executor-v1
```

Do not hand-copy hashes.
Build an unsigned review packet locally:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --evidence-root /secure/path/to/evidence-root \
  --source-dir /secure/path/to/evidence-root/founder-reference-directory \
  --capture /secure/path/to/evidence-root/frozen-capture.json \
  --capture-public-key /secure/path/to/evidence-root/executor-public-key \
  --capture-key-id secured-executor-v1 \
  --out /secure/path/to/evidence-root/unsigned-review-packet.json
```

The builder makes zero provider calls and first requires the capture's executor
signature, exact plan coverage, artifact hashes, and signed persistence binding to
validate. It verifies every ring-quality source referenced by the pinned
workload, derives replay paths without changing the signed hashes, embeds the
verified persistence attestation, and generates exactly one pending reviewer
decision per declared 58-source/evaluation assignment. Full 144-source byte and
image integrity remains a separate prerequisite. The packet's top-level
`capture_sha256` and nested capture provenance both bind the exact signed
capture bytes used by the replay compiler and subsequent founder chain. Its
output is intentionally unsigned with
`completed: false`, null decisions, and `pending_review` coverage. The
GIA-trained reviewer completes those fields, verifies the images, recomputes
the declared confusion summary, and signs the entire canonical payload outside
the repository. The replay verifier rejects the packet until that happens.
The CLI validates against the operator-supplied executor key path and ID and
records their identity in capture provenance; key custody/enrollment is an
external operational control, not something a locally self-generated key can
satisfy by itself.

All referenced sources, capture, executor key, signed persistence attestation,
candidates, edit masks, replay packet, and gate outputs must stay within the
explicit evidence root. The packet and replay use only root-relative paths and
a canonical sorted artifact index. Absolute references, traversal, symlink
escape, omitted index entries, or hash drift invalidate the run.

### Execute

Run from the repository root. Use secured operator-selected paths; do not copy
the founder sources, signing key, or unsigned working evidence into the output
directory.

```bash
set +x
umask 077
EVIDENCE_ROOT=/secure/path/to/evidence-root
ARTIFACT_DIR="$EVIDENCE_ROOT/gate-artifacts/frozen-founder-corpus-v1"
mkdir -p "$ARTIFACT_DIR"
set +e
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --source-dir "$EVIDENCE_ROOT/founder-reference-directory" \
  --evidence "$EVIDENCE_ROOT/signed-facetta-frozen-replay.v1.json" \
  --outdir "$ARTIFACT_DIR" > "$ARTIFACT_DIR/command-result.json"
GATE_EXIT=$?
set -e
printf '%s\n' "$GATE_EXIT" > "$ARTIFACT_DIR/exit-code.txt"
test "$GATE_EXIT" -eq 0
```

The output directory is the canonical machine-result location for this run:

- `results.json` — complete compiled decision and failure details.
- `report.md` — concise human-readable decision.
- `command-result.json` and `exit-code.txt` — invocation summary and retained
  process result.

The GIA-trained review is part of the signed replay. Founder approval is a
second release decision because it must bind the already-generated
`results.json` bytes. The founder public key must already have been enrolled
and frozen in the config before capture; do not edit the config at this stage.
After reviewing the result, the founder signs a
`facetta-founder-approval.v1` record containing `results_sha256`, decision
`approved`, founder name, timezone-qualified `approved_at`, and release-ticket
identifier. Then compile the final decision:

```bash
set +x
umask 077
set +e
PYTHONPATH=src .venv/bin/python scripts/verify_frozen_corpus_release.py \
  --results "$ARTIFACT_DIR/results.json" \
  --approval /secure/path/to/signed-founder-approval.json \
  --outdir "$ARTIFACT_DIR" \
  > "$ARTIFACT_DIR/final-command-result.json"
FINAL_EXIT=$?
set -e
printf '%s\n' "$FINAL_EXIT" > "$ARTIFACT_DIR/final-exit-code.txt"
test "$FINAL_EXIT" -eq 0
```

The final machine authority for **this gate only** is `final-decision.json`
with `corpus_gate_ready: true`. It never emits `external_beta_ready`; staging
is a separate required authority. Neither approval may be inferred from
scores, and editing `results.json` after approval invalidates the founder
signature. The finalizer also re-verifies the gate-result schema and run kind,
the exact config and manifest hashes, and the frozen implementation pins before
accepting the founder signature.

### Pass criteria

The replay command and final-decision command must both exit `0`;
`results.json.status` must be `pass`, `results.json.corpus_gate_ready` must be
`true`, and `final-decision.json.corpus_gate_ready` must be `true`. All of the
following must hold:

- Definition and implementation pins pass without manifest/config drift.
- Source integrity is `144/144`; quality assignments match the pinned
  58-source ring workload matrix and the signed evaluation IDs exactly match
  verified attempts. Until the replay compiler consumes that matrix directly,
  this external gate remains `unmet` even if capture-envelope validation passes.
- Every declared render and edit evaluation has artifact-verified evidence;
  every edit has replayable source, candidate, and mask pixels.
- Render hard-gate pass rate is at least `0.90`; mean render conformance is at
  least `85`; mean edit fidelity is at least `90`.
- No evaluation uses more than `3` attempts, and replayed outside-mask drift is
  at most `0.18`.
- Signed reviewer acceptance for the manifest's quick-appearance class is at
  least `0.90`. Structural results meet mean fidelity `90`, have no major
  drift, and every structural outside-mask replay is at most `0.18`.
- The config-enrolled canonical API runner's Ed25519 persistence attestation
  binds the exact capture `corpus_run_id`, commit, API schema, frozen
  definitions, and selected result set; proves atomic image/specification
  persistence and stale-write rejection; and reports exactly `0` rejected
  candidates becoming active assets.
- The Ed25519 signature verifies against the pinned reviewer public key, the
  GIA-trained review is complete with false-positive/false-negative counts,
  and founder approval is recorded against this exact result hash.
- The run reports `0` provider calls; this command verifies a captured replay
  and must not regenerate images.

Any nonzero exit, `corpus_gate_ready: false`, incomplete/unsigned evidence,
missing founder approval, or missing GIA review leaves this gate `unmet`.

## Gate 2: live two-principal staging isolation

### Required staging state

Use two already-seeded, distinct Supabase principals. Each principal must own a
different canonical project, Design Family, and image asset in the deployed
production-filtered staging API. The probe is read-only and must not be used to
seed those records.

Inject these exact environment variables from the staging secret manager:

```text
FACETTA_STAGING_BASE_URL
FACETTA_STAGING_USER_A_ACCESS_TOKEN
FACETTA_STAGING_USER_A_PROJECT_ID
FACETTA_STAGING_USER_A_FAMILY_ID
FACETTA_STAGING_USER_A_ASSET_ID
FACETTA_STAGING_USER_B_ACCESS_TOKEN
FACETTA_STAGING_USER_B_PROJECT_ID
FACETTA_STAGING_USER_B_FAMILY_ID
FACETTA_STAGING_USER_B_ASSET_ID
```

`FACETTA_STAGING_BASE_URL` must be an exact HTTPS origin with no path, query,
fragment, or embedded credentials. Each access token must be a Supabase JWT
whose `sub` is a UUID, the two subjects must differ, and all paired record IDs
must differ.

### Execute

Disable shell tracing before secret injection. Do not place tokens in a checked
in `.env`, command arguments, command history, screenshots, or CI artifacts.
After the secret manager has populated the environment, capture only stdout:

```bash
set +x
umask 077
ARTIFACT_DIR=/secure/path/to/gate-artifacts/staging-two-principal
mkdir -p "$ARTIFACT_DIR"
set +e
.venv/bin/python scripts/run_staging_two_user_isolation.py \
  > "$ARTIFACT_DIR/results.json"
GATE_EXIT=$?
set -e
printf '%s\n' "$GATE_EXIT" > "$ARTIFACT_DIR/exit-code.txt"
test "$GATE_EXIT" -eq 0
```

The redirected `results.json` and adjacent `exit-code.txt` are the canonical
machine artifacts. The script
does not print credentials or response bodies and declares `secrets_logged`,
`provider_calls`, and `mutations` in its result. Store the exit code and an
operator/date sign-off beside it. Never archive the process environment or
access tokens with the result; revoke or expire both staging tokens after the
evidence is accepted.

### Pass criteria

The command must exit `0`; `results.json.passed` must be `true`; every entry in
`results.json.checks` must have `passed: true`; and the summary must show:

```json
{
  "secrets_logged": false,
  "provider_calls": 0,
  "mutations": 0
}
```

In both A-to-B and B-to-A directions, the probe must prove:

- own project, history, image, and family reads succeed;
- project ownership equals the authenticated JWT subject;
- cross-principal project/history/image reads return `403`, cross-family
  enumeration returns `404`, owner-query spoofing returns `403`, and family
  listings contain the caller's family but not the other principal's family;
- unauthenticated project/image/family reads return `401`; and
- all legacy/admin metadata, history, component-map, share, OpenAPI, and docs
  surfaces checked by the script remain hidden with `404`.

Exit `77` means missing credentials/fixtures (`skipped`), exit `2` means invalid
or unreachable staging configuration, and exit `1` means at least one isolation
check failed. All three outcomes leave this gate `unmet`; investigate a failed
isolation check as a release blocker rather than rerunning until green.

## Final release decision

External beta remains blocked until both result artifacts pass and both human
sign-offs refer to the exact retained result hashes. A corpus decision is not
an external-beta decision. The repository currently exposes separate corpus
and staging authorities; a future combined release controller must verify both
versioned artifacts and their retained hashes before it may emit a full
external-beta-ready decision. Update this document's status table only from
that evidence; never from local test output.
