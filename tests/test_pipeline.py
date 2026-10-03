from __future__ import annotations

from datetime import datetime, timezone

from roofin import verticals
from roofin.crawl import fetch_site
from roofin.detect import build_market, detect, score
from roofin.discovery import parse_place
from roofin.facts import extract
from roofin.models import Business, Review
from roofin.outreach import Sender, draft_email
from roofin.report import html_page, markdown

ROOFING = verticals.get("roofing")
TODAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
SENDER = Sender("Terry", "terry@example.org", "123 Main St, Rochester NY 14604")


def weak_business():
    return Business(
        id=1, name="ABC Roofing", website="abcroofing.com", phone="(585) 555-0101", rating=4.7, review_count=12,
        reviews=[
            Review(5, "After the storm took half our shingles off they came out the next day.", "2026-09-01T00:00:00Z"),
            Review(5, "Hail damage everywhere and they handled the insurance claim with our adjuster.", "2026-08-01T00:00:00Z"),
        ],
    )


def strong_business():
    return Business(id=2, name="Summit Roofing", website="https://summitroofing.com", phone="(585) 555-0199",
                    rating=4.9, review_count=240,
                    reviews=[Review(5, "Storm damage fixed fast.", "2026-09-20T00:00:00Z")])


def audit(b, session):
    facts = extract(fetch_site(b.website, session=session))
    return facts


def test_crawl_follows_priority_links(weak_session):
    snap = fetch_site("abcroofing.com", session=weak_session)
    urls = [p.url for p in snap.pages]
    assert urls[0] == "http://abcroofing.com"
    assert "http://abcroofing.com/emergency-roof-repair" in urls
    assert "http://abcroofing.com/contact" in urls


def test_facts_from_weak_site(weak_session):
    f = audit(weak_business(), weak_session)
    assert f.reachable and not f.https and not f.has_viewport
    assert not f.any_form, "a search box is not a lead form"
    assert not f.any_tel
    assert f.emails == ["office@abcroofing.com"]
    assert f.copyright_year == 2019


def test_weak_site_findings(weak_session, strong_session):
    weak, strong = weak_business(), strong_business()
    facts = {1: audit(weak, weak_session), 2: audit(strong, strong_session)}
    ctx = build_market([weak, strong], facts, ROOFING, "Rochester")
    codes = {f.code for f in detect(weak, facts[1], ROOFING, ctx, TODAY)}
    assert {"no_quote_form", "weak_cta", "no_click_to_call", "emergency_page_no_action", "storm_gap",
            "insurance_gap", "reviews_not_shown", "not_mobile_friendly", "no_https", "city_missing",
            "stale_site"} <= codes
    # competitor proof points at the business that does it right
    assert ctx.leaders["no_quote_form"] == "Summit Roofing"


def test_strong_site_is_mostly_clean(strong_session):
    strong = strong_business()
    facts = audit(strong, strong_session)
    ctx = build_market([strong], {2: facts}, ROOFING, "Rochester")
    findings = detect(strong, facts, ROOFING, ctx, TODAY)
    assert [f for f in findings if f.severity >= 2] == []


def test_score_prefers_weak_but_viable(weak_session, strong_session):
    weak, strong = weak_business(), strong_business()
    facts = {1: audit(weak, weak_session), 2: audit(strong, strong_session)}
    ctx = build_market([weak, strong], facts, ROOFING, "Rochester")
    s_weak = score(weak, detect(weak, facts[1], ROOFING, ctx, TODAY), facts[1])
    s_strong = score(strong, detect(strong, facts[2], ROOFING, ctx, TODAY), facts[2])
    assert s_weak > 70 > s_strong
    closed = Business(name="Gone", status="CLOSED_PERMANENTLY")
    assert score(closed, detect(closed, None, ROOFING, ctx, TODAY), None) == 0


def test_no_website():
    b = Business(id=3, name="Joe's Roofs", phone="585-555-0000", review_count=30, rating=4.8)
    ctx = build_market([b], {}, ROOFING, "Rochester")
    findings = detect(b, None, ROOFING, ctx, TODAY)
    assert findings[0].code == "no_website"
    assert score(b, findings, None) >= 90
    assert "Rochester" in findings[0].sample and "585-555-0000" in findings[0].sample


def test_report_and_email(weak_session):
    weak = weak_business()
    facts = audit(weak, weak_session)
    ctx = build_market([weak], {1: facts}, ROOFING, "Rochester")
    findings = detect(weak, facts, ROOFING, ctx, TODAY)
    draft = draft_email(weak, findings, ROOFING, 2500, SENDER)
    assert draft.subject == "3 things that may be costing ABC Roofing leads"
    assert "$25" in draft.body and "don't pay" in draft.body
    assert SENDER.postal_address in draft.body and "stop" in draft.body.lower()
    md = markdown(weak, findings, 80, 2500, draft)
    assert "Outreach draft" in md
    page = html_page(weak, findings, 2500)
    assert "Outreach" not in page and "score" not in page.lower()
    assert "<script" not in page


def test_parse_place():
    b = parse_place({
        "id": "abc", "displayName": {"text": "X Roofing"}, "websiteUri": "https://x.com", "rating": 4.2,
        "userRatingCount": 9, "businessStatus": "OPERATIONAL",
        "reviews": [{"rating": 5, "text": {"text": "Great"}, "publishTime": "2026-01-01T00:00:00Z"}],
    })
    assert b.name == "X Roofing" and b.review_count == 9 and b.reviews[0].text == "Great"
