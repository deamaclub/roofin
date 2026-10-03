"""Turn raw HTML into the handful of facts the detectors reason about."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .models import SiteSnapshot

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})", re.I)
IGNORED_EMAIL_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "domain.com", "email.com")
TESTIMONIAL_WORDS = ("testimonial", "what our customers say", "reviews", "5 stars", "five star", "★★★★★")


@dataclass
class PageFacts:
    url: str
    label: str  # path + title + headings, lowercased: what the page is "about"
    text: str  # visible text, lowercased
    has_form: bool  # a form a customer could use to ask for work (not a search box / newsletter)
    has_tel: bool


@dataclass
class SiteFacts:
    reachable: bool
    error: str | None = None
    https: bool = False
    home_seconds: float | None = None
    has_viewport: bool = False
    title: str = ""
    meta_description: str = ""
    home_text: str = ""
    home_cta_text: str = ""  # text of links/buttons on the home page
    nav_text: str = ""  # hrefs + text of every link on the home page: pages the site has, crawled or not
    copyright_year: int | None = None
    pages: list[PageFacts] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones_on_home: list[str] = field(default_factory=list)

    @property
    def any_form(self) -> bool:
        return any(p.has_form for p in self.pages)

    @property
    def any_tel(self) -> bool:
        return any(p.has_tel for p in self.pages)

    @property
    def all_text(self) -> str:
        return " ".join(p.text for p in self.pages)

    @property
    def all_labels(self) -> str:
        return " ".join(p.label for p in self.pages) + " " + self.nav_text


def _is_lead_form(form) -> bool:
    fields = form.find_all(["input", "textarea", "select"])
    visible = [f for f in fields if (f.get("type") or "text").lower() not in ("hidden", "submit", "button")]
    if form.find("textarea"):
        return True
    names = " ".join(
        " ".join(filter(None, [f.get("name"), f.get("id"), f.get("placeholder"), f.get("type")])) for f in visible
    ).lower()
    contactish = sum(w in names for w in ("name", "phone", "tel", "email", "address", "message", "zip"))
    return len(visible) >= 2 and contactish >= 2


def page_facts(url: str, html: str) -> tuple[PageFacts, BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    headings = " ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
    has_tel = soup.find("a", href=re.compile(r"^\s*tel:", re.I)) is not None
    # Embedded scheduling/form widgets (Jobber, Housecall Pro, HubSpot, etc.) render forms in iframes.
    widget = soup.find("iframe", src=re.compile(r"form|jobber|housecall|calendly|hubspot|typeform|leadconnector", re.I))
    has_form = any(_is_lead_form(f) for f in soup.find_all("form")) or widget is not None
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    label = f"{urlparse(url).path} {title} {headings}".lower()
    return PageFacts(url=url, label=label, text=text.lower(), has_form=has_form, has_tel=has_tel), soup


def extract(snap: SiteSnapshot) -> SiteFacts:
    if not snap.pages or snap.error and not snap.pages[0].html:
        return SiteFacts(reachable=False, error=snap.error or "no response")
    home = snap.home
    facts = SiteFacts(reachable=True, error=snap.error, home_seconds=home.elapsed,
                      https=urlparse(home.url).scheme == "https")
    raw_home = BeautifulSoup(home.html, "html.parser")
    facts.has_viewport = raw_home.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) is not None
    facts.title = raw_home.title.get_text(" ", strip=True) if raw_home.title else ""
    desc = raw_home.find("meta", attrs={"name": re.compile("^description$", re.I)})
    facts.meta_description = (desc.get("content") or "").strip() if desc else ""
    facts.home_cta_text = " | ".join(
        el.get_text(" ", strip=True) for el in raw_home.find_all(["a", "button"]) if el.get_text(strip=True)
    ).lower()
    facts.nav_text = " ".join(
        f"{a['href']} {a.get_text(' ', strip=True)}" for a in raw_home.find_all("a", href=True)
    ).lower()

    emails: set[str] = set()
    for i, page in enumerate(snap.pages):
        pf, soup = page_facts(page.url, page.html)
        facts.pages.append(pf)
        for a in soup.find_all("a", href=re.compile(r"^\s*mailto:", re.I)):
            emails.add(a["href"].split(":", 1)[1].split("?")[0].strip().lower())
        emails.update(e.lower() for e in EMAIL_RE.findall(soup.get_text(" ")))
        if i == 0:
            facts.home_text = pf.text
            facts.phones_on_home = PHONE_RE.findall(soup.get_text(" "))
            years = [int(y) for y in COPYRIGHT_RE.findall(str(raw_home))]
            facts.copyright_year = max(years) if years else None
    facts.emails = sorted(
        e for e in emails
        if not e.endswith(IGNORED_EMAIL_DOMAINS) and not e.endswith((".png", ".jpg", ".webp", ".gif"))
    )
    return facts
