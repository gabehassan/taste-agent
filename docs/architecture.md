# Architecture

One Postgres database, one API process, one worker process, a dashboard, and thin transports in front.
Postgres holds all state and doubles as the job queue and the rate-limit store, so there is no Redis.

## Pieces

| Piece | Code | Role |
|---|---|---|
| api | `server/tasteserver/api.py`, `routes/` | FastAPI. Auth, rate limits, webhooks, the relay API, user and admin routes. |
| worker | `server/tasteserver/worker.py` | Same image, different entry point. Runs jobs (fetch, transcribe, digest, profile, sync), sends queued texts, and ticks the scheduler every minute. |
| Postgres | `server/tasteserver/schema.sql` | Everything. Jobs are claimed with `FOR UPDATE SKIP LOCKED`. |
| bucket | `server/tasteserver/storage.py` | Screenshots and video keyframes. Any S3-compatible store. |
| dashboard | `dashboard/` | Next.js. Users browse their saves; admins manage users, keys, settings. It calls the API server-side only. |
| transports | `routes/webhooks.py`, `routes/relay.py` | Blooio (a hosted iMessage number) or anything that speaks the relay API. |

## A message, end to end

```
phone ── iMessage ── Blooio ── POST /v1/webhooks/blooio ──┐
                                                         ├── api: verify, dedupe, rate limit,
relay client ─────────────── POST /v1/inbound ───────────┘   store attachments, insert message + job
                                                                         │
                                                  worker: claim job, check spend caps
                                                  command | link | screenshot | conversation
                                                                         │
                                                       queue outbound messages
                                                                         │
            Blooio: dispatcher sends bubbles ◄───────────────────────────┤
            relay: GET /v1/outbound, then POST /v1/outbound/{id}/ack ◄───┘
```

The webhook receipt, the stored message and its job are written in one transaction, serialized per sender with an
advisory lock, so a redelivered or concurrent webhook can't create two accounts or two jobs.

Outbound texts to Blooio go out in order for each user. A long reply is split into a few bubbles, each sent with an
idempotency key derived from the message id and bubble index. If the worker dies mid-send, the message is picked up
again and the provider drops any bubble it already delivered.

## Ingesting a link

1. Canonicalise the URL (strip trackers, normalise hosts) and expand known short links through the SSRF guard.
2. Skip it if this user already saved the same canonical URL.
3. Extract by source: trafilatura for articles, fxtwitter for X, the Reddit API for threads, yt-dlp for TikTok,
   YouTube and Instagram, Open Library for books.
4. For video, use captions when they exist. Otherwise download audio and video at low quality, transcribe the audio,
   and grab three keyframes for the vision pass.
5. One model call turns the extracted text, transcript and images into a title, summary, verbatim snippets, tags,
   a guess at why it was saved, a tapback, and the reply text.
6. Record the call's token usage and cost.

## Talking back

The scheduler gives each user a few random slots a day inside their waking hours. When a slot comes due, cheap checks
run first: not paused, at least 90 minutes since the last one, no conversation in the last 20 minutes, and fewer than
two unanswered suggestions since the user last replied or touched an item. Only then does a model see a shortlist of unread saves and decide whether any of
them deserves a text. It can say no, and that is the default. When it says yes, it returns an item id and an excerpt
index; the stored excerpt is sent verbatim, so the model never writes the quote.

The taste profile is rebuilt after every five new pieces of evidence (saves, finished items, connection imports) or
once a day if anything changed.

## Auth

- API keys are `tk_` plus 32 random bytes. Only the SHA-256 is stored, and a key is shown once.
- Scopes: `transport` (post inbound and poll outbound for its own user's handles), `user` (that user's data),
  `admin` (everything, plus `?user_id=` to act for a user). A transport key cannot read a user's saves.
- Users log in with a six-digit code texted to their registered number. Codes expire after 10 minutes, allow five
  guesses, and are bound to the number they were sent to. A successful login mints a 30-day user key, kept in an
  HttpOnly cookie by the dashboard.
- Admins log in to the dashboard with a password. The admin key never reaches the browser, and every request made with
  it first checks for a signed admin session, including server actions.
- Admin changes to users, handles, keys, invites and settings are recorded in `audit_log`.

## Limits

| Layer | Control | Default |
|---|---|---|
| Edge | requests per IP, keyed on the platform's client IP header (never `X-Forwarded-For`) | 120 / min |
| Key | requests per API key | 600 / hr |
| Login | code requests per IP and per phone; exchanges per IP and per phone | 10 / hr, 3 / hr; 30 / hr, 10 / hr |
| User | inbound messages | 60 / hr, 300 / day |
| User | links ingested | 100 / day |
| User | conversation turns | 100 / day |
| User | outbound texts | 20 / hr |
| Spend | model cost per user | $2 / day |
| Spend | model cost overall | $10 / day, $150 / month |
| Body | request size, counted as it streams | 8 MB |
| Attachments | count and size; JPEG, PNG, GIF, WebP and HEIC only | 5, 6 MB each |
| Fetch | response size and timeout | 10 MB, 25 s |
| Media | download size and length; download timeout | 200 MB, 60 min; 240 s |
| Jobs | attempts, with linear backoff; stuck jobs requeued | 3; after 15 min |

Defaults are editable in `/admin/settings`, and per-user spend caps on `/admin/users`. When a user hits a spend cap, links are saved as pending,
the user gets one "paused until tomorrow" text, and pending items are retried hourly once there is budget.

## Fetching untrusted URLs

Every server-side fetch goes through `netguard`. It allows only http and https on ports 80, 443, 8080 and 8443,
refuses anything that resolves to a non-global address (private, loopback, link-local, CGNAT, IPv4-mapped IPv6 and so
on), re-checks every redirect hop, and caps the response size. The check runs at connect time against the address the
socket actually connects to, so a DNS answer that changes between check and connect can't reach an internal service.

yt-dlp does its own networking, so it only ever receives URLs on the exact TikTok, YouTube, Instagram and X domains.

## Data model

`users`, `handles`, `api_keys`, `messages` (both directions; outbound rows are the send queue), `jobs`, `items`
(with a generated `tsvector` for search), `item_events`, `profiles`, `user_memories`, `surfaces` (what was texted
back), `chat_turns`, `usage`, `connections`, `rate_limits`, `settings`, `audit_log`, `invites`, `login_challenges`,
`webhook_events`. Every user-owned row carries `user_id`, and every query on user data is scoped by it.

The schema is applied on every boot and every statement is idempotent.
