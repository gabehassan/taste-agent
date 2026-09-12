# taste: architecture

Personal-first, multi-user-ready. One Postgres, one worker, one API, one dashboard, thin transports.

## Services

| Piece | Where | What |
|---|---|---|
| `api` | Railway (Docker, `server/`) | FastAPI. Auth, rate limits, inbound/outbound message queue, items, connections, admin. |
| `worker` | Railway (same image, different start command) | Job runner: fetch, download, transcribe, vision, digest, profile refresh, connection sync, surfacing ticks. |
| `Postgres` | Railway managed | All state. Also the job queue (`SELECT ... FOR UPDATE SKIP LOCKED`) and the rate-limit counters. No Redis. |
| `taste-media` | Railway Bucket (S3 API) | Screenshots, audio, keyframes. Swappable for Cloudflare R2 by changing five env vars. |
| `dashboard` | Vercel (Next.js, `dashboard/`) | Admin UI. Server-side only; the browser never sees the admin key. |
| Mac transport | this Mac (`src/taste`, relay mode) | Reads the self-chat from `chat.db`, POSTs to `/v1/inbound`, polls `/v1/outbound`, sends via AppleScript. |
| Hosted transport (later) | Sendblue / Blooio webhook | Same two endpoints. Adding it touches no other code. |

## Request path

```
iPhone share sheet -> iMessage self-chat -> chat.db
  -> Mac relay: POST /v1/inbound {handle, text, attachments, external_id}
     -> api: auth (transport key) -> handle belongs to user? -> idempotent on external_id
        -> rate limit (user, key, ip) -> attachments to bucket -> jobs.insert(handle_message)
  -> worker: claim job -> spend gate -> commands | ingest_url | ingest_image | chat
     -> messages.insert(direction=out, status=queued)
  -> Mac relay: GET /v1/outbound -> AppleScript send -> POST /v1/outbound/{id}/ack
```

## Auth model

- Every request except `GET /health` needs `Authorization: Bearer tk_...`.
- Keys are random 32-byte tokens shown once; only the SHA-256 hash is stored. Scopes: `transport` (inbound/outbound for its own user), `user` (own data), `admin` (everything, plus `?user_id=` impersonation for support).
- Transport keys can only speak for handles registered to their user. A stolen transport key cannot read items, only inject messages for that one user, which are still rate limited and spend capped.
- Dashboard login is a bcrypt password plus a signed HttpOnly cookie. Clerk slots in behind the same middleware when users get their own logins.
- Audit log on every admin mutation and every key use (last_used_at).

## Abuse and cost controls

| Layer | Control | Default |
|---|---|---|
| Edge | per-IP request limit (Postgres fixed window) | 120 / min |
| Key | per-key request limit | 600 / hr |
| User | inbound messages | 60 / hr, 300 / day |
| User | ingests (fetch + model) | 100 / day |
| User | chat turns | 100 / day |
| User | model spend | $2 / day (per-user setting) |
| Global | model spend | $10 / day, $150 / month (settings) |
| Fetch | SSRF guard: http(s) only, DNS resolved, private/loopback/link-local/metadata ranges rejected, re-checked after every redirect, 10 MB response cap, 25 s timeout | on |
| yt-dlp | `--no-playlist`, max filesize 200 MB, max duration 60 min, 180 s timeout, audio-only download | on |
| Transcription | audio compressed to 32 kbps mono, 25 MB cap, skipped over 60 min | on |
| Jobs | 3 attempts with backoff, 5 min hard timeout, worker concurrency 2 | on |
| Outbound | 20 sends / hr / user | on |
| Body | 8 MB request cap, 5 attachments, images only | on |
| Railway | workspace hard spending limit | set via CLI |
| OpenAI | project budget alert | set in OpenAI dashboard (manual) |

When a user hits a spend cap the worker drops the job, queues one outbound "paused until tomorrow" message, and stops. Admin sees it in the dashboard.

## Data model

`users`, `handles`, `api_keys`, `messages`, `jobs`, `items` (with `tsvector` full-text search), `profiles`, `surfaces`, `chat_turns`, `usage` (every model call: model, tokens, cost), `connections` (letterboxd, goodreads, rss, export uploads: `config`, `cursor`, `last_synced_at`), `rate_limits`, `settings`, `audit_log`, `invites`. Every user-owned table carries `user_id`; all queries are scoped by it.

## Ingestion pipeline

1. Canonicalise URL (strip trackers, expand short links through the SSRF guard).
2. Dedupe per user on canonical URL.
3. yt-dlp metadata for any URL (about a thousand extractors). If it resolves to media: download audio, transcribe, grab 3 keyframes with ffmpeg for the vision pass. Captions used instead of transcription when present.
4. Otherwise: trafilatura for articles, fxtwitter for X, Reddit OAuth, Open Library for books.
5. One multimodal model call (text + transcript + frames or screenshot) produces title, summary, verbatim snippets, tags, why-saved, ack.
6. Usage row written with tokens and cost. Full-text index updated.

## Connections

`letterboxd` and `goodreads`: username only. Poll their per-user RSS feeds hourly; one-time CSV import for history. Ratings feed the profile as explicit signal.
`export`: upload of a TikTok / Instagram / X data export; parser per platform, each saved item becomes an ingest job.
`x_bookmarks` (later): OAuth to the official API, paid tier required.

## Environments

Railway `production` only for now. Add `staging` with `railway environment new staging --duplicate production` when there is a second user.
