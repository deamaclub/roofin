"""The Telegram card for one prospect: everything you need, nothing to think about.

Each paste-ready piece is its own <pre> block (one tap to copy in Telegram), with a one-line instruction above
it saying exactly where to paste it.
"""
from __future__ import annotations

from .contacts import whatsapp_link
from .models import Finding
from .outreach import money, pick_top
from .telegram import copyable, esc

STARS = "⭐"


def short_message(name: str, findings: list[Finding], offer_cents: int, demo_url: str | None) -> str:
    """For contact forms, Facebook/Instagram DMs, texts and WhatsApp: short, no signature block."""
    top = pick_top(findings)
    lines = [f"Hi {name} team, I looked at your website the way a homeowner would and found "
             f"{len(top)} thing{'s' if len(top) != 1 else ''} that are probably costing you calls:"]
    lines += [f"{i}. {f.title}" for i, f in enumerate(top, 1)]
    if demo_url:
        lines.append(f"I already made a free example of the fix: {demo_url}")
    lines.append(f"I'll do the fix for {money(offer_cents)}, and you only pay if you like it. Want me to?")
    return "\n".join(lines)


def yes_reply(name: str, findings: list[Finding], offer_cents: int, pay_url: str | None, demo_url: str | None) -> str:
    fix = pick_top(findings)[0].fix.rstrip(".").lower() if findings else "the fix"
    lines = [
        "Great, I'll get started.",
        "",
        f"I'll send you a preview first ({fix}). Nothing goes live until you say so.",
        "To put it on your site I need one of these:",
        "1) a login for your website editor (WordPress, Wix, Squarespace, GoDaddy...), or",
        "2) the email of whoever manages your site, and I'll send them the finished section.",
        "",
    ]
    if pay_url:
        lines.append(f"If you like it, pay {money(offer_cents)} here: {pay_url}")
    else:
        lines.append(f"If you like it, it's {money(offer_cents)}. If not, you owe nothing.")
    if demo_url:
        lines += ["", f"Here's the example again: {demo_url}"]
    return "\n".join(lines)


def prospect_card(*, outreach_id: int, name: str, market: str | None, score: float, rating: float | None,
                  review_count: int | None, website: str | None, contacts: dict, listing_phone: str | None,
                  findings: list[Finding], offer_cents: int, subject: str, email_body: str,
                  demo_url: str | None, pay_url: str | None, emailed_to: list[str] | None) -> list[str]:
    """Returns the messages to send, in order."""
    top = pick_top(findings)
    emails = contacts.get("emails") or []
    phones = list(dict.fromkeys(([listing_phone] if listing_phone else []) + (contacts.get("phones") or [])))
    short = short_message(name, findings, offer_cents, demo_url)

    head = [f"🏠 <b>{esc(name)}</b>  ·  #{outreach_id}  ·  score {score:.0f}/100"]
    sub = [esc(market or "")]
    if rating is not None:
        sub.append(f"{STARS} {rating:.1f} ({review_count or 0} reviews)")
    head.append("  ·  ".join(x for x in sub if x))
    if website:
        head.append(esc(website))
    head += ["", "<b>What's wrong</b>"] + [f"{i}. {esc(f.title)}" for i, f in enumerate(top, 1)]
    if demo_url:
        head += ["", f"🔗 Demo: {esc(demo_url)}"]
    if pay_url:
        head.append(f"💳 Pay link: {esc(pay_url)}")
    head.append(f"💵 Price: {money(offer_cents)}")

    c = ["<b>All contact info found</b>"]
    for e in emails:
        c.append(f"📧 <code>{esc(e)}</code>")
    for p in phones:
        c.append(f"📞 <code>{esc(p)}</code>")
    if contacts.get("contact_form"):
        c.append(f"📝 Contact form: {esc(contacts['contact_form'])}")
    for w in contacts.get("whatsapp") or []:
        c.append(f"💬 WhatsApp (their link): {esc(w)}")
    for net, url in (contacts.get("socials") or {}).items():
        c.append(f"• {esc(net.title())}: {esc(url)}")
    if len(c) == 1:
        c.append("Only the website. Use its contact page.")
    head += [""] + c

    steps = ["<b>Do this</b>"]
    n = 1
    if emailed_to:
        steps.append(f"✅ Already emailed automatically to {esc(', '.join(emailed_to))}. Wait for a reply; "
                     "use the steps below only if you want to reach them another way too.")
    elif emails:
        steps.append(f"{n}. Gmail → new email to {esc(', '.join(emails))} → paste SUBJECT and EMAIL below.")
        n += 1
    if contacts.get("contact_form"):
        steps.append(f"{n}. Open the contact form → paste SHORT MESSAGE into the message box.")
        n += 1
    if contacts.get("socials", {}).get("facebook") or contacts.get("socials", {}).get("instagram"):
        steps.append(f"{n}. Facebook/Instagram → Message → paste SHORT MESSAGE.")
        n += 1
    wa = whatsapp_link(phones[0], short) if phones else None
    if wa:
        steps.append(f"{n}. Tap to open WhatsApp with SHORT MESSAGE typed (you press send): {esc(wa)}")
        n += 1
    if phones:
        steps.append(f"{n}. Or call {esc(phones[0])} and read SHORT MESSAGE.")
    steps.append(f"When they say yes → paste IF THEY SAY YES. When paid → it's recorded automatically"
                 f"{'' if pay_url else f' (or run: roofin paid {outreach_id} {offer_cents / 100:g})'}.")
    head += [""] + steps

    msgs = ["\n".join(head)]
    if emails and not emailed_to:
        msgs.append("📋 <b>SUBJECT</b>\n" + copyable(subject))
        msgs.append("📋 <b>EMAIL</b>\n" + copyable(email_body))
    msgs.append("📋 <b>SHORT MESSAGE</b> (contact form · DM · text · WhatsApp)\n" + copyable(short))
    msgs.append("📋 <b>IF THEY SAY YES</b>\n" + copyable(yes_reply(name, findings, offer_cents, pay_url, demo_url)))
    return msgs


def reply_card(outreach_id: int, name: str, sender: str, text: str, findings: list[Finding], offer_cents: int,
               pay_url: str | None, demo_url: str | None) -> list[str]:
    return [
        f"📨 <b>Reply from {esc(name)}</b>  ·  #{outreach_id}\nFrom: <code>{esc(sender)}</code>\n\n{esc(text[:1500])}",
        "📋 <b>IF THEY SAID YES</b> (reply to their email with this)\n"
        + copyable(yes_reply(name, findings, offer_cents, pay_url, demo_url)),
    ]
