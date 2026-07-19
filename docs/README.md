# Facetta documentation index

The root [README](../README.md) is the setup and development entry point. This index
separates current contracts from historical context and retained evidence.

## Current product and engineering contracts

- [Project constitution](../CLAUDE.md) — product identity, authority rules, and coding
  conventions.
- [Repository map](REPOSITORY_MAP.md) — where requests flow and where to make changes.
- [AI-first Studio architecture](ai-first-studio-architecture.md) — product loop,
  lineage, organization, editing, destinations, and optional Factory lane.
- [Trusted workflow architecture](trusted-workflow-architecture.md) — canonical
  persistence, QA, revision, approval, and consolidation boundaries.
- [Studio Confirm contract](STUDIO_CONFIRM_CONTRACT.md) — confirm-step UX and authority
  expectations.
- [Studio authentication](STUDIO_AUTH.md) — principal, ownership, and production auth
  boundaries.
- [Spec Schema v1](SPEC_SCHEMA.md) — jewelry specification fields and validation rules.
- [Trusted route inventory](trusted-workflow-route-inventory.md) — canonical,
  compatibility, and production-hidden API operations.

## Product background and research

- [Product requirements](PRD.md) — original problem, audience, phases, and non-goals;
  some phase ordering is historical.
- [RocoAI-to-Facetta study](ROCOAI_TO_FACETTA_AGENT_STUDY.md) — reference-product study
  and product decisions.
- [Data wanted](DATA_WANTED.md) — domain research backlog.
- [Hosting and data residency](hosting-and-data-residency.md) — current hosting decision
  and deferred cross-border work.
- [Jewelry agent system prompt](jewelry_agent_system_prompt.md) and
  [spec agent prompt pack](spec_agent_prompt_pack.md) — founder-supplied domain prompt
  references; code and tests remain the executable behavior.

## Operations and release evidence

- [Studio external beta gates](STUDIO_EXTERNAL_BETA_GATES.md) — frozen-corpus,
  independent-review, staging-isolation, and final release requirements.
- [Project status log](STATUS.md) — chronological checkpoints. It is retained context,
  not proof that the current checkout or live system is green.
- [Task ledger](../TASKS.md) — completed and open historical implementation items.
- [`evals/`](evals/) — retained fixtures, manifests, outputs, and evidence bundles.

Do not edit retained eval output to make a current run appear successful. Produce a new
run directory or use the documented release tooling, then preserve its provenance.
