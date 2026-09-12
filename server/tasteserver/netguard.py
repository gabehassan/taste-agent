"""SSRF-safe HTTP fetching: resolve the host, refuse private ranges, re-check on every redirect, cap size."""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from .config import MAX_FETCH_BYTES

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.5 Safari/605.1.15")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


class Blocked(Exception):
    pass


def check_url(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise Blocked(f"scheme {p.scheme!r} not allowed")
    host = p.hostname or ""
    if not host or host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        raise Blocked("host not allowed")
    if p.port and p.port not in (80, 443, 8080, 8443):
        raise Blocked("port not allowed")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise Blocked("dns failed")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or str(ip).startswith("169.254.") or str(ip) == "100.100.100.200"):
            raise Blocked(f"resolves to disallowed address {ip}")
    return url


def get(url, headers=None, params=None, timeout=25, max_bytes=MAX_FETCH_BYTES, max_redirects=5):
    """GET with redirect-by-redirect SSRF checks and a byte cap. Returns httpx.Response with .content."""
    h = dict(HEADERS); h.update(headers or {})
    with httpx.Client(headers=h, follow_redirects=False, timeout=timeout) as c:
        for _ in range(max_redirects + 1):
            check_url(url)
            with c.stream("GET", url, params=params) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = str(r.url.join(r.headers["location"]))
                    params = None
                    continue
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise Blocked("response too large")
                r._content = bytes(buf)
                return r
    raise Blocked("too many redirects")


def resolve(url):
    """Final URL after redirects (for short links), guarded."""
    try:
        r = get(url, max_bytes=512 * 1024, timeout=15)
        return str(r.url)
    except Blocked:
        raise
    except Exception:
        return url
