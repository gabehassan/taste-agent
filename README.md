# taste

An iMessage agent that learns what you like from what you send it.

Text it a link, a screenshot, a book title or a stray thought. It reads the thing properly, keeps it, and replies with
the one part worth knowing. Over time it builds a profile of your taste from what you actually save, finish and react
to. A few times a day it may text you an excerpt from something you saved and forgot about, but only when it has a
concrete reason to. Staying quiet is the default.

## What it reads

| You send | It does |
|---|---|
| an article or essay | extracts the full text with trafilatura |
| an X post | text, quoted post and image alt text, via fxtwitter |
| a Reddit thread | the post, the linked page and the top comments, via the Reddit API |
| a TikTok, YouTube or Instagram link | captions when they exist, otherwise transcribes the audio and looks at three frames |
| a Goodreads or Amazon book link, or just a title | author, year and description from Open Library |
| a screenshot | reads the image |
| anything else | a conversation, with tools to search, read and update your saves |

You can also connect Letterboxd, Goodreads, Substack and RSS feeds. Ratings from those count as stronger evidence than
saves.

Words it treats as commands: `taste` (your profile), `hit me` (something from your saves now), `more`, `read`,
`later`, `skip`, `status`, `pause`, `resume`, `login` and `help`.

## How it works

```
iMessage ── Blooio webhook ──┐
                             ├── api ── Postgres (state, job queue, rate limits)
relay client ── /v1/inbound ─┘               │
                                   worker: fetch, transcribe, digest, profile, schedule, send
dashboard (Next.js) ── api
```

A FastAPI process takes messages in, and a worker process does everything slow: fetching, transcription, model calls
and sending. They share one Postgres database, which is also the job queue. Every model call is priced and checked
against per-user and global spend caps. The dashboard is a Next.js app for browsing your saves, with an admin area for
users, keys and settings. Every prompt and canned reply lives in [`server/prompts.toml`](server/prompts.toml).

More detail, including the auth model and limits: [docs/architecture.md](docs/architecture.md).

## Running it locally

You need Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22, Postgres 13 or newer, ffmpeg (for video), and an
OpenAI API key.

```bash
cd server
cp .env.example .env    # set DATABASE_URL, OPENAI_API_KEY and ADMIN_BOOTSTRAP_KEY
uv sync
uv run --env-file .env uvicorn tasteserver.api:app --port 8080
```

In a second terminal, start the worker:

```bash
uv run --env-file .env python -m tasteserver.worker
```

The first boot creates the schema and an admin key from `ADMIN_BOOTSTRAP_KEY`. Use it to create yourself:

```bash
export ADMIN=tk_...    # your ADMIN_BOOTSTRAP_KEY
curl -s localhost:8080/v1/admin/users -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name": "you", "handles": ["+12025550143"]}'
```

You don't need a phone to try it. Give the new user a transport key and talk to it over the relay API:

```bash
curl -s localhost:8080/v1/admin/users/<user id>/keys -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" -d '{"name": "terminal", "scopes": ["transport"]}'
export KEY=tk_...      # the key from that response
curl -s localhost:8080/v1/inbound -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"handle": "+12025550143", "text": "https://www.paulgraham.com/greatwork.html"}'
curl -s localhost:8080/v1/outbound -H "Authorization: Bearer $KEY"
```

Then the dashboard:

```bash
cd dashboard
cp .env.example .env.local    # TASTE_API_URL, TASTE_ADMIN_KEY (the same admin key) and a password
npm install
npm run dev
```

The admin area is at `localhost:3000/admin`. Users log in with a code texted to them. Without a messaging provider,
print one instead and use "I already have a code" on the login page:

```bash
uv run --env-file .env python -m tasteserver.login +12025550143
```

## Messaging

**Blooio** gives the agent its own iMessage number, with tapbacks, typing bubbles and read receipts. Set the `BLOOIO_*`
variables and point a webhook at `https://<api>/v1/webhooks/blooio`. People who text the number need an invite code
from `/admin/users`, unless you turn on `open_signup`.

**The relay API** is for anything else that can send and receive messages, such as a Mac reading its own Messages
database or another provider. A relay authenticates with a transport-scoped key and can only speak for its user's
registered handles.

| Endpoint | Purpose |
|---|---|
| `POST /v1/transport/hello` | declare what the relay supports (`react`, `typing`, `effects`) |
| `POST /v1/inbound` | deliver a message: handle, text, optional base64 images, an external id for dedupe |
| `GET /v1/outbound` | poll for queued replies |
| `POST /v1/outbound/{id}/ack` | report a reply as sent or failed |

## Deploying

The setup this was built on: Railway for the API, worker, Postgres and a bucket, and Vercel for the dashboard.

1. Create a Railway project with Postgres and a bucket. Add two services from `server/`, named `api` and `worker`.
   They build the same Dockerfile; `start.sh` runs the worker when the service is named `worker` or `TASTE_ROLE=worker`.
2. Give both services the variables from [`server/.env.example`](server/.env.example).
3. Deploy `dashboard/` to Vercel with the variables from [`dashboard/.env.example`](dashboard/.env.example). Set the
   API's `DASHBOARD_URL` and `DASHBOARD_ORIGIN` to the dashboard's address, and give both sides the same
   `DASHBOARD_PROXY_SECRET`.
4. Point the Blooio webhook at the API.

Spend caps default to $2 per user per day and $10 per day overall. Change them and the model prices they are computed
from in `/admin/settings`. If your model isn't in `model_prices`, its calls count as free.

## Development

```bash
cd server
uv run ruff check . && uv run ruff format --check .
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres uv run pytest
```

Tests that need Postgres create and drop their own schema, and are skipped when `TEST_DATABASE_URL` isn't set. No test
calls a model or sends a message.

```bash
cd dashboard
npm run lint && npm run typecheck && npm run build
```

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## License

[MIT](LICENSE)
