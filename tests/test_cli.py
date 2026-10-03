from __future__ import annotations

import pytest

from roofin import cli, crawl
from conftest import STRONG_ROUTES, WEAK_ROUTES, FakeSession

CSV = """name,website,phone,rating,review_count,reviews
ABC Roofing,abcroofing.com,(585) 555-0101,4.7,12,After the storm the shingles blew off || Handled our insurance claim
Summit Roofing,https://summitroofing.com,(585) 555-0199,4.9,240,Great job
Joe's Roofs,,(585) 555-0000,4.8,30,
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    session = FakeSession({**WEAK_ROUTES, **STRONG_ROUTES})
    real = crawl.fetch_site
    monkeypatch.setattr(cli, "fetch_site", lambda url, **kw: real(url, session=session, **kw))
    for k, v in {"ROOFIN_SENDER_NAME": "Terry", "ROOFIN_SENDER_EMAIL": "t@example.org",
                 "ROOFIN_SENDER_ADDRESS": "123 Main St, Rochester NY"}.items():
        monkeypatch.setenv(k, v)
    csv = tmp_path / "leads.csv"
    csv.write_text(CSV)
    return tmp_path, csv


def run(tmp_path, *argv):
    cli.main(["--db", str(tmp_path / "t.db"), *argv])


def test_first_dollar_loop(env, capsys):
    tmp_path, csv = env
    run(tmp_path, "import", str(csv), "--market", "Rochester NY")
    run(tmp_path, "audit", "--workers", "1")
    run(tmp_path, "prospects")
    out = capsys.readouterr().out
    assert "ABC Roofing" in out and "no way to request a quote" in out

    run(tmp_path, "draft", "--out", str(tmp_path / "out"), "--offer", "1")
    reports = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert any(r.endswith("abc-roofing.html") for r in reports)
    assert not any("summit" in r for r in reports), "a clean site shouldn't be pitched"

    capsys.readouterr()
    run(tmp_path, "outreach")
    out = capsys.readouterr().out
    assert "draft" in out and "office@abcroofing.com" in out

    oid = next(line.split()[0] for line in out.splitlines() if "ABC Roofing" in line)
    run(tmp_path, "mark", oid, "sent")
    run(tmp_path, "paid", oid, "1")
    capsys.readouterr()
    run(tmp_path, "stats")
    out = capsys.readouterr().out
    assert "Revenue              $1" in out and "The machine has made money" in out


def test_draft_requires_sender_address(env, monkeypatch):
    tmp_path, csv = env
    monkeypatch.delenv("ROOFIN_SENDER_ADDRESS")
    run(tmp_path, "import", str(csv), "--market", "Rochester NY")
    with pytest.raises(SystemExit, match="postal address"):
        run(tmp_path, "draft")


def test_city_of():
    assert cli.city_of("Rochester NY") == "Rochester"
    assert cli.city_of("Grand Rapids, MI") == "Grand Rapids"
    assert cli.city_of("Buffalo") == "Buffalo"
