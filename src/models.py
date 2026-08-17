"""
Data contracts for the lead pipeline.

Every agent in the pipeline reads one of these and writes another. Nothing
passes between stages as a loose dict, which means a change in one agent's
output either validates or fails loudly instead of quietly corrupting the
stage downstream.

The rule that drives most of the design here: any value that came from the
outside world carries a Source with it. A revenue figure without a URL is
not a revenue figure, it's a guess, and a sales rep who gets burned once by
a made-up number stops trusting the whole system.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Generic, TypeVar

from pydantic import (BaseModel, ConfigDict, Field, HttpUrl, field_validator,
                      model_validator)

T = TypeVar("T")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Method(str, Enum):
    """How we came to know something. Ordered loosely by how much we trust it."""

    DIRECT = "direct"          # stated on the company's own site or filing
    ORGANIZER = "organizer"    # published by the event organizer
    AGGREGATOR = "aggregator"  # third-party listing site, often stale
    PROVIDER = "provider"      # Clay, Sales Navigator, or similar
    INFERRED = "inferred"      # a model concluded it from other evidence


# Precedence when two sources disagree. Higher wins.
METHOD_RANK = {
    Method.DIRECT: 4,
    Method.ORGANIZER: 3,
    Method.PROVIDER: 2,
    Method.AGGREGATOR: 1,
    Method.INFERRED: 0,
}


class Source(BaseModel):
    """Where a single value came from, and when."""

    url: HttpUrl | None = None
    method: Method
    fetched_at: datetime = Field(default_factory=_utcnow)
    note: str | None = None

    @model_validator(mode="after")
    def _url_required_for_external(self) -> Source:
        # An inferred value has no URL by definition. Everything else must
        # point somewhere, or it isn't sourced and shouldn't claim to be.
        if self.method is not Method.INFERRED and self.url is None:
            raise ValueError(f"{self.method.value} source needs a url")
        return self


class Sourced(BaseModel, Generic[T]):
    """A value plus its provenance. This is the core primitive."""

    value: T
    source: Source
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    def beats(self, other: Sourced[T] | None) -> bool:
        """Whether this value should win a conflict against another."""
        if other is None:
            return True
        mine, theirs = METHOD_RANK[self.source.method], METHOD_RANK[other.source.method]
        if mine != theirs:
            return mine > theirs
        if self.confidence != other.confidence:
            return self.confidence > other.confidence
        return self.source.fetched_at > other.source.fetched_at


class Region(str, Enum):
    NORTH_AMERICA = "north_america"
    SOUTH_ASIA = "south_asia"
    EUROPE = "europe"
    MENA = "mena"
    EAST_ASIA = "east_asia"
    SOUTHEAST_ASIA = "southeast_asia"
    OTHER = "other"


class Event(BaseModel):
    """A trade show or association gathering where the ICP shows up."""

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str
    organizer: str | None = None
    region: Region
    city: str | None = None
    country: str | None = None
    starts_on: Sourced[date] | None = None
    ends_on: Sourced[date] | None = None
    directory_url: Sourced[HttpUrl] | None = None
    adapter: str  # which source adapter can read this event's directory

    @property
    def is_upcoming(self) -> bool:
        """Upcoming shows are outreach triggers. Past ones are only evidence."""
        if self.starts_on is None:
            return False
        return self.starts_on.value >= date.today()


class Appearance(BaseModel):
    """One company showing up at one event. The join between the two."""

    event_slug: str
    booth: str | None = None
    categories: list[str] = Field(default_factory=list)
    source: Source


class Company(BaseModel):
    """
    A candidate lead, before and after enrichment.

    Identity is the domain when we have one, because the same company appears
    across four shows under three spellings ("3M", "3M Commercial Graphics",
    "3M Company") and deduping on name alone produces a mess.

    validate_assignment matters here: enrichment sets these fields one at a
    time after construction, and without it a raw string lands in a field
    typed as a URL and only surfaces as a serializer warning much later,
    long after the value it should have normalized got used.
    """

    model_config = ConfigDict(validate_assignment=True)

    name: str
    domain: str | None = None
    website: Sourced[HttpUrl] | None = None
    hq_city: Sourced[str] | None = None
    hq_country: Sourced[str] | None = None
    served_regions: list[Region] = Field(default_factory=list)

    revenue_usd: Sourced[float] | None = None
    revenue_band: Sourced[str] | None = None  # when an exact figure isn't public
    employees: Sourced[int] | None = None
    #: Sources publish headcount as "51-100" at least as often as a figure.
    #: A band is real information and does not belong in an int field.
    employees_band: Sourced[str] | None = None

    product_lines: list[Sourced[str]] = Field(default_factory=list)
    recent_signals: list[Sourced[str]] = Field(default_factory=list)

    appearances: list[Appearance] = Field(default_factory=list)

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower().removeprefix("http://").removeprefix("https://")
        v = v.removeprefix("www.").split("/")[0]
        return v or None

    @property
    def dedupe_key(self) -> str:
        if self.domain:
            return self.domain
        # Fall back to a squashed name. Imperfect, which is why domain
        # resolution runs before dedupe rather than after.
        return "".join(c for c in self.name.lower() if c.isalnum())

    @property
    def evidence(self) -> list[Sourced]:
        """Every sourced fact we hold. The outreach verifier reads this."""
        singles = [
            self.website, self.hq_city, self.hq_country,
            self.revenue_usd, self.revenue_band, self.employees,
            self.employees_band,
        ]
        return [s for s in singles if s is not None] + self.product_lines + self.recent_signals


class ScoreComponent(BaseModel):
    """
    One dimension of the qualification rubric.

    The model's job is to produce `raw` and cite why. The weighting and the
    final number are computed in Python, so the same inputs always give the
    same score and a rep can see exactly which dimension carried a lead.
    """

    name: str
    raw: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    rationale: str
    citations: list[Source] = Field(default_factory=list)

    @property
    def points(self) -> float:
        return self.raw * self.weight


class Tier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    DISQUALIFIED = "disqualified"


class Qualification(BaseModel):
    components: list[ScoreComponent]
    disqualified_reason: str | None = None
    #: Set when scoring itself failed. Distinct from being disqualified:
    #: one means assessed and out of scope, the other means never assessed.
    #: Collapsing them hides good leads inside a list of rejects.
    unassessed: bool = False

    @property
    def score(self) -> float:
        """0 to 100, normalized so weights don't have to sum to anything."""
        if self.disqualified_reason:
            return 0.0
        total_weight = sum(c.weight for c in self.components)
        if total_weight <= 0:
            return 0.0
        return round(100 * sum(c.points for c in self.components) / total_weight, 1)

    def tier(self, a_cut: float = 70.0, b_cut: float = 60.0) -> Tier:
        if self.disqualified_reason:
            return Tier.DISQUALIFIED
        if self.score >= a_cut:
            return Tier.A
        return Tier.B if self.score >= b_cut else Tier.C


