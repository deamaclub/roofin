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
    fee_cents INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    received_at TEXT NOT NULL
);

-- Addresses and domains that asked not to be contacted. Checked before every send, forever.
CREATE TABLE IF NOT EXISTS suppressions (
    value TEXT PRIMARY KEY,  -- an email address or a bare domain
    reason TEXT,
    created_at TEXT NOT NULL
);

-- Money spent. Only ever paid out of revenue already received.
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    spent_at TEXT NOT NULL
);

-- Small key/value store (Stripe product/price ids, etc.)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Calls to metered free tiers (SerpApi), so we stop before the monthly allowance runs out.
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    month TEXT NOT NULL,  -- YYYY-MM
    calls INTEGER NOT NULL,
    UNIQUE (provider, month)
);
"""

# Columns added after the first release; applied to existing databases on connect.
MIGRATIONS = {
    "businesses": {"data_id": "TEXT", "contacts_json": "TEXT"},
    "outreach": {"message_id": "TEXT", "sent_at": "TEXT", "followup_at": "TEXT", "reply_snippet": "TEXT",
                 "demo_path": "TEXT", "demo_url": "TEXT", "pay_url": "TEXT", "stripe_link_id": "TEXT",
                 "notified_at": "TEXT"},
    "payments": {"fee_cents": "INTEGER NOT NULL DEFAULT 0"},
}

OUTREACH_STATUSES = ("draft", "approved", "sent", "replied", "won", "paid", "lost", "opted_out")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()
    return conn


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                 (key, value))
    conn.commit()


def suppressed(conn: sqlite3.Connection, email: str) -> bool:
    email = email.lower().strip()
    domain = email.rsplit("@", 1)[-1]
    return conn.execute("SELECT 1 FROM suppressions WHERE value IN (?, ?)", (email, domain)).fetchone() is not None


def suppress(conn: sqlite3.Connection, value: str, reason: str) -> None:
    conn.execute("INSERT OR IGNORE INTO suppressions (value, reason, created_at) VALUES (?,?,?)",
                 (value.lower().strip(), reason, now()))


def month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def api_calls(conn: sqlite3.Connection, provider: str) -> int:
    row = conn.execute("SELECT calls FROM api_usage WHERE provider = ? AND month = ?", (provider, month())).fetchone()
    return row["calls"] if row else 0


def count_api_call(conn: sqlite3.Connection, provider: str) -> None:
    conn.execute(
        """INSERT INTO api_usage (provider, month, calls) VALUES (?, ?, 1)
           ON CONFLICT (provider, month) DO UPDATE SET calls = calls + 1""", (provider, month()))
    conn.commit()


def money_summary(conn: sqlite3.Connection) -> dict[str, int]:
    """All in cents. `available` is what may be spent: profit already received, minus what's been spent."""
    gross = conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments").fetchone()[0]
    fees = conn.execute("SELECT COALESCE(SUM(fee_cents),0) FROM payments").fetchone()[0]
    spent = conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM expenses").fetchone()[0]
    return {"gross": gross, "fees": fees, "spent": spent, "net": gross - fees - spent,
            "available": gross - fees - spent}


def upsert_business(conn: sqlite3.Connection, b: Business, vertical: str, market: str | None,
                    data_id: str | None = None) -> int:
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
        if data_id:
            conn.execute("UPDATE businesses SET data_id = ? WHERE id = ?", (data_id, existing["id"]))
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO businesses (vertical, market, place_id, name, address, phone, website, rating,
           review_count, maps_url, status, reviews_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (vertical, market, b.place_id, b.name, b.address, b.phone, b.website, b.rating, b.review_count,
         b.maps_url, b.status, reviews, now()),
    )
    if data_id:
        conn.execute("UPDATE businesses SET data_id = ? WHERE id = ?", (data_id, cur.lastrowid))
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
