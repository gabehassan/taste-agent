import pytest

from tasteserver.fetch import canonical, classify


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://www.tiktok.com/@a/video/1", "tiktok"),
        ("https://vm.tiktok.com/x", "tiktok"),
        ("https://twitter.com/a/status/1", "tweet"),
        ("https://youtu.be/abc", "youtube"),
        ("https://old.reddit.com/r/x/comments/abc", "reddit"),
        ("https://www.goodreads.com/book/show/1", "book"),
        ("https://letterboxd.com/film/heat/", "film"),
        ("https://example.com/post", "article"),
        # Lookalikes must not reach yt-dlp, which fetches without the SSRF guard.
        ("https://tiktok.com.evil.example/v", "article"),
        ("https://eviltiktok.com/v", "article"),
        ("https://notinstagram.com/p/x", "article"),
    ],
)
def test_classify(url, kind):
    assert classify(url) == kind


def test_canonical_strips_trackers_and_aliases():
    assert canonical("https://www.example.com/post/?utm_source=x&id=3&fbclid=y") == "https://example.com/post?id=3"
    assert canonical("https://mobile.twitter.com/a/status/1?s=20") == "https://x.com/a/status/1"
    assert canonical("https://www.youtube.com/watch?v=abc&list=PL1&t=30") == "https://youtube.com/watch?v=abc"
