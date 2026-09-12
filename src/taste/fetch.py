"""Turn a URL (or a bare title) into text Claude can read."""
import html as html_mod
import json
import re
import subprocess
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

import httpx
import trafilatura

from .config import MAX_TEXT_CHARS

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.5 Safari/605.1.15")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


@dataclass
class Extracted:
    kind: str
    url: str
    title: str = ""
    author: str = ""
    text: str = ""
    source: str = ""
    meta: dict = field(default_factory=dict)
    error: str = ""


def _client():
    return httpx.Client(headers=HEADERS, follow_redirects=True, timeout=25)


def resolve(url):
    """Follow short links (t.co, vm.tiktok.com, redd.it, ...) to the final URL."""
    try:
        with _client() as c:
            r = c.head(url)
            if r.status_code >= 400:
                r = c.get(url)
            return str(r.url)
    except Exception:
        return url


def _strip_query(url):
    p = urlparse(url)
    return urlunparse(p._replace(query="", fragment=""))


def classify(url):
    host = urlparse(url).netloc.lower().removeprefix("www.").removeprefix("m.")
    if host in ("x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com"):
        return "tweet"
    if host.endswith("reddit.com") or host == "redd.it":
        return "reddit"
    if "tiktok.com" in host:
        return "tiktok"
    if host in ("youtube.com", "youtu.be", "music.youtube.com"):
        return "youtube"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("goodreads.com") or (host.endswith("amazon.com") and "/dp/" in url):
        return "book"
    if url.lower().endswith(".pdf"):
        return "pdf"
    return "article"


def extract(url):
    if urlparse(url).netloc.lower() in ("t.co", "vm.tiktok.com", "vt.tiktok.com", "redd.it",
                                        "bit.ly", "tinyurl.com", "youtu.be", "a.co", "amzn.to"):
        url = resolve(url)
    kind = classify(url)
    fn = {
        "tweet": _tweet, "reddit": _reddit, "tiktok": _ytdlp, "youtube": _ytdlp,
        "instagram": _ytdlp, "book": _book_page, "pdf": _article, "article": _article,
    }[kind]
    try:
        ex = fn(url)
    except Exception as e:  # never let one bad fetch kill the daemon
        ex = Extracted(kind=kind, url=url, error=f"{type(e).__name__}: {e}")
    ex.kind = ex.kind or kind
    ex.text = (ex.text or "")[:MAX_TEXT_CHARS]
    return ex


# ---- tweets ----------------------------------------------------------------

def _tweet(url):
    m = re.search(r"/(?:status|statuses)/(\d+)", url)
    if not m:
        return _article(url)
    tid = m.group(1)
    with _client() as c:
        r = c.get(f"https://api.fxtwitter.com/status/{tid}")
        r.raise_for_status()
        t = r.json()["tweet"]
    parts = [t.get("text", "")]
    q = t.get("quote")
    if q:
        parts.append(f"\n[quoting @{q['author']['screen_name']}]: {q.get('text','')}")
    media = t.get("media") or {}
    alt = [m.get("altText") for m in media.get("all", []) if m.get("altText")]
    if alt:
        parts.append("\n[image alt text]: " + " | ".join(alt))
    author = t.get("author", {})
    return Extracted(
        kind="tweet", url=t.get("url", url),
        title=(t.get("text", "")[:80]).replace("\n", " "),
        author=f"{author.get('name','')} (@{author.get('screen_name','')})",
        text="\n".join(parts), source="x.com",
        meta={"likes": t.get("likes"), "replies": t.get("replies"), "created_at": t.get("created_at")},
    )


# ---- reddit ----------------------------------------------------------------

_reddit_token = {"value": None, "exp": 0}


