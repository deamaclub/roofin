"""Publish demo pages to Cloudflare Pages: free, unlimited bandwidth for static pages, 500 deploys/month.

Uses Cloudflare's own CLI (wrangler), so it needs Node.js:  sudo apt install -y nodejs npm
Setup: Cloudflare dashboard -> My Profile -> API Tokens -> Create Token -> "Edit Cloudflare Pages" (or a
custom token with Account / Cloudflare Pages / Edit). Then set
    CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID (dashboard URL / Workers & Pages overview), and
    ROOFIN_CF_PROJECT (a name you pick, e.g. roofin-demos-yourname -> https://roofin-demos-yourname.pages.dev)
"""
from __future__ import annotations

import os
import shlex
import sqlite3
import subprocess
from pathlib import Path

from . import db
from .netlify import DemoHostError, ensure_skeleton, site_fingerprint

PROVIDER = "cloudflare_pages"


class CloudflareError(DemoHostError):
    pass


def configured() -> bool:
    return all(os.environ.get(k) for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "ROOFIN_CF_PROJECT"))


def monthly_cap() -> int:
    return int(os.environ.get("ROOFIN_CF_MONTHLY_DEPLOYS", "450"))  # free plan allows 500


def run_wrangler(args: list[str]) -> subprocess.CompletedProcess:  # replaced in tests
    cmd = shlex.split(os.environ.get("ROOFIN_WRANGLER", "npx --yes wrangler@4")) + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=os.environ.copy())
    except FileNotFoundError as exc:
        raise CloudflareError("Node.js/npx not found. Install it: sudo apt install -y nodejs npm") from exc


class CloudflarePages:
    def __init__(self, project: str):
        self.project = project

    @classmethod
    def from_env(cls) -> "CloudflarePages | None":
        return cls(os.environ["ROOFIN_CF_PROJECT"]) if configured() else None

    def remaining(self, conn: sqlite3.Connection) -> int:
        return max(0, monthly_cap() - db.api_calls(conn, PROVIDER))

    def base_url(self, conn: sqlite3.Connection) -> str:
        return f"https://{self.project}.pages.dev"

    def _ensure_project(self, conn: sqlite3.Connection) -> None:
        if db.get_setting(conn, "cf_project") == self.project:
            return
        r = run_wrangler(["pages", "project", "create", self.project, "--production-branch", "main"])
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 and "already exists" not in out.lower():
            raise CloudflareError(f"couldn't create Pages project {self.project!r}: {out.strip()[-300:]}")
        db.set_setting(conn, "cf_project", self.project)

    def deploy(self, conn: sqlite3.Connection, site_dir: Path) -> str | None:
        ensure_skeleton(site_dir)
        _, _, fingerprint = site_fingerprint(site_dir)
        if db.get_setting(conn, "cf_fingerprint") == fingerprint:
            return None
        if self.remaining(conn) <= 0:
            raise CloudflareError(f"monthly deploy budget used ({monthly_cap()})")
        self._ensure_project(conn)
        r = run_wrangler(["pages", "deploy", str(site_dir), "--project-name", self.project,
                          "--branch", "main", "--commit-dirty=true"])
        if r.returncode != 0:
            raise CloudflareError(f"wrangler failed: {((r.stdout or '') + (r.stderr or '')).strip()[-400:]}")
        db.count_api_call(conn, PROVIDER)
        db.set_setting(conn, "cf_fingerprint", fingerprint)
        return "ok"
