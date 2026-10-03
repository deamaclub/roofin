"""Telegram cards, Netlify demos, Stripe payment links: the copy-paste hand-off."""
from __future__ import annotations

import hashlib
import json

import pytest

from roofin import cli, crawl, db
from roofin.cards import prospect_card
from roofin.crawl import fetch_site
from roofin.facts import extract, format_phone
from roofin.models import Finding
from roofin.netlify import Netlify, NetlifyError
from roofin.stripe_pay import Stripe
from roofin.telegram import split
from conftest import STRONG_ROUTES, WEAK_ROUTES, FakeSession
from test_cli import CSV
from test_loop import FakeMailer


def test_collects_all_contact_info(weak_session, strong_session):
    weak = extract(fetch_site("abcroofing.com", session=weak_session))
    assert weak.phones == ["(585) 555-0101"]
    assert weak.socials == {"facebook": "https://www.facebook.com/abcroofingroc"}  # share button ignored
    assert weak.contact_form_url is None
    strong = extract(fetch_site("https://summitroofing.com", session=strong_session))
    assert strong.contact_form_url == "https://summitroofing.com"
    assert "(585) 555-0199" in strong.phones
    assert format_phone("+1 585.555.0101") == "(585) 555-0101" and format_phone("123") is None


def test_card_is_copy_paste_ready():
    f = [Finding("no_quote_form", "There's no way to request a quote", 3, "e", "Add a form", "sample")]
    msgs = prospect_card(
        outreach_id=7, name="ABC <Roofing>", market="Rochester NY", score=91.7, rating=4.7, review_count=12,
        website="abcroofing.com", contacts={"emails": ["office@abc.com"], "phones": ["(585) 555-0101"],
                                           "socials": {"facebook": "https://facebook.com/abc"},
                                           "contact_form": "https://abc.com/contact", "whatsapp": []},
        listing_phone=None, findings=f, offer_cents=600, subject="Subj", email_body="Hello & welcome",
        demo_url="https://demos.netlify.app/abc-1234/", pay_url="https://buy.stripe.com/x", emailed_to=None)
    card = msgs[0]
    assert "ABC &lt;Roofing&gt;" in card  # escaped for Telegram HTML
    for want in ("office@abc.com", "(585) 555-0101", "https://abc.com/contact", "facebook.com/abc",
                 "https://demos.netlify.app/abc-1234/", "https://buy.stripe.com/x", "$6", "https://wa.me/15855550101"):
        assert want in card
    assert msgs[1] == "📋 <b>SUBJECT</b>\n<pre>Subj</pre>"
    assert "<pre>Hello &amp; welcome</pre>" in msgs[2]
    assert "SHORT MESSAGE" in msgs[3] and "https://demos.netlify.app/abc-1234/" in msgs[3]
    assert "IF THEY SAY YES" in msgs[4] and "https://buy.stripe.com/x" in msgs[4]
    # already emailed: no email blocks to paste
    msgs2 = prospect_card(
        outreach_id=7, name="ABC", market=None, score=50, rating=None, review_count=None, website=None,
        contacts={"emails": ["office@abc.com"]}, listing_phone=None, findings=f, offer_cents=600, subject="S",
        email_body="B", demo_url=None, pay_url=None, emailed_to=["office@abc.com"])
    assert "Already emailed" in msgs2[0] and not any("<b>EMAIL</b>" in m for m in msgs2)


def test_split_keeps_blocks_whole():
    parts = split("\n\n".join(["x" * 1500] * 5))
    assert len(parts) > 1 and all(len(p) <= 4000 for p in parts)


# ---------------------------------------------------------------- fakes

class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data if data is not None else {}
        self.content = json.dumps(self._data).encode()
        self.text = self.content.decode()

    def json(self):
        return self._data


class FakeNetlifyHTTP:
    def __init__(self, fail=False):
        self.fail, self.deploys, self.uploads = fail, [], []

    def request(self, method, url, headers=None, timeout=None, json=None, data=None, params=None, auth=None):
        if method == "GET" and url.endswith("/sites/site1"):
            return Resp(data={"ssl_url": "https://demos.netlify.app"})
        if method == "POST" and url.endswith("/sites/site1/deploys"):
            if self.fail:
                return Resp(422, {"message": "credits"})
            self.deploys.append(json["files"])
            return Resp(data={"id": f"d{len(self.deploys)}", "required": list(set(json["files"].values()))})
        if method == "PUT":
            self.uploads.append((url, data))
            return Resp(data={})
        if method == "GET" and "/deploys/" in url:
            return Resp(data={"state": "ready"})
        raise AssertionError((method, url))


