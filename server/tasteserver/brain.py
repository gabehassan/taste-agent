"""All model calls. OpenAI Responses API. Every call records usage; callers check the spend gate first."""
import json
import time

from openai import OpenAI
from pydantic import BaseModel, Field

from . import db
from .config import MODEL
from .media import image_b64

_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI(timeout=120, max_retries=2)
    return _client

BASE_VOICE = (
    "You are texting {name} over iMessage. You are warm, curious, and a little playful: a sharp friend who reads "
    "everything they send and remembers it, not an assistant. Plain text only (no markdown, no bullet markers, no "
    "headers, no em dashes). Never explain what you are doing, never say 'as an AI', never apologise for being a bot. "
    "Match their texting style: {voice}. Short is good. One idea per text."
)


def voice_desc(user):
    v = (user.get("state") or {}).get("voice") or {}
    parts = []
    if v.get("lowercase", 0) > 0.7:
        parts.append("they write in lowercase, so do you")
    if v.get("avg_len", 0) and v["avg_len"] < 60:
        parts.append("they send short texts, keep yours short too")
    if v.get("emoji", 0) > 0.3:
        parts.append("they use emoji sometimes, you may too, sparingly")
    else:
        parts.append("no emoji unless they use them first")
    if v.get("exclaim", 0) > 0.3:
        parts.append("they are expressive, be warm and energetic")
    return "; ".join(parts) if parts else "casual, lowercase is fine, no emoji unless they use them first"


def voice(user):
    return BASE_VOICE.format(name=(user.get("name") or "them").split(" ")[0], voice=voice_desc(user))


def _usage(user_id, resp, job_id=None, kind="llm"):
    u = resp.usage
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
    return db.record_usage(user_id, kind, resp.model or MODEL, u.input_tokens, u.output_tokens, cached, job_id=job_id)


def _parse(user, instructions, content, schema, effort="medium", max_output_tokens=4000, job_id=None):
    resp = client().responses.parse(model=MODEL, instructions=instructions, input=[{"role": "user", "content": content}],
                                  text_format=schema, reasoning={"effort": effort}, max_output_tokens=max_output_tokens)
    _usage(user["id"], resp, job_id)
    out = resp.output_parsed
    if out is None:
        refusal = next((c.refusal for o in resp.output if o.type == "message" for c in o.content if c.type == "refusal"), None)
        raise RuntimeError(f"no parsed output ({refusal or resp.status})")
    return out


# ---- digest ---------------------------------------------------------------------

class Digest(BaseModel):
    title: str = Field(description="Clean, short title for the item")
    kind: str = Field(description="one of: article, essay, tweet, thread, reddit, tiktok, video, podcast, book, film, paper, screenshot, note, other")
    summary: str = Field(description="2 to 4 sentences. What it actually says, not what it is about.")
    snippets: list[str] = Field(description="2 to 5 passages worth coming back to. Verbatim quotes when the source has real text (max ~60 words each). For video, the sharpest lines from the transcript, or a tight paraphrase of the idea if there is no transcript.")
    tags: list[str] = Field(description="3 to 7 lowercase topic tags")
    why_saved: str = Field(description="One sentence guessing why they saved this, given their taste profile. Second person.")
    read_minutes: int = Field(description="Estimated minutes to read or watch the original")
    reaction: str = Field(description="The tapback to put on their message, one of: love, like, laugh, emphasize, none. love for things that clearly fit their taste, laugh for funny things, emphasize for surprising or intense, like otherwise.")
    ack: str = Field(description="The text reply to send right now. One or two short sentences, warm, specific: the single most interesting hook from the item, and if it connects to something they saved before, say so. Plain text, no markdown.")


DIGEST_SYSTEM = """

They send you things they want to read, watch, or remember: articles, tweets, reddit threads, tiktoks, books, screenshots, stray thoughts. Read each one closely and turn it into a record they can come back to. Quote the source precisely. Do not pad. If the source is thin (a tiktok with only a caption, a book with only a blurb), say what can be said and keep snippets short and honest rather than inventing detail. When frames from a video are attached, use them to understand what is shown, not just said.
"""


