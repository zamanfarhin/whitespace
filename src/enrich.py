"""
Enrichment: turn a company name into a sourced profile.

Everything here sits behind one interface. That is not architecture for its
own sake, it is the thing the brief actually asks for when it says to make
provisions for Clay or LinkedIn Sales Navigator: a real deployment would
swap the web provider for a paid one and change nothing else in the
pipeline. So the paid providers exist here as working shells with the real
call shape, the real fields, and the real failure modes, and the only thing
missing is a key.

Two rules hold across every provider:

  Nothing is returned without a Source. A revenue figure with no URL is a
  guess wearing a number's clothes, and one hallucinated figure that
  reaches a sales rep costs more trust than the whole pipeline earns.

  A provider that cannot answer returns an empty profile, not an
  exception. Enriching four hundred companies means some pages are down,
  some companies have no web presence worth reading, and some responses
  come back malformed. Each of those costs one company.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from llm import HAIKU, LLM
from pydantic import HttpUrl

from models import Company, Method, Region, Source, Sourced

CONCURRENCY = 2

# The search tool hands back cited text, and the model passes the citation
# markup straight through into string fields. Harmless in a chat reply,
# ugly in a dashboard and worse in an outreach email, so it is stripped at
# the boundary rather than anywhere downstream.
CITE = re.compile(r"</?cite[^>]*>|\[\d+(?:[,\-]\d+)*\]", re.I)


def _plain(text: object) -> str:
    """Strip citation markup and collapse whitespace."""
    return re.sub(r"\s+", " ", CITE.sub("", str(text or ""))).strip()

# Capping searches per company is the main cost lever in this stage. Three
# is enough to find a company site and one or two supporting pages; without
# a cap a single stubborn lookup can burn a dollar on its own.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}

SYSTEM = """You research companies for a materials sales team at DuPont Tedlar.

Tedlar is a PVF protective overlaminate applied over printed graphics: \
vehicle wraps, outdoor signage, architectural graphics, awnings. It is sold \
into companies that manufacture or convert films, laminates, print media, \
and outdoor fabrics.

Search for the company, read its own site where you can, and report only \
what you actually found. Every field carries the URL it came from. If you \
cannot find something, omit the field. An omitted field is correct; an \
invented one is not, and a guessed revenue figure is worse than no figure.

Do not infer a value from the company's name, from what similar companies \
do, or from what would make them a good prospect. Facts only.

Reply with a JSON object and nothing else:

{
  "website": {"v": "https://...", "src": "url where found"},
  "hq_city": {"v": "...", "src": "..."},
  "hq_country": {"v": "US", "src": "..."},
  "revenue_usd": {"v": 8000000000, "src": "..."},
  "revenue_band": {"v": "$100M-$1B", "src": "..."},
  "employees": {"v": 4200, "src": "..."},   // a number, or a band like "51-100"
  "product_lines": [{"v": "cast vinyl wrap film", "src": "..."}],
  "served_regions": ["north_america", "mena"],
  "outdoor_life_years": {"v": 7, "src": "..."},
  "film_partners": [{"v": "3M Scotchgard overlaminate", "src": "..."}],
  "recent_signals": [{"v": "launched a weatherable wall graphic line", "src": "..."}],
  "icp_fit": true,
  "summary": "one sentence on what they actually manufacture, plain text"
}

Notes on the harder fields:

  revenue_usd only when a real figure is published. Otherwise use \
revenue_band with one of: under $10M, $10M-$100M, $100M-$1B, over $1B.
  served_regions from: north_america, south_asia, europe, mena, \
east_asia, southeast_asia, other. Base it on stated distribution, offices, \
or export markets, not on guesswork.
  outdoor_life_years is the durability or warranty figure they advertise \
on outdoor products, in years. This is often on a spec sheet or product \
page. Omit it rather than estimating.
  film_partners is any protective film or overlaminate brand they name as \
being used in or with their products. An empty list means you looked and \
found none, which is a meaningful answer here.
  icp_fit asks one question: could a premium protective overlaminate be \
specified into this company's product line, or applied to what they make?

Say true for manufacturers and converters of graphic films, laminating \
films, adhesive and pressure-sensitive media, print substrates, vehicle \
wrap material, banner and awning fabric, architectural graphic media, and \
outdoor signage material. A company that already makes laminating films is \
a yes, not a no: film makers build premium protective layers into their own \
top-tier lines, and the reference customer for this product is exactly such \
a company.

