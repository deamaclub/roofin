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

1. **Payments**: asks Stripe which payment links were paid, records them with Stripe's real fee, turns those
   links off, and pings your Telegram.
2. **Find** roofers in each market (searched again every 30 days; repeats are merged).
3. **Audit** every new business's website and listing and collect **all contact info** it publishes: emails
   (the business's own, not the web designer's), every phone number, contact-form page, Facebook/Instagram/
   LinkedIn/Yelp/etc., WhatsApp links.
4. **Draft**, per prospect: the email, a short message for forms/DMs/texts, a **demo page** (the report with
   ready-to-use fix copy, at an unguessable URL, hidden from search engines) and a **Stripe payment link**,
   priced to keep $5 after fees.
5. **Publish** new demos (Cloudflare Pages or Netlify). Anything that links to a demo waits until it's live.
6. **Inbox** (if Gmail is set up): replies go to your Telegram with a ready answer; "stop / unsubscribe /
   not interested" suppresses that whole company forever.
7. **Send** (if Gmail is set up): one email per business to all its addresses, max 15/day, plus **one**
   follow-up after 4 days of silence, in the same thread.
8. **Telegram you a card per prospect**: what's wrong, every contact method, the demo and pay links, numbered
   steps ("1. open the contact form → paste SHORT MESSAGE"), and each message in its own block, so one tap
   copies it. WhatsApp links open with the message already typed; you press send.

No Telegram? The loop prints the by-hand list instead. Sites that looked *down* are never auto-pitched (it
might have been your connection): check them and `roofin mark <id> approved`. `--dry-run` shows what would
go out; `--approved-only` sends only what you approved.

**When someone says yes:** paste the "IF THEY SAY YES" block, do the fix (the copy is on the demo page), and
they pay through the Stripe link. The next loop records it.

## Setup ($0)

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
sudo apt install -y nodejs npm        # only for Cloudflare Pages demos
```

Copy `.env.example` to `.env` in the folder you run roofin from (or to `~/.roofin.env`) and fill it in.
roofin reads it automatically. Never commit it (`.env` is git-ignored).

| Variable | What | Cost |
|---|---|---|
| `ROOFIN_SENDER_NAME`, `ROOFIN_SENDER_EMAIL` | You | — |
| `ROOFIN_SENDER_ADDRESS` | A real postal address (US law for commercial email; a PO box works) | — |
| `SERPAPI_KEY` | Google Maps data incl. ratings & reviews. Free plan, 250 searches/month, no card | $0 |
| `ROOFIN_TELEGRAM_TOKEN`, `ROOFIN_TELEGRAM_CHAT_ID` | Your bot: Telegram → @BotFather → `/newbot`; message the bot, then `roofin telegram-setup` prints the chat id | $0 |
| `STRIPE_SECRET_KEY` | Restricted key: write Products/Prices/Payment Links, read Checkout Sessions/Payment Intents/Charges/Balance transactions. `rk_test_…` to try with fake cards | fee only when paid |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `ROOFIN_CF_PROJECT` | Demo hosting on Cloudflare Pages: unlimited static bandwidth, 500 deploys/month. Token template "Edit Cloudflare Pages"; project name becomes `https://<name>.pages.dev` | $0 |
| `ROOFIN_SMTP_USER`, `ROOFIN_SMTP_PASSWORD` | Optional auto-email: your Gmail + an [App Password](https://myaccount.google.com/apppasswords). Leave unset to send everything yourself from the Telegram cards | $0 |
| `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID` | Alternative demo host (about 20 deploys/month free; the site pauses if credits run out) | $0 |
| `ROOFIN_PAY_LINK` | Fallback pay link (PayPal.me) if you don't use Stripe | $0 until paid |

Everything is optional except the sender lines: without SerpApi it uses OpenStreetMap, without a demo host the
demo is sent to your Telegram as a file, without Stripe it uses `ROOFIN_PAY_LINK`.

**Free-tier budgets** are counted locally and never exceeded: SerpApi 250 calls/month (a new market is about
13), Cloudflare 450 deploys/month (one per run at most, and only if something changed), Netlify 15 deploys/month.
At their limits these services refuse instead of billing.

## Money: never spend a dime you didn't earn

```bash
roofin price                       # with Stripe: Charge $6 (2.9% + $0.30 = $0.48) → you keep $5.52
roofin price --processor paypal    # Charge $6 via paypal (3.49% + $0.49 fee = $0.70) → you keep $5.30
roofin price --processor zelle     # Charge $5 → you keep $5.00
roofin paid 3 6                    # record a non-Stripe payment (Stripe ones are recorded automatically)
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
roofin notify                      # send pending prospects to Telegram
roofin publish                     # push new demos live
roofin payments                    # check Stripe now
roofin telegram-setup              # find your chat id, send a test message
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

* **Done:** find → audit → all contacts → demo + pay link → send / Telegram hand-off → replies/opt-outs →
  follow-up → Stripe payments → expense guard.
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
  telegram.py    your bot: messages and files to you
  cards.py       the copy-paste Telegram card per prospect, reply cards
  cloudflare.py  demo pages on Cloudflare Pages (via wrangler)
  netlify.py     demo pages on Netlify (file-digest API)
  stripe_pay.py  payment link per prospect, payment detection
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
