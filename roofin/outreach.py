"""The pitch: a short, specific, honest email that leads with proof and asks for a small payment."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Business, Finding
from .verticals import Vertical


@dataclass
class Sender:
    name: str
    email: str
    postal_address: str  # required in US commercial email (CAN-SPAM)


@dataclass
class Draft:
    subject: str
    body: str


def pick_top(findings: list[Finding], n: int = 3) -> list[Finding]:
    """Highest severity first; prefer findings we can show a sample fix for."""
    return sorted(findings, key=lambda f: (-f.severity, f.sample is None))[:n]


def money(cents: int) -> str:
    return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def first_name_greeting(b: Business) -> str:
    return f"Hi {b.name} team,"


def draft_email(b: Business, findings: list[Finding], v: Vertical, offer_cents: int, sender: Sender,
                report_url: str | None = None) -> Draft:
    top = pick_top(findings)
    n = len(top)
    subject = f"{n} thing{'s' if n != 1 else ''} that may be costing {b.name} leads"
    lines = [first_name_greeting(b), ""]
    lines.append(
        f"I was looking at {v.trade}s in your area and went through your website and Google listing the way "
        f"a homeowner would. I found {n} thing{'s' if n != 1 else ''} that are probably costing you calls:"
    )
    lines.append("")
    for i, f in enumerate(top, 1):
        lines.append(f"{i}. {f.title}.")
        lines.append(f"   ({f.evidence})")
    sample = next((f for f in top if f.sample), None)
    lines.append("")
    if sample:
        lines.append(f"I already wrote a fix for #{top.index(sample) + 1} so you can see what I mean"
                     + (f" — it's in the one-page report here: {report_url}" if report_url else " (below)."))
        if not report_url:
            lines += ["", "---", sample.sample, "---"]
    elif report_url:
        lines.append(f"The details are in a one-page report: {report_url}")
    lines += [
        "",
        f"If you want, I'll implement one of these for {money(offer_cents)}. If you don't like the result, "
        "you don't pay.",
        "",
        "Just reply \"yes\" and tell me which one.",
        "",
        sender.name,
        sender.email,
        "",
        "—",
        f"{sender.name} · {sender.postal_address}",
        "You're receiving this one-time note because your business is publicly listed. "
        "Reply \"stop\" and I won't contact you again.",
    ]
    return Draft(subject=subject, body="\n".join(lines))