class FakeStripeHTTP:
    def __init__(self):
        self.links, self.paid = [], set()

    def request(self, method, url, auth=None, data=None, params=None, timeout=None):
        path = url.split("/v1", 1)[1]
        if path == "/products":
            return Resp(data={"id": "prod_1"})
        if path == "/prices":
            assert data["unit_amount"] == 600
            return Resp(data={"id": "price_600"})
        if path == "/payment_links" and method == "POST":
            self.links.append(data)
            n = len(self.links)
            return Resp(data={"id": f"plink_{n}", "url": f"https://buy.stripe.com/test_{n}"})
        if path == "/checkout/sessions":
            if params["payment_link"] in self.paid:
                return Resp(data={"data": [{"id": "cs_1", "payment_status": "paid", "amount_total": 600,
                                            "customer_details": {"email": "owner@abc.com"},
                                            "payment_intent": {"latest_charge": {"balance_transaction": {"fee": 47}}}}]})
            return Resp(data={"data": []})
        if path.startswith("/payment_links/") and method == "POST":
            assert data == {"active": "false"}
            return Resp(data={})
        raise AssertionError((method, path))


class FakeTelegram:
    def __init__(self):
        self.messages, self.files = [], []

    def send(self, text):
        self.messages.append(text)

    def send_file(self, path, caption=""):
        self.files.append(path)


