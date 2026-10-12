-- Applied on every boot by db.migrate(). Every statement is idempotent.

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE,
  name TEXT,
  role TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'active',
  tz TEXT NOT NULL DEFAULT 'UTC',
  transport TEXT NOT NULL DEFAULT 'relay',  -- 'blooio' (hosted number) or 'relay' (polls /v1/outbound)
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,  -- user-tunable overrides of the global settings
  state JSONB NOT NULL DEFAULT '{}'::jsonb,     -- scheduler plan, voice stats, counters
  onboarded_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Addresses a user texts from. A transport may only speak for handles registered to its user.
CREATE TABLE IF NOT EXISTS handles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'imessage',
  address TEXT NOT NULL,
  capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,  -- react, typing, effects
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, address)
);

-- Only the SHA-256 of each key is stored. Scopes: transport, user, admin.
CREATE TABLE IF NOT EXISTS api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  name TEXT,
  key_hash TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL,
  scopes TEXT[] NOT NULL,
  last_used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Both directions. Outbound rows are the send queue: queued -> sending -> sent | failed | cancelled.
CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  direction TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'text',
  handle_id UUID REFERENCES handles(id),
  chat_id TEXT,
  text TEXT,
  attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
  external_id TEXT,
  status TEXT NOT NULL DEFAULT 'received',
  meta JSONB NOT NULL DEFAULT '{}'::jsonb,
  send_attempts INT NOT NULL DEFAULT 0,
  send_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  send_locked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ,
  UNIQUE (user_id, direction, external_id)
);
CREATE INDEX IF NOT EXISTS messages_out_queue ON messages(user_id, status) WHERE direction = 'out';

-- The job queue. Workers claim with FOR UPDATE SKIP LOCKED.
CREATE TABLE IF NOT EXISTS jobs (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  locked_at TIMESTAMPTZ,
  locked_by TEXT,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, run_after) WHERE status = 'queued';

CREATE TABLE IF NOT EXISTS items (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  url TEXT,
  canonical_url TEXT,
  external_id TEXT,
  kind TEXT,
  source TEXT,
  title TEXT,
  author TEXT,
  raw_text TEXT,
  transcript TEXT,
  summary TEXT,
  snippets JSONB NOT NULL DEFAULT '[]'::jsonb,
  tags TEXT[] NOT NULL DEFAULT '{}',
  why TEXT,
  read_minutes INT DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'unread',
  note TEXT,
  media JSONB NOT NULL DEFAULT '[]'::jsonb,
  meta JSONB NOT NULL DEFAULT '{}'::jsonb,
  message_id BIGINT,
  surfaced_count INT NOT NULL DEFAULT 0,
  last_surfaced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  tsv TSVECTOR GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(note, '')), 'B') ||
    setweight(array_to_tsvector(tags), 'B') ||
    setweight(to_tsvector('english', left(coalesce(raw_text, ''), 20000)), 'C')
  ) STORED
);
CREATE INDEX IF NOT EXISTS items_user ON items(user_id, id DESC);
CREATE INDEX IF NOT EXISTS items_tsv ON items USING GIN(tsv);
CREATE UNIQUE INDEX IF NOT EXISTS items_external ON items(user_id, source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_events (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,  -- finished, later, not_for_me
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS item_events_owner ON item_events(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS profiles (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text TEXT,
  observations JSONB NOT NULL DEFAULT '[]'::jsonb,
  one_liner TEXT,
  item_count INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Things the user explicitly asked it to remember. Capped at 30 per user.
CREATE TABLE IF NOT EXISTS user_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'user',
  evidence TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, text)
);
CREATE INDEX IF NOT EXISTS user_memories_owner ON user_memories(user_id, created_at DESC);

-- Snippets and observations texted back to the user.
CREATE TABLE IF NOT EXISTS surfaces (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id BIGINT,
  kind TEXT,
  text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_turns (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per model or transcription call, priced at write time. Spend caps sum this table.
CREATE TABLE IF NOT EXISTS usage (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  model TEXT,
  input_tokens INT DEFAULT 0,
  output_tokens INT DEFAULT 0,
  cached_tokens INT DEFAULT 0,
  seconds REAL DEFAULT 0,
  cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
  job_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_time ON usage(created_at);
CREATE INDEX IF NOT EXISTS usage_user_time ON usage(user_id, created_at);

-- Letterboxd, Goodreads, Substack and RSS sources, polled hourly.
CREATE TABLE IF NOT EXISTS connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'active',
  last_synced_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fixed-window counters. Old windows are deleted hourly.
CREATE TABLE IF NOT EXISTS rate_limits (
  key TEXT NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  count INT NOT NULL DEFAULT 0,
  PRIMARY KEY (key, window_start)
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value JSONB
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor_key_id UUID,
  user_id UUID,
  action TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT,
  token_hash TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL DEFAULT 'user',
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Six-digit login codes, bound to the phone they were sent to. Five guesses each.
CREATE TABLE IF NOT EXISTS login_challenges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  phone TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  attempts INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS login_challenges_phone ON login_challenges(phone, created_at DESC);

-- Webhook delivery ids already processed, so retries are no-ops.
CREATE TABLE IF NOT EXISTS webhook_events (
  id TEXT PRIMARY KEY,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
