"""
Entry point. Right now it runs the sourcing stage only; enrichment,
scoring, stakeholders, and outreach get wired in as they land.

    python src/cli.py source              # live fetch
    python src/cli.py source --offline    # read fixtures, no network
    python src/cli.py source --snapshot   # live fetch, save fixtures
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv  # noqa: E402

from config import load_events, load_icp  # noqa: E402
from fetch import Fetcher  # noqa: E402
from models import Company, Lead, RunStats  # noqa: E402
from outreach import draft_all  # noqa: E402
from score import score_all  # noqa: E402
from stakeholders import find_all  # noqa: E402
from screen import Bucket, screen_all  # noqa: E402
from classify import classify, enrichment_queue  # noqa: E402
from enrich import (FixtureProvider, SalesNavProvider, WebProvider,  # noqa: E402
                    enrich_all)
from llm import LLM, LLMError  # noqa: E402
import sources  # noqa: E402,F401  (import registers the adapters)
from sources.base import build, merge  # noqa: E402

OUT_DIR = Path("out")
FIXTURE_DIR = Path("fixtures/exhibitors")


async def run_sourcing(offline: bool, snapshot: bool) -> tuple[list, RunStats]:
    events, adapter_cfg = load_events()
    stats = RunStats(events_discovered=len(events))
    collected = []

    async with Fetcher() as fetcher:
        for event in events:
            name = "fixtures" if offline else event.adapter
            try:
                adapter = build(name, fetcher, adapter_cfg)
            except Exception as exc:
                print(f"  {event.slug:26} skipped ({exc})")
                continue

            found = await adapter.exhibitors(event)
            stats.companies_sourced += len(found)
            collected.extend(found)

            status = "no companies found" if not found else f"{len(found)} companies"
            print(f"  {event.slug:26} {status}")

            if snapshot and found:
                FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
                rows = [
                    {"name": c.name, "domain": c.domain,
                     "booth": c.appearances[0].booth if c.appearances else None,
                     "categories": c.appearances[0].categories if c.appearances else []}
                    for c in found
                ]
                (FIXTURE_DIR / f"{event.slug}.json").write_text(
                    json.dumps(rows, indent=2), encoding="utf-8")

        stats.cache_hits = fetcher.cache_hits
        stats.fetch_failures = len(fetcher.failures)
        if fetcher.failures:
            print("\n  fetch failures:")
            for f in fetcher.failures[:10]:
                print(f"    {f.status or '-'} {f.reason}: {f.url[:90]}")

    unique = merge(collected)
    stats.companies_after_dedupe = len(unique)
    return unique, stats


def main() -> int:
    parser = argparse.ArgumentParser(prog="whitespace")
    parser.add_argument("--version", action="version", version="whitespace v14")
    sub = parser.add_subparsers(dest="command", required=True)
    src = sub.add_parser("source", help="fetch exhibitor lists")
    src.add_argument("--offline", action="store_true", help="read fixtures, no network")
    src.add_argument("--snapshot", action="store_true", help="save fetches as fixtures")

    scr = sub.add_parser("screen", help="triage sourced companies before enrichment")
    scr.add_argument("--limit", type=int, default=120,
                     help="how many companies to hand to enrichment")
    scr.add_argument("--show", type=int, default=15, help="rows to print per bucket")
    scr.add_argument("--no-llm", action="store_true",
                     help="keyword screen only, skip the model pass")

    enr = sub.add_parser("enrich", help="research the shortlisted companies")
    enr.add_argument("--limit", type=int, default=25,
                     help="how many to enrich this run (start small)")
    enr.add_argument("--offline", action="store_true",
                     help="replay saved enrichment, no network or spend")
    enr.add_argument("--max-spend", type=float, default=6.0,
                     help="hard USD ceiling for this run")

    sc = sub.add_parser("score", help="qualify enriched companies against the rubric")
    sc.add_argument("--limit", type=int, default=0, help="0 scores everything")
    sc.add_argument("--max-spend", type=float, default=5.0,
                    help="hard USD ceiling for this run")

    out = sub.add_parser("outreach",
                         help="find stakeholders and draft verified messages")
    out.add_argument("--top", type=int, default=30,
                     help="how many of the highest-scoring leads to work")
    out.add_argument("--max-spend", type=float, default=4.0,
                     help="hard USD ceiling for this run")
    args = parser.parse_args()

    if args.command == "screen":
        return run_screen(args.limit, args.show, args.no_llm)
    if args.command == "enrich":
        return run_enrich(args.limit, args.offline, args.max_spend)
    if args.command == "score":
        return run_score(args.limit, args.max_spend)
    if args.command == "outreach":
        return run_outreach(args.top, args.max_spend)

    print("sourcing exhibitors\n")
    companies, stats = asyncio.run(run_sourcing(args.offline, args.snapshot))

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "companies.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in companies], indent=2),
        encoding="utf-8")

    print(f"\n  {stats.companies_sourced} listings -> "
          f"{stats.companies_after_dedupe} unique companies")
    print(f"  {stats.cache_hits} cache hits, {stats.fetch_failures} fetch failures")
    print(f"  written to {OUT_DIR / 'companies.json'}")
    return 0


def run_screen(limit: int, show: int, no_llm: bool) -> int:
    path = OUT_DIR / "companies.json"
    if not path.exists():
        print(f"no {path}. run `python src/cli.py source` first.")
        return 1

    companies = [Company.model_validate(r)
                 for r in json.loads(path.read_text(encoding="utf-8"))]
    results = screen_all(companies)
    counts = {b: sum(1 for s in results if s.bucket is b) for b in Bucket}

    print(f"screened {len(results)} companies\n")
    for b in (Bucket.STRONG, Bucket.UNKNOWN, Bucket.EXCLUDED):
        print(f"  {b.value:9} {counts[b]:5}")

    print(f"\n  top {show} by signal:")
    for s in [r for r in results if r.bucket is Bucket.STRONG][:show]:
        print(f"    {s.signal:5.1f}  {s.name[:58]}")

    print(f"\n  {show} excluded, with reasons:")
    for s in [r for r in results if r.bucket is Bucket.EXCLUDED][:show]:
        print(f"    {s.name[:44]:46} {s.reason}")

    if no_llm:
        print("\n  --no-llm set, stopping after the keyword screen")
        return 0

    load_dotenv()
    try:
        llm = LLM()
    except LLMError as exc:
        print(f"\n  {exc}")
        return 1

    print(f"\n  classifying {sum(1 for r in results if r.bucket is not Bucket.EXCLUDED)}"
          f" companies with the model, no web search")
    classified = asyncio.run(classify(llm, results))

    counts: dict[str, int] = {}
    for c in classified:
        counts[c.klass.value] = counts.get(c.klass.value, 0) + 1
    print()
    for k in ("maker", "fabricator", "unsure", "supply", "equipment", "service"):
        if counts.get(k):
            print(f"  {k:11} {counts[k]:5}")

    print(f"\n  makers found, top {show}:")
    for c in [x for x in classified if x.klass.value == "maker"][:show]:
        print(f"    {c.name[:44]:46} {c.note}")

    queue = enrichment_queue(classified, limit)
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "shortlist.json").write_text(
        json.dumps([{"name": c.name, "class": c.klass.value, "note": c.note,
                     "screen_signal": c.screen_signal,
                     "company": c.company.model_dump(mode="json")} for c in queue],
                   indent=2), encoding="utf-8")
    print(f"\n  {len(queue)} companies queued for enrichment "
          f"-> {OUT_DIR / 'shortlist.json'}")
    print(f"  {llm.ledger.summary()}")
    return 0


def run_enrich(limit: int, offline: bool, max_spend: float) -> int:
    path = OUT_DIR / "shortlist.json"
    if not path.exists():
        print(f"no {path}. run `python src/cli.py screen` first.")
        return 1

    rows = json.loads(path.read_text(encoding="utf-8"))[:limit]
    companies = [Company.model_validate(r["company"]) for r in rows]

    if offline:
        provider, llm = FixtureProvider(), None
    else:
        load_dotenv()
        try:
            llm = LLM(max_spend=max_spend)
        except LLMError as exc:
            print(f"  {exc}")
            return 1
        provider = WebProvider(llm)
        estimate = len(companies) * provider.cost_per_lookup
        print(f"enriching {len(companies)} companies via {provider.name}\n"
              f"  estimate ${estimate:.2f}, hard ceiling ${max_spend:.2f}\n"
              f"  already-cached companies cost nothing\n")

    def tick(done: int, total: int, name: str) -> None:
        print(f"\r  {done:>4}/{total}  {name[:44]:46}", end="", flush=True)

    journal = OUT_DIR / "enrich-journal.jsonl"
    OUT_DIR.mkdir(exist_ok=True)
    enriched, profiles = asyncio.run(
        enrich_all(provider, companies, tick, journal))
    print("\r" + " " * 60 + "\r", end="")

    gaps = [p for p in profiles if p.gap]
    filtered = sum(1 for p in profiles if p.makes_films is False)

    for c, p in zip(enriched[:20], profiles[:20]):
        size = (f"${c.revenue_usd.value/1e6:,.0f}M" if c.revenue_usd
                else (c.revenue_band.value if c.revenue_band else "size unknown"))
        flag = "" if p.makes_films is not False else "  [no film surface]"
        print(f"  {c.name[:38]:40} {size:16} {p.summary[:44]}{flag}")

    print(f"\n  {len(enriched) - len(gaps)}/{len(enriched)} enriched, "
          f"{len(gaps)} thin, {filtered} ruled out as non-film")
    if gaps:
        for p in gaps[:5]:
            print(f"    gap: {p.gap}")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "enriched.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in enriched], indent=2),
        encoding="utf-8")
    print(f"  written to {OUT_DIR / 'enriched.json'}")
    if llm is not None:
        print(f"  {llm.ledger.summary()}")
    return 0


def run_score(limit: int, max_spend: float) -> int:
    path = OUT_DIR / "enriched.json"
    if not path.exists():
        print(f"no {path}. run `python src/cli.py enrich` first.")
        return 1

    rows = json.loads(path.read_text(encoding="utf-8"))
    companies = [Company.model_validate(r) for r in (rows[:limit] if limit else rows)]

    load_dotenv()
    try:
        llm = LLM(max_spend=max_spend)
    except LLMError as exc:
        print(f"  {exc}")
        return 1

    icp = load_icp()
    print(f"  hard ceiling ${max_spend:.2f}, cached work is free\n")
    print(f"scoring {len(companies)} companies against "
          f"{len(icp['rubric'])} fit and {len(icp['leverage'])} leverage dimensions\n")

    scored = asyncio.run(score_all(llm, icp, companies))
    leads = [Lead(company=c, qualification=fit, leverage=lev)
             for c, (fit, lev) in zip(companies, scored)]
    leads.sort(key=lambda l: (-l.score, -l.leverage_score))

    live = [l for l in leads if not l.qualification.disqualified_reason]
    quadrants: dict[str, int] = {}
    for l in live:
        quadrants[l.quadrant] = quadrants.get(l.quadrant, 0) + 1

    print(f"  {'company':38} {'fit':>5} {'lev':>5}  tier  quadrant")
    for l in live[:25]:
        print(f"  {l.company.name[:36]:38} {l.score:5.1f} {l.leverage_score:5.1f}"
              f"  {l.qualification.tier().value:4}  {l.quadrant}")

    dq = [l for l in leads
          if l.qualification.disqualified_reason and not l.qualification.unassessed]
    if dq:
        print(f"\n  {len(dq)} disqualified, with reasons:")
        for l in dq[:8]:
            print(f"    {l.company.name[:36]:38} {l.qualification.disqualified_reason[:52]}")

    missed = [l for l in leads if l.qualification.unassessed]
    if missed:
        print(f"\n  {len(missed)} not assessed (scoring failed, rerun to retry):")
        for l in missed[:6]:
            print(f"    {l.company.name[:36]}")

    print(f"\n  quadrants: " + ", ".join(f"{k} {v}" for k, v in sorted(quadrants.items())))
    if live:
        top = live[0]
        print(f"\n  why {top.company.name} scored {top.score:.0f}:")
        for comp in sorted(top.qualification.components, key=lambda c: -c.points):
            print(f"    {comp.name:24} {comp.raw:.1f} x {comp.weight:<4.0f} "
                  f"= {comp.points:5.1f}  {comp.rationale[:52]}")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "leads.json").write_text(
        json.dumps([l.model_dump(mode="json") for l in leads], indent=2),
        encoding="utf-8")
    print(f"\n  written to {OUT_DIR / 'leads.json'}")
    print(f"  {llm.ledger.summary()}")
    return 0


def run_outreach(top: int, max_spend: float) -> int:
    path = OUT_DIR / "leads.json"
    if not path.exists():
        print(f"no {path}. run `python src/cli.py score` first.")
        return 1

    leads = [Lead.model_validate(r)
             for r in json.loads(path.read_text(encoding="utf-8"))]
    live = [l for l in leads
            if not l.qualification.disqualified_reason and l.quadrant != "ignore"]
    working = live[:top]
    if not working:
        print("  no qualified leads to work")
        return 1

    load_dotenv()
    try:
        llm = LLM(max_spend=max_spend)
    except LLMError as exc:
        print(f"  {exc}")
        return 1

    icp = load_icp()
    roles = icp.get("target_roles", [])

    print(f"finding decision makers at {len(working)} companies "
          f"(ceiling ${max_spend:.2f})\n")
    people = asyncio.run(find_all(llm, [l.company for l in working], roles))
    for lead, found in zip(working, people):
        lead.stakeholders = found

    with_person = sum(1 for l in working if l.stakeholders)
    print(f"  named contacts found at {with_person}/{len(working)} companies\n")
    for l in working[:12]:
        if l.stakeholders:
            p = l.stakeholders[0]
            print(f"  {l.company.name[:30]:32} {p.full_name[:22]:24} {p.title[:34]}")

    print(f"\ndrafting and verifying messages\n")
    drafts = asyncio.run(draft_all(llm, working))
    for lead, draft in zip(working, drafts):
        lead.outreach = draft

    wrote = [d for d in drafts if d]
    clean = [d for d in wrote if d.safe_to_send]
    print(f"  {len(wrote)} drafted, {len(clean)} passed verification, "
          f"{len(wrote) - len(clean)} flagged for review")

    for lead, draft in zip(working, drafts):
        if draft and draft.safe_to_send:
            print(f"\n  --- {lead.company.name} ({lead.quadrant}) ---")
            print(f"  subject: {draft.subject}")
            for line in draft.body.split(". ")[:4]:
                print(f"  {line.strip()[:88]}")
            break

    for lead, draft in zip(working, drafts):
        if draft and not draft.safe_to_send:
            print(f"\n  flagged: {lead.company.name}")
            for claim in draft.unverified_claims[:3]:
                print(f"    unsupported: {claim[:78]}")
            break

    by_slug = {id(l): l for l in working}
    merged = [by_slug.get(id(l), l) for l in leads]
    (OUT_DIR / "leads.json").write_text(
        json.dumps([l.model_dump(mode="json") for l in merged], indent=2),
        encoding="utf-8")
    print(f"\n  written to {OUT_DIR / 'leads.json'}")
    print(f"  {llm.ledger.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
