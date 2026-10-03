from __future__ import annotations

from email.message import EmailMessage

import pytest

from roofin import cli, crawl, db, pricing, serp
from roofin.contacts import usable_emails, whatsapp_link
from roofin.mailer import parse_reply
from conftest import STRONG_ROUTES, WEAK_ROUTES, FakeSession
from test_cli import CSV


# ---------------------------------------------------------------- units

@pytest.mark.parametrize("proc", sorted(pricing.PROCESSORS))
def test_price_nets_at_least_five(proc):
    pct, fixed = pricing.PROCESSORS[proc]
    price = pricing.price_for_profit(500, pct, fixed)
    assert price % 100 == 0
    assert price - pricing.fee_cents(price, pct, fixed) >= 500
    assert price - 100 - pricing.fee_cents(price - 100, pct, fixed) < 500  # and it's the cheapest such price


def test_usable_emails_keeps_owner_drops_vendors():
    got = usable_emails(
        ["office@abcroofing.com", "bob.abc@gmail.com", "support@wixsites.com", "noreply@abcroofing.com",
         "help@webdesignpros.com"], "https://www.abcroofing.com/")
    assert got == ["bob.abc@gmail.com", "office@abcroofing.com"]


def test_whatsapp_link_is_manual_click_to_chat():
    assert whatsapp_link("(585) 555-0101", "hi there") == "https://wa.me/15855550101?text=hi%20there"
    assert whatsapp_link("12", "x") is None


def reply(sender, text, refs=None, subject="Re: 3 things"):
    m = EmailMessage()
    m["From"], m["Subject"] = sender, subject
    if refs:
        m["In-Reply-To"] = refs
    m.set_content(text + "\n\nOn Mon, Oct 5, 2026 Terry wrote:\n> original")
    return m


def test_parse_reply_detects_opt_out_and_strips_quote():
    r = parse_reply(reply("Bob <BOB@abc.com>", "Please remove me from your list"))
    assert r.opt_out and r.sender == "bob@abc.com" and "original" not in r.text
    assert not parse_reply(reply("bob@abc.com", "Sure, what would the storm page cost?")).opt_out


class FakeHTTP:
    def __init__(self, payloads):
        self.payloads, self.calls = list(payloads), []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        data = self.payloads.pop(0)

        class R:
            status_code, text = 200, "{}"

            def json(self):
                return data
        return R()


def test_serpapi_search_reviews_and_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "k")
    monkeypatch.setenv("ROOFIN_SERPAPI_MONTHLY", "2")
    conn = db.connect(str(tmp_path / "t.db"))
    http = FakeHTTP([
        {"local_results": [{"title": "ABC Roofing", "place_id": "p1", "data_id": "d1", "website": "abc.com",
                            "phone": "(585) 555-0101", "rating": 4.7, "reviews": 12}]},
        {"reviews": [{"rating": 5, "snippet": "Storm damage fixed", "iso_date": "2026-09-01T00:00:00Z"}]},
    ])
    [(b, data_id)] = serp.search_maps(conn, "roofers in Rochester NY", session=http)
    assert (b.name, b.review_count, b.rating, data_id) == ("ABC Roofing", 12, 4.7, "d1")
    assert http.calls[0]["engine"] == "google_maps" and http.calls[0]["api_key"] == "k"
    assert serp.fetch_reviews(conn, "d1", session=http)[0].text == "Storm damage fixed"
    assert serp.remaining(conn) == 0
    with pytest.raises(Exception, match="used up"):
        serp.search_maps(conn, "again", session=http)


# ---------------------------------------------------------------- the loop, end to end with fakes

class FakeMailer:
    def __init__(self):
        self.sent, self.inbox = [], []

    def send(self, msg):
        self.sent.append(msg)

    def fetch_recent(self, days=21):
        return self.inbox


