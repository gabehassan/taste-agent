"""URL -> text. Every network call goes through netguard (SSRF-safe, size-capped)."""

import html as html_mod
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import trafilatura

from . import netguard
from .config import MAX_TEXT_CHARS, YTDLP_PROXY

TRACKERS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "igshid",
    "si",
    "ref_src",
    "ref_url",
    "s",
    "t",
    "feature",
    "_r",
    "mc_cid",
    "mc_eid",
}
SHORTENERS = {
    "t.co",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "redd.it",
    "bit.ly",
    "tinyurl.com",
    "youtu.be",
    "a.co",
    "amzn.to",
    "lnkd.in",
    "buff.ly",
    "ow.ly",
    "l.instagram.com",
}


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
    media_url: str = ""  # set when yt-dlp found downloadable media
    thumbnail: str = ""


def canonical(url):
    p = urlparse(url)
    qs = [(k, v) for k, v in parse_qsl(p.query) if k not in TRACKERS]
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.").removeprefix("mobile.")
    if host in ("twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com"):
        host = "x.com"
    path = p.path.rstrip("/") or "/"
    if host == "youtube.com" and path == "/watch":
        qs = [(k, v) for k, v in qs if k == "v"]
    return urlunparse((p.scheme or "https", host, path, "", urlencode(qs), ""))


def _on(host, domain):
    return host == domain or host.endswith("." + domain)


def classify(url):
    # Exact domain matching matters: tiktok/youtube/instagram URLs go to yt-dlp, which does its own networking.
    host = (urlparse(url).hostname or "").removeprefix("www.").removeprefix("m.")
    if host in ("x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com"):
        return "tweet"
    if _on(host, "reddit.com") or host == "redd.it":
        return "reddit"
    if _on(host, "tiktok.com"):
        return "tiktok"
    if host in ("youtube.com", "youtu.be", "music.youtube.com"):
        return "youtube"
    if _on(host, "instagram.com"):
        return "instagram"
    if _on(host, "goodreads.com") or (_on(host, "amazon.com") and "/dp/" in url):
        return "book"
    if _on(host, "letterboxd.com") and "/film/" in url:
        return "film"
    if url.lower().endswith(".pdf"):
        return "pdf"
    return "article"


def extract(url):
    if urlparse(url).netloc.lower() in SHORTENERS:
        url = netguard.resolve(url)
    netguard.check_url(url)
    kind = classify(url)
    fn = {
        "tweet": _tweet,
        "reddit": _reddit,
        "tiktok": _ytdlp,
        "youtube": _ytdlp,
        "instagram": _ytdlp,
        "book": _book_page,
        "film": _article,
        "pdf": _article,
        "article": _article,
    }[kind]
    try:
        ex = fn(url)
    except netguard.Blocked:
        raise
    except Exception as e:
        ex = Extracted(kind=kind, url=url, error=f"{type(e).__name__}: {str(e)[:300]}")
    ex.kind = ex.kind or kind
    ex.text = (ex.text or "")[:MAX_TEXT_CHARS]
    return ex


# ---- tweets ----------------------------------------------------------------


def _tweet(url):
    m = re.search(r"/(?:status|statuses)/(\d+)", url)
    if not m:
        return _article(url)
    r = netguard.get(f"https://api.fxtwitter.com/status/{m.group(1)}")
    r.raise_for_status()
    t = r.json()["tweet"]
    parts = [t.get("text", "")]
    q = t.get("quote")
    if q:
        parts.append(f"\n[quoting @{q['author']['screen_name']}]: {q.get('text', '')}")
    media = t.get("media") or {}
    alt = [x.get("altText") for x in media.get("all", []) if x.get("altText")]
    if alt:
        parts.append("\n[image alt text]: " + " | ".join(alt))
    videos = [x for x in media.get("all", []) if x.get("type") in ("video", "gif")]
    photos = [x for x in media.get("all", []) if x.get("type") == "photo"]
    author = t.get("author", {})
    return Extracted(
        kind="tweet",
        url=t.get("url", url),
        title=(t.get("text", "")[:80]).replace("\n", " "),
        author=f"{author.get('name', '')} (@{author.get('screen_name', '')})",
        text="\n".join(parts),
        source="x.com",
        meta={
            "likes": t.get("likes"),
            "replies": t.get("replies"),
            "created_at": t.get("created_at"),
            "photos": [p.get("url") for p in photos][:4],
            "author_avatar": author.get("avatar_url"),
        },
        media_url=url if videos else "",
        thumbnail=(photos[0].get("url") if photos else ""),
    )


