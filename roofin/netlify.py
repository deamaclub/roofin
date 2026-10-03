"""Publish demo pages to a Netlify site you own, on Netlify's free plan.

Free plan facts this module is built around: each production deploy costs 15 of 300 monthly credits, and
when credits run out the site pauses (no bill). So we deploy at most once per run, only when something
changed, and stop at ROOFIN_NETLIFY_MONTHLY_DEPLOYS (default 15) to leave credits for page views.

Setup: create an empty site in Netlify (drag any folder onto app.netlify.com/drop), then set
NETLIFY_AUTH_TOKEN (User settings -> Applications -> Personal access token) and NETLIFY_SITE_ID
(Site configuration -> Site details).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import requests

from . import db

API = "https://api.netlify.com/api/v1"
PROVIDER = "netlify"
ROBOTS = "User-agent: *\nDisallow: /\n"
INDEX = "<!doctype html><meta charset=utf-8><meta name=robots content=noindex><title>Demos</title><p>Nothing here.\n"


class DemoHostError(RuntimeError):
    """Any demo host (Netlify, Cloudflare Pages) failing to publish."""


class NetlifyError(DemoHostError):
    pass


def site_fingerprint(site_dir: Path) -> tuple[dict[str, Path], dict[str, str], str]:
    files = {f"/{p.relative_to(site_dir).as_posix()}": p for p in sorted(site_dir.rglob("*")) if p.is_file()}
    digest = {path: hashlib.sha1(p.read_bytes()).hexdigest() for path, p in files.items()}
    return files, digest, hashlib.sha1(repr(sorted(digest.items())).encode()).hexdigest()


def monthly_cap() -> int:
    return int(os.environ.get("ROOFIN_NETLIFY_MONTHLY_DEPLOYS", "15"))


def remaining(conn: sqlite3.Connection) -> int:
    return max(0, monthly_cap() - db.api_calls(conn, PROVIDER))


def configured() -> bool:
    return bool(os.environ.get("NETLIFY_AUTH_TOKEN") and os.environ.get("NETLIFY_SITE_ID"))


class Netlify:
    def __init__(self, token: str, site_id: str, session: requests.Session | None = None):
        self.site_id = site_id
        self.http = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def from_env(cls) -> "Netlify | None":
        return cls(os.environ["NETLIFY_AUTH_TOKEN"], os.environ["NETLIFY_SITE_ID"]) if configured() else None

    def _req(self, method: str, path: str, **kw) -> dict:
        resp = self.http.request(method, API + path, headers={**self.headers, **kw.pop("headers", {})},
                                 timeout=120, **kw)
        if resp.status_code >= 400:
            raise NetlifyError(f"Netlify {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def remaining(self, conn: sqlite3.Connection) -> int:
        return remaining(conn)

    def base_url(self, conn: sqlite3.Connection) -> str:
        """Site URL (cached). Reading site info is free; only deploys cost credits."""
        url = db.get_setting(conn, "netlify_url")
        if not url:
            site = self._req("GET", f"/sites/{self.site_id}")
            url = (site.get("ssl_url") or site.get("url") or "").rstrip("/")
            if not url:
                raise NetlifyError("couldn't read the site URL")
            db.set_setting(conn, "netlify_url", url)
        return url

    def deploy(self, conn: sqlite3.Connection, site_dir: Path) -> str | None:
        """Deploy the whole folder if it changed since the last deploy. Returns the deploy id, or None."""
        ensure_skeleton(site_dir)
        files, digest, fingerprint = site_fingerprint(site_dir)
        if db.get_setting(conn, "netlify_fingerprint") == fingerprint:
            return None
        if remaining(conn) <= 0:
            raise NetlifyError(f"monthly deploy budget used ({monthly_cap()}); new demos go live next month")
        dep = self._req("POST", f"/sites/{self.site_id}/deploys", json={"files": digest})
        by_sha = {}
        for path, sha in digest.items():
            by_sha.setdefault(sha, path)
        for sha in dep.get("required", []):
            path = by_sha[sha]
            self._req("PUT", f"/deploys/{dep['id']}/files{path}", data=files[path].read_bytes(),
                      headers={"Content-Type": "application/octet-stream"})
        db.count_api_call(conn, PROVIDER)
        self.wait_ready(dep["id"])
        db.set_setting(conn, "netlify_fingerprint", fingerprint)
        return dep["id"]

    def wait_ready(self, deploy_id: str, tries: int = 30, pause: float = 2.0) -> None:
        import time
        for _ in range(tries):
            state = self._req("GET", f"/deploys/{deploy_id}").get("state")
            if state == "ready":
                return
            if state == "error":
                raise NetlifyError("deploy failed on Netlify's side")
            time.sleep(pause)
        raise NetlifyError("deploy didn't become ready in time")


def ensure_skeleton(site_dir: Path) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (("robots.txt", ROBOTS), ("index.html", INDEX)):
        f = site_dir / name
        if not f.exists():
            f.write_text(body, encoding="utf-8")