def digest(user, extracted, note="", images=(), transcript="", job_id=None):
    profile = db.latest_profile(user["id"])
    recent = db.list_items(user["id"], limit=8)
    header = (f"kind: {extracted.kind}\nurl: {extracted.url}\ntitle: {extracted.title}\nauthor: {extracted.author}\n"
              f"source: {extracted.source}\nmeta: {json.dumps(extracted.meta, default=str)}")
    if extracted.error:
        header += f"\nfetch error: {extracted.error}"
    body = extracted.text or "(no text could be extracted)"
    if transcript:
        body += f"\n\n--- transcript ---\n{transcript}"
    content = [{"type": "input_image", "detail": "auto", "image_url": image_b64(m, d)} for m, d in images]
    content.append({"type": "input_text", "text":
        f"<taste_profile>\n{profile['text'] if profile else '(no taste profile yet, this is one of the first items)'}\n</taste_profile>\n\n"
        f"<recently_saved>\n{_brief(recent)}\n</recently_saved>\n\n"
        f"<their_note>{note or '(none)'}</their_note>\n\n<item>\n{header}\n\n{body}\n</item>"})
    return _parse(user, voice(user) + DIGEST_SYSTEM, content, Digest, effort="medium", job_id=job_id)


# ---- profile --------------------------------------------------------------------

class Profile(BaseModel):
    profile: str = Field(description="The taste profile as plain prose paragraphs (no markdown). Sections in order: what you keep reaching for; how you like things said (tone, form, length); tensions or contradictions in what you save; what you have not saved but probably would love; what has shifted recently. Second person, specific, 250 to 500 words. Cite actual saved items by title when making a claim. Use ratings from letterboxd/goodreads as explicit signal when present.")
    observations: list[str] = Field(description="8 to 15 standalone one-liners about their taste that would be fun to receive as a random text from a friend. Second person, specific, each under 30 words, each referencing a real saved item or a concrete pattern, some connecting two items they may not have connected themselves. No em dashes.")
    one_liner: str = Field(description="A single sentence that captures their taste right now, under 25 words.")


PROFILE_SYSTEM = """

You maintain a living profile of their taste, built only from what they have actually sent you or rated. Be concrete and a little opinionated. Notice form as much as subject: long essays or one-line tweets, arguments or vibes, practical or contemplative. Notice what they reacted to (love, laugh) versus ignored. Update the previous profile rather than rewriting from scratch when one exists; keep what still holds, drop what no longer does, and say what changed.
"""


def refresh_profile(user, job_id=None):
    items = [i for i in db.list_items(user["id"], limit=250) if i["status"] != "pending"]
    if not items:
        return None
    prev = db.latest_profile(user["id"])
    lines = []
    for it in items:
        meta = it.get("meta") or {}
        extra = []
        if meta.get("rating") is not None:
            extra.append(f"rating: {meta['rating']}")
        if meta.get("reactions"):
            extra.append(f"their reactions: {', '.join(meta['reactions'])}")
        if it.get("note"):
            extra.append(f"their note: {it['note']}")
        if it.get("status") != "unread":
            extra.append(f"status: {it['status']}")
        lines.append(f"- [{it['kind']}] {it['title']} ({it.get('source') or ''}) saved {it['created_at']:%Y-%m-%d}"
                     f"\n  tags: {', '.join(it['tags'] or [])}\n  summary: {it['summary'] or ''}"
                     + ("".join(f"\n  {e}" for e in extra)))
    prompt = (f"<previous_profile>\n{prev['text'] if prev else '(none yet)'}\n</previous_profile>\n\n"
              f"<saved_items count=\"{len(items)}\" newest_first=\"true\">\n" + "\n".join(lines) + "\n</saved_items>")
    p = _parse(user, voice(user) + PROFILE_SYSTEM, [{"type": "input_text", "text": prompt}], Profile, effort="high",
               max_output_tokens=6000, job_id=job_id)
    db.save_profile(user["id"], p.profile, p.observations, p.one_liner, len(items))
    return p


# ---- chat -----------------------------------------------------------------------

