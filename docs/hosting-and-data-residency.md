# Hosting & data residency

A standing decision record for where Facetta's data lives, and how the
US ↔ China cross-border story is meant to work. Written before we had real
users so the reasoning survives — revisit it, don't re-derive it.

## Decision (today)

**One database: Supabase PostgreSQL in a North America region (`us-east-1`).**
No China-specific infrastructure yet. Ship here.

## Why North America, not Asia

Put the database near the **users and the app server**, not near the
developer. Supabase suggests a region from the *developer's* IP — ignore that.

- Initial users are North American designers.
- Jewelry factories cluster in **Shenzhen and Hong Kong**, but our workload is
  latency-tolerant (fill a form → submit a spec → view a generated sheet →
  async messages), so ~200–400 ms to Asia is fine.
- **Region is permanent per Supabase project** — you cannot move it later
  without creating a new project and migrating. So this choice matters now;
  the app-server should be deployed in the *same* region to keep the API↔DB
  hop local.

## The Shenzhen / Hong Kong reality

- **Hong Kong is not behind the Great Firewall.** Open internet, no ICP
  license, excellent connectivity. A HK factory reaches a US-hosted app
  directly — no special work.
- **Shenzhen (mainland) is behind the GFW**, but the GFW is not a wall for
  business SaaS — it throttles and blocks specific consumer sites. A mainland
  factory can log into a US-hosted web app to view a sheet and reply to a
  message; it's "slower and occasionally flaky," not "blocked."
- **ICP license + in-country hosting** (Tencent Cloud / Alibaba Cloud) is only
  required to host a public **consumer** service inside China at scale. We are
  a B2B tool where factories occasionally log in — not that, not yet.

## Escalation ladder

| Stage | Users | What we host | China story |
|---|---|---|---|
| **Now** | US designers, HK/Shenzhen factories | One Supabase, `us-east-1` | Works as-is |
| **Asia growth** | More Asia factories | + CDN/edge in HK or Singapore | Faster last mile, still one DB |
| **China consumer play** | Mainland end-users, WeChat login | Separate in-country stack + a bridge | See below |

We are firmly in **row 1**, which needs zero China-specific engineering.
Hong Kong is the natural Asia beachhead when the time comes (open internet,
next to Shenzhen, low mainland latency, no ICP).

## Cross-border collaboration (the future bridge)

The core Facetta loop is **designer ↔ factory**, and factories are often in
China — so once a mainland stack exists, a US user must still be able to chat
with, and share designs to, a factory whose data lives on the mainland server.
That is a **bridge between two stacks**, not a merged database.

Principles:

1. **Two stacks, each the home of its own users' personal data.** China's PIPL
   restricts exporting a mainland user's personal data; keep it resident.
2. **The design is the unit that crosses.** A spec object is self-contained,
   non-personal JSON. When a US designer shares a design with a mainland
   factory, replicate *that design version + its message thread* across the
   border — not the user tables.
3. **Each side reads/writes its local database; the bridge syncs deltas.** The
   US designer hits the US DB, the Shenzhen factory hits the mainland DB, and a
   sync service forwards new messages both ways. Chat is the *easiest* thing to
   bridge: small, append-only, retry-friendly — a flaky link just queues and
   retries, delivering in seconds.
4. **Order by `created_at` (UTC), globally.** Merged threads sort chronologically
   regardless of which region a message originated in.
5. **Minimal handles across the border.** The other side sees a collaborator's
   display name, not their full personal record.
6. **Ride an accelerated path** (HK relay / cloud cross-border network) so the
   GFW doesn't make sync unreliable.

## What we already did to keep this cheap (pre-data)

Identity choices are the expensive-to-change-later ones, so they were made now
while there is no data to migrate:

- **Opaque, globally-unique IDs everywhere** (`dsn_…`, `usr_…`, `msg_…`,
  `cmt_…`), 64-bit random. Two regions can mint rows independently and sync
  them into one shared design/thread without primary-key collisions — the
  property auto-increment integers break. `design_messages` and `comments`
  were migrated off integer PKs specifically for this (`src/facetta/db.py`,
  locked by `tests/test_ids.py`).
- **Self-contained spec objects** (portable JSON, no cross-row foreign keys in
  the payload) — a design can move or replicate between databases as a unit.
- **Immutable versions** — a shared design version is a frozen, safely-copyable
  artifact.
- **`created_at` is UTC and authoritative for ordering**, so cross-region
  merges stay chronological.

## Intentionally deferred (do NOT build yet)

These are cheap to add later (additive) or only matter at China scale:

- A `region` / residency column on users and designs — an **additive** column
  (`_apply_additive_migrations` already handles that pattern); current data is
  all one region, backfill trivially when the second stack appears.
- The sync/bridge service, cross-border acceleration, and conflict handling.
- In-country China hosting, ICP license, and **WeChat (OAuth) login** — an
  app-layer auth integration, largely independent of where the DB lives.

Don't pull these forward. Row 1 is the job.
