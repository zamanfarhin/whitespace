"""
Find the person to contact at a qualified company.

The brief asks for decision makers with LinkedIn Sales Navigator links.
Sales Navigator has no open API: access runs through LinkedIn's partner
programme, and teams in practice get there via a reseller or through Clay's
LinkedIn integration. Building against an endpoint that does not exist
would be a nicer demo and a worse answer.

So this splits the problem. Names and titles come from public sources,
which is slower but works today and covers private mid-size converters that
firmographic databases handle badly. The Sales Navigator link is
*constructed* from the company and the target titles, so a rep with a seat
clicks straight into the right filtered search, and a rep without one still
has a name to work with. Neither path depends on credentials this project
does not have.

Which titles to look for comes from config/icp.yaml, not from here. Tedlar
sells a specified material, so the buying centre is product development,
innovation, and R&D rather than procurement, and that judgement belongs in
config where a sales lead can argue with it.
"""

from __future__ import annotations

import asyncio

from enrich import WEB_SEARCH_TOOL, _plain
from llm import HAIKU, LLM
from models import Company, Method, Source, Sourced, Stakeholder

CONCURRENCY = 2

SYSTEM = """You find named decision makers at companies, using public sources.

The client sells a specified industrial material into product lines, so the \
people who matter are in product development, innovation, R&D, technical \
management, and materials sourcing. Not general procurement, not sales, not \
marketing.

Search for named individuals currently at the company whose titles match \
the target roles. Report only people you can actually find named on a \
public page: a company leadership page, a press release, a conference \
speaker listing, an association committee roster, a trade publication, or a \
public LinkedIn profile.

Never invent a person. Never guess an email address. Never infer that a \
company "probably has" a VP of Product Development. An empty list is a \
correct and useful answer, and a plausible fabricated contact is the single \
most damaging thing this system could produce, because a sales rep will act \
on it.

Reply with a JSON object and nothing else:

{
  "people": [
    {
      "name": "Full Name",
      "title": "their actual title",
      "role_match": "which target role this satisfies",
      "linkedin": "https://www.linkedin.com/in/... or null",
      "src": "url of the page where you found them",
      "confidence": 0.8
    }
  ]
}

At most three people, best match first. confidence between 0 and 1: high \
when the source is the company's own site and the title matches a target \
role exactly, low when the source is older or the title is adjacent."""


async def find_one(llm: LLM, company: Company,
                   target_roles: list[str]) -> list[Stakeholder]:
    from enrich import SalesNavProvider

    roles = "\n".join(f"  {r}" for r in target_roles)
    site = f"\nCompany website: {company.website.value}" if company.website else ""
    payload = await llm.json_call(
        stage="stakeholders",
        system=SYSTEM,
        prompt=(f"Company: {company.name}{site}\n\n"
                f"Target roles, in priority order:\n{roles}\n\n"
                f"Find decision makers at this company."),
        model=HAIKU,
        max_tokens=1200,
        tools=[WEB_SEARCH_TOOL],
    )
    if not isinstance(payload, dict):
        return []

    rows = payload.get("people")
    if not isinstance(rows, list):
        return []

    # The search link is built once per company, not per person: it filters
    # by company and target titles, which is the search a rep would run.
    nav = SalesNavProvider.search_url(company.name, target_roles)

    out: list[Stakeholder] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        name = _plain(row.get("name"))
        title = _plain(row.get("title"))
        src = row.get("src")
        # No source, no person. This is the gate that stops a plausible
        # invention reaching a rep's outbox.
        if not name or not title or not isinstance(src, str) or not src.startswith("http"):
            continue

        try:
            confidence = min(1.0, max(0.0, float(row.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5

        linkedin = row.get("linkedin")
        profile = None
        if isinstance(linkedin, str) and "linkedin.com/in/" in linkedin:
            try:
                profile = Sourced(value=linkedin,
                                  source=Source(url=src, method=Method.DIRECT),
                                  confidence=confidence)
            except Exception:
                profile = None

        try:
            out.append(Stakeholder(
                full_name=name[:80],
                title=title[:100],
                company_domain=company.domain,
                linkedin_url=profile,
                sales_nav_url=nav,
                role_match=_plain(row.get("role_match"))[:60] or "unspecified",
                source=Source(url=src, method=Method.DIRECT,
                              note=f"named on a public page for {company.name}"),
            ))
        except Exception:
            continue
    return out


async def find_all(llm: LLM, companies: list[Company],
                   target_roles: list[str]) -> list[list[Stakeholder]]:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(c: Company) -> list[Stakeholder]:
        async with sem:
            try:
                return await find_one(llm, c, target_roles)
            except Exception:
                # One company without a contact is a lead a rep researches
                # by hand. One exception without a guard is a dead run.
                return []

    return await asyncio.gather(*(one(c) for c in companies))