class Stakeholder(BaseModel):
    """A named decision maker at a qualified company."""

    full_name: str
    title: str
    company_domain: str | None = None
    linkedin_url: Sourced[HttpUrl] | None = None
    sales_nav_url: HttpUrl | None = None  # constructed, not fetched
    email: Sourced[str] | None = None
    role_match: str  # which target role this person satisfies
    source: Source


class OutreachDraft(BaseModel):
    """
    A generated message plus the receipts.

    `unverified_claims` is populated by the verification pass. If it's
    non-empty the draft does not get sent, it gets flagged for a human.
    """

    subject: str
    body: str
    hook: str  # the specific fact the personalization hangs on
    supporting: list[Source] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)

    @property
    def safe_to_send(self) -> bool:
        return not self.unverified_claims


class ReviewStatus(str, Enum):
    NEW = "new"
    APPROVED = "approved"
    EDITED = "edited"
    SENT = "sent"
    REJECTED = "rejected"


class Lead(BaseModel):
    """What the dashboard renders. One row, fully assembled."""

    company: Company
    qualification: Qualification
    #: The second axis. Fit asks whether we should want them; leverage asks
    #: whether we can win them. Same machinery, different question, and the
    #: two together decide which sales motion the outreach agent writes for.
    leverage: Qualification | None = None
    stakeholders: list[Stakeholder] = Field(default_factory=list)
    outreach: OutreachDraft | None = None
    status: ReviewStatus = ReviewStatus.NEW
    generated_at: datetime = Field(default_factory=_utcnow)

    @property
    def score(self) -> float:
        return self.qualification.score

    @property
    def leverage_score(self) -> float:
        return self.leverage.score if self.leverage else 0.0

    @property
    def quadrant(self) -> str:
        """Which of the four sales motions this lead falls into."""
        if self.qualification.disqualified_reason:
            return "disqualified"
        fit_high = self.score >= 60
        lev_high = self.leverage_score >= 60
        if fit_high and lev_high:
            return "call_now"
        if fit_high:
            return "displacement"
        return "low_priority" if lev_high else "ignore"

    @property
    def needs_review(self) -> bool:
        """Anything a human has to look at before this can go out."""
        return (
            self.outreach is None
            or not self.outreach.safe_to_send
            or not self.stakeholders
        )


class RunStats(BaseModel):
    """Per-run accounting. Goes straight into the results section of the doc."""

    events_discovered: int = 0
    companies_sourced: int = 0
    companies_after_dedupe: int = 0
    companies_enriched: int = 0
    leads_qualified: int = 0
    stakeholders_found: int = 0
    drafts_generated: int = 0
    drafts_flagged: int = 0
    fetch_failures: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None

    @property
    def cost_per_qualified_lead(self) -> float | None:
        if not self.leads_qualified:
            return None
        return round(self.cost_usd / self.leads_qualified, 4)
