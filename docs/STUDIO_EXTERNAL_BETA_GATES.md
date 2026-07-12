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
  `current_evidence_status` is `not_run` and `reviewer_public_key` is `null`, so
  the gate cannot pass yet.
- Reviewer enrollment must configure an Ed25519 public key by key ID, path, and
  SHA-256 in `config.json`. Keep the private signing key outside the repository
  and outside the run artifacts.
- The replay passed to `--evidence` must be one complete
  `facetta-frozen-replay.v1` JSON payload signed by that enrolled key. It must
  bind its manifest/config hashes, all source/candidate/mask artifact hashes,
  canonical persistence evidence, source coverage, scores, and the completed
  named GIA-trained false-positive/false-negative review.

### Execute

Run from the repository root. Use secured operator-selected paths; do not copy
the founder sources, signing key, or unsigned working evidence into the output
directory.

```bash
set +x
umask 077
ARTIFACT_DIR=/secure/path/to/gate-artifacts/frozen-founder-corpus-v1
mkdir -p "$ARTIFACT_DIR"
set +e
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --source-dir /secure/path/to/founder-reference-directory \
  --evidence /secure/path/to/signed-facetta-frozen-replay.v1.json \
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

Record founder approval against the SHA-256 of `results.json` in the release
ticket or a sign-off record stored beside these two files. The GIA-trained
review is part of the signed replay; the founder approval is the separate
release decision. Neither may be inferred from scores alone.

### Pass criteria

The command must exit `0`, `results.json.status` must be `pass`, and
`results.json.release_ready` must be `true`. All of the following must hold:

- Definition and implementation pins pass without manifest/config drift.
- Source integrity is `144/144`, and signed quality source coverage is
  `144/144` with the signed evaluation IDs exactly matching verified attempts.
- Every declared render and edit evaluation has artifact-verified evidence;
  every edit has replayable source, candidate, and mask pixels.
- Render hard-gate pass rate is at least `0.90`; mean render conformance is at
  least `85`; mean edit fidelity is at least `90`.
- No evaluation uses more than `3` attempts, and replayed outside-mask drift is
  at most `0.18`.
- Canonical API persistence evidence is present and the count of rejected
  candidates that became active assets is exactly `0`.
- The Ed25519 signature verifies against the pinned reviewer public key, the
  GIA-trained review is complete with false-positive/false-negative counts,
  and founder approval is recorded against this exact result hash.
- The run reports `0` provider calls; this command verifies a captured replay
  and must not regenerate images.

Any nonzero exit, `release_ready: false`, incomplete/unsigned evidence,
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
sign-offs refer to the exact retained result hashes. Update this document's
status table only from that evidence; never from local test output.