@pytest.fixture
def full(tmp_path, monkeypatch):
    session = FakeSession({**WEAK_ROUTES, **STRONG_ROUTES})
    real = crawl.fetch_site
    monkeypatch.setattr(cli, "fetch_site", lambda url, **kw: real(url, session=session, **kw))
    mailer, tg = FakeMailer(), FakeTelegram()
    nl_http, st_http = FakeNetlifyHTTP(), FakeStripeHTTP()
    monkeypatch.setattr(cli, "make_mailer", lambda cfg: mailer)
    monkeypatch.setattr(cli, "make_telegram", lambda: tg)
    monkeypatch.setattr(cli, "make_host", lambda: Netlify("tok", "site1", session=nl_http))
    monkeypatch.setattr(cli, "make_stripe", lambda: Stripe("rk_test", session=st_http))
    monkeypatch.setattr(Netlify, "wait_ready", lambda self, d, **k: None)
    env = {"ROOFIN_SENDER_NAME": "Terry", "ROOFIN_SENDER_EMAIL": "terry@gmail.com",
           "ROOFIN_SENDER_ADDRESS": "123 Main St", "ROOFIN_SMTP_USER": "terry@gmail.com",
           "ROOFIN_SMTP_PASSWORD": "x", "STRIPE_SECRET_KEY": "rk_test", "ROOFIN_SITE_DIR": str(tmp_path / "site")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.delenv("ROOFIN_PAY_LINK", raising=False)
    (tmp_path / "leads.csv").write_text(CSV)
    dbfile = str(tmp_path / "t.db")

    def run(*argv):
        cli.main(["--db", dbfile, *argv])
    run("import", str(tmp_path / "leads.csv"), "--market", "Rochester NY")

    def loop(*extra):
        run("loop", "Rochester NY", "--delay", "0", "--rediscover-days", "9999", "--out", str(tmp_path / "out"), *extra)
    return loop, run, mailer, tg, nl_http, st_http, dbfile, tmp_path


def test_full_handoff(full):
    loop, run, mailer, tg, nl_http, st_http, dbfile, tmp_path = full
    loop()
    conn = db.connect(dbfile)
    rows = conn.execute("SELECT o.*, b.name FROM outreach o JOIN businesses b ON b.id = o.business_id").fetchall()
    abc = next(r for r in rows if r["name"] == "ABC Roofing")

    # Stripe: price computed for stripe fees ($6 keeps $5.52), one link per prospect
    assert abc["offer_cents"] == 600 and abc["pay_url"].startswith("https://buy.stripe.com/")
    assert len(st_http.links) == len(rows)

    # Netlify: one deploy containing every demo + robots/index; demo URL is unguessable
    assert len(nl_http.deploys) == 1
    files = nl_http.deploys[0]
    assert "/robots.txt" in files and f"/{abc['demo_url'].split('/')[-2]}/index.html" in files
    assert abc["demo_url"].startswith("https://demos.netlify.app/abc-roofing-")
    demo = (tmp_path / "site" / abc["demo_url"].split("/")[-2] / "index.html").read_text()
    assert "noindex" in demo and abc["pay_url"] in demo

    # Email went out with demo + pay link; card says it was already emailed
    body = mailer.sent[0].get_content()
    assert abc["demo_url"] in body and abc["pay_url"] in body
    cards = "\n".join(tg.messages)
    assert "ABC Roofing" in cards and "Already emailed" in cards and "facebook.com/abcroofingroc" in cards
    assert "Joe&#x27;s Roofs" in cards or "Joe's Roofs" in cards  # phone-only prospect still gets a card
    n_msgs = len(tg.messages)

    # Second run: nothing changed, so no new deploy, no repeat cards
    loop()
    assert len(nl_http.deploys) == 1 and len(tg.messages) == n_msgs

    # They pay through the Stripe link: recorded with Stripe's real fee, link turned off, you get pinged
    st_http.paid.add(abc["stripe_link_id"])
    loop()
    pay = conn.execute("SELECT * FROM payments").fetchone()
    assert (pay["amount_cents"], pay["fee_cents"]) == (600, 47)
    assert conn.execute("SELECT status FROM outreach WHERE id = ?", (abc["id"],)).fetchone()[0] == "paid"
    assert any("paid $6" in m for m in tg.messages)


def test_demo_not_live_means_nothing_links_to_it(full):
    loop, run, mailer, tg, nl_http, st_http, dbfile, tmp_path = full
    nl_http.fail = True
    loop()
    assert mailer.sent == [] and not any("ABC Roofing" in m for m in tg.messages)
    nl_http.fail = False
    loop()
    assert len(mailer.sent) == 1 and any("ABC Roofing" in m for m in tg.messages)


def test_netlify_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOFIN_NETLIFY_MONTHLY_DEPLOYS", "1")
    monkeypatch.setattr(Netlify, "wait_ready", lambda self, d, **k: None)
    conn = db.connect(str(tmp_path / "t.db"))
    http = FakeNetlifyHTTP()
    nl = Netlify("t", "site1", session=http)
    site = tmp_path / "site"
    (site / "a").mkdir(parents=True)
    (site / "a" / "index.html").write_text("one")
    assert nl.deploy(conn, site)
    assert nl.deploy(conn, site) is None  # unchanged: free
    (site / "b").mkdir()
    (site / "b" / "index.html").write_text("two")
    with pytest.raises(NetlifyError, match="budget"):
        nl.deploy(conn, site)
    assert http.deploys[0]["/a/index.html"] == hashlib.sha1(b"one").hexdigest()


def test_cloudflare_pages_deploy(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from roofin import cloudflare
    calls = []

    def fake(args):
        calls.append(args)
        if args[:3] == ["pages", "project", "create"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="A project with this name already exists")
        return SimpleNamespace(returncode=0, stdout="Deployment complete!", stderr="")
    monkeypatch.setattr(cloudflare, "run_wrangler", fake)
    for k, v in {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a", "ROOFIN_CF_PROJECT": "demos-x"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ROOFIN_DEMO_HOST", raising=False)
    conn = db.connect(str(tmp_path / "t.db"))
    host = cli.make_host()
    assert isinstance(host, cloudflare.CloudflarePages)
    assert host.base_url(conn) == "https://demos-x.pages.dev"
    site = tmp_path / "site"
    assert host.deploy(conn, site) == "ok"
    assert host.deploy(conn, site) is None  # unchanged: no deploy spent
    assert calls[-1][:3] == ["pages", "deploy", str(site)] and "--project-name" in calls[-1]
    assert (site / "robots.txt").exists()
    assert sum(1 for c in calls if c[:2] == ["pages", "deploy"]) == 1

    monkeypatch.setattr(cloudflare, "run_wrangler",
                        lambda a: SimpleNamespace(returncode=1, stdout="", stderr="Authentication error"))
    (site / "new.html").write_text("x")
    with pytest.raises(cloudflare.CloudflareError, match="Authentication"):
        host.deploy(conn, site)
