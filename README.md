# taste

An iMessage agent that learns what you like from what you send it.

Text yourself (the "message to self" thread on iMessage) a link, a screenshot, a book title, or a stray thought. The agent reads it, files it, replies with the one interesting hook, and keeps a living profile of your taste. A few times a day it texts you a snippet from something you saved, or an observation about what you keep reaching for.

Everything runs on this Mac. Messages are read from `~/Library/Messages/chat.db` and sent through Messages.app with AppleScript. Nothing goes to a third-party iMessage provider. Content and the taste profile go to the Claude API.

## What it understands

| You send | It does |
|---|---|
| article / essay / blog link | full text via trafilatura, summary, 2 to 5 verbatim snippets, tags |
| x.com / twitter link | tweet text, quoted tweet, image alt text (via fxtwitter) |
| reddit link | post + top comments, and the linked page if it is a link post (Reddit OAuth) |
| tiktok / youtube / instagram | title, caption, transcript when captions exist (yt-dlp) |
| goodreads / amazon book link, or just a title | Open Library lookup: author, year, blurb |
| screenshot | Claude reads the image |
| anything else | free-form chat with tools over your saved items |

Words it treats as commands: `taste` (send the profile), `hit me` (surface something now), `more` (another snippet from the same item), `read` (mark the last one read), `status`, `pause`, `resume`, `help`.

## Layout

```
src/taste/
  imessage.py   read chat.db, send via AppleScript (the only iMessage-specific file)
  fetch.py      URL -> text for each source type
  brain.py      Claude calls: digest, taste profile, chat with tools
  scheduler.py  when to surface, what to pick
  daemon.py     poll loop, commands, replies
  cli.py        `taste` command
data/           sqlite db + log (gitignored)
.env            ANTHROPIC_API_KEY, REDDIT_CLIENT_ID/SECRET (gitignored)
```

## Commands

```bash
.venv/bin/taste run            # foreground daemon
.venv/bin/taste ingest URL     # save something without iMessage
.venv/bin/taste surface --dry  # print what it would send next
.venv/bin/taste profile --refresh
.venv/bin/taste chat "what should i read tonight"
.venv/bin/taste status
.venv/bin/taste items
.venv/bin/taste install        # launchd agent (com.gabe.taste-agent), starts at login
.venv/bin/taste uninstall
.venv/bin/taste logs
```

## Config

Environment variables (put them in `.env`):

- `TASTE_SELF_HANDLES` comma-separated handles that count as you (default `you@example.com`)
- `TASTE_MODEL` default `claude-opus-5`
- `TASTE_SURFACES_PER_DAY` default 3, between `TASTE_WAKE_START` (10) and `TASTE_WAKE_END` (22) local time
- `TASTE_MIN_GAP_MINUTES` default 90

## Permissions

The process that runs the daemon needs Full Disk Access (to read `chat.db`) and Automation access to Messages (to send). Under launchd that process is the Python binary in `.venv`, which resolves to the uv-managed CPython at `~/.local/share/uv/python/...`. If the log shows `unable to open database` or `Not authorized to send Apple events`, add that binary in System Settings > Privacy & Security > Full Disk Access and > Automation.

## Notes

- The agent's own replies land in the same self-chat. They are recognised by matching against the last 48h of sent texts and skipped.
- Links that fail to digest (no API credits, site down) are stored as `pending` and retried every 10 minutes.
- A hard cap of 20 sends per hour protects against runaway loops.
