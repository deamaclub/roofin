"""Plain data objects passed between pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Review:
    rating: float | None
    text: str
    published: str | None = None  # ISO-8601 timestamp when known


@dataclass
class Business:
    name: str
    place_id: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    maps_url: str | None = None
    status: str | None = None  # e.g. OPERATIONAL, CLOSED_PERMANENTLY
    reviews: list[Review] = field(default_factory=list)
    id: int | None = None  # database id once stored


@dataclass
class Page:
    url: str
    status: int
    html: str
    elapsed: float  # seconds


@dataclass
class SiteSnapshot:
    """What we saw when we visited a business's website."""

    start_url: str
    pages: list[Page] = field(default_factory=list)
    error: str | None = None

    @property
    def home(self) -> Page | None:
        return self.pages[0] if self.pages else None


@dataclass
class Finding:
    code: str
    title: str  # phrased as the problem, addressed to the owner
    severity: int  # 1 = minor, 2 = costs some leads, 3 = clearly costing leads
    evidence: str
    fix: str
    sample: str | None = None  # ready-to-use replacement copy, when we can write one


@dataclass
class MarketContext:
    """Facts about the whole batch, so findings can compare against competitors."""

    city: str | None
    median_reviews: float | None = None
    leaders: dict[str, str] = field(default_factory=dict)  # finding code -> competitor that gets it right
