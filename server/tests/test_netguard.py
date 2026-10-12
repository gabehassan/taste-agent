import socket
from unittest.mock import patch

import pytest

from tasteserver import netguard


def answer(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "100.100.100.200",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fd12::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "fe80::1%en0",
    ],
)
def test_non_public_addresses_blocked(ip):
    with patch.object(netguard.socket, "getaddrinfo", return_value=answer(ip)), pytest.raises(netguard.Blocked):
        netguard.check_url("https://example.com/")


def test_public_address_allowed():
    with patch.object(netguard.socket, "getaddrinfo", return_value=answer("93.184.215.14")):
        assert netguard.check_url("https://example.com/") == "https://example.com/"


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://localhost/", "http://db.railway.internal/", "http://example.com:5432/"]
)
def test_schemes_hosts_and_ports_blocked(url):
    with pytest.raises(netguard.Blocked):
        netguard.check_url(url)


def test_rebinding_after_the_check_is_refused_at_connect():
    answers = [answer("93.184.215.14"), answer("127.0.0.1")]
    with (
        patch.object(netguard.socket, "getaddrinfo", side_effect=lambda *a, **k: answers.pop(0)),
        pytest.raises(netguard.Blocked),
    ):
        netguard.get("http://rebind.example/")
