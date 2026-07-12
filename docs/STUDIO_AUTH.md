# Studio authenticated principal boundary

All `/projects/*`, `/studio/*`, Studio-consumed `/assets/*`, and trusted
`/image-runs/*` requests require:

```http
Authorization: Bearer <first-party-session-token>
```

In production the server verifies a Supabase access JWT locally against the
project's asymmetric JWKS. It requires an exact issuer and audience, a valid
signature and lifetime, `role=authenticated`, a non-anonymous session, and UUID
`sub` and `session_id` claims. The Supabase subject is represented losslessly as
32 lowercase hexadecimal characters so it fits the existing canonical owner
fields. Email, profile metadata, and provider claims never grant authority.

Request `owner` and `created_by` fields remain audit metadata; when present,
they must equal the verified principal. They never establish access. Project
reads and mutations also require the principal to own the stored project.

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

Authentication fails closed by default; an omitted environment is treated as
production. Production requires:

```dotenv
FACETTA_ENV=production
FACETTA_AUTH_MODE=supabase
FACETTA_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
FACETTA_SUPABASE_AUDIENCE=authenticated
FACETTA_CORS_ORIGINS=https://studio.example.com
```

The JWKS URL is derived from the validated project URL and cached for no longer
than ten minutes. Only ES256 and RS256 are accepted; shared-secret HS256 tokens
are not supported. `opaque`, `local`, and `test` are explicit non-production
compatibility modes. Production startup rejects them.

The production application surface omits legacy Designs, Library, Users,
Saved Stones, and share-administration routers; it also disables OpenAPI/Swagger
and wildcard CORS. Only the eight specification adapters consumed by Studio
are mounted and require the same principal boundary; provider-heavy legacy
build/render routes are absent. The production Assets surface is limited to
authenticated image reads and Studio's temporary markup read/preview seam;
direct render, view, restyle, video, pin, and technical-drawing routes are not
mounted. Catalog preview/candidate routes additionally authorize the canonical
asset project or image run and bind `created_by` to the verified principal;
deprecated direct catalog apply is not mounted. Legacy routers remain mounted
only in test/development until their callers and historical compatibility
readers have migrated.

For an emergency signing-key event, restart every API process to clear its
in-memory JWKS cache, then follow the Supabase key-revocation procedure. The
Supabase edge also caches public keys, so plan for its documented rotation
window rather than promising instantaneous backend revocation. Keep access
tokens short-lived: ordinary sign-out or session deletion does not invalidate a
previously issued offline-verified access JWT before its expiry. Factory-grade
sensitive operations will need an online `session_id` check before public use.

Stable failures:

- `401 authentication_required`: bearer header missing or malformed.
- `401 invalid_authentication_token`: signature or required claims are invalid,
  or the token is expired.
- `503 authentication_verifier_unavailable`: JWKS is temporarily unavailable;
  preserve the client session and allow retry.
- `503 authentication_configuration_error`: authentication is misconfigured.
- `403 principal_actor_mismatch`: body/query audit actor attempts spoofing.
- `403 project_access_denied`: authenticated user does not own the project.
- `403 asset_access_denied`: authenticated user does not own the asset.
- `403 image_run_access_denied`: authenticated user does not own the run.

This boundary does not mint sessions. Supabase Auth owns login, refresh, expiry,
and session issuance. A legacy owner such as `usr_owner` will not automatically
match a real Supabase subject; beta cutover therefore requires either a clean
database or a reviewed transactional owner backfill. Never map ownership from
mutable email or user metadata.
