import os
import pathlib

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / "taste.sqlite"
LOG_PATH = DATA / "taste.log"
CHAT_DB = pathlib.Path.home() / "Library/Messages/chat.db"

# The iMessage handles that count as "you". Texts sent to yourself land in a
# chat whose chat_identifier is one of these.
SELF_HANDLES = [
    h.strip()
    for h in os.environ.get("TASTE_SELF_HANDLES", "you@example.com").split(",")
    if h.strip()
]
SEND_TO = os.environ.get("TASTE_SEND_TO", SELF_HANDLES[0])

MODEL = os.environ.get("TASTE_MODEL", "claude-opus-5")
POLL_SECONDS = int(os.environ.get("TASTE_POLL_SECONDS", "5"))

# Resurfacing schedule (local time).
SURFACES_PER_DAY = int(os.environ.get("TASTE_SURFACES_PER_DAY", "3"))
WAKE_START = int(os.environ.get("TASTE_WAKE_START", "10"))
WAKE_END = int(os.environ.get("TASTE_WAKE_END", "22"))
MIN_GAP_MINUTES = int(os.environ.get("TASTE_MIN_GAP_MINUTES", "90"))
OBSERVATION_CHANCE = 0.25  # share of surfaces that are a taste observation, not a snippet

PROFILE_REFRESH_EVERY = 5  # new items
PROFILE_MAX_AGE_HOURS = 24

MAX_SENDS_PER_HOUR = 20  # hard safety cap
MAX_TEXT_CHARS = 40_000  # cap on extracted content passed to Claude
