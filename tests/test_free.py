from __future__ import annotations

from roofin import cli, verticals
from roofin.discovery import overpass_query, search_osm


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


class FakeOSM:
    def __init__(self):
        self.posted = None

    def get(self, url, params=None, headers=None, timeout=None):
        assert "nominatim" in url and params["q"] == "Rochester NY"
        return Resp(200, [{"boundingbox": ["43.1", "43.2", "-77.7", "-77.5"]}])

    def post(self, url, data=None, headers=None, timeout=None):
        self.posted = data["data"]
        return Resp(200, {"elements": [
            {"type": "node", "id": 1, "tags": {"name": "ABC Roofing", "website": "abcroofing.com",
                                               "phone": "585-555-0101", "addr:housenumber": "12",
                                               "addr:street": "Main St", "addr:city": "Rochester"}},
            {"type": "way", "id": 2, "tags": {"name": "abc roofing"}},  # duplicate name
            {"type": "node", "id": 3, "tags": {"craft": "roofer"}},  # unnamed
            {"type": "node", "id": 4, "tags": {"name": "Joe's Roofs", "contact:website": "https://joes.com"}},
        ]})


def test_overpass_query_shape():
    v = verticals.get("roofing")
    q = overpass_query((43.1, -77.7, 43.2, -77.5), v.osm_tags, v.osm_name_words)
    assert 'nwr["craft"="roofer"](43.1,-77.7,43.2,-77.5);' in q
    assert '["name"~"roof",i][!"highway"][!"place"]' in q


def test_search_osm_parses_and_dedupes():
    v = verticals.get("roofing")
    s = FakeOSM()
    found = search_osm("Rochester NY", v.osm_tags, v.osm_name_words, session=s)
    assert [b.name for b in found] == ["ABC Roofing", "Joe's Roofs"]
    assert found[0].address == "12 Main St, Rochester" and found[0].place_id == "osm:node/1"
    assert found[1].website == "https://joes.com"
    assert "(43.1,-77.7,43.2,-77.5)" in s.posted  # nominatim gives S,N,W,E; overpass wants S,W,N,E


def test_discover_defaults_to_free_source(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    called = {}
    monkeypatch.setattr(cli, "search_places", lambda *a, **k: called.setdefault("google", True) and [])
    monkeypatch.setattr(cli, "search_osm", lambda *a, **k: called.setdefault("osm", True) and [])
    cli.main(["--db", str(tmp_path / "t.db"), "discover", "Rochester NY"])
    assert called == {"osm": True}
    assert "free" in capsys.readouterr().out


def test_add_by_hand(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    cli.main(["--db", db, "add", "ABC Roofing", "--market", "Rochester NY", "--website", "abcroofing.com",
              "--rating", "4.7", "--reviews", "12", "--review", "Fixed our storm damage", "--review", "Great"])
    from roofin import db as rdb
    conn = rdb.connect(db)
    b = rdb.row_to_business(conn.execute("SELECT * FROM businesses").fetchone())
    assert b.review_count == 12 and [r.text for r in b.reviews] == ["Fixed our storm damage", "Great"]
