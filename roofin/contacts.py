"""Who to contact and how: every usable email on the site, plus manual phone/WhatsApp helpers."""
from __future__ import annotations

import re
from urllib.parse import quote, urlparse

FREE_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "live.com",
             "msn.com", "comcast.net", "verizon.net", "att.net", "frontier.com", "rochester.rr.com")
ROLE_NOISE = ("noreply", "no-reply", "donotreply", "privacy", "abuse", "webmaster", "postmaster")


def site_domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website if "//" in website else "http://" + website).netloc.lower()
    return host.removeprefix("www.") or None


def usable_emails(emails: list[str], website: str | None) -> list[str]:
    """Emails that belong to this business: same domain as the site, or a free mailbox the owner uses.

    Drops addresses of the web designer / plugin vendor that often appear in footers, and no-reply boxes.
    """
    dom = site_domain(website)
    keep = []
    for e in emails:
        local, _, edom = e.lower().partition("@")
        if any(n in local for n in ROLE_NOISE):
            continue
        if (dom and (edom == dom or edom.endswith("." + dom) or dom.endswith("." + edom))) or edom in FREE_MAIL:
            keep.append(e.lower())
    return sorted(set(keep))


def split_emails(field: str | None) -> list[str]:
    return [e.strip() for e in (field or "").split(",") if "@" in e]


def e164_us(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "1" + digits
    return digits if len(digits) == 11 and digits.startswith("1") else None


def whatsapp_link(phone: str | None, text: str) -> str | None:
    """Click-to-chat link you open and send yourself (nothing is sent automatically)."""
    num = e164_us(phone)
    return f"https://wa.me/{num}?text={quote(text)}" if num else None


def short_pitch(name: str, top_title: str, offer: str) -> str:
    return (f"Hi, this is a quick note for {name}. I looked at your website and noticed: {top_title.lower()}. "
            f"I can fix that for {offer} and you only pay if you like it. Want me to send the details?")