@pytest.fixture
def machine(tmp_path, monkeypatch):
    session = FakeSession({**WEAK_ROUTES, **STRONG_ROUTES})
    real = crawl.fetch_site
    monkeypatch.setattr(cli, "fetch_site", lambda url, **kw: real(url, session=session, **kw))
    mailer = FakeMailer()
    monkeypatch.setattr(cli, "make_mailer", lambda cfg: mailer)
    for k, v in {"ROOFIN_SENDER_NAME": "Terry", "ROOFIN_SENDER_EMAIL": "terry@gmail.com",
                 "ROOFIN_SENDER_ADDRESS": "123 Main St, Rochester NY", "ROOFIN_SMTP_USER": "terry@gmail.com",
                 "ROOFIN_SMTP_PASSWORD": "app-pass", "ROOFIN_PAY_LINK": "https://paypal.me/terry"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    (tmp_path / "leads.csv").write_text(CSV)
    dbfile = str(tmp_path / "t.db")

    def run(*argv):
        cli.main(["--db", dbfile, *argv])
    run("import", str(tmp_path / "leads.csv"), "--market", "Rochester NY")
    return run, mailer, dbfile, tmp_path


def loop(run, tmp_path, *extra):
    run("loop", "Rochester NY", "--delay", "0", "--rediscover-days", "9999", "--out", str(tmp_path / "out"), *extra)


def test_loop_sends_once_handles_replies_and_follows_up(machine, capsys):
    run, mailer, dbfile, tmp_path = machine
    loop(run, tmp_path)
    out = capsys.readouterr().out
    assert len(mailer.sent) == 1
    msg = mailer.sent[0]
    assert msg["To"] == "office@abcroofing.com"
    body = msg.get_content()
    assert "$6" in body and "https://paypal.me/terry" in body and "123 Main St" in body
    assert msg["List-Unsubscribe"]
    # Joe's Roofs has no website/email: shows up as a by-hand task with a WhatsApp link, nothing auto-sent
    assert "Joe's Roofs" in out and "https://wa.me/15855550000" in out

    # Running again the same day sends nothing new.
    loop(run, tmp_path)
    assert len(mailer.sent) == 1

    # Four days later with no reply: exactly one follow-up, in the same thread.
    conn = db.connect(dbfile)
    conn.execute("UPDATE outreach SET sent_at = '2026-01-01T00:00:00+00:00' WHERE status = 'sent'")
    conn.commit()
    loop(run, tmp_path)
    assert len(mailer.sent) == 2
    assert mailer.sent[1]["In-Reply-To"] == msg["Message-ID"] and mailer.sent[1]["Subject"].startswith("Re:")
    loop(run, tmp_path)
    assert len(mailer.sent) == 2

    # They reply "stop": suppressed forever.
    mailer.inbox = [reply("office@abcroofing.com", "stop emailing me", refs=msg["Message-ID"])]
    capsys.readouterr()
    loop(run, tmp_path)
    assert "OPT-OUT" in capsys.readouterr().out
    assert db.suppressed(conn, "office@abcroofing.com") and db.suppressed(conn, "anyone@abcroofing.com")
    assert conn.execute("SELECT status FROM outreach WHERE channel='email'").fetchone()[0] == "opted_out"


def test_reply_marks_replied(machine, capsys):
    run, mailer, dbfile, tmp_path = machine
    loop(run, tmp_path)
    mailer.inbox = [reply("Owner <office@abcroofing.com>", "Yes, do the storm page please")]
    capsys.readouterr()
    run("inbox")
    assert "REPLY" in capsys.readouterr().out
    conn = db.connect(dbfile)
    row = conn.execute("SELECT status, reply_snippet FROM outreach WHERE channel='email'").fetchone()
    assert row["status"] == "replied" and "storm page" in row["reply_snippet"]


def test_daily_cap_and_dry_run(machine):
    run, mailer, dbfile, tmp_path = machine
    loop(run, tmp_path, "--dry-run")
    assert mailer.sent == []
    loop(run, tmp_path, "--daily-cap", "0")
    assert mailer.sent == []


def test_spending_only_from_earnings(machine, capsys):
    run, mailer, dbfile, tmp_path = machine
    with pytest.raises(SystemExit, match="Refused"):
        run("expense", "SerpApi", "4")
    loop(run, tmp_path)
    oid = db.connect(dbfile).execute("SELECT id FROM outreach WHERE channel='email'").fetchone()[0]
    run("paid", str(oid), "6")  # paypal: $6 - (21c + 49c) = $5.30 kept
    capsys.readouterr()
    run("expense", "SerpApi", "4")
    assert "Left to spend: $1.30" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="Refused"):
        run("expense", "More", "2")


def test_opted_out_business_is_never_redrafted(machine, capsys):
    run, mailer, dbfile, tmp_path = machine
    conn = db.connect(dbfile)
    db.suppress(conn, "abcroofing.com", "test")
    conn.commit()
    loop(run, tmp_path)
    assert mailer.sent == []
    names = [r[0] for r in conn.execute(
        "SELECT b.name FROM outreach o JOIN businesses b ON b.id = o.business_id")]
    assert "ABC Roofing" not in names
