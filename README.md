# roofin — the Roofing Opportunity Agent

Not a SaaS. A machine with one job:

**find a business losing money online → prove it → ask for a small payment.**

```
Google Maps (SerpApi free plan) → roofers → website + reviews audit → specific evidenced problems
   → one-page report with a ready-to-use fix → email to every address they publish
   → "I'll fix one for $6. If you don't like it, don't pay." → replies, opt-outs, one follow-up
   → roofin paid 7 6 → repeat tomorrow
```

The KPI is `roofin stats`. Until it says someone paid, nothing else matters. Running it costs $0.

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

## The loop

```
roofin loop "Rochester NY" "Buffalo NY"
```

One pass, safe to run every day (Windows Task Scheduler / cron):

1. **Find** roofers in each market (searched again every 30 days; repeats are merged).
2. **Audit** every new business's website and listing.
3. **Collect every email** on the site that belongs to the business (same domain as the site, or a Gmail-type
   address). Web-designer and no-reply addresses are dropped.
4. **Draft** a report + email for the top prospects, priced to keep $5 after payment fees.
5. **Read your inbox**: replies are flagged for you; "stop / unsubscribe / not interested" suppresses that
   whole company forever (every address, and the domain).
6. **Send** new pitches (one email per business, to all of its addresses) and **one** follow-up after 4 days
   of silence, in the same thread. Hard cap: 15 emails/day, spaced out.
7. **Print your by-hand list**: businesses with only a phone number get a short script and a WhatsApp link
   that opens with the message typed; you press send (or call them).
8. **Stats**: funnel, revenue, profit, free-tier usage.

Sites that looked *down* are never auto-pitched (it might have been your connection): check them and
`roofin mark <id> approved`. Use `--dry-run` to see what would go out, or `--approved-only` to send only what
you've approved.

**When someone says yes:** you do the fix (the report has the copy), send your pay link, then
`roofin paid <id> 6`.

## Setup ($0)

```bash
pip install -e .
```

Set these once (PowerShell: `$env:NAME = "value"`; macOS/Linux: `export NAME=value`):

| Variable | What | Cost |
|---|---|---|
| `ROOFIN_SENDER_NAME`, `ROOFIN_SENDER_EMAIL` | You | — |
| `ROOFIN_SENDER_ADDRESS` | A real postal address (US law for commercial email; a PO box works) | — |
| `SERPAPI_KEY` | Google Maps data incl. ratings & reviews. Free plan, 250 searches/month, no card | $0 |
| `ROOFIN_SMTP_USER`, `ROOFIN_SMTP_PASSWORD` | Your Gmail + an [App Password](https://myaccount.google.com/apppasswords) (needs 2-step verification) | $0 |
| `ROOFIN_PAY_LINK` | Your PayPal.me (or other) link, put in emails | $0 until paid |
| `ROOFIN_PROCESSOR` | `paypal` (default), `stripe`, `venmo`, `cashapp`, `zelle`, which sets the fees | — |

No `SERPAPI_KEY`? Discovery falls back to OpenStreetMap (free, no account, fewer businesses, no reviews).
No mail settings? The loop still drafts everything; you send by hand.

**SerpApi budget:** a market search costs 3 calls (60 businesses), reviews cost 1 call each and are fetched
only for the top 10 new prospects. Roughly 13 calls per new market, so about 15 markets/month on the free
plan. roofin counts calls and stops at 250 (`ROOFIN_SERPAPI_MONTHLY` to change). At the limit, SerpApi
refuses instead of billing, because the free plan has no card on file.

## Money: never spend a dime you didn't earn

```bash
roofin price                       # Charge $6 via paypal (3.49% + $0.49 fee = $0.70) → you keep $5.30
roofin price --processor zelle     # Charge $5 → you keep $5.00
roofin paid 3 6                    # records the payment and its fee
roofin expense "SerpApi upgrade" 4 # allowed only if earnings cover it; otherwise refused
roofin stats
```

The price is the cheapest whole-dollar amount that keeps `--profit` (default $5) after fees. Every expense is
checked against profit already received, so any bill is paid by a customer, not by you.

## Other commands

```bash
roofin discover "Rochester NY"     # just find (serpapi if key, else osm; --source to force)
roofin add "ABC Roofing" --market "Rochester NY" --website abcroofing.com --rating 4.7 --reviews 12 \
    --review "They tarped our roof the same day after the storm"
roofin import leads.csv --market "Rochester NY"   # name,website,phone,address,rating,review_count,reviews
roofin audit [--new-only]
roofin prospects                   # ranked, with each one's top 3 problems
roofin draft                       # reports in out/: .md (internal) and .html (client-facing)
roofin outreach / --show 3         # list / read one (and their reply)
roofin send [--dry-run]            # just the sending step
roofin inbox                       # just the reply-reading step
roofin calls                       # phone-only prospects, script + WhatsApp link
roofin mark 3 approved|sent|replied|won|lost|opted_out
```

## What it won't do, and why

* **Auto-message WhatsApp or Telegram.** WhatsApp bans numbers that send unsolicited messages or use
  unofficial automation, and its official API needs recipient opt-in and charges per conversation. Telegram
  bans accounts for unsolicited bulk messages. Automated texts to cell phones also fall under the TCPA in the US
  ($500–$1,500 per message). So phone-only leads get a script and a click-to-chat link, and you send each one
  yourself.
* **Touch Google listings.** Google is only read. No fake reviews or profiles.
* **Email anyone twice** beyond one follow-up, or ever again after "stop".
* **Spend money you haven't earned.** `--llm` (Claude copy polish) is the only paid feature, off by default.

## Sending responsibly

Every email has your name, real postal address, an honest subject, a "reply stop" line and a
List-Unsubscribe header (CAN-SPAM). Keep the daily cap low: a personal Gmail that blasts strangers gets
flagged, and then nothing you send lands. 10–15 a day of specific, personal emails beats 200 generic ones.

## Roadmap

* **Done:** find → audit → report → send → replies/opt-outs → follow-up → payments & expense guard.
* **Next:** after written authorization, apply fixes to the client's site; monthly re-audit billed as a
  subscription ($49–$199/month).

## Adding a vertical

Copy `roofin/verticals/roofing.py`, change the vocabulary (`review_words`, `site_words`), CTA phrases and
sample copy, and register it in `roofin/verticals/__init__.py`. Plumbers, electricians, tree service, junk
removal, concrete, pressure washing, auto detailing — same engine, new word lists.

## Layout

```
roofin/
  discovery.py   OpenStreetMap (free) / Google Places (paid) / CSV import
  serp.py        SerpApi Google Maps + reviews (free plan), with a monthly call budget
  crawl.py       polite shallow crawl (robots.txt, priority links)
  facts.py       HTML → facts (forms, tel links, CTAs, emails, viewport, nav…)
  detect.py      findings, competitor leaders, prospect score
  verticals/     industry packs (roofing, hvac)
  contacts.py    which emails belong to the business; WhatsApp click-to-chat links
  outreach.py    email draft, follow-up, offer
  pricing.py     price that nets your target profit after payment fees
  mailer.py      send via your mailbox (SMTP), read replies (IMAP), opt-out detection
  report.py      Markdown (internal) and HTML (client-facing) one-pagers
  llm.py         optional Claude rewrite of copy (structured output, no new claims)
  db.py          SQLite: businesses, audits, findings, outreach, payments, expenses, suppressions
  cli.py         the commands above
tests/           offline tests with fixture websites (pytest)
```
