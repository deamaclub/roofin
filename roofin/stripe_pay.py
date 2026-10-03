"""Stripe Payment Links: one link per prospect, and payments detected by polling (no server needed).

Free: Stripe charges only a fee on successful payments. Use a restricted key (Developers -> API keys ->
Create restricted key) with write access to Products, Prices and Payment Links, and read access to
Checkout Sessions, Payment Intents, Charges and Balance transactions. Put it in STRIPE_SECRET_KEY.
A test-mode key (rk_test_ / sk_test_) works for trying everything with fake cards.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

import requests

from . import db

API = "https://api.stripe.com/v1"


class StripeError(RuntimeError):
    pass


@dataclass
class Payment:
    amount_cents: int
    fee_cents: int | None  # None when Stripe hasn't settled the fee yet
    email: str | None
    session_id: str


class Stripe:
    def __init__(self, key: str, session: requests.Session | None = None):
        self.http = session or requests.Session()
        self.auth = (key, "")

    @classmethod
    def from_env(cls) -> "Stripe | None":
        key = os.environ.get("STRIPE_SECRET_KEY")
        return cls(key) if key else None

    def _req(self, method: str, path: str, data: dict | None = None, params=None) -> dict:
        resp = self.http.request(method, API + path, auth=self.auth, data=data, params=params, timeout=60)
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise StripeError(f"Stripe {resp.status_code}: {(body.get('error') or {}).get('message', resp.text[:200])}")
        return body

    def price_for(self, conn: sqlite3.Connection, amount_cents: int, product_name: str) -> str:
        """One Product, one Price per amount, created once and remembered."""
        key = f"stripe_price_{amount_cents}"
        price = db.get_setting(conn, key)
        if price:
            return price
        product = db.get_setting(conn, "stripe_product")
        if not product:
            product = self._req("POST", "/products", {"name": product_name})["id"]
            db.set_setting(conn, "stripe_product", product)
        price = self._req("POST", "/prices", {"product": product, "unit_amount": amount_cents, "currency": "usd"})["id"]
        db.set_setting(conn, key, price)
        return price

    def payment_link(self, conn: sqlite3.Connection, amount_cents: int, outreach_id: int, business: str,
                     product_name: str = "Website fix") -> tuple[str, str]:
        price = self.price_for(conn, amount_cents, product_name)
        link = self._req("POST", "/payment_links", {
            "line_items[0][price]": price,
            "line_items[0][quantity]": 1,
            "metadata[outreach_id]": outreach_id,
            "metadata[business]": business[:400],
            "after_completion[type]": "hosted_confirmation",
            "after_completion[hosted_confirmation][custom_message]": "Thank you! Payment received.",
        })
        return link["id"], link["url"]

    def completed(self, link_id: str) -> list[Payment]:
        data = self._req("GET", "/checkout/sessions", params={
            "payment_link": link_id, "status": "complete", "limit": 10,
            "expand[]": "data.payment_intent.latest_charge.balance_transaction",
        })
        out = []
        for s in data.get("data", []):
            if s.get("payment_status") != "paid":
                continue
            fee = None
            try:
                fee = s["payment_intent"]["latest_charge"]["balance_transaction"]["fee"]
            except (KeyError, TypeError):
                pass
            out.append(Payment(s.get("amount_total") or 0, fee, (s.get("customer_details") or {}).get("email"), s["id"]))
        return out

    def deactivate(self, link_id: str) -> None:
        self._req("POST", f"/payment_links/{link_id}", {"active": "false"})
