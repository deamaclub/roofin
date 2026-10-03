from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, url: str, status: int, text: str):
        self.url = url
        self.status_code = status
        self.text = text
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class FakeSession:
    """Maps URLs to fixture files; anything else is a 404."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.headers: dict[str, str] = {}
        self.requested: list[str] = []

    def get(self, url, timeout=None, allow_redirects=True):
        self.requested.append(url)
        name = self.routes.get(url.rstrip("/")) or self.routes.get(url)
        if name is None:
            return FakeResponse(url, 404, "")
        return FakeResponse(url, 200, (FIXTURES / name).read_text())


WEAK_ROUTES = {
    "http://abcroofing.com": "weak_home.html",
    "http://abcroofing.com/emergency-roof-repair": "weak_emergency.html",
    "http://abcroofing.com/contact": "weak_contact.html",
}
STRONG_ROUTES = {
    "https://summitroofing.com": "strong_home.html",
    "https://summitroofing.com/emergency": "strong_emergency.html",
}


@pytest.fixture
def weak_session():
    return FakeSession(WEAK_ROUTES)


@pytest.fixture
def strong_session():
    return FakeSession(STRONG_ROUTES)
