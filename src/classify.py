"""
Tier 2 triage: batched name classification, no web search.

The keyword screen is high precision and poor recall. It correctly excludes
anything called "Arcus Printers", and it has nothing to say about ORAFOL,
Drytac, or General Formulations, which are three of the most on-target
companies in the industry. Sorting those into an `unknown` pile and then
enriching alphabetically means paying to look up A4 and AA Mills while the
real leads sit unread at position 400.

The model already knows what ORAFOL makes. That knowledge is free at
inference time; web search is the part that costs a cent a query. So this
stage spends the cheap resource to decide where to spend the expensive one.

Names go out forty at a time, which keeps each response small enough to
parse reliably and cuts the per-call overhead by a factor of forty. Roughly
twenty calls for eight hundred companies, well under a dollar.

Nothing here is treated as fact. A model's recall about a mid-size private
converter is a prior, not evidence, and everything it says gets re-derived
from sources in tier 3. What it produces is an ordering.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from llm import HAIKU, LLM
from models import Company
from screen import Bucket, Screened

BATCH_SIZE = 40
CONCURRENCY = 3

SYSTEM = """You triage company names for a materials sales team at DuPont Tedlar.

Tedlar is a PVF film applied as a protective overlaminate on top of printed \
graphics: vehicle wraps, outdoor signage, architectural graphics, awnings. \
It is sold to companies that MANUFACTURE or CONVERT films, laminates, print \
media, and outdoor fabrics, so that they can build it into their own product.

Sort each company into exactly one class:

  maker      manufactures or converts films, laminates, adhesive media, print \
substrates, graphic vinyl, or outdoor/architectural fabric
  fabricator makes finished signs, wraps, displays, or awnings from bought \
materials (a plausible but weaker fit)
  equipment  printers, cutters, routers, machinery, hardware, electronics
  supply     inks, toners, chemicals, tools, and other consumables
  service    software, staffing, logistics, consulting, associations, media
  unsure     you do not recognise the name well enough to place it

Judge on what you actually know about the company. Do not guess from the \
name alone: if the name is uninformative and you do not recognise it, say \
unsure. unsure is a useful answer and is much better than a wrong one.

Reply with a JSON array and nothing else. One object per input company, in \
the same order, each: {"n": <index>, "c": "<class>", "w": "<what they make, \
under 10 words, or empty if unsure>"}"""

VALID = {"maker", "fabricator", "equipment", "supply", "service", "unsure"}

# How much of the enrichment budget each class deserves.
PRIORITY = {
    "maker": 0,
    "fabricator": 1,
    "unsure": 2,
    "supply": 3,
    "equipment": 4,
    "service": 4,
}


class Klass(str, Enum):
    MAKER = "maker"
    FABRICATOR = "fabricator"
    EQUIPMENT = "equipment"
    SUPPLY = "supply"
    SERVICE = "service"
    UNSURE = "unsure"


@dataclass
class Classified:
    company: Company
    klass: Klass
    note: str = ""
    screen_signal: float = 0.0

    @property
    def name(self) -> str:
        return self.company.name

    @property
    def priority(self) -> int:
        return PRIORITY[self.klass.value]


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


async def _classify_batch(llm: LLM, batch: list[Screened],
                          sem: asyncio.Semaphore) -> list[Classified]:
    listing = "\n".join(f"{i}. {s.name}" for i, s in enumerate(batch))
    async with sem:
        payload = await llm.json_call(
            stage="classify",
            system=SYSTEM,
            prompt=f"Classify these {len(batch)} companies:\n\n{listing}",
            model=HAIKU,
            max_tokens=4000,
        )

    # A batch that failed to parse is not lost. Everything in it falls back
    # to unsure, which keeps it in the enrichment queue at middling
    # priority rather than silently dropping forty companies.
    if not isinstance(payload, list):
        return [Classified(s.company, Klass.UNSURE, "batch unparsed", s.signal)
                for s in batch]

    by_index: dict[int, dict] = {}
    for row in payload:
        if isinstance(row, dict) and isinstance(row.get("n"), int):
            by_index[row["n"]] = row

    out = []
    for i, s in enumerate(batch):
        row = by_index.get(i, {})
        raw = str(row.get("c", "")).strip().lower()
        klass = Klass(raw) if raw in VALID else Klass.UNSURE
        out.append(Classified(s.company, klass, str(row.get("w", ""))[:80], s.signal))
    return out


async def classify(llm: LLM, screened: list[Screened]) -> list[Classified]:
    """
    Classify everything the keyword screen did not already exclude.

    Excluded companies skip this entirely: the regex was confident and
    re-asking a model about "Arcus Printers" is spending money to confirm
    something already known.
    """
    candidates = [s for s in screened if s.bucket is not Bucket.EXCLUDED]
    if not candidates:
        return []

    sem = asyncio.Semaphore(CONCURRENCY)
    batches = _chunk(candidates, BATCH_SIZE)
    results = await asyncio.gather(*(_classify_batch(llm, b, sem) for b in batches))

    flat = [c for batch in results for c in batch]
    flat.sort(key=lambda c: (
        c.priority,
        -c.screen_signal,
        -len(c.company.appearances),
        c.name.lower(),
    ))
    return flat


def enrichment_queue(classified: list[Classified], limit: int) -> list[Classified]:
    """Makers and fabricators first, then unsure. Never equipment or service."""
    keep = [c for c in classified
            if c.klass in (Klass.MAKER, Klass.FABRICATOR, Klass.UNSURE)]
    return keep[:limit] if limit > 0 else keep
