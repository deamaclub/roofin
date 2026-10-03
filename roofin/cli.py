"""roofin: find money -> create proof -> ask for money. Free by default.

    roofin loop "Rochester NY" "Buffalo NY"   # the whole loop; schedule it daily
        Stripe payments -> find businesses -> audit sites -> collect all contact info -> draft + demo
        + pay link -> publish demos (Cloudflare Pages / Netlify) -> replies / opt-outs -> send email (capped) + one follow-up
        -> Telegram you a copy-paste card per prospect

    roofin price                         # what to charge to net $5 after payment fees
    roofin inbox                         # who replied
    roofin paid 3 6                      # someone paid you $6
    roofin expense "SerpApi" 4           # spend only money the machine already made
    roofin stats
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import json
import secrets
import shutil

from . import db, pricing, serp, verticals
from .cards import prospect_card, reply_card
from .cloudflare import CloudflarePages
from .netlify import DemoHostError, Netlify
from .stripe_pay import Stripe, StripeError
from .telegram import Telegram, TelegramError, find_chat_id
from .contacts import FREE_MAIL, split_emails, short_pitch, usable_emails, whatsapp_link
from .crawl import fetch_site
from .detect import build_market, detect, score
from .discovery import DiscoveryError, load_csv, search_osm, search_places
from .facts import SiteFacts, extract
from .mailer import MailConfig, Mailer, build_message, parse_reply
from .models import Business, Review
from .outreach import Sender, draft_email, followup_email, money, pick_top
from .report import html_page, markdown, slug

US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH "
    "OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
# Findings that could be a fluke of our own network; a human checks these before anything is sent.
NEEDS_HUMAN_CHECK = {"site_down"}


def city_of(market: str | None) -> str | None:
    if not market:
        return None
    head = market.split(",")[0].strip()
    words = head.split()
    if len(words) > 1 and words[-1].upper() in US_STATES:
        words = words[:-1]
    return " ".join(words) or None


def cents(amount: str) -> int:
    return round(float(str(amount).lstrip("$")) * 100)


def processor_fees(args) -> tuple[float, int]:
    pct, fixed = pricing.PROCESSORS[args.processor]
    if args.fee_pct is not None:
        pct = args.fee_pct
    if args.fee_fixed is not None:
        fixed = cents(args.fee_fixed)
    return pct, fixed


def offer_cents(args) -> int:
    if args.offer:
        return cents(args.offer)
    pct, fixed = processor_fees(args)
    return pricing.price_for_profit(cents(args.profit), pct, fixed)


def suppress_all(conn, emails: list[str], reason: str) -> None:
    """Opt-out covers the whole company: every address we have, plus its domain (unless it's Gmail etc.)."""
    for e in emails:
        db.suppress(conn, e, reason)
        domain = e.rsplit("@", 1)[-1]
        if domain not in FREE_MAIL:
            db.suppress(conn, domain, reason)


def make_mailer(cfg: MailConfig):  # these factories are replaced in tests
    return Mailer(cfg)


def make_telegram():
    return Telegram.from_env()


def make_host():
    """Where demo pages are published. Cloudflare Pages if configured (unlimited bandwidth), else Netlify."""
    choice = os.environ.get("ROOFIN_DEMO_HOST", "auto")
    if choice in ("auto", "cloudflare"):
        cf = CloudflarePages.from_env()
        if cf or choice == "cloudflare":
            return cf
    return Netlify.from_env()


def make_stripe():
    return Stripe.from_env()


def demo_ready(conn, row) -> bool:
    """A message that links to a demo may only go out once that demo is actually live."""
    if not row["demo_url"]:
        return True
    live_until = int(db.get_setting(conn, "demos_live_until") or 0)
    return row["id"] <= live_until


def site_dir() -> Path:
    return Path(os.environ.get("ROOFIN_SITE_DIR", "site"))


# ---------------------------------------------------------------- find

def pick_source(requested: str) -> str:
    if requested != "auto":
        return requested
    if os.environ.get("SERPAPI_KEY"):
        return "serpapi"
    if os.environ.get("GOOGLE_PLACES_API_KEY"):
        return "google"
    return "osm"


def cmd_discover(args, conn) -> None:
    v = verticals.get(args.vertical)
    source = pick_source(args.source)
    query = args.query or f"{v.search_suffix} in {args.market}"
    try:
        if source == "serpapi":
            print(f"Searching Google Maps via SerpApi (free plan, {serp.remaining(conn)} calls left this month): {query!r}")
            pairs = serp.search_maps(conn, query, limit=args.limit)
            for b, data_id in pairs:
                db.upsert_business(conn, b, v.key, args.market, data_id=data_id)
            found = [b for b, _ in pairs]
        elif source == "google":
            print(f"Searching Google Places (paid API): {query!r} (limit {args.limit})")
            found = search_places(query, limit=args.limit)
        else:
            print(f"Searching OpenStreetMap (free) for {v.key} businesses in {args.market!r}")
            found = search_osm(args.market, v.osm_tags, v.osm_name_words, limit=args.limit)
    except DiscoveryError as exc:
        sys.exit(f"error: {exc}")
    if source != "serpapi":
        for b in found:
            db.upsert_business(conn, b, v.key, args.market)
    conn.commit()
    with_site = sum(1 for b in found if b.website)
    print(f"Stored {len(found)} businesses ({with_site} with websites).")
    if source == "osm":
        print("OpenStreetMap misses many businesses and has no reviews. Set SERPAPI_KEY (free plan) for "
              "Google Maps data, or add businesses by hand with `roofin add`.")


def cmd_add(args, conn) -> None:
    v = verticals.get(args.vertical)
    b = Business(
        name=args.name, website=args.website, phone=args.phone, address=args.address,
        rating=args.rating, review_count=args.reviews,
        reviews=[Review(rating=None, text=t) for t in args.review or []],
    )
    bid = db.upsert_business(conn, b, v.key, args.market)
    conn.commit()
    print(f"Saved #{bid} {b.name} in {args.market!r}.")


def cmd_import(args, conn) -> None:
    v = verticals.get(args.vertical)
    found = load_csv(args.csv)
    for b in found:
        db.upsert_business(conn, b, v.key, args.market)
    conn.commit()
    print(f"Imported {len(found)} businesses into market {args.market!r}.")


# ---------------------------------------------------------------- audit

def _business_rows(conn, vertical: str, market: str | None, new_only: bool = False):
    sql, params = "SELECT * FROM businesses b WHERE vertical = ?", [vertical]
    if market:
        sql += " AND market = ?"
        params.append(market)
    if new_only:
        sql += " AND NOT EXISTS (SELECT 1 FROM audits a WHERE a.business_id = b.id)"
    return conn.execute(sql + " ORDER BY id", params).fetchall()


def cmd_audit(args, conn) -> None:
    v = verticals.get(args.vertical)
    markets = [args.market] if args.market else [
        r[0] for r in conn.execute("SELECT DISTINCT market FROM businesses WHERE vertical = ?", (v.key,))
    ]
    for market in markets:
        rows = _business_rows(conn, v.key, market, new_only=getattr(args, "new_only", False))
        if args.limit:
            rows = rows[: args.limit]
        if not rows:
            continue
        businesses = [db.row_to_business(r) for r in rows]
        data_ids = {r["id"]: r["data_id"] for r in rows}
        # Competitor comparisons use the whole market, not just the new rows.
        everyone = [db.row_to_business(r) for r in _business_rows(conn, v.key, market)]
        print(f"Auditing {len(businesses)} {v.key} businesses in {market or '(no market)'}…")

        def visit(b: Business) -> tuple[Business, SiteFacts | None, int]:
            if not b.website:
                return b, None, 0
            snap = fetch_site(b.website, max_pages=args.max_pages, respect_robots=not args.ignore_robots)
            return b, extract(snap), len(snap.pages)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            visited = list(pool.map(visit, businesses))
        all_facts = {b.id: f for b, f, _ in visited if f}
        ctx = build_market(everyone, all_facts, v, city_of(market))

        # Spend metered review lookups only on the best prospects that don't have reviews yet.
        if args.reviews and os.environ.get("SERPAPI_KEY"):
            prelim = sorted(visited, key=lambda t: score(t[0], detect(t[0], t[1], v, ctx), t[1]), reverse=True)
            wanted = [b for b, _, _ in prelim if not b.reviews and data_ids.get(b.id)][: args.reviews]
            for b in wanted:
                if serp.remaining(conn) <= 0:
                    print("  SerpApi monthly allowance reached; skipping remaining review lookups.")
                    break
                try:
                    b.reviews = serp.fetch_reviews(conn, data_ids[b.id])
                except DiscoveryError as exc:
                    print(f"  reviews for {b.name}: {exc}")
                    break
                db.upsert_business(conn, b, v.key, market)

        for b, facts, n_pages in visited:
            findings = detect(b, facts, v, ctx)
            s = score(b, findings, facts)
            db.save_audit(conn, b.id, s, findings, facts.error if facts else None, n_pages)
            emails = usable_emails(facts.emails, b.website) if facts else []
            if emails:
                conn.execute("UPDATE businesses SET email = ? WHERE id = ?", (", ".join(emails), b.id))
            if facts:
                contacts = {"emails": emails, "phones": facts.phones, "socials": facts.socials,
                            "whatsapp": facts.whatsapp, "contact_form": facts.contact_form_url}
                conn.execute("UPDATE businesses SET contacts_json = ? WHERE id = ?", (json.dumps(contacts), b.id))
            print(f"  {s:5.1f}  {b.name[:40]:40}  {len(findings)} finding(s)  {len(emails)} email(s)")
        conn.commit()


def _ranked(conn, vertical: str, market: str | None, min_score: float = 0):
    sql = """SELECT b.*, a.id AS audit_id, a.score FROM businesses b
             JOIN audits a ON a.id = (SELECT MAX(id) FROM audits WHERE business_id = b.id)
             WHERE b.vertical = ? AND a.score >= ?"""
    params: list = [vertical, min_score]
    if market:
        sql += " AND b.market = ?"
        params.append(market)
    return conn.execute(sql + " ORDER BY a.score DESC", params).fetchall()


def cmd_prospects(args, conn) -> None:
    rows = _ranked(conn, args.vertical, args.market)[: args.top]
    if not rows:
        print("No audited prospects yet. Run `roofin audit` first.")
        return
    print(f"{'id':>4}  {'score':>5}  {'name':40}  {'reviews':>7}  contact")
    for r in rows:
        contact = r["email"] or r["phone"] or "-"
        print(f"{r['id']:>4}  {r['score']:5.1f}  {r['name'][:40]:40}  {r['review_count'] or 0:>7}  {contact}")
        for f in db.audit_findings(conn, r["audit_id"])[:3]:
            print(f"{'':13}- [{f.severity}] {f.title}")


# ---------------------------------------------------------------- draft

def sender_from(args) -> Sender:
    missing = [n for n in ("sender_name", "sender_email", "sender_address") if not getattr(args, n)]
    if missing:
        flags = ", ".join("--" + m.replace("_", "-") for m in missing)
        env = ", ".join("ROOFIN_" + m.upper() for m in missing)
        sys.exit(f"error: set {flags} (or env {env}). A real postal address is legally required in US cold email.")
    return Sender(args.sender_name, args.sender_email, args.sender_address)


def cmd_draft(args, conn) -> None:
    v = verticals.get(args.vertical)
    sender = sender_from(args)
    offer = offer_cents(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    already = {r[0] for r in conn.execute("SELECT business_id FROM outreach")}
    rows = [r for r in _ranked(conn, v.key, args.market, args.min_score) if r["id"] not in already][: args.top]
    if not rows:
        print("Nothing new to draft (all top prospects already have outreach, or nothing is audited).")
        return
    # Live demo links only if this run can actually publish them; otherwise the demo is sent as a file.
    host, base = make_host(), None
    if host and host.remaining(conn) > 0:
        try:
            base = host.base_url(conn)
        except DemoHostError as exc:
            print(f"  Demo host: {exc}; demos will be attached as files instead")
    stripe = make_stripe()
    for r in rows:
        b = db.row_to_business(r)
        findings = db.audit_findings(conn, r["audit_id"])
        if not findings:
            continue
        emails = split_emails(r["email"])
        if any(db.suppressed(conn, e) for e in emails):
            continue  # they asked not to be contacted; not by email, not by phone
        now = db.now()
        oid = conn.execute(
            """INSERT INTO outreach (business_id, audit_id, channel, recipient, subject, body, offer_cents,
               status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,'draft',?,?)""",
            (r["id"], r["audit_id"], "pending", "", "", "", offer, now, now),
        ).lastrowid

        pay_url, link_id = args.pay_link, None
        if stripe:
            try:
                link_id, pay_url = stripe.payment_link(conn, offer, oid, b.name)
            except StripeError as exc:
                print(f"  Stripe: {exc}; using ROOFIN_PAY_LINK instead")

        token = f"{slug(b.name)[:40]}-{secrets.token_hex(4)}"  # unguessable, so demos can't be browsed
        demo_url = f"{base}/{token}/" if base else None
        draft = draft_email(b, findings, v, offer, sender, report_url=demo_url, pay_link=pay_url)
        if args.llm:
            from .llm import polish
            draft, findings = polish(b, findings, v, city_of(r["market"]), offer, sender, draft)
        page = html_page(b, findings, offer, pay_url=pay_url)
        demo_file = site_dir() / token / "index.html"
        demo_file.parent.mkdir(parents=True, exist_ok=True)
        demo_file.write_text(page, encoding="utf-8")
        base_out = out_dir / f"{oid:04d}-{slug(b.name)}"
        base_out.with_suffix(".md").write_text(markdown(b, findings, r["score"], offer, draft), encoding="utf-8")
        shutil.copyfile(demo_file, base_out.with_suffix(".html"))

        if emails:
            channel, recipient, body = "email", ", ".join(emails), draft.body
        elif r["phone"]:
            pitch = short_pitch(b.name, pick_top(findings)[0].title, money(offer))
            link = whatsapp_link(r["phone"], pitch)
            channel, recipient = "phone", r["phone"]
            body = pitch + (f"\n\nWhatsApp (opens with this message, you press send): {link}" if link else "")
        else:
            channel, recipient, body = "web_form", r["website"], draft.body
        conn.execute(
            """UPDATE outreach SET channel=?, recipient=?, subject=?, body=?, report_path=?, demo_path=?,
               demo_url=?, pay_url=?, stripe_link_id=? WHERE id=?""",
            (channel, recipient, draft.subject, body, str(base_out.with_suffix(".html")), str(demo_file),
             demo_url, pay_url, link_id, oid),
        )
        conn.commit()
        print(f"  drafted  #{oid} {b.name[:40]:40} {channel:8} {recipient}")


def cmd_publish(args, conn) -> bool:
    """Push new demo pages live. Returns False if demos that emails link to are not live."""
    host = make_host()
    if not host:
        return True
    pending = conn.execute("SELECT COUNT(*) FROM outreach WHERE demo_url IS NOT NULL").fetchone()[0]
    if not pending:
        return True
    try:
        dep = host.deploy(conn, site_dir())
    except DemoHostError as exc:
        print(f"Demo host: {exc}. Holding messages that link to new demos until they're live.")
        return False
    newest = conn.execute("SELECT MAX(id) FROM outreach WHERE demo_url IS NOT NULL").fetchone()[0]
    db.set_setting(conn, "demos_live_until", str(newest))
    print("Demos published." if dep else "Demos already live; nothing to publish.")
    return True


def cmd_payments(args, conn) -> None:
    """Ask Stripe which payment links were paid; record them and turn those links off."""
    stripe = make_stripe()
    if not stripe:
        return
    rows = conn.execute(
        """SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id
           WHERE o.stripe_link_id IS NOT NULL AND o.status NOT IN ('paid','opted_out')"""
    ).fetchall()
    tg = make_telegram()
    for r in rows:
        try:
            paid = stripe.completed(r["stripe_link_id"])
        except StripeError as exc:
            print(f"  Stripe: {exc}")
            return
        if not paid:
            continue
        pct, fixed = pricing.PROCESSORS["stripe"]
        for p in paid:
            fee = p.fee_cents if p.fee_cents is not None else pricing.fee_cents(p.amount_cents, pct, fixed)
            conn.execute("INSERT INTO payments (outreach_id, amount_cents, fee_cents, note, received_at) "
                         "VALUES (?,?,?,?,?)", (r["id"], p.amount_cents, fee, f"stripe {p.session_id}", db.now()))
        db.set_outreach_status(conn, r["id"], "paid")
        conn.commit()
        try:
            stripe.deactivate(r["stripe_link_id"])
        except StripeError:
            pass
        total = sum(p.amount_cents for p in paid)
        print(f"  PAID     #{r['id']} {r['name']} {money(total)}")
        if tg:
            m = db.money_summary(conn)
            tg.send(f"💰 <b>{r['name']} paid {money(total)}</b> (#{r['id']})\n"
                    f"Profit so far: {money(m['net'])}")


def _contacts(row) -> dict:
    try:
        return json.loads(row["contacts_json"] or "{}")
    except ValueError:
        return {}


def cmd_notify(args, conn) -> None:
    """Send each new prospect to your Telegram as a ready-to-paste card."""
    tg = make_telegram()
    if not tg:
        print("Telegram not set up (ROOFIN_TELEGRAM_TOKEN / ROOFIN_TELEGRAM_CHAT_ID); see `roofin telegram-setup`.")
        return
    rows = conn.execute(
        """SELECT o.*, b.name, b.market, b.rating, b.review_count, b.website, b.phone AS listing_phone,
                  b.contacts_json, a.score
           FROM outreach o JOIN businesses b ON b.id = o.business_id JOIN audits a ON a.id = o.audit_id
           WHERE o.notified_at IS NULL AND o.status IN ('draft','approved','sent') ORDER BY a.score DESC"""
    ).fetchall()
    for r in rows:
        if not demo_ready(conn, r):
            continue
        findings = db.audit_findings(conn, r["audit_id"])
        contacts = _contacts(r)
        if r["channel"] == "email" and not contacts.get("emails"):
            contacts["emails"] = split_emails(r["recipient"])
        emailed = split_emails(r["recipient"]) if r["status"] == "sent" and r["channel"] == "email" else None
        msgs = prospect_card(
            outreach_id=r["id"], name=r["name"], market=r["market"], score=r["score"], rating=r["rating"],
            review_count=r["review_count"], website=r["website"], contacts=contacts,
            listing_phone=r["listing_phone"], findings=findings, offer_cents=r["offer_cents"],
            subject=r["subject"], email_body=r["body"] if r["channel"] == "email" else "",
            demo_url=r["demo_url"], pay_url=r["pay_url"], emailed_to=emailed,
        )
        try:
            for m in msgs:
                tg.send(m)
            if not r["demo_url"] and r["demo_path"] and Path(r["demo_path"]).exists():
                tg.send_file(r["demo_path"], "Demo page: send this file to them (or open it to copy the fix).")
        except TelegramError as exc:
            print(f"  Telegram: {exc}")
            return
        conn.execute("UPDATE outreach SET notified_at = ? WHERE id = ?", (db.now(), r["id"]))
        conn.commit()
        print(f"  telegram #{r['id']} {r['name']}")


def cmd_telegram_setup(args, conn) -> None:
    token = os.environ.get("ROOFIN_TELEGRAM_TOKEN")
    if not token:
        sys.exit("Set ROOFIN_TELEGRAM_TOKEN first (Telegram → @BotFather → /newbot).")
    try:
        chats = find_chat_id(token)
    except TelegramError as exc:
        sys.exit(f"error: {exc}")
    if not chats:
        sys.exit("No messages yet. Open your bot in Telegram, press Start / send it 'hi', then run this again.")
    for cid, who in chats:
        print(f"ROOFIN_TELEGRAM_CHAT_ID={cid}   ({who})")
    if len(chats) == 1:
        Telegram(token, chats[0][0]).send("✅ roofin is connected. Prospects will arrive here.")
        print("Sent a test message to your Telegram.")


# ---------------------------------------------------------------- send / inbox

def _sent_today(conn) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return conn.execute(
        "SELECT (SELECT COUNT(*) FROM outreach WHERE substr(sent_at,1,10) = ?)"
        " + (SELECT COUNT(*) FROM outreach WHERE substr(followup_at,1,10) = ?)", (today, today)
    ).fetchone()[0]


def cmd_send(args, conn) -> None:
    cfg = MailConfig.from_env()
    if not cfg:
        sys.exit("error: set ROOFIN_SMTP_USER and ROOFIN_SMTP_PASSWORD (a Gmail App Password works, free).")
    sender = sender_from(args)
    mailer = make_mailer(cfg)
    budget = args.daily_cap - _sent_today(conn)
    if budget <= 0:
        print(f"Daily cap of {args.daily_cap} emails reached; the rest go out tomorrow.")
        return
    statuses = ("approved",) if args.approved_only else ("draft", "approved")
    rows = conn.execute(
        f"""SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id
            WHERE o.channel = 'email' AND o.status IN ({','.join('?' * len(statuses))}) ORDER BY o.id""",
        statuses,
    ).fetchall()
    sent = 0
    for r in rows:
        if sent >= budget:
            break
        if not demo_ready(conn, r):
            continue
        codes = {f.code for f in db.audit_findings(conn, r["audit_id"])}
        if codes & NEEDS_HUMAN_CHECK and r["status"] != "approved":
            print(f"  hold     #{r['id']} {r['name']}: check the site yourself, then `roofin mark {r['id']} approved`")
            continue
        to = [e for e in split_emails(r["recipient"]) if not db.suppressed(conn, e)]
        if not to:
            db.set_outreach_status(conn, r["id"], "opted_out")
            continue
        msg = build_message(sender.name, cfg.user, to, r["subject"], r["body"])
        if args.dry_run:
            print(f"  dry-run  #{r['id']} → {', '.join(to)}: {r['subject']}")
            sent += 1
            continue
        mailer.send(msg)
        conn.execute("UPDATE outreach SET status='sent', sent_at=?, message_id=?, updated_at=? WHERE id=?",
                     (db.now(), msg["Message-ID"], db.now(), r["id"]))
        conn.commit()
        sent += 1
        print(f"  sent     #{r['id']} {r['name']} → {', '.join(to)}")
        if sent < budget and args.delay:
            time.sleep(random.uniform(args.delay, args.delay * 2))

    # One follow-up, only for people who never answered.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.followup_days)).isoformat(timespec="seconds")
    due = conn.execute(
        """SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id
           WHERE o.status = 'sent' AND o.followup_at IS NULL AND o.sent_at <= ? ORDER BY o.sent_at""", (cutoff,)
    ).fetchall()
    for r in due:
        if sent >= budget or args.no_followups:
            break
        to = [e for e in split_emails(r["recipient"]) if not db.suppressed(conn, e)]
        if not to:
            continue
        b = db.row_to_business(conn.execute("SELECT * FROM businesses WHERE id = ?", (r["business_id"],)).fetchone())
        fu = followup_email(b, r["subject"], r["offer_cents"], sender)
        msg = build_message(sender.name, cfg.user, to, fu.subject, fu.body, in_reply_to=r["message_id"])
        if args.dry_run:
            print(f"  dry-run  follow-up #{r['id']} → {', '.join(to)}")
        else:
            mailer.send(msg)
            conn.execute("UPDATE outreach SET followup_at = ?, updated_at = ? WHERE id = ?", (db.now(), db.now(), r["id"]))
            conn.commit()
            print(f"  followup #{r['id']} {r['name']}")
        sent += 1
    print(f"Sent {sent} email(s) today (cap {args.daily_cap}).")


def cmd_inbox(args, conn) -> None:
    cfg = MailConfig.from_env()
    if not cfg:
        sys.exit("error: set ROOFIN_SMTP_USER and ROOFIN_SMTP_PASSWORD to read replies.")
    pending = conn.execute(
        """SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id
           WHERE o.status IN ('sent','replied','won') AND o.channel = 'email'"""
    ).fetchall()
    if not pending:
        print("Nothing sent yet, so no replies to look for.")
        return
    by_msgid = {r["message_id"]: r for r in pending if r["message_id"]}
    by_addr = {e: r for r in pending for e in split_emails(r["recipient"])}
    by_domain = {e.rsplit("@", 1)[1]: r for e, r in by_addr.items() if e.rsplit("@", 1)[1] not in FREE_MAIL}
    found = 0
    tg = make_telegram()
    seen = set(filter(None, (db.get_setting(conn, "seen_replies") or "").split("\n")))
    for msg in make_mailer(cfg).fetch_recent(days=args.days):
        mid = msg.get("Message-ID") or f"{msg.get('From')}|{msg.get('Date')}|{msg.get('Subject')}"
        if mid in seen:
            continue
        seen.add(mid)
        rep = parse_reply(msg)
        if rep.sender == cfg.user.lower():
            continue
        r = next((by_msgid[m] for m in by_msgid if m in rep.refs), None) or by_addr.get(rep.sender) \
            or by_domain.get(rep.sender.rsplit("@", 1)[-1])
        if not r:
            continue
        found += 1
        if rep.opt_out:
            suppress_all(conn, split_emails(r["recipient"]) + [rep.sender], f"replied: {rep.text[:80]}")
            db.set_outreach_status(conn, r["id"], "opted_out")
            print(f"  OPT-OUT  #{r['id']} {r['name']} — suppressed forever")
            if tg:
                tg.send(f"🚫 {r['name']} (#{r['id']}) asked not to be contacted. Done, they won't hear from you again.")
        else:
            if r["status"] == "sent":
                db.set_outreach_status(conn, r["id"], "replied")
            conn.execute("UPDATE outreach SET reply_snippet = ? WHERE id = ?", (rep.text[:500], r["id"]))
            print(f"  REPLY    #{r['id']} {r['name']} <{rep.sender}>:\n           {rep.text[:300]!r}")
            if tg:
                for m in reply_card(r["id"], r["name"], rep.sender, rep.text, db.audit_findings(conn, r["audit_id"]),
                                    r["offer_cents"], r["pay_url"], r["demo_url"]):
                    tg.send(m)
        conn.commit()
    db.set_setting(conn, "seen_replies", "\n".join(sorted(seen)[-2000:]))
    if not found:
        print("No new replies.")
    else:
        print("\nAnswer replies yourself; when they say yes, do the fix, send your pay link, then `roofin paid <id> <amount>`.")


def cmd_calls(args, conn) -> None:
    rows = conn.execute(
        """SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id
           WHERE o.channel = 'phone' AND o.status IN ('draft','approved') ORDER BY o.id"""
    ).fetchall()
    if not rows:
        print("No phone-only prospects waiting.")
    for r in rows:
        print(f"#{r['id']} {r['name']} — {r['recipient']}\n{r['body']}\n"
              f"(after you call or message: roofin mark {r['id']} sent)\n")


# ---------------------------------------------------------------- money

def cmd_price(args, conn) -> None:
    pct, fixed = processor_fees(args)
    price = offer_cents(args)
    fee = pricing.fee_cents(price, pct, fixed)
    print(f"Charge {money(price)} via {args.processor} ({pct}% + {money(fixed)} fee = {money(fee)}) "
          f"→ you keep {money(price - fee)}.")


def cmd_mark(args, conn) -> None:
    try:
        db.set_outreach_status(conn, args.id, args.status)
    except (ValueError, LookupError) as exc:
        sys.exit(f"error: {exc}")
    if args.status == "opted_out":
        r = conn.execute("SELECT recipient FROM outreach WHERE id = ?", (args.id,)).fetchone()
        suppress_all(conn, split_emails(r["recipient"]), "marked opted_out")
    conn.commit()
    print(f"outreach #{args.id} → {args.status}")


def cmd_paid(args, conn) -> None:
    amount = cents(args.amount)
    pct, fixed = processor_fees(args)
    fee = pricing.fee_cents(amount, pct, fixed)
    try:
        db.set_outreach_status(conn, args.id, "paid")
    except LookupError as exc:
        sys.exit(f"error: {exc}")
    conn.execute("INSERT INTO payments (outreach_id, amount_cents, fee_cents, note, received_at) VALUES (?,?,?,?,?)",
                 (args.id, amount, fee, args.note, db.now()))
    conn.commit()
    m = db.money_summary(conn)
    print(f"Recorded {money(amount)} (fee {money(fee)}) from outreach #{args.id}. "
          f"Available to spend: {money(m['available'])}")


def cmd_expense(args, conn) -> None:
    amount = cents(args.amount)
    m = db.money_summary(conn)
    if amount > m["available"] and not args.force:
        sys.exit(f"Refused: {args.name} costs {money(amount)} but the machine has only earned "
                 f"{money(m['available'])} you can spend. Earn it first (or --force to pay out of pocket).")
    conn.execute("INSERT INTO expenses (name, amount_cents, spent_at) VALUES (?,?,?)", (args.name, amount, db.now()))
    conn.commit()
    print(f"Logged {money(amount)} for {args.name}. Left to spend: {money(m['available'] - amount)}")


def cmd_stats(args, conn) -> None:
    count = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    prospects = count("SELECT COUNT(*) FROM businesses")
    audited = count("SELECT COUNT(DISTINCT business_id) FROM audits")
    by_status = dict(conn.execute("SELECT status, COUNT(*) FROM outreach GROUP BY status").fetchall())
    contacted = sum(by_status.get(s, 0) for s in ("sent", "replied", "won", "paid", "lost", "opted_out"))
    replied = sum(by_status.get(s, 0) for s in ("replied", "won", "paid"))
    payers = count("SELECT COUNT(DISTINCT outreach_id) FROM payments")
    m = db.money_summary(conn)
    print(f"Prospects found      {prospects}")
    print(f"Audited              {audited}")
    print(f"Drafts / approved    {by_status.get('draft', 0)} / {by_status.get('approved', 0)}")
    print(f"Contacted            {contacted}")
    print(f"Replied              {replied}" + (f"  ({100 * replied / contacted:.0f}%)" if contacted else ""))
    print(f"Opted out            {by_status.get('opted_out', 0)}")
    print(f"Paying customers     {payers}")
    print(f"Revenue              {money(m['gross'])}  (fees {money(m['fees'])}, spent {money(m['spent'])})")
    print(f"Profit               {money(m['net'])}")
    print(f"SerpApi this month   {db.api_calls(conn, serp.PROVIDER)} / {serp.monthly_cap()} free calls")
    print()
    if m["gross"] == 0:
        print("Goal: get one stranger to pay. Not there yet.")
    else:
        print(f"The machine has made money. You can spend up to {money(m['available'])} on it without paying a dime.")


# ---------------------------------------------------------------- the loop

def cmd_run(args, conn) -> None:
    cmd_discover(args, conn)
    args.limit = None
    cmd_audit(args, conn)
    cmd_draft(args, conn)


def cmd_loop(args, conn) -> None:
    """One pass of the whole machine. Safe to run every day: it never contacts anyone twice
    (except one follow-up), never contacts anyone who opted out, and stops at the daily cap."""
    v = verticals.get(args.vertical)
    print("=== payments ===")
    cmd_payments(args, conn)
    for market in args.markets:
        print(f"\n=== {market} ===")
        last = conn.execute("SELECT MAX(created_at) FROM businesses WHERE vertical = ? AND market = ?",
                            (v.key, market)).fetchone()[0]
        stale = not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(days=args.rediscover_days)
        if stale:
            args.market = market
            args.limit = args.find
            try:
                cmd_discover(args, conn)
            except SystemExit as exc:
                print(exc)
        args.market, args.limit, args.new_only = market, None, True
        cmd_audit(args, conn)
        cmd_draft(args, conn)
    print("\n=== demos ===")
    cmd_publish(args, conn)
    if MailConfig.from_env():
        print("\n=== replies ===")
        cmd_inbox(args, conn)
        print("\n=== sending ===")
        cmd_send(args, conn)
    if make_telegram():
        print("\n=== telegram ===")
        cmd_notify(args, conn)
    else:
        print("\n=== yours to do by hand (set up Telegram to get these as copy-paste cards) ===")
        cmd_calls(args, conn)
    print()
    cmd_stats(args, conn)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="roofin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=os.environ.get("ROOFIN_DB", "roofin.db"), help="SQLite file (default roofin.db)")
    p.add_argument("--vertical", default="roofing", choices=verticals.available())
    sub = p.add_subparsers(dest="cmd", required=True)

    def money_opts(sp):
        sp.add_argument("--processor", choices=sorted(pricing.PROCESSORS),
                        default=os.environ.get("ROOFIN_PROCESSOR") or ("stripe" if os.environ.get("STRIPE_SECRET_KEY") else "paypal"),
                        help="how you get paid (sets fees); stripe when STRIPE_SECRET_KEY is set")
        sp.add_argument("--fee-pct", type=float, help="override the processor's percentage fee")
        sp.add_argument("--fee-fixed", help="override the processor's fixed fee in dollars")
        sp.add_argument("--profit", default=os.environ.get("ROOFIN_PROFIT", "5"),
                        help="what you want to keep per sale, in dollars (default 5)")
        sp.add_argument("--offer", default=os.environ.get("ROOFIN_OFFER"),
                        help="fixed price in dollars; default is computed from --profit and fees")

    def discover_opts(sp):
        sp.add_argument("--source", choices=("auto", "serpapi", "osm", "google"), default="auto",
                        help="auto = SerpApi if SERPAPI_KEY is set, else OpenStreetMap (both free)")
        sp.add_argument("--limit", type=int, default=60, help="max businesses to find")
        sp.add_argument("--query", help="override the search text")

    def audit_opts(sp):
        sp.add_argument("--max-pages", type=int, default=6, help="pages to visit per site")
        sp.add_argument("--workers", type=int, default=8)
        sp.add_argument("--ignore-robots", action="store_true", help="skip robots.txt checks (not recommended)")
        sp.add_argument("--reviews", type=int, default=10,
                        help="fetch Google reviews (1 SerpApi call each) for this many top prospects (default 10)")

    def sender_opts(sp):
        sp.add_argument("--sender-name", default=os.environ.get("ROOFIN_SENDER_NAME"))
        sp.add_argument("--sender-email", default=os.environ.get("ROOFIN_SENDER_EMAIL"))
        sp.add_argument("--sender-address", default=os.environ.get("ROOFIN_SENDER_ADDRESS"))

    def draft_opts(sp):
        sp.add_argument("--top", type=int, default=10, help="how many new drafts to create")
        sp.add_argument("--min-score", type=float, default=30)
        sp.add_argument("--out", default="out", help="where reports are written")
        sp.add_argument("--pay-link", default=os.environ.get("ROOFIN_PAY_LINK"),
                        help="your PayPal.me / payment link, included in emails")
        sp.add_argument("--llm", action="store_true", help="polish copy with Claude (PAID API; the default template copy is free)")
        sender_opts(sp)
        money_opts(sp)

    def send_opts(sp):
        sp.add_argument("--daily-cap", type=int, default=int(os.environ.get("ROOFIN_DAILY_CAP", "15")),
                        help="max emails per day incl. follow-ups (default 15; keeps your mailbox healthy)")
        sp.add_argument("--delay", type=float, default=45, help="seconds between emails (randomized up to 2x)")
        sp.add_argument("--followup-days", type=int, default=4)
        sp.add_argument("--no-followups", action="store_true")
        sp.add_argument("--approved-only", action="store_true", help="only send drafts you marked approved")
        sp.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")
        sp.add_argument("--days", type=int, default=21, help="how far back to look for replies")

    sp = sub.add_parser("loop", help="the whole machine, one pass; run it daily")
    sp.add_argument("markets", nargs="+", help='e.g. "Rochester NY" "Buffalo NY"')
    sp.add_argument("--find", type=int, default=60, help="businesses to find per market")
    sp.add_argument("--rediscover-days", type=int, default=30, help="search a market again after this many days")
    discover_opts(sp)
    audit_opts(sp)
    draft_opts(sp)
    send_opts(sp)
    sp.set_defaults(fn=cmd_loop)

    sp = sub.add_parser("discover", help="find businesses")
    sp.add_argument("market", help='e.g. "Rochester NY"')
    discover_opts(sp)
    sp.set_defaults(fn=cmd_discover)

    sp = sub.add_parser("add", help="add one business by hand (e.g. copied from Google Maps)")
    sp.add_argument("name")
    sp.add_argument("--market", required=True, help='e.g. "Rochester NY"')
    sp.add_argument("--website")
    sp.add_argument("--phone")
    sp.add_argument("--address")
    sp.add_argument("--rating", type=float, help="Google star rating, e.g. 4.6")
    sp.add_argument("--reviews", type=int, help="number of Google reviews")
    sp.add_argument("--review", action="append", help="paste a review's text; repeat for several")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("import", help="load businesses from a CSV")
    sp.add_argument("csv")
    sp.add_argument("--market", required=True, help='e.g. "Rochester NY"')
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser("audit", help="visit websites and detect opportunities")
    sp.add_argument("--market")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--new-only", action="store_true", help="only businesses never audited")
    audit_opts(sp)
    sp.set_defaults(fn=cmd_audit)

    sp = sub.add_parser("prospects", help="ranked prospects with their top problems")
    sp.add_argument("--market")
    sp.add_argument("--top", type=int, default=20)
    sp.set_defaults(fn=cmd_prospects)

    sp = sub.add_parser("draft", help="write reports + outreach drafts for top prospects")
    sp.add_argument("--market")
    draft_opts(sp)
    sp.set_defaults(fn=cmd_draft)

    sp = sub.add_parser("send", help="email drafts through your mailbox (capped), plus one follow-up")
    sender_opts(sp)
    send_opts(sp)
    sp.set_defaults(fn=cmd_send)

    sp = sub.add_parser("inbox", help="read replies; opt-outs are suppressed forever")
    sp.add_argument("--days", type=int, default=21)
    sp.set_defaults(fn=cmd_inbox)

    sp = sub.add_parser("publish", help="push new demo pages live (Cloudflare Pages or Netlify)")
    sp.set_defaults(fn=cmd_publish)

    sp = sub.add_parser("payments", help="check Stripe for payments and record them")
    sp.set_defaults(fn=cmd_payments)

    sp = sub.add_parser("notify", help="send new prospects to your Telegram as copy-paste cards")
    sp.set_defaults(fn=cmd_notify)

    sp = sub.add_parser("telegram-setup", help="find your Telegram chat id and send a test message")
    sp.set_defaults(fn=cmd_telegram_setup)

    sp = sub.add_parser("calls", help="phone-only prospects: script + WhatsApp link to send yourself")
    sp.set_defaults(fn=cmd_calls)

    sp = sub.add_parser("outreach", help="list drafts / show one")
    sp.add_argument("--status", choices=db.OUTREACH_STATUSES)
    sp.add_argument("--show", type=int, metavar="ID")
    sp.set_defaults(fn=cmd_outreach)

    sp = sub.add_parser("mark", help="update an outreach status")
    sp.add_argument("id", type=int)
    sp.add_argument("status", choices=db.OUTREACH_STATUSES)
    sp.set_defaults(fn=cmd_mark)

    sp = sub.add_parser("price", help="what to charge to keep your target profit after fees")
    money_opts(sp)
    sp.set_defaults(fn=cmd_price)

    sp = sub.add_parser("paid", help="record money received")
    sp.add_argument("id", type=int, help="outreach id")
    sp.add_argument("amount", help="dollars, e.g. 6")
    sp.add_argument("--note")
    money_opts(sp)
    sp.set_defaults(fn=cmd_paid)

    sp = sub.add_parser("expense", help="log spending; refused unless the machine already earned it")
    sp.add_argument("name")
    sp.add_argument("amount", help="dollars")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_expense)

    sp = sub.add_parser("stats", help="funnel, revenue, profit, free-tier usage")
    sp.set_defaults(fn=cmd_stats)

    sp = sub.add_parser("run", help="discover + audit + draft for one market (no sending)")
    sp.add_argument("market")
    discover_opts(sp)
    audit_opts(sp)
    draft_opts(sp)
    sp.set_defaults(fn=cmd_run)
    return p


def cmd_outreach(args, conn) -> None:
    if args.show:
        r = conn.execute(
            "SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id WHERE o.id = ?",
            (args.show,),
        ).fetchone()
        if not r:
            sys.exit(f"no outreach #{args.show}")
        print(f"#{r['id']} {r['name']}  [{r['status']}]  via {r['channel']} → {r['recipient']}")
        print(f"report: {r['report_path']}\n\nSubject: {r['subject']}\n\n{r['body']}")
        if r["reply_snippet"]:
            print(f"\n--- their reply ---\n{r['reply_snippet']}")
        return
    sql = "SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id"
    params = []
    if args.status:
        sql += " WHERE o.status = ?"
        params.append(args.status)
    rows = conn.execute(sql + " ORDER BY o.id", params).fetchall()
    for r in rows:
        print(f"{r['id']:>4}  {r['status']:10}  {money(r['offer_cents']):>6}  {r['name'][:40]:40}  {r['channel']}: {r['recipient']}")
    if not rows:
        print("No outreach yet. Run `roofin draft`.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    conn = db.connect(args.db)
    try:
        args.fn(args, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
