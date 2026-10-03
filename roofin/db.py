"""SQLite storage: prospects, audits, findings, outreach, and money received."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .models import Business, Finding, Review

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    vertical TEXT NOT NULL,
    market TEXT,
    place_id TEXT UNIQUE,
    name TEXT NOT NULL,
    address TEXT,
    phone TEXT,
    website TEXT,
    email TEXT,
    rating REAL,
    review_count INTEGER,
    maps_url TEXT,
    status TEXT,
    reviews_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    score REAL NOT NULL,
    site_error TEXT,
    pages_crawled INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES audits(id),
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    severity INTEGER NOT NULL,
    evidence TEXT NOT NULL,
    fix TEXT NOT NULL,
    sample TEXT
);

-- One row per pitch. status: draft -> approved -> sent -> replied -> won -> paid (or lost / opted_out)
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    audit_id INTEGER NOT NULL REFERENCES audits(id),
    channel TEXT NOT NULL,
    recipient TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    offer_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    report_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    outreach_id INTEGER NOT NULL REFERENCES outreach(id),
    amount_cents INTEGER NOT NULL,
    note TEXT,
    received_at TEXT NOT NULL
);
"""

OUTREACH_STATUSES = ("draft", "approved", "sent", "replied", "won", "paid", "lost", "opted_out")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def upsert_business(conn: sqlite3.Connection, b: Business, vertical: str, market: str | None) -> int:
    reviews = json.dumps([r.__dict__ for r in b.reviews])
    existing = None
    if b.place_id:
        existing = conn.execute("SELECT id FROM businesses WHERE place_id = ?", (b.place_id,)).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM businesses WHERE name = ? AND IFNULL(website,'') = IFNULL(?,'')", (b.name, b.website)
        ).fetchone()
    if existing:
        conn.execute(
            """UPDATE businesses SET name=?, address=?, phone=?, website=?, rating=?, review_count=?,
               maps_url=?, status=?, reviews_json=? WHERE id=?""",
            (b.name, b.address, b.phone, b.website, b.rating, b.review_count, b.maps_url, b.status, reviews,
             existing["id"]),
        )
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO businesses (vertical, market, place_id, name, address, phone, website, rating,
           review_count, maps_url, status, reviews_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (vertical, market, b.place_id, b.name, b.address, b.phone, b.website, b.rating, b.review_count,
         b.maps_url, b.status, reviews, now()),
    )
    return cur.lastrowid


def row_to_business(row: sqlite3.Row) -> Business:
    return Business(
        id=row["id"], name=row["name"], place_id=row["place_id"], address=row["address"], phone=row["phone"],
        website=row["website"], rating=row["rating"], review_count=row["review_count"], maps_url=row["maps_url"],
        status=row["status"], reviews=[Review(**r) for r in json.loads(row["reviews_json"])],
    )


def save_audit(conn: sqlite3.Connection, business_id: int, score: float, findings: list[Finding],
               site_error: str | None, pages_crawled: int) -> int:
    cur = conn.execute(
        "INSERT INTO audits (business_id, score, site_error, pages_crawled, created_at) VALUES (?,?,?,?,?)",
        (business_id, score, site_error, pages_crawled, now()),
    )
    audit_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO findings (audit_id, code, title, severity, evidence, fix, sample) VALUES (?,?,?,?,?,?,?)",
        [(audit_id, f.code, f.title, f.severity, f.evidence, f.fix, f.sample) for f in findings],
    )
    return audit_id


def latest_audit(conn: sqlite3.Connection, business_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM audits WHERE business_id = ? ORDER BY id DESC LIMIT 1", (business_id,)
    ).fetchone()


def audit_findings(conn: sqlite3.Connection, audit_id: int) -> list[Finding]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE audit_id = ? ORDER BY severity DESC, id", (audit_id,)
    ).fetchall()
    return [Finding(code=r["code"], title=r["title"], severity=r["severity"], evidence=r["evidence"],
                    fix=r["fix"], sample=r["sample"]) for r in rows]


def set_outreach_status(conn: sqlite3.Connection, outreach_id: int, status: str) -> None:
    if status not in OUTREACH_STATUSES:
        raise ValueError(f"status must be one of {', '.join(OUTREACH_STATUSES)}")
    cur = conn.execute("UPDATE outreach SET status = ?, updated_at = ? WHERE id = ?", (status, now(), outreach_id))
    if cur.rowcount == 0:
        raise LookupError(f"no outreach #{outreach_id}")
