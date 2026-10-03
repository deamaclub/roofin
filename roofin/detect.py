"""Opportunity detectors: specific, evidenced reasons a business is losing leads online."""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from .facts import TESTIMONIAL_WORDS, SiteFacts
from .models import Business, Finding, MarketContext
from .verticals import Topic, Vertical

SLOW_SECONDS = 4.0


def _fmt(template: str, b: Business, ctx: MarketContext, v: Vertical) -> str:
    return template.format(
        name=b.name, city=ctx.city or "your area", phone=b.phone or "(your number)", cta=v.default_cta
    )


def has_cta(facts: SiteFacts, v: Vertical) -> bool:
    return any(p in facts.home_cta_text for p in v.cta_phrases)


def topic_covered(facts: SiteFacts, topic: Topic) -> bool:
    return any(w in facts.all_labels for w in topic.site_words)


def topic_review_mentions(b: Business, topic: Topic) -> list[str]:
    hits = []
    for r in b.reviews:
        text = r.text.lower()
        if any(w in text for w in topic.review_words):
            hits.append(r.text)
    return hits


def _quote(text: str, words: tuple[str, ...], width: int = 140) -> str:
    """Short excerpt of a review centered on the first matching word."""
    low = text.lower()
    idx = min((low.find(w) for w in words if w in low), default=0)
    start = max(0, idx - width // 2)
    snippet = text[start:start + width].strip()
    return ("…" if start else "") + snippet + ("…" if start + width < len(text) else "")


def build_market(businesses: list[Business], all_facts: dict[int, SiteFacts], v: Vertical,
                 city: str | None) -> MarketContext:
    counts = [b.review_count for b in businesses if b.review_count is not None]
    ctx = MarketContext(city=city, median_reviews=statistics.median(counts) if counts else None)
    # For each check, name the most-reviewed competitor that gets it right: concrete social proof for the pitch.
    by_reviews = sorted(businesses, key=lambda b: b.review_count or 0, reverse=True)
    ctx.leaders_by_reviews = any(b.review_count for b in businesses)
    checks = {
        "no_quote_form": lambda f: f.any_form,
        "weak_cta": lambda f: has_cta(f, v),
        "no_click_to_call": lambda f: f.any_tel,
    }
    for code, ok in checks.items():
        for b in by_reviews:
            f = all_facts.get(b.id)
            if f and f.reachable and ok(f):
                ctx.leaders[code] = b.name
                break
    return ctx


def detect(b: Business, facts: SiteFacts | None, v: Vertical, ctx: MarketContext,
           today: datetime | None = None) -> list[Finding]:
    today = today or datetime.now(timezone.utc)
    out: list[Finding] = []

    def leader_note(code: str) -> str:
        leader = ctx.leaders.get(code)
        if not leader or leader == b.name:
            return ""
        where = ctx.city or "your market"
        if ctx.leaders_by_reviews:
            return f" {leader}, one of the most-reviewed competitors in {where}, does."
        return f" {leader}, a competitor in {where}, does."

    # --- No site / broken site: the biggest leak of all.
    if not b.website:
        out.append(Finding(
            code="no_website", severity=3,
            title="You don't have a website, so people who find you on Google have nowhere to go",
            evidence=f"Your Google listing has {b.review_count or 0} reviews but no website link.",
            fix="A one-page site with your services, service area, reviews and a quote form.",
            sample=_fmt(v.hero_sample, b, ctx, v),
        ))
        return out + review_findings(b, v, ctx, today)
    if facts is None or not facts.reachable:
        out.append(Finding(
            code="site_down", severity=3,
            title="Your website didn't load when we tried it",
            evidence=f"{b.website} → {facts.error if facts else 'not checked'}",
            fix="Get the site back up (hosting, domain renewal, or SSL certificate), then add monitoring.",
        ))
        return out + review_findings(b, v, ctx, today)

    # --- Conversion basics.
    if not facts.any_form:
        out.append(Finding(
            code="no_quote_form", severity=3,
            title="There's no way to request a quote on your website without calling",
            evidence=f"We checked {len(facts.pages)} page(s) and found no estimate/contact form.{leader_note('no_quote_form')}",
            fix="Add a short form (name, phone, address, what's wrong) on the home page and every service page.",
            sample=f"[ Name ] [ Phone ] [ Address ] [ What do you need? ]  **[{v.default_cta}]**",
        ))
    if not has_cta(facts, v):
        out.append(Finding(
            code="weak_cta", severity=2,
            title=f"Your home page never asks visitors to \"{v.default_cta}\"",
            evidence=f"None of your home page buttons or links offer a free estimate, inspection or quote.{leader_note('weak_cta')}",
            fix=f"Put a high-contrast \"{v.default_cta}\" button in the header and the first screen.",
            sample=_fmt(v.hero_sample, b, ctx, v),
        ))
    if not facts.any_tel:
        if facts.phones_on_home or (b.phone and b.phone[-4:] in facts.home_text):
            out.append(Finding(
                code="no_click_to_call", severity=2,
                title="Mobile visitors can't tap your phone number to call",
                evidence=f"Your number appears as plain text; there's no tap-to-call link.{leader_note('no_click_to_call')}",
                fix="Wrap the phone number in a tel: link and add a sticky \"Call Now\" button on mobile.",
                sample=f'<a href="tel:{"".join(c for c in (b.phone or "") if c.isdigit())}">Call {b.phone or "now"}</a>',
            ))
        else:
            out.append(Finding(
                code="phone_hidden", severity=3,
                title="Your phone number isn't on your home page",
                evidence="We couldn't find a phone number or tap-to-call link on the home page.",
                fix="Put the phone number in the header of every page as a tap-to-call link.",
            ))

    # --- Industry topics: urgent pages without a way to act, and services customers talk about but the site ignores.
    for topic in v.topics:
        covered = topic_covered(facts, topic)
        if covered and topic.urgent:
            topic_pages = [p for p in facts.pages if any(w in p.label for w in topic.site_words)]
            stranded = [p for p in topic_pages if not p.has_form and not p.has_tel]
            if topic_pages and len(stranded) == len(topic_pages):
                out.append(Finding(
                    code=f"{topic.key}_page_no_action", severity=3,
                    title=f"Your {topic.page_name.lower()} page has no quote form or tap-to-call",
                    evidence=f"{stranded[0].url} — someone with an urgent problem lands here and has to go looking for how to reach you.",
                    fix="Add tap-to-call and a 4-field form at the top of the page.",
                    sample=_fmt(topic.sample, b, ctx, v),
                ))
        if not covered:
            mentions = topic_review_mentions(b, topic)
            if mentions:
                out.append(Finding(
                    code=f"{topic.key}_gap", severity=3 if len(mentions) >= 2 or topic.urgent else 2,
                    title=f"Your Google reviews mention {topic.page_name.lower()}, but your website has no page for it",
                    evidence=f"{len(mentions)} review(s), e.g. \"{_quote(mentions[0], topic.review_words)}\"",
                    fix=f"Add a dedicated \"{topic.page_name}\" page so people searching for it find you.",
                    sample=_fmt(topic.sample, b, ctx, v),
                ))

    # --- Trust.
    if (b.rating or 0) >= 4.5 and (b.review_count or 0) >= 10 and not any(w in facts.all_text for w in TESTIMONIAL_WORDS):
        out.append(Finding(
            code="reviews_not_shown", severity=2,
            title=f"You have {b.rating:.1f} stars from {b.review_count} Google reviews, but your website doesn't show them",
            evidence="No testimonials or review section found on the pages we checked.",
            fix="Add a reviews strip (3 short quotes + star rating + link to Google) near the top of the home page.",
            sample="\n".join(f"> ★★★★★ \"{_quote(r.text, ('',), 160)}\"" for r in b.reviews if (r.rating or 5) >= 5)[:900] or None,
        ))

    # --- Technical.
    if not facts.has_viewport:
        out.append(Finding(
            code="not_mobile_friendly", severity=2,
            title="Your website isn't set up for phones",
            evidence="The home page has no mobile viewport tag, so phones show a zoomed-out desktop page.",
            fix="Add a responsive layout (at minimum the viewport meta tag and a mobile stylesheet).",
            sample='<meta name="viewport" content="width=device-width, initial-scale=1">',
        ))
    if facts.home_seconds and facts.home_seconds > SLOW_SECONDS:
        out.append(Finding(
            code="slow", severity=2,
            title="Your home page is slow to load",
            evidence=f"The home page took {facts.home_seconds:.1f}s to respond to us.",
            fix="Compress images, enable caching, or move to faster hosting.",
        ))
    if not facts.https:
        out.append(Finding(
            code="no_https", severity=2,
            title="Browsers label your website \"Not secure\"",
            evidence=f"The site loads over plain http ({facts.pages[0].url}).",
            fix="Install a free SSL certificate and redirect http to https.",
        ))
    if ctx.city and ctx.city.lower() not in facts.all_text:
        out.append(Finding(
            code="city_missing", severity=1,
            title=f"Your website never mentions {ctx.city}",
            evidence=f"\"{ctx.city}\" doesn't appear on any page we checked, which makes it harder to rank for local searches.",
            fix=f"Name {ctx.city} and the towns you serve in the home page headline and a service-area section.",
        ))
    if not facts.meta_description:
        out.append(Finding(
            code="no_meta_description", severity=1,
            title="Google has no description to show for your home page",
            evidence="The home page has no meta description.",
            fix="Write a 150-character description with your service, city and offer.",
            sample=_fmt(f"{{name}}: trusted local {v.trade} serving {{city}}. {v.default_cta} — call {{phone}}.", b, ctx, v),
        ))
    if facts.copyright_year and facts.copyright_year < today.year - 2:
        out.append(Finding(
            code="stale_site", severity=1,
            title="Your website looks abandoned",
            evidence=f"The footer says © {facts.copyright_year}.",
            fix="Update the footer year and add something recent (a project photo, a new review).",
        ))
    return out + review_findings(b, v, ctx, today)


def review_findings(b: Business, v: Vertical, ctx: MarketContext, today: datetime) -> list[Finding]:
    out = []
    if ctx.median_reviews and b.review_count is not None and b.review_count < ctx.median_reviews / 2:
        out.append(Finding(
            code="few_reviews", severity=2,
            title="Competitors have far more Google reviews than you",
            evidence=f"You have {b.review_count}; the typical {v.trade} in this search has {ctx.median_reviews:.0f}.",
            fix="Text a review link to every customer the day the job is finished.",
        ))
    dates = []
    for r in b.reviews:
        if r.published:
            try:
                dates.append(datetime.fromisoformat(r.published.replace("Z", "+00:00")))
            except ValueError:
                pass
    if dates:
        days = (today - max(dates)).days
        if days > 180:
            out.append(Finding(
                code="no_recent_reviews", severity=1,
                title="Your newest Google review is months old",
                evidence=f"The most recent review we saw is {days} days old.",
                fix="Ask your last 10 customers for a review; recent reviews matter to buyers comparing roofers.",
            ))
    return out


def score(b: Business, findings: list[Finding], facts: SiteFacts | None) -> float:
    """0-100. High = a real, active business with serious, fixable problems we can reach."""
    if b.status and b.status != "OPERATIONAL":
        return 0.0
    if any(f.code in ("no_website", "site_down") for f in findings):
        opportunity = 1.0  # every visitor is lost; the easiest fix to prove
    else:
        opportunity = min(sum(sorted((f.severity for f in findings), reverse=True)[:4]), 12) / 12
    viability = 0.4
    if (b.review_count or 0) >= 5:
        viability += 0.3  # has customers, so has revenue and something to lose
    if (b.rating or 0) >= 4.0:
        viability += 0.1
    if (facts and facts.emails) or b.phone:
        viability += 0.2  # we can actually contact them
    return round(100 * opportunity * min(viability, 1.0), 1)
