import os

DATABASE_URL = os.environ["DATABASE_URL"]
MODEL = os.environ.get("TASTE_MODEL", "gpt-5.6-luna")
TRANSCRIBE_MODEL = os.environ.get("TASTE_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "")
# Public dashboard address, used for links in texts.
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:3000")
# Time zone for new users until they set their own. Schedules and quiet hours use it.
DEFAULT_TZ = os.environ.get("TASTE_DEFAULT_TZ", "UTC")

# Rate limits key on the caller's address. X-Forwarded-For is client-controlled, so the address comes from a header
# the platform edge overwrites (Railway sets X-Real-IP). Set CLIENT_IP_HEADER="" to use the socket address.
CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "x-real-ip").lower()
# The dashboard calls the API server-side, so it forwards the browser's address alongside this shared secret.
DASHBOARD_PROXY_SECRET = os.environ.get("DASHBOARD_PROXY_SECRET", "")

# object storage (S3 compatible: Railway bucket or Cloudflare R2)
# Named S3_* on purpose: AWS_* names leak into Railway's own builder and break image pushes.
S3_ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_REGION = os.environ.get("S3_REGION", "auto")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY_ID", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", "")

YTDLP_PROXY = os.environ.get("YTDLP_PROXY", "")
YTDLP_COOKIES_B64 = os.environ.get("YTDLP_COOKIES_B64", "")

WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "2"))
JOB_TIMEOUT_SECONDS = int(os.environ.get("JOB_TIMEOUT_SECONDS", "300"))

# hard limits (not user-tunable)
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 6 * 1024 * 1024
MAX_FETCH_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 40_000
MAX_MEDIA_MB = 200
MAX_MEDIA_SECONDS = 3600
MAX_AUDIO_BYTES = 25 * 1024 * 1024

DEFAULT_SETTINGS = {
    "global_daily_cap_usd": 10.0,
    "global_monthly_cap_usd": 150.0,
    "default_user_daily_cap_usd": 2.0,
    "surfaces_per_day": 3,
    "wake_start": 10,
    "wake_end": 22,
    "min_gap_minutes": 90,
    "observation_chance": 0.25,
    "profile_refresh_every": 5,
    "profile_max_age_hours": 24,
    "rate_ip_per_min": 120,
    "rate_key_per_hour": 600,
    "rate_inbound_per_hour": 60,
    "rate_inbound_per_day": 300,
    "rate_ingest_per_day": 100,
    "rate_chat_per_day": 100,
    "rate_outbound_per_hour": 20,
    "open_signup": False,
    # USD per 1M tokens (in/out/cached) or per minute of audio. EDIT in dashboard if wrong.
    "model_prices": {
        "gpt-5.6-luna": {"in": 0.20, "out": 1.20, "cached_in": 0.02},
        "gpt-4o-mini-transcribe": {"per_minute": 0.003},
        "gpt-4o-transcribe": {"per_minute": 0.006},
    },
}
