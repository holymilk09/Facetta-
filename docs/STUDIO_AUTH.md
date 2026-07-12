# Studio authenticated principal boundary

All `/projects/*`, `/studio/*`, Studio-consumed `/assets/*`, and trusted
`/image-runs/*` requests require:

```http
Authorization: Bearer <first-party-session-token>
```

The server resolves that opaque token to one canonical principal using
`FACETTA_AUTH_PRINCIPALS_JSON`. Request `owner` and `created_by` fields remain
audit metadata; when present, they must equal the authenticated principal.
They never establish access. Project reads and mutations also require the
principal to own the stored project.

Resource authorization is resolved from canonical records, not URL labels:

- families use `DesignFamily.owner`, including unfiltered list requests;
- history and project routes use the stored `Project.owner`;
- assets use their root `Project.owner`, falling back to
  `ImageAsset.created_by` only for legacy/orphan assets;
- image-run evidence uses its root project owner, falling back to
  `ImageRun.created_by` for unbound runs;
- temporary preview candidates use their stored creator or owner.

Unknown or ownerless legacy resources fail closed. Every `image_url` emitted
by Studio requires the same bearer header; it is not a public CDN URL.

Authentication fails closed by default. `FACETTA_AUTH_MODE=local` and `test`
are explicit non-public bypasses only. Public beta deployments must leave the
mode at `required` and inject the token mapping through deployment secrets.

Stable failures:

- `401 authentication_required`: bearer header missing or malformed.
- `401 invalid_authentication_token`: token unknown or revoked.
- `403 principal_actor_mismatch`: body/query audit actor attempts spoofing.
- `403 project_access_denied`: authenticated user does not own the project.
- `403 asset_access_denied`: authenticated user does not own the asset.
- `403 image_run_access_denied`: authenticated user does not own the run.

This boundary does not mint sessions. The first-party login/session service is
responsible for issuing and delivering the opaque token to the mobile client.
