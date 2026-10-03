"""roofin: find money -> create proof -> ask for money.

    roofin run "Rochester NY"            # discover (free OpenStreetMap) + audit + draft
    roofin add "ABC Roofing" --market "Rochester NY" --website abcroofing.com   # add one by hand
    roofin prospects                     # ranked list
    roofin outreach                      # drafts waiting for your approval
    roofin mark 3 sent                   # after you send it yourself
    roofin paid 3 1                      # someone paid you $1
    roofin stats                         # the only KPI that matters
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db, verticals
from .crawl import fetch_site
from .detect import build_market, detect, score
from .discovery import DiscoveryError, load_csv, search_osm, search_places
from .facts import SiteFacts, extract
from .models import Business, Review
from .outreach import Sender, draft_email, money
from .report import html_page, markdown, slug

US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH "
    "OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)


def city_of(market: str | None) -> str | None:
    if not market:
        return None
    head = market.split(",")[0].strip()
    words = head.split()
    if len(words) > 1 and words[-1].upper() in US_STATES:
        words = words[:-1]
    return " ".join(words) or None


def cents(amount: str) -> int:
    return round(float(amount.lstrip("$")) * 100)


# ---------------------------------------------------------------- commands

def cmd_discover(args, conn) -> None:
    v = verticals.get(args.vertical)
    source = args.source
    if source == "auto":
        source = "google" if os.environ.get("GOOGLE_PLACES_API_KEY") else "osm"
    try:
        if source == "google":
            query = args.query or f"{v.search_suffix} in {args.market}"
            print(f"Searching Google Places (paid API): {query!r} (limit {args.limit})")
            found = search_places(query, limit=args.limit)
        else:
            print(f"Searching OpenStreetMap (free) for {v.key} businesses in {args.market!r}")
            found = search_osm(args.market, v.osm_tags, v.osm_name_words, limit=args.limit)
    except DiscoveryError as exc:
        sys.exit(f"error: {exc}")
    for b in found:
        db.upsert_business(conn, b, v.key, args.market)
    conn.commit()
    with_site = sum(1 for b in found if b.website)
    print(f"Stored {len(found)} businesses ({with_site} with websites).")
    if source == "osm":
        print("OpenStreetMap misses many businesses and has no reviews. Add more for free with `roofin add` "
              "while browsing Google Maps.")


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


def _businesses(conn, vertical: str, market: str | None) -> list[Business]:
    sql, params = "SELECT * FROM businesses WHERE vertical = ?", [vertical]
    if market:
        sql += " AND market = ?"
        params.append(market)
    return [db.row_to_business(r) for r in conn.execute(sql + " ORDER BY id", params)]


def cmd_audit(args, conn) -> None:
    v = verticals.get(args.vertical)
    markets = [args.market] if args.market else [
        r[0] for r in conn.execute("SELECT DISTINCT market FROM businesses WHERE vertical = ?", (v.key,))
    ]
    for market in markets:
        businesses = _businesses(conn, v.key, market)
        if args.limit:
            businesses = businesses[: args.limit]
        if not businesses:
            continue
        print(f"Auditing {len(businesses)} {v.key} businesses in {market or '(no market)'}…")

        def visit(b: Business) -> tuple[Business, SiteFacts | None, int]:
            if not b.website:
                return b, None, 0
            snap = fetch_site(b.website, max_pages=args.max_pages, respect_robots=not args.ignore_robots)
            return b, extract(snap), len(snap.pages)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            visited = list(pool.map(visit, businesses))
        all_facts = {b.id: f for b, f, _ in visited if f}
        ctx = build_market(businesses, all_facts, v, city_of(market))
        for b, facts, n_pages in visited:
            findings = detect(b, facts, v, ctx)
            s = score(b, findings, facts)
            db.save_audit(conn, b.id, s, findings, facts.error if facts else None, n_pages)
            if facts and facts.emails:
                conn.execute("UPDATE businesses SET email = ? WHERE id = ?", (facts.emails[0], b.id))
            print(f"  {s:5.1f}  {b.name[:40]:40}  {len(findings)} finding(s)")
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
    offer = cents(args.offer)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    already = {r[0] for r in conn.execute("SELECT business_id FROM outreach")}
    rows = [r for r in _ranked(conn, v.key, args.market, args.min_score) if r["id"] not in already][: args.top]
    if not rows:
        print("Nothing new to draft (all top prospects already have outreach, or nothing is audited).")
        return
    for r in rows:
        b = db.row_to_business(r)
        findings = db.audit_findings(conn, r["audit_id"])
        if not findings:
            continue
        draft = draft_email(b, findings, v, offer, sender)
        if args.llm:
            from .llm import polish
            draft, findings = polish(b, findings, v, city_of(r["market"]), offer, sender, draft)
        base = out_dir / f"{r['id']:04d}-{slug(b.name)}"
        base.with_suffix(".md").write_text(markdown(b, findings, r["score"], offer, draft), encoding="utf-8")
        base.with_suffix(".html").write_text(html_page(b, findings, offer), encoding="utf-8")
        channel = "email" if r["email"] else "phone" if r["phone"] else "web_form"
        now = db.now()
        conn.execute(
            """INSERT INTO outreach (business_id, audit_id, channel, recipient, subject, body, offer_cents,
               status, report_path, created_at, updated_at) VALUES (?,?,?,?,?,?,?,'draft',?,?,?)""",
            (r["id"], r["audit_id"], channel, r["email"] or r["phone"] or r["website"], draft.subject, draft.body,
             offer, str(base.with_suffix(".html")), now, now),
        )
        print(f"  drafted  {b.name[:40]:40} → {base}.md / .html  ({channel})")
    conn.commit()
    print("\nReview each draft, then: roofin mark <outreach-id> approved   (see ids with `roofin outreach`)")


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


def cmd_mark(args, conn) -> None:
    try:
        db.set_outreach_status(conn, args.id, args.status)
    except (ValueError, LookupError) as exc:
        sys.exit(f"error: {exc}")
    conn.commit()
    print(f"outreach #{args.id} → {args.status}")


def cmd_paid(args, conn) -> None:
    amount = cents(args.amount)
    try:
        db.set_outreach_status(conn, args.id, "paid")
    except LookupError as exc:
        sys.exit(f"error: {exc}")
    conn.execute("INSERT INTO payments (outreach_id, amount_cents, note, received_at) VALUES (?,?,?,?)",
                 (args.id, amount, args.note, db.now()))
    conn.commit()
    total = conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments").fetchone()[0]
    print(f"Recorded {money(amount)} from outreach #{args.id}. Lifetime revenue: {money(total)}")


def cmd_stats(args, conn) -> None:
    count = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    prospects = count("SELECT COUNT(*) FROM businesses")
    audited = count("SELECT COUNT(DISTINCT business_id) FROM audits")
    by_status = dict(conn.execute("SELECT status, COUNT(*) FROM outreach GROUP BY status").fetchall())
    contacted = sum(by_status.get(s, 0) for s in ("sent", "replied", "won", "paid", "lost", "opted_out"))
    replied = sum(by_status.get(s, 0) for s in ("replied", "won", "paid"))
    revenue = count("SELECT COALESCE(SUM(amount_cents),0) FROM payments")
    payers = count("SELECT COUNT(DISTINCT outreach_id) FROM payments")
    print(f"Prospects found      {prospects}")
    print(f"Audited              {audited}")
    print(f"Drafts / approved    {by_status.get('draft', 0)} / {by_status.get('approved', 0)}")
    print(f"Contacted            {contacted}")
    print(f"Replied              {replied}" + (f"  ({100 * replied / contacted:.0f}%)" if contacted else ""))
    print(f"Paying customers     {payers}")
    print(f"Revenue              {money(revenue)}")
    print()
    if revenue == 0:
        print("Goal: get one stranger to pay $1. Not there yet.")
    else:
        ladder = [100, 500, 2500, 10000]
        nxt = next((c for c in ladder if c > revenue), None)
        print("The machine has made money." + (f" Next rung: {money(nxt)}." if nxt else " Time for recurring."))


def cmd_run(args, conn) -> None:
    cmd_discover(args, conn)
    args.limit = None
    cmd_audit(args, conn)
    cmd_draft(args, conn)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="roofin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=os.environ.get("ROOFIN_DB", "roofin.db"), help="SQLite file (default roofin.db)")
    p.add_argument("--vertical", default="roofing", choices=verticals.available())
    sub = p.add_subparsers(dest="cmd", required=True)

    def audit_opts(sp):
        sp.add_argument("--max-pages", type=int, default=6, help="pages to visit per site")
        sp.add_argument("--workers", type=int, default=8)
        sp.add_argument("--ignore-robots", action="store_true", help="skip robots.txt checks (not recommended)")

    def draft_opts(sp):
        sp.add_argument("--top", type=int, default=10, help="how many new drafts to create")
        sp.add_argument("--min-score", type=float, default=30)
        sp.add_argument("--offer", default="25", help="price of the fix in dollars (default 25)")
        sp.add_argument("--out", default="out", help="where reports are written")
        sp.add_argument("--llm", action="store_true", help="polish copy with Claude (PAID API; the default template copy is free)")
        sp.add_argument("--sender-name", default=os.environ.get("ROOFIN_SENDER_NAME"))
        sp.add_argument("--sender-email", default=os.environ.get("ROOFIN_SENDER_EMAIL"))
        sp.add_argument("--sender-address", default=os.environ.get("ROOFIN_SENDER_ADDRESS"))

    def discover_opts(sp):
        sp.add_argument("--source", choices=("auto", "osm", "google"), default="auto",
                        help="osm = free OpenStreetMap; google = paid Places API; "
                             "auto = google only if GOOGLE_PLACES_API_KEY is set (default)")
        sp.add_argument("--limit", type=int, default=60, help="max results (Google caps a query at 60)")
        sp.add_argument("--query", help="override the Google search text")

    sp = sub.add_parser("discover", help="find businesses (free OpenStreetMap by default)")
    sp.add_argument("market", help='e.g. "Rochester NY"')
    discover_opts(sp)
    sp.set_defaults(fn=cmd_discover)

    sp = sub.add_parser("add", help="add one business by hand (e.g. copied from Google Maps), free")
    sp.add_argument("name")
    sp.add_argument("--market", required=True, help='e.g. "Rochester NY"')
    sp.add_argument("--website")
    sp.add_argument("--phone")
    sp.add_argument("--address")
    sp.add_argument("--rating", type=float, help="Google star rating, e.g. 4.6")
    sp.add_argument("--reviews", type=int, help="number of Google reviews")
    sp.add_argument("--review", action="append", help="paste a review's text; repeat for several")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("import", help="load businesses from a CSV instead of Google")
    sp.add_argument("csv")
    sp.add_argument("--market", required=True, help='e.g. "Rochester NY"')
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser("audit", help="visit websites and detect opportunities")
    sp.add_argument("--market")
    sp.add_argument("--limit", type=int)
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

    sp = sub.add_parser("outreach", help="list drafts / show one")
    sp.add_argument("--status", choices=db.OUTREACH_STATUSES)
    sp.add_argument("--show", type=int, metavar="ID")
    sp.set_defaults(fn=cmd_outreach)

    sp = sub.add_parser("mark", help="update an outreach status")
    sp.add_argument("id", type=int)
    sp.add_argument("status", choices=db.OUTREACH_STATUSES)
    sp.set_defaults(fn=cmd_mark)

    sp = sub.add_parser("paid", help="record money received")
    sp.add_argument("id", type=int, help="outreach id")
    sp.add_argument("amount", help="dollars, e.g. 1 or 25")
    sp.add_argument("--note")
    sp.set_defaults(fn=cmd_paid)

    sp = sub.add_parser("stats", help="funnel and revenue")
    sp.set_defaults(fn=cmd_stats)

    sp = sub.add_parser("run", help="discover + audit + draft for a market")
    sp.add_argument("market")
    discover_opts(sp)
    audit_opts(sp)
    draft_opts(sp)
    sp.set_defaults(fn=cmd_run)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    conn = db.connect(args.db)
    try:
        args.fn(args, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