# ---- reddit ----------------------------------------------------------------

_reddit_token = {"value": None, "exp": 0}


def _reddit_auth():
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not sec:
        return None
    if _reddit_token["value"] and time.time() < _reddit_token["exp"] - 60:
        return _reddit_token["value"]
    r = httpx.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(cid, sec),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": "taste-agent/0.2 (personal reading assistant)"},
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    _reddit_token["value"] = j["access_token"]
    _reddit_token["exp"] = time.time() + int(j.get("expires_in", 3600))
    return j["access_token"]


def _reddit(url):
    m = re.search(r"/comments/([a-z0-9]+)", url)
    if not m:
        return _article(url)
    token = _reddit_auth()
    if not token:
        raise RuntimeError("reddit credentials not configured")
    r = netguard.get(
        f"https://oauth.reddit.com/comments/{m.group(1)}",
        params={"raw_json": 1, "limit": 40},
        headers={"Authorization": f"bearer {token}", "User-Agent": "taste-agent/0.2"},
    )
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
    comments = [
        f"u/{d.get('author')} (+{d.get('score', 0)}): {d['body']}"
        for ch in data[1]["data"]["children"][:15]
        if ch.get("kind") == "t1" and (d := ch.get("data", {})).get("body")
    ]
    if comments:
        parts.append("\n--- top comments ---\n" + "\n\n".join(comments))
    return Extracted(
        kind="reddit",
        url=f"https://www.reddit.com{post.get('permalink', '')}",
        title=post.get("title", ""),
        author=f"u/{post.get('author', '')}",
        text="\n".join(p for p in parts if p),
        source=f"r/{post.get('subreddit')}",
        meta={"score": post.get("score"), "num_comments": post.get("num_comments"), "link": link},
        thumbnail=post.get("thumbnail") if str(post.get("thumbnail", "")).startswith("http") else "",
    )


# ---- anything yt-dlp knows ---------------------------------------------------


def ytdlp_info(url, timeout=90):
    cmd = ["yt-dlp", "-J", "--no-warnings", "--skip-download", "--no-playlist", "--socket-timeout", "30"]
    if YTDLP_PROXY:
        cmd += ["--proxy", YTDLP_PROXY]
    r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError((r.stderr or "yt-dlp failed").strip()[-300:])
    info = json.loads(r.stdout)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    return info


