"""One-page opportunity report per business, as Markdown and a self-contained HTML page."""
from __future__ import annotations

import html
import re

from .models import Business, Finding
from .outreach import Draft, money, pick_top

SEVERITY = {3: "Costing you leads", 2: "Likely costing leads", 1: "Worth fixing"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "business"


def markdown(b: Business, findings: list[Finding], score: float, offer_cents: int, draft: Draft | None) -> str:
    top = pick_top(findings)
    lines = [f"# {b.name} — Website Opportunity Report", ""]
    meta = [x for x in (b.address, b.phone, b.website) if x]
    if b.rating is not None:
        meta.append(f"{b.rating:.1f}★ ({b.review_count or 0} Google reviews)")
    lines += [" · ".join(meta), "", f"**Prospect score:** {score:.0f}/100", ""]
    lines += [f"## I found {len(top)} thing{'s' if len(top) != 1 else ''} potentially costing you leads", ""]
    for i, f in enumerate(top, 1):
        lines += [
            f"### {i}. {f.title}",
            f"*{SEVERITY[f.severity]}*",
            "",
            f"**Evidence:** {f.evidence}",
            "",
            f"**Recommended fix:** {f.fix}",
            "",
        ]
        if f.sample:
            lines += ["**Ready-to-use fix (sample):**", "", "```", f.sample, "```", ""]
    rest = [f for f in findings if f not in top]
    if rest:
        lines += ["## Also noticed", ""]
        lines += [f"- {f.title} — {f.evidence}" for f in rest]
        lines.append("")
    lines += [
        "## Offer",
        "",
        f"I'll fix one of these for **{money(offer_cents)}**. If you don't like it, don't pay.",
        "",
    ]
    if draft:
        lines += ["---", "", "## Outreach draft (internal — not part of the client report)", "",
                  f"**Subject:** {draft.subject}", "", "```", draft.body, "```", ""]
    return "\n".join(lines)


def html_page(b: Business, findings: list[Finding], offer_cents: int, pay_url: str | None = None) -> str:
    """Client-facing page (the demo): no score, no internal notes, kept out of search engines."""
    e = html.escape
    top = pick_top(findings)
    cards = []
    for i, f in enumerate(top, 1):
        sample = f"<h4>Sample fix</h4><pre>{e(f.sample)}</pre>" if f.sample else ""
        cards.append(
            f'<section class="card sev{f.severity}"><h3>{i}. {e(f.title)}</h3>'
            f'<p class="tag">{SEVERITY[f.severity]}</p>'
            f"<p><b>What I saw:</b> {e(f.evidence)}</p><p><b>Fix:</b> {e(f.fix)}</p>{sample}</section>"
        )
    rest = "".join(f"<li>{e(f.title)}</li>" for f in findings if f not in top)
    rest_html = f"<h2>Also noticed</h2><ul>{rest}</ul>" if rest else ""
    pay_html = (f'<p><a class="pay" href="{e(pay_url)}">Pay {money(offer_cents)} after you approve the fix</a></p>'
                if pay_url else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{e(b.name)} — Opportunity Report</title>
<style>
:root {{ --bg:#f7f7f5; --fg:#1d1d1b; --muted:#666; --card:#fff; --line:#e3e3df; --hot:#c2410c; --warm:#b45309; --mild:#4b5563; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141413; --fg:#eeeeea; --muted:#a3a39e; --card:#1f1f1d; --line:#33332f; }} }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif; margin:0; padding:24px 16px; }}
main {{ max-width:760px; margin:0 auto; }}
h1 {{ font-size:1.6rem; margin:0 0 4px; }} .sub {{ color:var(--muted); margin:0 0 24px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--mild); border-radius:8px; padding:16px 18px; margin:0 0 16px; }}
.sev3 {{ border-left-color:var(--hot); }} .sev2 {{ border-left-color:var(--warm); }}
.card h3 {{ margin:0 0 4px; font-size:1.1rem; }} .tag {{ margin:0 0 8px; color:var(--muted); font-size:.85rem; }}
pre {{ white-space:pre-wrap; background:var(--bg); border:1px solid var(--line); border-radius:6px; padding:12px; font-size:.9rem; }}
.pay {{ display:inline-block; margin-top:8px; padding:10px 16px; border-radius:6px; background:var(--fg); color:var(--bg); text-decoration:none; font-weight:600; }}
.offer {{ background:var(--card); border:2px solid var(--fg); border-radius:8px; padding:16px 18px; }}
</style></head>
<body><main>
<h1>{e(b.name)}</h1>
<p class="sub">I found {len(top)} thing{'s' if len(top) != 1 else ''} potentially costing you leads.</p>
{''.join(cards)}
{rest_html}
<div class="offer"><b>I'll fix one of these for {money(offer_cents)}.</b> If you don't like it, don't pay. Just reply to my message.{pay_html}</div>
</main></body></html>
"""
