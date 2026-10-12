from unittest.mock import patch

from starlette.requests import Request

from tasteserver import ratelimit


def request(headers):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": ("10.0.0.9", 1234)})


def test_forwarded_for_is_never_trusted():
    assert ratelimit.client_ip(request({"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"})) == "5.6.7.8"
    assert ratelimit.client_ip(request({"X-Forwarded-For": "1.2.3.4"})) == "10.0.0.9"


def test_dashboard_forwarding_needs_the_secret():
    forged = {"X-Taste-Client-IP": "1.1.1.1", "X-Taste-Proxy-Secret": "guess", "X-Real-IP": "5.6.7.8"}
    with patch.object(ratelimit, "DASHBOARD_PROXY_SECRET", "s3cret"):
        assert ratelimit.client_ip(request(forged)) == "5.6.7.8"
        assert ratelimit.client_ip(request({**forged, "X-Taste-Proxy-Secret": "s3cret"})) == "1.1.1.1"
    with patch.object(ratelimit, "DASHBOARD_PROXY_SECRET", ""):
        assert ratelimit.client_ip(request({"X-Taste-Client-IP": "1.1.1.1", "X-Taste-Proxy-Secret": ""})) == "10.0.0.9"
