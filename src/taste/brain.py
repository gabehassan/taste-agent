"""All Claude calls live here."""
import base64
import json
import time

import anthropic
from pydantic import BaseModel, Field

from . import db
from .config import MODEL

client = anthropic.Anthropic()
BETAS = ["server-side-fallback-2026-07-01"]

VOICE = (
    "You are texting Gabe over iMessage. Write like a sharp friend, not an assistant: "
    "short, lowercase is fine, plain text only (no markdown, no bullet lists, no headers, "
    "no em dashes, no emoji unless he uses them first). Never explain what you are doing. "
    "Never say 'as an AI'. Talk to him like a peer."
)


# ---- digest a saved item ---------------------------------------------------

class Digest(BaseModel):
    title: str = Field(description="Clean, short title for the item")
    kind: str = Field(description="one of: article, essay, tweet, thread, reddit, tiktok, video, podcast, book, paper, note, other")
    summary: str = Field(description="2 to 4 sentences. What it actually says, not what it is about.")
    snippets: list[str] = Field(description="2 to 5 passages worth coming back to. Verbatim quotes when the source has real text (max ~60 words each). For videos with no transcript, the sharpest paraphrase of the idea.")
    tags: list[str] = Field(description="3 to 7 lowercase topic tags")
    why_saved: str = Field(description="One sentence guessing why Gabe saved this, given his taste profile. Second person.")
    read_minutes: int = Field(description="Estimated minutes to read or watch the original")
    ack: str = Field(description="The iMessage reply to send back right now. One or two short sentences: confirm it is saved and give the single most interesting hook from it. Plain text, no markdown.")


DIGEST_SYSTEM = VOICE + """

Gabe sends you things he wants to read, watch, or remember: articles, tweets, reddit threads, tiktoks, books, screenshots, stray thoughts. Your job is to read each one closely and turn it into a record he can come back to. Quote the source precisely. Do not pad. If the source text is thin (a tiktok with only a caption, a book with only a blurb), say what can be said and keep snippets short and honest rather than inventing detail.
"""


