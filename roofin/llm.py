"""Optional: have Claude rewrite the pitch and sample fixes in a natural voice.

The detectors stay the source of truth. Claude only rewords what was found; it is told not to add claims.
Requires `pip install roofin[llm]` and Anthropic credentials (ANTHROPIC_API_KEY or `ant auth login`).
"""
from __future__ import annotations

import json

from .models import Business, Finding
from .outreach import Draft, Sender, money, pick_top
from .verticals import Vertical

MODEL = "claude-opus-5-5"

SYSTEM = """You write cold outreach for a one-person web consultant who helps local trade businesses \
get more leads from their websites. The reader is a busy owner who will skim on a phone.

Rules:
- Use only the findings and evidence provided. Never invent numbers, competitors, reviews, or claims.
- Plain, specific, friendly, no hype, no exclamation marks, no "I hope this finds you well".
- Under 160 words in the body before the signature.
- Keep the offer exactly as given (price and "if you don't like it, don't pay").
- Sample fixes are website copy the owner could paste in: short headline, 2-4 sentences, one clear call to action. \
Use the business's real name, city and phone when given; never placeholder brackets other than form fields."""


def _schema_models():
    from pydantic import BaseModel

    class SampleFix(BaseModel):
        code: str
        sample: str

    class Pitch(BaseModel):
        subject: str
        body: str
        samples: list[SampleFix]

    return Pitch


def polish(b: Business, findings: list[Finding], v: Vertical, city: str | None, offer_cents: int,
           sender: Sender, draft: Draft) -> tuple[Draft, list[Finding]]:
    """Return a reworded draft and findings with improved samples. Falls back to the inputs on refusal."""
    import anthropic

    top = pick_top(findings)
    payload = {
        "business": {"name": b.name, "city": city, "phone": b.phone, "website": b.website,
                     "rating": b.rating, "review_count": b.review_count, "trade": v.trade},
        "findings": [{"code": f.code, "title": f.title, "evidence": f.evidence, "fix": f.fix,
                      "current_sample": f.sample} for f in top],
        "offer": f"I'll implement one of these for {money(offer_cents)}. If you don't like it, you don't pay.",
        "template_draft": {"subject": draft.subject, "body": draft.body},
    }
    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": (
                "Rewrite this outreach email and improve each sample fix. Return one sample per finding code. "
                "Do not include the signature or the opt-out footer in the body; I add those.\n\n"
                + json.dumps(payload, indent=2)
            ),
        }],
        output_format=_schema_models(),
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return draft, findings
    pitch = response.parsed_output
    samples = {s.code: s.sample for s in pitch.samples}
    new_findings = [
        Finding(**{**f.__dict__, "sample": samples.get(f.code, f.sample)}) for f in findings
    ]
    footer = draft.body[draft.body.index(sender.name):] if sender.name in draft.body else ""
    return Draft(subject=pitch.subject, body=pitch.body.rstrip() + "\n\n" + footer), new_findings
