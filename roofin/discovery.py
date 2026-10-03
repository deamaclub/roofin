"""Find businesses to audit: OpenStreetMap (free), Google Places API (paid, read-only), or a CSV you made."""
from __future__ import annotations

import csv
import os

import requests

from .models import Business, Review

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join(
    f"places.{f}"
    for f in (
        "id", "displayName", "formattedAddress", "nationalPhoneNumber", "websiteUri", "rating",
        "userRatingCount", "googleMapsUri", "businessStatus", "reviews",
    )
) + ",nextPageToken"


class DiscoveryError(RuntimeError):
    pass


def search_places(query: str, limit: int = 60, api_key: str | None = None,
                  session: requests.Session | None = None) -> list[Business]:
    """Text-search Google Places. The API returns at most 20 per page and 60 per query."""
    api_key = api_key or os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise DiscoveryError(
            "GOOGLE_PLACES_API_KEY is not set. Get a key with the Places API (New) enabled, "
            "or use `roofin import <file.csv>` instead."
        )
    http = session or requests.Session()
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS, "Content-Type": "application/json"}
    results: list[Business] = []
    page_token = None
    while len(results) < limit:
        body = {"textQuery": query, "pageSize": min(20, limit - len(results))}
        if page_token:
            body["pageToken"] = page_token
        resp = http.post(PLACES_URL, json=body, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise DiscoveryError(f"Places API {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        results.extend(parse_place(p) for p in data.get("places", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return results[:limit]


def parse_place(p: dict) -> Business:
    reviews = [
        Review(
            rating=r.get("rating"),
            text=(r.get("text") or r.get("originalText") or {}).get("text", ""),
            published=r.get("publishTime"),
        )
        for r in p.get("reviews", [])
    ]
    return Business(
        name=(p.get("displayName") or {}).get("text", "Unknown"),
        place_id=p.get("id"),
        address=p.get("formattedAddress"),
        phone=p.get("nationalPhoneNumber"),
        website=p.get("websiteUri"),
        rating=p.get("rating"),
        review_count=p.get("userRatingCount"),
        maps_url=p.get("googleMapsUri"),
        status=p.get("businessStatus"),
        reviews=reviews,
    )


def load_csv(path: str) -> list[Business]:
    """Columns (header row, any order): name, website, phone, address, rating, review_count, reviews.

    `reviews` is optional free text; separate multiple reviews with ' || '.
    """
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("name"):
                continue
            reviews = [Review(rating=None, text=t.strip()) for t in row.get("reviews", "").split("||") if t.strip()]
            out.append(Business(
                name=row["name"],
                website=row.get("website") or None,
                phone=row.get("phone") or None,
                address=row.get("address") or None,
                rating=float(row["rating"]) if row.get("rating") else None,
                review_count=int(float(row["review_count"])) if row.get("review_count") else None,
                reviews=reviews,
            ))
    return out


# ---------------------------------------------------------------- OpenStreetMap (free, no key, no account)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_USER_AGENT = "roofin/0.1 (local business website audit; low volume)"


def _osm_regex(words: tuple[str, ...]) -> str:
    return "|".join(w.replace('"', "").replace("\\", "") for w in words)


def overpass_query(bbox: tuple[float, float, float, float], tags: tuple[tuple[str, str], ...],
                   name_words: tuple[str, ...]) -> str:
    s, w, n, e = bbox
    box = f"({s},{w},{n},{e})"
    parts = [f'nwr["{k}"="{v}"]{box};' for k, v in tags]
    if name_words:
        # Named things that aren't roads/places: businesses whose name contains the trade word.
        parts.append(f'nwr["name"~"{_osm_regex(name_words)}",i][!"highway"][!"place"]{box};')
    return "[out:json][timeout:60];(" + "".join(parts) + ");out center tags;"


def search_osm(market: str, tags: tuple[tuple[str, str], ...], name_words: tuple[str, ...], limit: int = 100,
               session: requests.Session | None = None) -> list[Business]:
    """Free discovery from OpenStreetMap. Coverage is thinner than Google and there are no reviews."""
    http = session or requests.Session()
    headers = {"User-Agent": OSM_USER_AGENT}
    geo = http.get(NOMINATIM_URL, params={"q": market, "format": "json", "limit": 1}, headers=headers, timeout=30)
    if geo.status_code != 200 or not geo.json():
        raise DiscoveryError(f"couldn't find {market!r} on OpenStreetMap (HTTP {geo.status_code})")
    south, north, west, east = (float(x) for x in geo.json()[0]["boundingbox"])
    query = overpass_query((south, west, north, east), tags, name_words)
    resp = http.post(OVERPASS_URL, data={"data": query}, headers=headers, timeout=90)
    if resp.status_code != 200:
        raise DiscoveryError(f"Overpass API {resp.status_code}: {resp.text[:300]} (it's a shared free service; retry in a minute)")
    seen: set[str] = set()
    out: list[Business] = []
    for el in resp.json().get("elements", []):
        b = parse_osm(el)
        if b and b.name.lower() not in seen:
            seen.add(b.name.lower())
            out.append(b)
    return out[:limit]


def parse_osm(el: dict) -> Business | None:
    t = el.get("tags", {})
    name = t.get("name")
    if not name:
        return None
    street = " ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street")]))
    address = ", ".join(filter(None, [street, t.get("addr:city"), t.get("addr:state"), t.get("addr:postcode")]))
    return Business(
        name=name,
        place_id=f"osm:{el.get('type')}/{el.get('id')}",
        address=address or None,
        phone=t.get("phone") or t.get("contact:phone"),
        website=t.get("website") or t.get("contact:website") or t.get("url"),
    )