def _reddit_auth():
    """Reddit blocks anonymous .json fetches. Use script-app OAuth (client_credentials)."""
    import os, time
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not sec:
        return None
    if _reddit_token["value"] and time.time() < _reddit_token["exp"] - 60:
        return _reddit_token["value"]
    with _client() as c:
        r = c.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec),
                   data={"grant_type": "client_credentials"},
                   headers={"User-Agent": "taste-agent/0.1 (personal reading assistant)"})
        r.raise_for_status()
        j = r.json()
    _reddit_token["value"] = j["access_token"]
    _reddit_token["exp"] = time.time() + int(j.get("expires_in", 3600))
    return j["access_token"]


def _reddit(url):
    clean = _strip_query(url).rstrip("/")
    m = re.search(r"/comments/([a-z0-9]+)", clean)
    if not m:
        return _article(url)
    post_id = m.group(1)
    token = _reddit_auth()
    with _client() as c:
        if token:
            r = c.get(f"https://oauth.reddit.com/comments/{post_id}", params={"raw_json": 1, "limit": 40},
                      headers={"Authorization": f"bearer {token}",
                               "User-Agent": "taste-agent/0.1 (personal reading assistant)"})
        else:
            r = c.get(clean + ".json", params={"raw_json": 1, "limit": 40})
        r.raise_for_status()
        data = r.json()
    post = data[0]["data"]["children"][0]["data"]
    parts = [f"r/{post.get('subreddit')} · {post.get('title')}", post.get("selftext", "")]
    link = post.get("url_overridden_by_dest") or ""
    if link and not post.get("is_self") and "reddit.com" not in link and "redd.it" not in link:
        try:
            linked = _article(link)
            if linked.text:
                parts.append(f"\n[linked page: {linked.title}]\n{linked.text[:8000]}")
        except Exception:
            pass
    comments = []
    for ch in data[1]["data"]["children"][:15]:
        d = ch.get("data", {})
        if ch.get("kind") != "t1" or not d.get("body"):
            continue
        comments.append(f"u/{d.get('author')} (+{d.get('score',0)}): {d['body']}")
    if comments:
        parts.append("\n--- top comments ---\n" + "\n\n".join(comments))
    return Extracted(
        kind="reddit", url=f"https://www.reddit.com{post.get('permalink', '')}" if post.get("permalink") else clean,
        title=post.get("title", ""), author=f"u/{post.get('author','')}",
        text="\n".join(p for p in parts if p), source=f"r/{post.get('subreddit')}",
        meta={"score": post.get("score"), "num_comments": post.get("num_comments"), "link": link},
    )


# ---- tiktok / youtube / instagram via yt-dlp --------------------------------

