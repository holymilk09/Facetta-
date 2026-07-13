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
- The production config intentionally has no resolved assignment bundle,
  executor key, canonical API-runner key, GIA reviewer key, founder key,
  jewelry-designer reviewer key, or staging-release reviewer key. It is a
  frozen definition, not an executable release configuration.
- None of these definition files contains generated candidates, visual scores,
  designer acceptance, staging isolation, or factory authority.

Validate the frozen definition and produce its deterministic secured-executor
plan with zero provider calls:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-definition
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  --out /secure/path/to/provider-call-plan.json plan
```

The plan contains 1,044 **logical** evaluation sequences: each of the 58 ring
sources is paired with seven render cases and eleven edit operations. The
3,132-attempt figure is therefore only the logical-scope ceiling at the frozen
three-attempt cap. It is not an executable provider budget. Each logical row
must first receive a separately reviewed, source-specific assignment with an
explicit `execute` or `not_applicable` decision, concrete regions/references,
and a canonical `resolved_inputs_sha256`. That assignment bundle is hash-pinned
in the config and preassigns the `corpus_run_id`. With the repository's
production config, all 1,044 rows remain unresolved, the execution-ready count
and executable maximum-attempt count are both zero, and capture is blocked.
Synthetic all-row tests prove deterministic contract coverage only; they are
not external evidence.

Before any live call, enroll the independently controlled executor public key
in `config.json`, pin the reviewed assignment bundle, regenerate the plan, and
confirm every intended execution row is resolved. The secured executor's
`facetta-frozen-capture.v2` envelope must bind the exact preassigned
`corpus_run_id`; manifest, config, workload, assignment, and resolved-input
hashes; every planned source/evaluation key; relative candidate and edit-mask
paths plus their hashes; and a signed canonical-persistence attestation.
Validate its separate Ed25519 executor signature before preparing the human
review packet:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_frozen_corpus_capture.py \
  validate-capture \
  --capture /secure/path/to/frozen-capture.json \
  --capture-public-key /secure/path/to/executor-public-key \
  --capture-key-id secured-executor-v1
```

Passing capture validation proves machine provenance and artifact completeness
only. It never substitutes for measured quality, independent classification,
separate designer acceptance, the signed GIA-trained review, or founder
approval.

The repository now includes a fail-closed capture producer. Its default CLI
adapter consumes an already-produced, hash-bound execution bundle and therefore
makes **zero** image-provider calls itself. A secured deployment can replace
that adapter through the programmatic executor seam, but the same preflight is
mandatory: all assignments must be resolved and executable, both signing keys
must prove control of their config-enrolled public identities, every source and
input artifact must remain inside the evidence root with its exact hash, and
the output directory must not already exist. The producer caps every sequence
at three attempts and records an exhausted sequence with zero accepted attempts;
when an attempt is accepted, it must be the final attempt. It stages the
complete output atomically, builds a canonical source/candidate/mask/
persistence artifact index, signs the canonical persistence attestation, signs
the capture envelope separately, and re-verifies both signatures before making
the output visible.

The input execution bundle uses schema
`facetta-frozen-execution-bundle.v1` and binds `corpus_run_id`, the canonical
provider-call-plan hash, the declared provider-call count, every planned
sequence and resolved-input hash, and one to three scored attempt rows with
root-relative candidate/mask paths and SHA-256 values. The canonical API
observation file uses schema
`facetta-canonical-persistence-observations.v1` and binds the same run plus the
exact selected-result-set hash/count and the three required persistence checks.
Private signing keys must remain outside both the repository and evidence root.

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
```

Run the integrity-only gate with:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_frozen_corpus_gate.py \
  --evidence-root /secure/path/to/evidence-root \
  --source-dir /secure/path/to/evidence-root/founder-reference-directory \
  --outdir /secure/path/to/evidence-root/gate-output
```

Validated machine captures should be converted to the review schema with
`scripts/prepare_frozen_corpus_review.py`. The packet builder hash-binds every
ring-quality source, candidate, and edit mask and creates exactly one pending
decision row for every source/evaluation assignment in the pinned workload; it
never calls a provider, fills a human decision, or signs evidence. The command
requires the enrolled executor public key and key ID and refuses to build a
packet unless `facetta-frozen-capture.v2` validation passes. The source
directory, capture, executor public key, signed persistence attestation,
candidates, masks, and output must all resolve inside the explicit
`--evidence-root`. The packet stores only normalized root-relative references
and a canonical, sorted, hash-bound artifact index. Absolute references, `..`
traversal, symlink escape, missing index membership, and hash drift fail closed.
It embeds the verified persistence attestation for replay compatibility while
retaining its exact capture binding. The replay packet records the SHA-256 of the
exact signed capture bytes both at its schema-required top level and inside its
detailed capture provenance, allowing the compiled result and later founder
approval to retain the same capture chain. The 144-source integrity result
remains a separate prerequisite and is never inferred from the 58-source
review packet.