def _ytdlp(url):
    kind = classify(url)
    try:
        info = ytdlp_info(url)
    except Exception as e:
        ex = _oembed(url, kind)
        if ex:
            ex.error = f"yt-dlp: {str(e)[:200]}"
            return ex
        raise
    title = info.get("title") or ""
    desc = info.get("description") or ""
    author = info.get("uploader") or info.get("channel") or info.get("creator") or ""
    parts = [f"{title}\n\n{desc}".strip()]
    transcript = _captions(info)
    if transcript:
        parts.append("\n--- captions ---\n" + transcript)
    comments = [c.get("text") for c in (info.get("comments") or [])[:10] if c.get("text")]
    if comments:
        parts.append("\n--- comments ---\n" + "\n".join(comments))
    return Extracted(
        kind=kind,
        url=info.get("webpage_url") or url,
        title=title,
        author=author,
        text="\n".join(parts),
        source=info.get("extractor_key", kind),
        meta={
            "duration": info.get("duration"),
            "views": info.get("view_count"),
            "likes": info.get("like_count"),
            "has_captions": bool(transcript),
            "upload_date": info.get("upload_date"),
            "author_avatar": next(
                (t.get("url") for t in (info.get("thumbnails") or []) if str(t.get("id", "")).startswith("avatar")),
                None,
            ),
        },
        media_url=url if info.get("duration") else "",
        thumbnail=info.get("thumbnail") or "",
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
    body = netguard.get(url).text
    if ext == "json3":
        text = "".join(
            seg.get("utf8", "") for ev in json.loads(body).get("events", []) for seg in (ev.get("segs") or [])
        )
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
    ep = {"tiktok": "https://www.tiktok.com/oembed", "youtube": "https://www.youtube.com/oembed"}.get(kind)
    if not ep:
        return None
    try:
        d = netguard.get(ep, params={"url": url}).json()
        return Extracted(
            kind=kind,
            url=url,
            title=d.get("title", ""),
            author=d.get("author_name", ""),
            text=d.get("title", ""),
            source=d.get("provider_name", kind),
            meta={"oembed_only": True},
            thumbnail=d.get("thumbnail_url", ""),
        )
    except Exception:
        return None


# ---- articles ---------------------------------------------------------------


def _article(url):
    r = netguard.get(url)
    r.raise_for_status()
    final = str(r.url)
    if "pdf" in r.headers.get("content-type", "") or final.lower().endswith(".pdf"):
        return Extracted(
            kind="pdf", url=final, title=final.rsplit("/", 1)[-1], text="", error="pdf extraction not implemented yet"
        )
    j = trafilatura.extract(
        r.text, url=final, output_format="json", with_metadata=True, include_comments=False, favor_recall=True
    )
    if not j:
        raise RuntimeError("could not extract readable text")
    d = json.loads(j)
    m = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
    return Extracted(
        kind="article",
        url=final,
        title=d.get("title") or "",
        author=d.get("author") or "",
        text=d.get("text") or "",
        source=d.get("sitename") or urlparse(final).netloc,
        meta={"date": d.get("date"), "description": d.get("description")},
        thumbnail=html_mod.unescape(m.group(1)) if m else "",
    )


# ---- books ------------------------------------------------------------------


def _book_page(url):
    title = ""
    try:
        html = netguard.get(url).text
        m = re.search(r'<meta property="og:title" content="([^"]+)"', html) or re.search(
            r"<title>([^<]+)</title>", html
        )
        if m:
            title = html_mod.unescape(m.group(1))
            title = re.sub(r"\s*(\||by|:)\s*(Goodreads|Amazon).*$", "", title).replace("…", "").strip()
    except Exception:
        pass
    query = title.split(":")[0].strip() if title else ""
    ex = lookup_book(query) if query else None
    if ex:
        ex.url = url
        return ex
    return Extracted(kind="book", url=url, title=title, text=title)


def lookup_book(query):
    r = netguard.get(
        "https://openlibrary.org/search.json",
        params={"q": query, "limit": 3, "fields": "key,title,author_name,first_publish_year,subject,cover_i"},
    )
    r.raise_for_status()
    docs = r.json().get("docs") or []
    if not docs:
        return None
    d = docs[0]
    desc = ""
    try:
        w = netguard.get(f"https://openlibrary.org{d['key']}.json").json()
        desc = w.get("description") or ""
        if isinstance(desc, dict):
            desc = desc.get("value", "")
    except Exception:
        pass
    author = ", ".join(d.get("author_name") or [])
    subjects = ", ".join((d.get("subject") or [])[:12])
    text = f"{d.get('title')} by {author} ({d.get('first_publish_year', '?')})\n\n{desc}\n\nsubjects: {subjects}"
    cover = f"https://covers.openlibrary.org/b/id/{d['cover_i']}-L.jpg" if d.get("cover_i") else ""
    return Extracted(
        kind="book",
        url=f"https://openlibrary.org{d['key']}",
        title=d.get("title", query),
        author=author,
        text=text,
        source="openlibrary",
        meta={"year": d.get("first_publish_year")},
        thumbnail=cover,
    )
