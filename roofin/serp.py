"""SerpApi: Google Maps results (ratings, review counts, reviews) on SerpApi's free plan.

The free plan has a monthly search allowance and needs no card; when it runs out, requests fail rather than bill.
We count every call locally and stop at ROOFIN_SERPAPI_MONTHLY (default 250) so the allowance is spent on purpose:
a 60-business search costs 3 calls; reviews cost 1 call per business, so we only fetch them for the shortlist.
"""
from __future__ import annotations

import os
import sqlite3

import requests

from . import db
from .discovery import DiscoveryError
from .models import Business, Review

URL = "https://serpapi.com/search.json"
PROVIDER = "serpapi"


def monthly_cap() -> int:
    return int(os.environ.get("ROOFIN_SERPAPI_MONTHLY", "250"))


def remaining(conn: sqlite3.Connection) -> int:
    return max(0, monthly_cap() - db.api_calls(conn, PROVIDER))


def _call(conn: sqlite3.Connection, params: dict, session: requests.Session | None) -> dict:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        raise DiscoveryError("SERPAPI_KEY is not set (free account at serpapi.com, no card needed).")
    if remaining(conn) <= 0:
        raise DiscoveryError(
            f"SerpApi free allowance for this month is used up ({monthly_cap()} calls). "
            "Use `--source osm` or wait for next month."
        )
    http = session or requests.Session()
    resp = http.get(URL, params={**params, "api_key": key}, timeout=60)
    db.count_api_call(conn, PROVIDER)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200 or "error" in data:
        raise DiscoveryError(f"SerpApi {resp.status_code}: {data.get('error') or resp.text[:300]}")
    return data


def search_maps(conn: sqlite3.Connection, query: str, limit: int = 60,
                session: requests.Session | None = None) -> list[tuple[Business, str | None]]:
    """Returns (business, data_id) pairs; data_id is what the reviews call needs."""
    out: list[tuple[Business, str | None]] = []
    start = 0
    while len(out) < limit:
        data = _call(conn, {"engine": "google_maps", "type": "search", "q": query, "start": start}, session)
        page = data.get("local_results") or []
        for r in page:
            out.append((parse_local(r), r.get("data_id")))
        if len(page) < 20:
            break
        start += 20
    return out[:limit]


def parse_local(r: dict) -> Business:
    closed = any(
        "permanently closed" in str(r.get(k, "")).lower() for k in ("open_state", "hours", "type", "description")
    )
    return Business(
        name=r.get("title", "Unknown"),
        place_id=r.get("place_id") or (f"serp:{r['data_id']}" if r.get("data_id") else None),
        address=r.get("address"),
        phone=r.get("phone"),
        website=r.get("website"),
        rating=r.get("rating"),
        review_count=r.get("reviews"),
        status="CLOSED_PERMANENTLY" if closed else "OPERATIONAL",
    )


def fetch_reviews(conn: sqlite3.Connection, data_id: str, session: requests.Session | None = None) -> list[Review]:
    data = _call(conn, {"engine": "google_maps_reviews", "data_id": data_id, "sort_by": "newestFirst"}, session)
    out = []
    for r in data.get("reviews") or []:
        text = r.get("snippet") or (r.get("extracted_snippet") or {}).get("original") or ""
        if text:
            out.append(Review(rating=r.get("rating"), text=text, published=r.get("iso_date")))
    return out
