"""
The adapter contract.

An adapter knows how to read one *kind* of exhibitor directory, not one
event. That distinction is the whole reason the pipeline scales: ISA Sign
Expo and PRINTING United are different shows run by different associations
in different cities, and they need zero different code because both sit on
MapYourShow.

Adding an event = a block in config/events.yaml.
Adding a platform = one file in this directory.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date

from models import Appearance, Company, Event, Method, Region, Source

# Words that mean "this is a legal suffix, not part of the name". Stripped
# before dedupe so "Drytac Corp" and "Drytac Corporation" collapse.
SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|company|gmbh|bv|nv|sa|"
    r"srl|spa|ag|plc|pvt|private|pte|kk|kg|holdings?|group|intl|international)\b\.?",
    re.I,
)
PUNCT = re.compile(r"[^\w\s]")
SPACES = re.compile(r"\s+")


def canonical_name(raw: str) -> str:
    """
    Squash a company name to something comparable.

    Exhibitor directories are typed by hand by whoever booked the booth, so
    the same company genuinely appears as "3M", "3M Company", "3M
    Commercial Graphics" and "3M  Commercial Solutions Div." across four
    shows. This gets them closer together; domain resolution finishes the job.
    """
    name = SUFFIXES.sub(" ", raw)
    name = PUNCT.sub(" ", name)
    return SPACES.sub(" ", name).strip().lower()


class DirectoryError(Exception):
    """Raised only when an adapter is misconfigured, never for a bad page."""


# Site navigation that a link-following parser will happily mistake for
# companies. Learned the hard way: a directory whose exhibitor list is
# rendered client-side returns its own menu instead, and seven plausible
# looking rows entered the dataset without a single error being raised.
CHROME = re.compile(
    r"\b(exhibitor (application|services|search|list|manual|portal|login)"
    r"|information for|media package|online application|t&cs|terms"
    r"|planning|preparation|press release|contact us|privacy|sitemap"
    r"|register|log ?in|sign ?up|download|brochure|floor ?plan|my ?show)\b",
    re.I,
)


def looks_like_exhibitors(rows: list[Company], *, min_rows: int = 10) -> str | None:
    """
    Sanity-check an adapter's output before it enters the pipeline.

    Returns None if the batch looks like real companies, or a short reason
    if it does not. The point is to fail loudly on a directory we cannot
    actually read, instead of accepting whatever the parser scraped off the
    page and letting it corrupt every stage downstream.
    """
    if not rows:
        return "no rows returned"

    chrome = sum(1 for r in rows if CHROME.search(r.name))
    if chrome / len(rows) > 0.3:
        return f"{chrome}/{len(rows)} rows look like site navigation"

    # A real trade show directory is not eight entries long. A short batch
    # means we found a fragment of the page, not the list.
    if len(rows) < min_rows:
        return f"only {len(rows)} rows, below the {min_rows} row floor"

    named = sum(1 for r in rows if len(r.name.split()) >= 2 or r.name.isupper())
    if named / len(rows) < 0.5:
        return "rows do not look like company names"

    return None


class SourceAdapter(ABC):
    """
    Reads companies out of one platform's exhibitor directory.

    Implementations must not raise on a bad page. Return what you got and
    let the orchestrator record the gap, because a directory that half
    loads is still worth more than nothing.
    """

    name: str
    rate_limit: float = 2.0

    def __init__(self, fetcher, config: dict) -> None:
        self.fetcher = fetcher
        self.config = config
        self.rate_limit = float(config.get("rate_limit_per_sec", self.rate_limit))

    @abstractmethod
    async def exhibitors(self, event: Event) -> list[Company]:
        """Every company listed in this event's directory."""

    def _appearance(self, event: Event, booth: str | None = None,
                    categories: list[str] | None = None) -> Appearance:
        url = str(event.directory_url.value) if event.directory_url else None
        return Appearance(
            event_slug=event.slug,
            booth=booth,
            categories=categories or [],
            source=Source(url=url, method=Method.ORGANIZER,
                          note=f"listed as exhibitor at {event.name}"),
        )


_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    _REGISTRY[cls.name] = cls
    return cls


def build(name: str, fetcher, config: dict) -> SourceAdapter:
    if name not in _REGISTRY:
        raise DirectoryError(f"no adapter named {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name](fetcher, config.get(name, {}))


def merge(companies: list[Company]) -> list[Company]:
    """
    Collapse the same company appearing at several events into one record.

    Appearances accumulate rather than overwrite, which is the point: a
    company at three shows scores higher on engagement than the same
    company at one, and that only works if we keep all three.
    """
    by_key: dict[str, Company] = {}
    for c in companies:
        key = c.domain or canonical_name(c.name)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = c
            continue
        seen = {(a.event_slug, a.booth) for a in existing.appearances}
        existing.appearances.extend(
            a for a in c.appearances if (a.event_slug, a.booth) not in seen
        )
        # Keep the longer name. "Avery Dennison Graphics Solutions" beats
        # "Avery Dennison" for the enrichment agent's search query.
        if len(c.name) > len(existing.name):
            existing.name = c.name
        if existing.domain is None and c.domain:
            existing.domain = c.domain
    return list(by_key.values())
