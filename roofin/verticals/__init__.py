"""Industry packs. The engine is shared; each vertical only supplies vocabulary and sample copy."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Topic:
    """A service customers ask about. If reviews mention it and the site doesn't cover it, that's a gap."""

    key: str
    page_name: str  # what the missing page/section should be called
    review_words: tuple[str, ...]  # how customers describe it in reviews
    site_words: tuple[str, ...]  # how a site would label it in URLs, links, headings
    sample: str  # replacement section copy; may use {name}, {city}, {phone}, {cta}
    urgent: bool = False  # urgent jobs need a form or tap-to-call on the page itself


@dataclass(frozen=True)
class Vertical:
    key: str
    trade: str  # "roofing company", used in prose
    search_suffix: str  # appended to the market for discovery, e.g. "roofing companies"
    cta_phrases: tuple[str, ...]  # phrases a strong primary call-to-action contains
    default_cta: str  # the CTA we recommend
    hero_sample: str  # copy for businesses with no website or no clear CTA
    topics: tuple[Topic, ...] = field(default_factory=tuple)


def _packs() -> dict[str, Vertical]:
    from . import hvac, roofing

    return {v.key: v for v in (roofing.VERTICAL, hvac.VERTICAL)}


def get(key: str) -> Vertical:
    packs = _packs()
    if key not in packs:
        raise KeyError(f"unknown vertical {key!r}; choose from {', '.join(sorted(packs))}")
    return packs[key]


def available() -> list[str]:
    return sorted(_packs())