def digest(extracted, note="", image=None):
    profile = db.latest_profile()
    profile_text = profile["text"] if profile else "(no taste profile yet, this is one of the first items)"
    header = f"kind: {extracted.kind}\nurl: {extracted.url}\ntitle: {extracted.title}\nauthor: {extracted.author}\nsource: {extracted.source}\nmeta: {json.dumps(extracted.meta, default=str)}"
    if extracted.error:
        header += f"\nfetch error: {extracted.error}"
    body = extracted.text or "(no text could be extracted)"
    content = []
    if image:
        media, data = image
        content.append({"type": "image", "source": {"type": "base64", "media_type": media,
                                                     "data": base64.standard_b64encode(data).decode()}})
    content.append({"type": "text", "text":
        f"<taste_profile>\n{profile_text}\n</taste_profile>\n\n"
        f"<gabe_note>{note or '(none)'}</gabe_note>\n\n"
        f"<item>\n{header}\n\n{body}\n</item>"})
    resp = client.beta.messages.parse(
        model=MODEL, max_tokens=4000, betas=BETAS, fallbacks="default",
        thinking={"type": "adaptive"}, output_config={"effort": "medium"},
        system=[{"type": "text", "text": DIGEST_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_format=Digest,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {resp.stop_details}")
    return resp.parsed_output


# ---- taste profile ---------------------------------------------------------

class Profile(BaseModel):
    profile: str = Field(description="The taste profile as plain prose paragraphs (no markdown). Sections in order: what you keep reaching for; how you like things said (tone, form, length); tensions or contradictions in what you save; what you have not saved but probably would love; what has shifted recently. Second person, specific, 250 to 500 words. Cite actual saved items by title when making a claim.")
    observations: list[str] = Field(description="8 to 15 standalone one-liners about Gabe's taste that would be fun to receive as a random text. Second person, specific, each under 30 words, each referencing a real saved item or a concrete pattern. No em dashes.")
    one_liner: str = Field(description="A single sentence that captures his taste right now, under 25 words.")


PROFILE_SYSTEM = VOICE + """

You maintain a living profile of Gabe's taste, built only from what he has actually sent you. Be concrete and a little opinionated. Notice form as much as subject: does he save long essays or one-line tweets, arguments or vibes, practical or contemplative. Update the previous profile rather than rewriting from scratch when one exists; keep what still holds, drop what no longer does, and say what changed.
"""


def refresh_profile():
    items = db.list_items(limit=200)
    if not items:
        return None
    prev = db.latest_profile()
    lines = []
    for it in items:
        lines.append(
            f"- [{it['kind']}] {it['title']} ({it.get('source') or ''}) saved {time.strftime('%Y-%m-%d', time.localtime(it['created_at']))}"
            f"\n  tags: {', '.join(it['tags'])}\n  summary: {it['summary']}"
            + (f"\n  his note: {it['note']}" if it.get("note") else "")
            + (f"\n  status: {it['status']}" if it.get("status") != "unread" else "")
        )
    prompt = (
        f"<previous_profile>\n{prev['text'] if prev else '(none yet)'}\n</previous_profile>\n\n"
        f"<saved_items count=\"{len(items)}\" newest_first=\"true\">\n" + "\n".join(lines) + "\n</saved_items>"
    )
    resp = client.beta.messages.parse(
        model=MODEL, max_tokens=6000, betas=BETAS, fallbacks="default",
        thinking={"type": "adaptive"}, output_config={"effort": "high"},
        system=PROFILE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=Profile,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {resp.stop_details}")
    p = resp.parsed_output
    db.save_profile(p.profile, p.observations, len(items))
    db.set_state("one_liner", p.one_liner)
    return p


# ---- free-form chat with tools --------------------------------------------

TOOLS = [
    {"name": "search_items", "description": "Search Gabe's saved items by keyword (title, summary, tags, full text, his notes).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "list_recent", "description": "List the most recently saved items.",
     "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}, "status": {"type": "string", "description": "unread, read, or omit for all"}}}},
    {"name": "get_item", "description": "Get one saved item in full, including its snippets and extracted text.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "mark_item", "description": "Change an item's status: read, unread, or archived.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}, "status": {"type": "string"}}, "required": ["id", "status"]}},
    {"name": "save_note", "description": "Save something Gabe said as an item (a book he wants to read, a thought, a recommendation someone gave him). Use when his message is clearly something to remember rather than a question.",
     "input_schema": {"type": "object", "properties": {"title": {"type": "string"}, "kind": {"type": "string", "description": "book, note, film, album, idea, other"}, "text": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "kind", "text"]}},
]


def _run_tool(name, inp):
    if name == "search_items":
        return _brief(db.search_items(inp["query"]))
    if name == "list_recent":
        return _brief(db.list_items(limit=inp.get("n", 10), status=inp.get("status") or None))
    if name == "get_item":
        it = db.get_item(inp["id"])
        if not it:
            return "no such item"
        it = dict(it); it["raw_text"] = (it.get("raw_text") or "")[:6000]
        return json.dumps(it, default=str)
    if name == "mark_item":
        db.update_item(inp["id"], status=inp["status"])
        return "ok"
    if name == "save_note":
        from .fetch import lookup_book
        text = inp["text"]; url = None; author = ""
        if inp["kind"] == "book":
            try:
                b = lookup_book(inp["title"])
                if b:
                    text = b.text; url = b.url; author = b.author
            except Exception:
                pass
        iid = db.add_item(url=url, kind=inp["kind"], source="note", title=inp["title"], author=author,
                          raw_text=text, summary=inp["text"], tags=inp.get("tags") or [], snippets=[inp["text"]][:1])
        db.set_state("items_since_profile", (db.get_state("items_since_profile", 0) or 0) + 1)
        return f"saved as item {iid}"
    return "unknown tool"


def _brief(items):
    return json.dumps([{"id": i["id"], "kind": i["kind"], "title": i["title"], "source": i.get("source"),
                        "tags": i["tags"], "status": i["status"], "url": i.get("url"),
                        "summary": i["summary"], "saved": time.strftime("%Y-%m-%d", time.localtime(i["created_at"]))}
                       for i in items], default=str)


CHAT_SYSTEM = VOICE + """

You are Gabe's taste agent. He sends you links and thoughts; you keep them, learn his taste, and text him snippets to come back to. Right now he has texted you something that is not a link. Figure out what he wants: a question about his stuff (use the tools), a recommendation from his own queue, something to remember (save_note), a reaction to the last thing you sent, or just conversation. Keep replies to a few sentences, the length of a normal text. If you list items, use short lines with the title and, if useful, the link, not bullet markers. When he asks what to read, pick from his unread items and say why in one line each.
"""


def chat(user_text):
    profile = db.latest_profile()
    recent = db.list_items(limit=15)
    last = db.last_surface()
    context = (
        f"<taste_profile>\n{profile['text'] if profile else '(none yet)'}\n</taste_profile>\n"
        f"<recent_items>\n{_brief(recent)}\n</recent_items>\n"
        f"<last_thing_you_texted_him>\n{json.dumps(last, default=str) if last else '(nothing yet)'}\n</last_thing_you_texted_him>\n"
        f"<now>{time.strftime('%A %Y-%m-%d %H:%M')}</now>"
    )
    history = db.recent_chat()
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": user_text})
    system = [{"type": "text", "text": CHAT_SYSTEM, "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": context}]
    for _ in range(6):
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=2000, betas=BETAS, fallbacks="default",
            thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            system=system, tools=TOOLS, messages=messages,
        )
        if resp.stop_reason == "refusal":
            return "can't help with that one"
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                try:
                    out = _run_tool(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"error: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
    text = " ".join(b.text for b in resp.content if b.type == "text").strip()
    db.add_chat("user", user_text)
    db.add_chat("assistant", text or "(no reply)")
    return text
