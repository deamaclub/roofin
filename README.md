# roofin — the $1 Roofing Opportunity Agent

Not a SaaS. A machine with one job:

**find a business losing money online → prove it → ask for a small payment.**

```
Google Maps → roofers → website + reviews audit → specific evidenced problems
           → one-page report with a ready-to-use fix → outreach draft → you approve & send
           → "I'll fix one for $25. If you don't like it, don't pay." → roofin paid 7 25
```

The KPI is `roofin stats`. Until it says someone paid $1, nothing else matters.

## What it checks

For every business it finds, roofin visits the website (home page plus the ~5 pages a customer would
click: contact, quote, emergency, storm, services…) and reads the Google listing and reviews.

| Finding | Why it costs leads |
|---|---|
| No website / site down | Everyone who finds them on Google hits a dead end |
| No quote/estimate form on any page | Only people willing to call convert |
| Emergency/storm page with no form or tap-to-call | The most urgent, highest-value visitors get stranded |
| Reviews mention storm, hail, insurance, gutters… but the site has no page for it | Customers are telling you what they buy; search can't find it |
| No "Free Inspection / Estimate" CTA on the home page | Competitor X has one (named from the same search) |
| Phone number not tap-to-call / missing | Mobile visitors can't call in one tap |
| 4.5★+ on Google but no reviews shown on the site | Free trust left on the table |
| Not mobile-friendly, slow, no HTTPS ("Not secure") | Visitors bounce |
| City never mentioned, no meta description, © 2019 footer | Local ranking + "is this business still open?" |
| Far fewer reviews than the local median, no recent reviews | Loses side-by-side comparisons |

Each finding carries **evidence** (the URL, the review quote, the competitor's name) and, where possible,
a **sample fix** — actual replacement copy using the business's name, city and phone. That sample is the
proof that gets the reply.

Every business gets a **prospect score** (0–100): severity of the problems × whether it's a real, active,
reachable business with customers. Closed businesses score 0. Clean sites score low and are never pitched.

## Setup

```bash
pip install -e .            # add [llm] for optional Claude copywriting, [dev] for tests
export GOOGLE_PLACES_API_KEY=...          # Places API (New) enabled
export ROOFIN_SENDER_NAME="Your Name"
export ROOFIN_SENDER_EMAIL="you@yourdomain.com"
export ROOFIN_SENDER_ADDRESS="Your real postal address"   # legally required in US commercial email
```

No Google key? Build a CSV by hand from Google Maps (`name,website,phone,rating,review_count,reviews`,
multiple reviews separated by ` || `) and use `roofin import`.

> Cost note: requesting `reviews` from Places puts the call in a higher pricing tier. A 60-business
> search is a few API calls; check current Google pricing for your account.

## Use

```bash
roofin run "Rochester NY"              # discover (≤60 per query) + audit + draft top 10
# or step by step:
roofin discover "Rochester NY"
roofin discover "Rochester NY" --query "roof repair in Greece NY"   # widen the net; dedupes by place id
roofin import leads.csv --market "Rochester NY"
roofin audit
roofin prospects                       # ranked, with each one's top 3 problems
roofin draft --top 10 --offer 25       # writes out/NNNN-name.md (internal) + .html (client-facing)
roofin draft --llm                     # same, copy polished by Claude; facts stay from the detectors

roofin outreach                        # list drafts
roofin outreach --show 3               # read one
roofin mark 3 approved                 # you read it and it's accurate
roofin mark 3 sent                     # you sent it yourself
roofin mark 3 replied
roofin paid 3 1 --note "first dollar"
roofin stats
```

`--vertical hvac` swaps the industry pack. Everything else is the same engine.

### What V1 deliberately does not do

* **It never sends anything.** You read each draft and send it yourself (email, their contact form, or a
  phone call using the report as your script). Every claim in a draft comes from something the detectors
  actually saw; verify it before you send.
* **It never touches Google listings.** Google is used read-only to research legitimate businesses. No fake
  reviews, fake profiles, or listing manipulation — Google prohibits it, and lead-gen businesses aren't even
  eligible for a Business Profile.
* It respects `robots.txt`, visits at most 6 pages per site, and identifies itself in the User-Agent.

### Sending responsibly

Drafts include your name, a real postal address, and a "reply stop" line (CAN-SPAM). One personal email per
business; if they say stop, `roofin mark <id> opted_out` and never contact them again. Send from your own
mailbox, a few a day, not a bulk tool.

## The ladder

1. Get one stranger to pay **$1** (`--offer 1`, or "free sample, $25 for the full fix").
2. $5 → $25 → $100 per fix.
3. Recurring: monthly re-audit + fixes for $49–$199/month.

## Roadmap

* **V1 (this)** — find, audit, report, draft; you approve and send.
* **V2** — automated sending with throttling, reply detection, follow-ups, opt-out handling.
* **V3** — after written authorization, the agent applies fixes to the client's site.
* **V4** — monthly monitoring + re-audit report, billed as a subscription.

## Adding a vertical

Copy `roofin/verticals/roofing.py`, change the vocabulary (`review_words`, `site_words`), CTA phrases and
sample copy, and register it in `roofin/verticals/__init__.py`. Plumbers, electricians, tree service, junk
removal, concrete, pressure washing, auto detailing — same engine, new word lists.

## Layout

```
roofin/
  discovery.py   Google Places text search / CSV import
  crawl.py       polite shallow crawl (robots.txt, priority links)
  facts.py       HTML → facts (forms, tel links, CTAs, emails, viewport, nav…)
  detect.py      findings, competitor leaders, prospect score
  verticals/     industry packs (roofing, hvac)
  outreach.py    email draft + offer
  report.py      Markdown (internal) and HTML (client-facing) one-pagers
  llm.py         optional Claude rewrite of copy (structured output, no new claims)
  db.py          SQLite: businesses, audits, findings, outreach, payments
  cli.py         the commands above
tests/           offline tests with fixture websites (pytest)
```