Say false for printers, cutters, routers and other machinery; inks, toners \
and chemicals; software and services; LED and digital display hardware; \
trade associations and publishers; and apparel textiles, which never see \
outdoor weathering.

When you are unsure, say true and let the later scoring stage decide. This \
field only controls whether a company is looked at more closely.

Write summary as plain prose. Do not include citation markup, reference \
numbers, or bracketed tags in any text field."""


@dataclass
class Profile:
    """What a provider returns. Merged into the Company by the orchestrator."""

    fields: dict = field(default_factory=dict)
    makes_films: bool | None = None
    summary: str = ""
    provider: str = ""
    gap: str | None = None

    @property
    def empty(self) -> bool:
        return not self.fields and self.makes_films is None


class EnrichmentProvider(ABC):
    """
    One source of company facts.

    Implementations must not raise. Return a Profile with `gap` set when
    the lookup fails, so the run report can say how many companies came
    back thin and why.
    """

    name: str
    #: Roughly what one lookup costs, used to pick a provider under budget.
    cost_per_lookup: float = 0.0

    @abstractmethod
    async def enrich(self, company: Company) -> Profile:
        ...


def _sourced(raw: object, method: Method = Method.DIRECT,
             confidence: float = 0.8, as_url: bool = False) -> Sourced | None:
    """
    Wrap a {"v": ..., "src": ...} pair, dropping anything unsourced.

    This is the gate that keeps unsourced values out of the dataset. A
    field the model produced without a URL does not become a low-confidence
    fact, it does not become a fact at all.
    """
    if not isinstance(raw, dict):
        return None
    value, url = raw.get("v"), raw.get("src")
    if value in (None, "", []):
        return None
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    if isinstance(value, str):
        value = _plain(value)
        if not value:
            return None
    try:
        # Sourced is generic, so an unparameterized construction never
        # coerces. Ask for the URL flavour explicitly where the field wants
        # one, otherwise a raw string sails through and breaks on
        # serialization instead of here.
        model = Sourced[HttpUrl] if as_url else Sourced
        return model(value=value, source=Source(url=url, method=method),
                     confidence=confidence)
    except Exception:
        # A malformed URL fails Pydantic's validation. Drop the field
        # rather than the company.
        return None


HEADCOUNT_RANGE = re.compile(r"(\d[\d,]*)\s*(?:-|to|–)\s*(\d[\d,]*)")
HEADCOUNT_NUM = re.compile(r"(\d[\d,]*)")


def _split_headcount(raw: object, fields: dict) -> None:
    """
    Headcount arrives as a figure, a range, or "500+". Route each correctly.

    A range is not a failed integer, it is the answer the source published,
    so it goes to employees_band and the lower bound goes to employees for
    sorting. Discarding the band to force an int throws away the only thing
    the source actually said.
    """
    if not isinstance(raw, dict):
        return
    value = raw.get("v")

    if isinstance(value, (int, float)) and value > 0:
        got = _sourced({"v": int(value), "src": raw.get("src")})
        if got is not None:
            fields["employees"] = got
        return

    if not isinstance(value, str):
        return

    band = _sourced({"v": _plain(value)[:40], "src": raw.get("src")})
    if band is not None:
        fields["employees_band"] = band

    match = HEADCOUNT_RANGE.search(value) or HEADCOUNT_NUM.search(value)
    if match:
        try:
            fields["employees"] = _sourced(
                {"v": int(match.group(1).replace(",", "")), "src": raw.get("src")},
                confidence=0.6)
        except ValueError:
            pass
    fields.pop("employees", None) if fields.get("employees") is None else None


class WebProvider(EnrichmentProvider):
    """
    Public web research via the model's search tool.

    The default provider, and the one that runs without any account. Slower
    and less structured than a paid enrichment API, but it reaches private
    mid-size converters that firmographic databases cover badly, which in
    this industry is most of the interesting names.
    """

    name = "web"
    cost_per_lookup = 0.03

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    async def enrich(self, company: Company) -> Profile:
        shows = ", ".join(sorted({a.event_slug for a in company.appearances}))
        payload = await self.llm.json_call(
            stage="enrich",
            system=SYSTEM,
            prompt=(f"Company: {company.name}\n"
                    f"Seen exhibiting at: {shows or 'unknown'}\n\n"
                    f"Research this company and return the JSON object."),
            model=HAIKU,
            max_tokens=2500,
            tools=[WEB_SEARCH_TOOL],
        )
        if not isinstance(payload, dict):
            return Profile(provider=self.name, gap="no parseable response")

        fields: dict = {}
        for key in ("website", "hq_city", "hq_country", "revenue_usd",
                    "revenue_band", "outdoor_life_years"):
            got = _sourced(payload.get(key), as_url=(key == "website"))
            if got is not None:
                fields[key] = got

        _split_headcount(payload.get("employees"), fields)

        for key in ("product_lines", "film_partners", "recent_signals"):
            rows = payload.get(key)
            if isinstance(rows, list):
                kept = [s for s in (_sourced(r) for r in rows) if s is not None]
                if kept:
                    fields[key] = kept[:6]
                elif key == "film_partners":
                    # An empty list here is evidence, not a missing field:
                    # it means we looked and found no incumbent.
                    fields[key] = []

        regions = payload.get("served_regions")
        if isinstance(regions, list):
            valid = [r for r in regions if r in {m.value for m in Region}]
            if valid:
                fields["served_regions"] = [Region(r) for r in valid][:6]

        fit = payload.get("icp_fit")
        return Profile(
            fields=fields,
            makes_films=fit if isinstance(fit, bool) else None,
            summary=_plain(payload.get("summary", ""))[:240],
            provider=self.name,
            gap=None if fields else "nothing found",
        )


class ClayProvider(EnrichmentProvider):
    """
    Clay enrichment. Not wired to an account; the shape is real.

    Clay runs waterfall enrichment across many upstream vendors and returns
    a flat record per company, so the integration is a straight field map
    rather than any parsing. Where it would beat the web provider is
    firmographics: headcount and revenue on private companies, which is
    exactly the weakest part of the free path.

    To make this live:
      1. Put CLAY_API_KEY in .env.
      2. POST the company name and domain to the table webhook, which
         returns a row id.
      3. Poll the row until its enrichment status is complete; Clay's
         waterfall is asynchronous and typically settles in seconds.
      4. Map the response fields below and stamp each with
         Method.PROVIDER so precedence resolves against web findings.

    Precedence is the part worth thinking about now rather than later. A
    Clay revenue figure should beat a model's web reading, but it should
    not beat a figure published on the company's own site, which is why
    Method.PROVIDER sits below Method.DIRECT in the ranking.
    """

    name = "clay"
    cost_per_lookup = 0.10

    #: Clay response key -> our model field. The whole integration, really.
    FIELD_MAP = {
        "company_domain": "website",
        "hq_city": "hq_city",
        "hq_country": "hq_country",
        "annual_revenue": "revenue_usd",
        "employee_count": "employees",
        "industry_tags": "product_lines",
    }

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    async def enrich(self, company: Company) -> Profile:
        if not self.api_key:
            return Profile(provider=self.name, gap="CLAY_API_KEY not set")
        raise NotImplementedError(
            "Clay integration is specified but not wired. See the class "
            "docstring for the four steps and the field map."
        )


class SalesNavProvider(EnrichmentProvider):
    """
    LinkedIn Sales Navigator. Used for people, not companies.

    Kept in this module because it implements the same interface and the
    stakeholder stage calls it the same way. Sales Navigator has no open
    API: access is through the Sales Insights partner programme, and most
    teams in practice go through a licensed reseller or Clay's LinkedIn
    integration rather than direct.

    That constraint is worth designing around rather than wishing away. The
    pipeline therefore never depends on it: stakeholders are resolved from
    public sources, and the Sales Navigator URL is *constructed* from the
    company and person we already found. A rep with a seat clicks straight
    through; a rep without one still gets the name and title.
    """

    name = "sales_navigator"
    cost_per_lookup = 0.0

    BASE = "https://www.linkedin.com/sales/search/people"

    @staticmethod
    def search_url(company: str, titles: list[str]) -> str:
        """
        Build a Sales Navigator search link.

        No account needed to generate it, which is the point: the value is
        in knowing which search to run, and that comes from the ICP config.
        """
        from urllib.parse import quote

        title_filter = " OR ".join(f'"{t}"' for t in titles[:4])
        query = f'{company} ({title_filter})' if titles else company
        return f"{SalesNavProvider.BASE}?query={quote(query)}"

    async def enrich(self, company: Company) -> Profile:
        return Profile(provider=self.name, gap="people lookup, see stakeholders stage")


class FixtureProvider(EnrichmentProvider):
    """Replays saved enrichment so the pipeline runs offline and for free."""

    name = "fixtures"

    def __init__(self, path: str = "fixtures/enrichment.json") -> None:
        from pathlib import Path

        self.rows: dict[str, dict] = {}
        p = Path(path)
        if p.exists():
            try:
                self.rows = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.rows = {}

    async def enrich(self, company: Company) -> Profile:
        raw = self.rows.get(company.dedupe_key) or self.rows.get(company.name)
        if not raw:
            return Profile(provider=self.name, gap="no fixture")
        return Profile(fields=raw.get("fields", {}),
                       makes_films=raw.get("makes_films"),
                       summary=raw.get("summary", ""), provider=self.name)


def apply(company: Company, profile: Profile) -> Company:
    """
    Fold a profile into the company, letting the better source win.

    `beats()` handles the conflict: a figure from the company's own site
    outranks a provider record, which outranks an aggregator. Without this
    the last provider to run would silently overwrite the best one.
    """
    for key in ("website", "hq_city", "hq_country", "revenue_usd",
                "revenue_band", "employees", "employees_band"):
        incoming = profile.fields.get(key)
        if incoming is None or not incoming.beats(getattr(company, key, None)):
            continue
        try:
            setattr(company, key, incoming)
        except Exception:
            # Validation rejected the value. That costs this field and
            # nothing else. An earlier version let the exception escape and
            # one company returning a headcount range as "51-100" took down
            # a run of 120 that had already been paid for.
            continue

    if company.domain is None and company.website is not None:
        company.domain = str(company.website.value)

    for key in ("product_lines", "recent_signals"):
        rows = profile.fields.get(key)
        if rows:
            seen = {s.value for s in getattr(company, key)}
            getattr(company, key).extend(s for s in rows if s.value not in seen)

    regions = profile.fields.get("served_regions")
    if regions:
        company.served_regions = list(dict.fromkeys(company.served_regions + regions))

    return company


async def enrich_all(provider: EnrichmentProvider, companies: list[Company],
                     on_progress=None, journal: Path | None = None
                     ) -> tuple[list[Company], list[Profile]]:
    """
    Enrich a batch, appending each result to a journal as it completes.

    The journal exists because a crash in the merge step once discarded a
    completed, paid-for run of 120 companies. Results are now durable the
    moment they arrive, so the worst a later failure can cost is the time
    to re-read a file.
    """
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    lock = asyncio.Lock()

    async def one(c: Company) -> Profile:
        nonlocal done
        async with sem:
            try:
                return await provider.enrich(c)
            except NotImplementedError as exc:
                return Profile(provider=provider.name, gap=str(exc)[:80])
            except Exception as exc:
                # A provider that blows up costs one company. The gap is
                # recorded and the run continues.
                return Profile(provider=provider.name,
                               gap=f"{type(exc).__name__}: {exc}"[:80])
            finally:
                done += 1
                if on_progress:
                    on_progress(done, len(companies), c.name)

    async def record(c: Company) -> Profile:
        profile = await one(c)
        if journal is not None:
            async with lock:
                try:
                    with journal.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({
                            "name": c.name,
                            "fields": {k: (v.model_dump(mode="json")
                                           if hasattr(v, "model_dump") else
                                           [x.model_dump(mode="json") for x in v]
                                           if isinstance(v, list) and v
                                           and hasattr(v[0], "model_dump") else v)
                                       for k, v in profile.fields.items()},
                            "makes_films": profile.makes_films,
                            "summary": profile.summary,
                            "gap": profile.gap,
                        }, default=str) + "\n")
                except OSError:
                    pass
        return profile

    profiles = await asyncio.gather(*(record(c) for c in companies),
                                    return_exceptions=True)

    # A budget stop or any other raised exception becomes a gap on that one
    # company. Everything already enriched survives.
    clean: list[Profile] = []
    for p in profiles:
        if isinstance(p, BaseException):
            clean.append(Profile(provider=provider.name,
                                 gap=f"{type(p).__name__}: {p}"[:90]))
        else:
            clean.append(p)

    return [apply(c, p) for c, p in zip(companies, clean)], clean
