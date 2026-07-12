# Studio Confirm design contract

`POST /projects/{project_id}/creative-candidates/{candidate_id}/confirm-design`
reads the exact server-held candidate into a reviewable ring-first design draft.
It does not persist a design or revision.

Request:

```ts
type ConfirmDesignRequest = {
  created_by: string;
  notes?: string;
  run_independent_audit?: boolean;
};
```

Response shape:

```ts
type ConfirmDesignResponse = {
  confirmation_token: string;
  expires_at: string;
  candidate_id: string;
  candidate_sha256: string;
  spec_visual_hash: string;
  fact_groups: Array<{
    key: 'design' | 'center_stone' | 'setting' | 'metal' | 'ring_fit' | 'accents';
    label: string;
    facts: Array<{
      key: string;
      label: string;
      value: string;
      authority: 'suggested' | 'estimated' | 'designer_supplied';
    }>;
  }>;
  unresolved_source_questions: string[];
  audit_eligibility: {
    eligible: boolean;
    state: 'not_ready' | 'ready' | 'complete';
    reason: string;
  };
};
```

Mobile maps `fact_groups` to review cards, shows
`unresolved_source_questions` as required decisions, and uses
`audit_eligibility` only to enable the next review action. It preserves the
three authority values verbatim; `suggested` must never be presented as a
designer-supplied fact. The exact specification remains server-side. The
opaque `confirmation_token` is single-use, expires after 30 minutes, and is
bound to the owner, project, selected candidate bytes, and specification hash.

Promotion uses only the opaque token:

```ts
type PromoteCreativeCandidateRequest = {
  created_by: string;
  confirmation_token: string;
};
```

The server rejects expired, reused, tampered, or incorrectly bound tokens
before creating any Design, DesignVersion, imported child, or revision record.

The current manual-entry mobile confirmation draft is the next phase of the
same flow, not a replacement for this source-read response. Designer edits
must be applied to this exact candidate/spec pair using all three optimistic
identity fields before a confirmed revision can be saved.