def _ytdlp(url):
    kind = classify(url)
    cmd = ["yt-dlp", "-J", "--no-warnings", "--skip-download", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if r.returncode != 0 or not r.stdout.strip():
        ex = _oembed(url, kind)
        if ex:
            return ex
        raise RuntimeError(r.stderr.strip()[-300:] or "yt-dlp failed")
    info = json.loads(r.stdout)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    title = info.get("title") or ""
    desc = info.get("description") or ""
    author = info.get("uploader") or info.get("channel") or info.get("creator") or ""
    parts = [f"{title}\n\n{desc}".strip()]
    transcript = _captions(info)
    if transcript:
        parts.append("\n--- transcript ---\n" + transcript)
    comments = [c.get("text") for c in (info.get("comments") or [])[:10] if c.get("text")]
    if comments:
        parts.append("\n--- comments ---\n" + "\n".join(comments))
    return Extracted(
        kind=kind, url=info.get("webpage_url") or url, title=title, author=author,
        text="\n".join(parts), source=info.get("extractor_key", kind),
        meta={"duration": info.get("duration"), "views": info.get("view_count"),
              "likes": info.get("like_count"), "has_transcript": bool(transcript)},
    )


def _captions(info):
    for key in ("subtitles", "automatic_captions"):
        subs = info.get(key) or {}
        for lang in ("en", "en-US", "en-GB", "en-orig", "eng-US"):
            for fmt in subs.get(lang, []):
                if fmt.get("ext") in ("json3", "vtt", "srv3"):
                    try:
                        return _fetch_caption(fmt["url"], fmt["ext"])
                    except Exception:
                        continue
    return ""


def _fetch_caption(url, ext):
    with _client() as c:
        body = c.get(url).text
    if ext == "json3":
        data = json.loads(body)
        words = []
        for ev in data.get("events", []):
            for seg in ev.get("segs", []) or []:
                words.append(seg.get("utf8", ""))
        text = "".join(words)
    else:
        lines = []
        for line in body.splitlines():
            if not line or "-->" in line or line.strip().isdigit() or line.startswith(("WEBVTT", "Kind:", "Language:")):
                continue
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line and (not lines or lines[-1] != line):
                lines.append(line)
        text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()[:20000]


def _oembed(url, kind):
    endpoints = {
        "tiktok": "https://www.tiktok.com/oembed",
        "youtube": "https://www.youtube.com/oembed",
        "instagram": None,
    }
    ep = endpoints.get(kind)
    if not ep:
        return None
    try:
        with _client() as c:
            d = c.get(ep, params={"url": url}).json()
        return Extracted(kind=kind, url=url, title=d.get("title", ""),
                         author=d.get("author_name", ""), text=d.get("title", ""),
                         source=d.get("provider_name", kind), meta={"oembed_only": True})
    except Exception:
        return None


# ---- articles ---------------------------------------------------------------

def _article(url):
    with _client() as c:
        r = c.get(url)
        r.raise_for_status()
        final = str(r.url)
        ctype = r.headers.get("content-type", "")
        if "pdf" in ctype or final.lower().endswith(".pdf"):
            return Extracted(kind="pdf", url=final, title=final.rsplit("/", 1)[-1],
                             text="", error="pdf extraction not implemented yet")
        html = r.text
    j = trafilatura.extract(html, url=final, output_format="json", with_metadata=True,
                            include_comments=False, favor_recall=True)
    if not j:
        raise RuntimeError("could not extract readable text")
    d = json.loads(j)
    return Extracted(
        kind="article", url=final, title=d.get("title") or "", author=d.get("author") or "",
        text=d.get("text") or "", source=d.get("sitename") or urlparse(final).netloc,
        meta={"date": d.get("date"), "description": d.get("description")},
    )


# ---- books ------------------------------------------------------------------

def _book_page(url):
    """Goodreads / Amazon page: grab the title from the page, then look it up."""
    title = ""
    try:
        with _client() as c:
            html = c.get(url).text
        m = re.search(r'<meta property="og:title" content="([^"]+)"', html) or \
            re.search(r"<title>([^<]+)</title>", html)
        if m:
            title = html_mod.unescape(m.group(1))
            title = re.sub(r"\s*(\||by|:)\s*(Goodreads|Amazon).*$", "", title)
            title = title.replace("…", "").strip()
    except Exception:
        pass
    query = title.split(":")[0].strip() if title else ""
    ex = lookup_book(query) if query else None
    if ex:
        ex.url = url
        return ex
    return Extracted(kind="book", url=url, title=title, text=title)


def lookup_book(query):
    """Open Library search -> title, author, year, description."""
    with _client() as c:
        r = c.get("https://openlibrary.org/search.json", params={"q": query, "limit": 3, "fields": "key,title,author_name,first_publish_year,subject"})
        r.raise_for_status()
        docs = r.json().get("docs") or []
        if not docs:
            return None
        d = docs[0]
        desc = ""
        try:
            w = c.get(f"https://openlibrary.org{d['key']}.json").json()
            desc = w.get("description") or ""
            if isinstance(desc, dict):
                desc = desc.get("value", "")
        except Exception:
            pass
    author = ", ".join(d.get("author_name") or [])
    subjects = ", ".join((d.get("subject") or [])[:12])
    text = f"{d.get('title')} by {author} ({d.get('first_publish_year','?')})\n\n{desc}\n\nsubjects: {subjects}"
    return Extracted(kind="book", url=f"https://openlibrary.org{d['key']}", title=d.get("title", query),
                     author=author, text=text, source="openlibrary",
                     meta={"year": d.get("first_publish_year")})