TOOLS = [
    {"type": "function", "name": "search_items", "strict": False,
     "description": "Full-text search over their saved items (title, summary, tags, text, notes).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"type": "function", "name": "list_recent", "strict": False, "description": "Most recently saved items.",
     "parameters": {"type": "object", "properties": {"n": {"type": "integer"}, "status": {"type": "string"}}}},
    {"type": "function", "name": "get_item", "strict": False, "description": "One item in full, with snippets and text.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"type": "function", "name": "mark_item", "strict": False, "description": "Set an item's status: read, unread, archived.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}, "status": {"type": "string"}}, "required": ["id", "status"]}},
    {"type": "function", "name": "save_note", "strict": False,
     "description": "Save something they said as an item (a book they want to read, a thought, a recommendation someone gave them). Use when the message is clearly something to remember rather than a question.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "kind": {"type": "string"}, "text": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "kind", "text"]}},
]


def _run_tool(user, name, inp):
    uid = user["id"]
    if name == "search_items":
        return _brief(db.search_items(uid, inp["query"]))
    if name == "list_recent":
        return _brief(db.list_items(uid, limit=inp.get("n", 10), status=inp.get("status") or None))
    if name == "get_item":
        it = db.get_item(uid, inp["id"])
        if not it:
            return "no such item"
        it = dict(it); it["raw_text"] = (it.get("raw_text") or "")[:6000]; it.pop("tsv", None)
        return json.dumps(it, default=str)
    if name == "mark_item":
        if db.get_item(uid, inp["id"]):
            db.update_item(inp["id"], status=inp["status"])
        return "ok"
    if name == "save_note":
        from .fetch import lookup_book
        text = inp["text"]; url = None; author = ""; thumb = ""
        if inp["kind"] == "book":
            try:
                b = lookup_book(inp["title"])
                if b:
                    text, url, author, thumb = b.text, b.url, b.author, b.thumbnail
            except Exception:
                pass
        iid = db.add_item(uid, url=url, canonical_url=url, kind=inp["kind"], source="note", title=inp["title"], author=author,
                          raw_text=text, summary=inp["text"], tags=inp.get("tags") or [], snippets=[inp["text"]],
                          meta={"thumbnail": thumb})
        db.set_user_state(uid, items_since_profile=(db.user_state(uid).get("items_since_profile") or 0) + 1)
        return f"saved as item {iid}"
    return "unknown tool"


def _brief(items):
    return json.dumps([{"id": i["id"], "kind": i["kind"], "title": i["title"], "source": i.get("source"), "tags": i["tags"],
                        "status": i["status"], "url": i.get("url"), "summary": i["summary"], "saved": f"{i['created_at']:%Y-%m-%d}"}
                       for i in items], default=str)


CHAT_SYSTEM = """

You are their taste agent. They send you links and thoughts; you keep them, learn their taste, and text them bits back. Right now they texted something that is not a link. Figure out what they want: a question about their stuff (use the tools), a recommendation from their own queue, something to remember (save_note), a reaction to the last thing you sent, or just conversation. Reply like a friend would, a few sentences at most. If you list items, use short lines with the title and, if useful, the link. When they ask what to read, pick from their unread items and say why in one line each. If they are just reacting ("lol", "wow", "ok"), reply in kind, briefly, or with one follow-on thought.
"""


def chat(user, user_text, job_id=None):
    uid = user["id"]
    profile = db.latest_profile(uid)
    context = (f"<taste_profile>\n{profile['text'] if profile else '(none yet)'}\n</taste_profile>\n"
               f"<recent_items>\n{_brief(db.list_items(uid, limit=15))}\n</recent_items>\n"
               f"<last_thing_you_texted_them>\n{json.dumps(db.last_surface(uid), default=str)}\n</last_thing_you_texted_them>\n"
               f"<now>{time.strftime('%A %Y-%m-%d %H:%M')}</now>")
    inp = [{"role": "user", "content": [{"type": "input_text", "text": context}]}, {"role": "assistant", "content": "got it."}]
    for h in db.recent_chat(uid):
        inp.append({"role": h["role"], "content": h["content"]})
    inp.append({"role": "user", "content": user_text})
    instructions = voice(user) + CHAT_SYSTEM
    resp = client().responses.create(model=MODEL, instructions=instructions, input=inp, tools=TOOLS,
                                   reasoning={"effort": "medium"}, max_output_tokens=2000)
    _usage(uid, resp, job_id)
    for _ in range(6):
        calls = [o for o in resp.output if o.type == "function_call"]
        if not calls:
            break
        outputs = []
        for c in calls:
            try:
                result = _run_tool(user, c.name, json.loads(c.arguments or "{}"))
            except Exception as e:
                result = f"error: {e}"
            outputs.append({"type": "function_call_output", "call_id": c.call_id, "output": result})
        resp = client().responses.create(model=MODEL, instructions=instructions, previous_response_id=resp.id, input=outputs,
                                       tools=TOOLS, reasoning={"effort": "medium"}, max_output_tokens=2000)
        _usage(uid, resp, job_id)
    text = (resp.output_text or "").strip()
    db.add_chat(uid, "user", user_text)
    db.add_chat(uid, "assistant", text or "(no reply)")
    return text