Packet construction therefore includes the evidence root explicitly:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_frozen_corpus_review.py \
  --evidence-root /secure/path/to/evidence-root \
  --source-dir /secure/path/to/evidence-root/sources \
  --capture /secure/path/to/evidence-root/capture.json \
  --capture-public-key /secure/path/to/evidence-root/keys/executor-public-key \
  --capture-key-id secured-executor-v1 \
  --out /secure/path/to/evidence-root/review/unsigned-packet.json
```

The command intentionally exits nonzero with image quality `not_run` until
`--evidence` points to a complete `facetta-frozen-replay.v1` JSON capture. A
replay pins the manifest/config hashes and contains:

- byte/image integrity for every one of the 144 manifest sources, with
  provider-backed capture assignments governed separately by the pinned
  58-source ring workload matrix;
- the exact `workload.json` SHA-256 and one to three contiguous attempts for
  every one of its 1,044 source/evaluation assignments;
- hash-bound source and candidate artifacts for every attempt, plus a
  hash-bound mask for every edit attempt;
- captured render conformance and edit-fidelity results;
- a signed canonical API-runner persistence attestation, bound to the capture's
  exact `corpus_run_id` and selected result-set digest, proving atomic image and
  specification writes, stale-write rejection, and zero rejected candidates
  becoming active assets;
- completed GIA-trained false-positive/false-negative review.

The review packet and replay compiler consume the pinned workload directly:
quality coverage is limited to the 58 ring sources and their 1,044 declared
assignments, while integrity still covers all 144 sources. This closes the
local scope mismatch only. It does not run a provider, supply an external
source directory or executor/reviewer key, complete human review, approve a
release, or make `corpus_gate_ready` true.

Replay fails closed on a missing or extra assignment, a non-ring quality
attempt, operation-class drift, non-contiguous or over-limit attempts,
mismatched source/artifact hashes, non-finite scores, unusable edit masks, or
any GIA rejection.

The signed reviewer block contains one decision for every selected
`kind/evaluation_id/source_filename` result. The verifier derives confusion
counts from those decisions instead of trusting summary numbers. It also
evaluates the workload classes declared in the manifest: quick appearance
edits require at least 90% reviewer acceptance within the three-attempt cap;
structural edits must meet the frozen fidelity and outside-mask drift
thresholds. Missing, duplicate, or unclassified decisions fail closed.

Machine scores, source coverage, indexed artifacts, persistence attestation,
and review assertions remain separately attributable within the evidence
chain. The persistence attestation is Ed25519-signed by the config-enrolled
canonical API runner; the completed review payload is independently signed by
the GIA-trained reviewer. The reviewer public-key file is configured outside
the evidence and its SHA-256 is
pinned in `config.json`. The production key is intentionally unconfigured
until the reviewer enrollment step is complete; no key or unsigned evidence
can become release-ready.

Founder approval is deliberately not folded into `results.json`: it must bind
the exact bytes the founder reviewed. The separate `founder_public_key` must
already be enrolled in the frozen config before capture; do not edit the config
after capture. After reviewer replay passes, use that enrolled private-key
holder to create and sign a
`facetta-founder-approval.v1` record bound to the SHA-256 of `results.json`, and
run `scripts/verify_frozen_corpus_release.py`. Only its
`final-decision.json.corpus_gate_ready: true` satisfies the complete corpus
gate. It deliberately cannot claim full external-beta readiness because the
live two-principal staging-isolation gate is separate. The repository ships
with all production public keys unconfigured and contains no human sign-off.

Full external-beta composition is owned by
`scripts/verify_external_beta_release.py`. The combined verifier and staging
probe are hash-pinned in this config. It re-verifies the signed corpus decision,
requires a separate config-enrolled jewelry-designer approval of the exact
quick-appearance result, and requires a config-enrolled staging reviewer to
sign the exact v2 isolation result and retained zero exit-code bytes. Local or
self-generated signatures do not satisfy those external custody requirements.

The offline replay verifies artifact hashes and recalculates outside-mask drift
from the captured pixels. Coverage counts come from verified attempts, never
from signed summary claims alone. Absent source coverage, unsigned or tampered
evidence, missing captures, changed configuration, more than three attempts,
failed metrics, rejected-candidate persistence, or missing review all fail
closed.
