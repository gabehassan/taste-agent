"""All model calls live here. Runs on OpenAI's Responses API (gpt-5.6-luna by default)."""
import base64
import json
import time

from openai import OpenAI
from pydantic import BaseModel, Field

from . import db
from .config import MODEL

client = OpenAI()

VOICE = (
    "You are texting Gabe over iMessage. Write like a sharp friend, not an assistant: "
    "short, lowercase is fine, plain text only (no markdown, no bullet lists, no headers, "
    "no em dashes, no emoji unless he uses them first). Never explain what you are doing. "
    "Never say 'as an AI'. Talk to him like a peer."
)


def _parse(instructions, content, schema, effort="medium", max_output_tokens=4000):
    resp = client.responses.parse(
        model=MODEL,
        instructions=instructions,
        input=[{"role": "user", "content": content}],
        text_format=schema,
        reasoning={"effort": effort},
        max_output_tokens=max_output_tokens,
    )
    out = resp.output_parsed
    if out is None:
        refusal = next((c.refusal for o in resp.output if o.type == "message" for c in o.content if c.type == "refusal"), None)
        raise RuntimeError(f"no parsed output ({refusal or resp.status})")
    return out


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
    header = (f"kind: {extracted.kind}\nurl: {extracted.url}\ntitle: {extracted.title}\nauthor: {extracted.author}\n"
              f"source: {extracted.source}\nmeta: {json.dumps(extracted.meta, default=str)}")
    if extracted.error:
        header += f"\nfetch error: {extracted.error}"
    body = extracted.text or "(no text could be extracted)"
    content = []
    if image:
        media, data = image
        content.append({"type": "input_image", "detail": "auto",
                        "image_url": f"data:{media};base64,{base64.standard_b64encode(data).decode()}"})
    content.append({"type": "input_text", "text":
        f"<taste_profile>\n{profile_text}\n</taste_profile>\n\n"
        f"<gabe_note>{note or '(none)'}</gabe_note>\n\n"
        f"<item>\n{header}\n\n{body}\n</item>"})
    return _parse(DIGEST_SYSTEM, content, Digest, effort="medium")


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
    items = [i for i in items if i["status"] != "pending"]
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
    p = _parse(PROFILE_SYSTEM, [{"type": "input_text", "text": prompt}], Profile, effort="high", max_output_tokens=6000)
    db.save_profile(p.profile, p.observations, len(items))
    db.set_state("one_liner", p.one_liner)
    return p


# ---- free-form chat with tools --------------------------------------------

TOOLS = [
    {"type": "function", "name": "search_items", "strict": False,
     "description": "Search Gabe's saved items by keyword (title, summary, tags, full text, his notes).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"type": "function", "name": "list_recent", "strict": False,
     "description": "List the most recently saved items.",
     "parameters": {"type": "object", "properties": {"n": {"type": "integer"}, "status": {"type": "string", "description": "unread, read, or omit for all"}}}},
    {"type": "function", "name": "get_item", "strict": False,
     "description": "Get one saved item in full, including its snippets and extracted text.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"type": "function", "name": "mark_item", "strict": False,
     "description": "Change an item's status: read, unread, or archived.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}, "status": {"type": "string"}}, "required": ["id", "status"]}},
    {"type": "function", "name": "save_note", "strict": False,
     "description": "Save something Gabe said as an item (a book he wants to read, a thought, a recommendation someone gave him). Use when his message is clearly something to remember rather than a question.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "kind": {"type": "string", "description": "book, note, film, album, idea, other"}, "text": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "kind", "text"]}},
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
    inp = [{"role": "user", "content": [{"type": "input_text", "text": context}]},
           {"role": "assistant", "content": "got it."}]
    for h in db.recent_chat():
        inp.append({"role": h["role"], "content": h["content"]})
    inp.append({"role": "user", "content": user_text})

    resp = client.responses.create(model=MODEL, instructions=CHAT_SYSTEM, input=inp, tools=TOOLS,
                                   reasoning={"effort": "medium"}, max_output_tokens=2000)
    for _ in range(6):
        calls = [o for o in resp.output if o.type == "function_call"]
        if not calls:
            break
        outputs = []
        for c in calls:
            try:
                result = _run_tool(c.name, json.loads(c.arguments or "{}"))
            except Exception as e:
                result = f"error: {e}"
            outputs.append({"type": "function_call_output", "call_id": c.call_id, "output": result})
        resp = client.responses.create(model=MODEL, instructions=CHAT_SYSTEM, previous_response_id=resp.id,
                                       input=outputs, tools=TOOLS, reasoning={"effort": "medium"},
                                       max_output_tokens=2000)
    text = (resp.output_text or "").strip()
    db.add_chat("user", user_text)
    db.add_chat("assistant", text or "(no reply)")
    return text
