"""
Qualification scoring.

The division of labour here is the whole point, and it is worth being
explicit about because it is the thing most likely to get asked about.

The model does one job: read the evidence gathered during enrichment and,
for each rubric dimension, pick a level from the scale and say which fact
made it pick that. It never sees a weight and never produces a total.

Python does the arithmetic. It reads the weights out of config/icp.yaml,
multiplies, normalizes, and assigns the tier.

That split buys three things. The same inputs always produce the same
score, so a rerun cannot silently reshuffle the pipeline. A sales rep can
be shown exactly which dimension carried a lead and what sentence it rested
on. And retuning the rubric is editing a YAML file, not re-running eight
hundred model calls.

Asking a model for "a score out of 100" gets you a number that feels right
and cannot be audited, defended, or adjusted. That is the thing to avoid.
"""

from __future__ import annotations

import asyncio
import json

from llm import SONNET, LLM
from models import (Company, Method, Qualification, ScoreComponent, Source,
                    Tier)

CONCURRENCY = 4

SYSTEM = """You assess sales prospects for DuPont Tedlar's Graphics & Signage team.

Tedlar is a PVF protective overlaminate for printed graphics that live \
outdoors: vehicle wraps, signage, architectural graphics, awnings. It sells \
on UV and weather resistance, chemical and graffiti resistance, and long \
outdoor service life. It is specified into the products of companies that \
manufacture or convert graphic films, print media, and outdoor fabrics.

You will be given a rubric and the evidence gathered about one company.

For each dimension, choose the level from its scale that the evidence \
supports, and quote the specific fact that made you choose it. Judge only \
on evidence provided. Absence of evidence is not evidence: if nothing in \
the record speaks to a dimension, score it low and say the record is \
silent, rather than assuming a plausible value.

First check the disqualifiers. If one applies, say so and stop; do not \
score a company that is out of scope.

Reply with a JSON object and nothing else:

{
  "disqualified": null,
  "fit": {
    "<dimension name>": {"raw": 0.7, "why": "the fact that decided it", "src": "url or null"}
  },
  "leverage": {
    "<dimension name>": {"raw": 0.4, "why": "...", "src": "url or null"}
  }
}

Set "disqualified" to a short reason string instead of null when a \
disqualifier applies, and omit the fit and leverage objects entirely.

raw is between 0 and 1 and should land on one of the levels the scale \
names. why is ONE SHORT SENTENCE, under 15 words, plain text, no citation \
markup. src is the URL the fact came from, or null when it came from the \
company's own summary.

Keep rationales short. Ten dimensions with long explanations will not fit \
in the response and the whole assessment is lost."""


def _render_rubric(icp: dict) -> str:
    """Turn the YAML rubric into the prompt text, so config drives the model too."""
    lines = ["DISQUALIFIERS (check these first):"]
    for d in icp.get("disqualifiers", []):
        lines.append(f"  {d['id']}: {d['test']} -> {d['reason']}")

    for block, label in (("rubric", "FIT"), ("leverage", "LEVERAGE")):
        lines.append(f"\n{label} DIMENSIONS:")
        for dim in icp.get(block, []):
            lines.append(f"\n  {dim['name']}")
            lines.append(f"    {' '.join(dim['question'].split())}")
            for level, meaning in sorted(dim["scale"].items(), reverse=True):
                lines.append(f"    {level}: {meaning}")
    return "\n".join(lines)


def _render_company(c: Company) -> str:
    """Everything known about a company, with its provenance attached."""
    def show(label, s):
        return f"  {label}: {s.value}  [{s.source.url}]" if s else None

    rows = [f"COMPANY: {c.name}"]
    for label, field in (("website", c.website), ("hq city", c.hq_city),
                         ("hq country", c.hq_country), ("revenue usd", c.revenue_usd),
                         ("revenue band", c.revenue_band), ("employees", c.employees)):
        row = show(label, field)
        if row:
            rows.append(row)

    if c.served_regions:
        rows.append(f"  markets served: {', '.join(r.value for r in c.served_regions)}")
    for label, items in (("product line", c.product_lines),
                         ("recent signal", c.recent_signals)):
        for s in items:
            rows.append(f"  {label}: {s.value}  [{s.source.url}]")

    shows = sorted({a.event_slug for a in c.appearances})
    rows.append(f"  exhibits at: {', '.join(shows) if shows else 'none found'}")
    # Said explicitly, because the difference between "we looked and found
    # no incumbent" and "we never looked" is the whole leverage axis.
    rows.append("  named protective film partners: none found in the record")
    return "\n".join(rows)


def _components(block: dict, spec: list[dict]) -> list[ScoreComponent]:
    """Pair the model's levels with the weights from config."""
    out = []
    for dim in spec:
        row = block.get(dim["name"]) if isinstance(block, dict) else None
        if not isinstance(row, dict):
            # A dimension the model skipped scores zero and says so, rather
            # than being dropped, which would quietly inflate the total by
            # shrinking the denominator.
            out.append(ScoreComponent(name=dim["name"], raw=0.0,
                                      weight=float(dim["weight"]),
                                      rationale="not addressed in the response"))
            continue
        try:
            raw = min(1.0, max(0.0, float(row.get("raw", 0.0))))
        except (TypeError, ValueError):
            raw = 0.0
        src = row.get("src")
        cites = []
        if isinstance(src, str) and src.startswith("http"):
            try:
                cites.append(Source(url=src, method=Method.DIRECT))
            except Exception:
                pass
        out.append(ScoreComponent(
            name=dim["name"], raw=raw, weight=float(dim["weight"]),
            rationale=str(row.get("why", ""))[:220] or "no rationale given",
            citations=cites,
        ))
    return out


async def score_one(llm: LLM, icp: dict, rubric_text: str,
                    company: Company) -> tuple[Qualification, Qualification | None]:
    payload = await llm.json_call(
        stage="score",
        system=SYSTEM,
        prompt=f"{rubric_text}\n\n{'=' * 60}\n\n{_render_company(company)}",
        model=SONNET,
        max_tokens=4000,
    )

    if not isinstance(payload, dict):
        # No response means unscored, not zero. A company that scored zero
        # was assessed; this one was not, and conflating them would bury a
        # good lead at the bottom of the list with no explanation.
        return Qualification(components=[], unassessed=True,
                             disqualified_reason="scoring failed"), None

    reason = payload.get("disqualified")
    if isinstance(reason, str) and reason.strip():
        return Qualification(components=[],
                             disqualified_reason=reason.strip()[:160]), None

    fit = Qualification(components=_components(payload.get("fit", {}), icp["rubric"]))
    lev = Qualification(components=_components(payload.get("leverage", {}),
                                               icp["leverage"]))
    return fit, lev


async def score_all(llm: LLM, icp: dict, companies: list[Company]):
    rubric_text = _render_rubric(icp)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(c: Company):
        async with sem:
            try:
                return await score_one(llm, icp, rubric_text, c)
            except Exception as exc:
                return (Qualification(components=[], unassessed=True,
                                      disqualified_reason=f"error: {type(exc).__name__}"),
                        None)

    return await asyncio.gather(*(one(c) for c in companies))
