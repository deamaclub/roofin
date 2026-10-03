"""Polite, shallow website visits: the home page plus the few pages a customer would click."""
from __future__ import annotations

import time
from urllib import robotparser
from urllib.parse import urljoin, urldefrag, urlparse

import requests
from bs4 import BeautifulSoup

from .models import Page, SiteSnapshot

USER_AGENT = "RoofinAuditBot/0.1 (+website opportunity audit; contact via the email that referenced this visit)"

# Links worth following, in priority order. A customer looking for a roofer clicks these.
PRIORITY_WORDS = (
    "contact", "quote", "estimate", "inspection", "emergency", "storm", "repair", "service",
    "replacement", "insurance", "about", "review", "testimonial", "gutter", "siding",
)


def normalize_url(url: str) -> str:
    if not urlparse(url).scheme:
        url = "http://" + url
    return url


def candidate_links(base_url: str, html: str, limit: int) -> list[str]:
    host = urlparse(base_url).netloc.lower().removeprefix("www.")
    soup = BeautifulSoup(html, "html.parser")
    scored: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href, _ = urldefrag(urljoin(base_url, a["href"]))
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or parsed.netloc.lower().removeprefix("www.") != host:
            continue
        if parsed.path.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".webp")):
            continue
        haystack = (parsed.path + " " + a.get_text(" ")).lower()
        rank = next((i for i, w in enumerate(PRIORITY_WORDS) if w in haystack), None)
        if rank is not None and href.rstrip("/") != base_url.rstrip("/"):
            scored[href] = min(scored.get(href, 99), rank)
    return [u for u, _ in sorted(scored.items(), key=lambda kv: kv[1])][:limit]


def fetch_site(url: str, max_pages: int = 6, session: requests.Session | None = None,
               timeout: float = 15, respect_robots: bool = True) -> SiteSnapshot:
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", USER_AGENT)
    url = normalize_url(url)
    snap = SiteSnapshot(start_url=url)

    robots = None
    if respect_robots:
        robots = robotparser.RobotFileParser()
        try:
            r = http.get(urljoin(url, "/robots.txt"), timeout=timeout)
            robots.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            robots.parse([])

    def get(u: str) -> Page | None:
        if robots and not robots.can_fetch(USER_AGENT, u):
            return None
        start = time.monotonic()
        resp = http.get(u, timeout=timeout, allow_redirects=True)
        ctype = resp.headers.get("Content-Type", "")
        html = resp.text if "html" in ctype or not ctype else ""
        return Page(url=resp.url, status=resp.status_code, html=html, elapsed=time.monotonic() - start)

    try:
        home = get(url)
    except requests.RequestException as exc:
        snap.error = f"{type(exc).__name__}: {exc}"[:300]
        return snap
    if home is None:
        snap.error = "robots.txt disallows visiting this site"
        return snap
    snap.pages.append(home)
    if home.status >= 400:
        snap.error = f"home page returned HTTP {home.status}"
        return snap

    for link in candidate_links(home.url, home.html, max_pages - 1):
        try:
            page = get(link)
        except requests.RequestException:
            continue
        if page and page.status < 400:
            snap.pages.append(page)
    return snap
