"""SSRF-safe HTTP fetching: public addresses only, checked at connect time, size-capped."""

import ipaddress
import socket
from urllib.parse import urlparse

import httpcore
import httpx

from .config import MAX_FETCH_BYTES

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


class Blocked(Exception):
    pass


def _public(ip):
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def resolve_public(host, port=443):
    """Resolve a host and return one address, refusing if any address it resolves to is not public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise Blocked("dns failed") from None
    addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not addresses:
        raise Blocked("dns failed")
    for ip in addresses:
        if not _public(ip):
            raise Blocked(f"resolves to disallowed address {ip}")
    return str(addresses[0])


def check_url(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise Blocked(f"scheme {p.scheme!r} not allowed")
    host = p.hostname or ""
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise Blocked("host not allowed")
    if p.port and p.port not in (80, 443, 8080, 8443):
        raise Blocked("port not allowed")
    resolve_public(host)
    return url


class _PinnedBackend(httpcore.SyncBackend):
    """Connects to the address that passed the check. Checking a name and then letting the client resolve it
    again would leave a DNS-rebinding window. TLS still verifies against the original hostname."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return super().connect_tcp(
            resolve_public(host, port),
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class _GuardedTransport(httpx.HTTPTransport):
    def __init__(self):
        super().__init__()
        self._pool = httpcore.ConnectionPool(ssl_context=httpx.create_ssl_context(), network_backend=_PinnedBackend())


def get(url, headers=None, params=None, timeout=25, max_bytes=MAX_FETCH_BYTES, max_redirects=5):
    """GET with per-hop URL checks, connect-time address checks and a byte cap. Returns httpx.Response."""
    h = dict(HEADERS)
    h.update(headers or {})
    with httpx.Client(
        headers=h, follow_redirects=False, timeout=timeout, transport=_GuardedTransport(), trust_env=False
    ) as c:
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
