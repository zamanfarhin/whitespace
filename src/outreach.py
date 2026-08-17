"""
Draft the outreach note, then check it against the evidence.

Two model calls per lead, deliberately. The first writes; the second reads
what was written with no memory of having written it and asks, of each
factual claim, whether the evidence bundle supports it. A writer checking
its own work agrees with itself.

This is the stage that decides whether the whole system is usable. Fluent
personalized email is easy to generate and easy to get wrong, and a note
that confidently references a product line a company does not make is worse
than a generic one: it is the moment a prospect concludes the sender did
not do the work. That failure is what gets sales AI removed from a company,
so the gate is not decoration.

Anything that fails verification is not discarded and not silently fixed.
It is flagged and routed to a human, which is what "review, edit, or send
with one click" actually requires.

The quadrant drives the message. A high-fit, high-leverage lead gets a
direct note naming the gap we found. A high-fit lead whose account a
competitor already owns gets a longer-horizon note that leads on technical
difference rather than urgency, because pushing for a meeting there reads
as not understanding their situation.
"""

from __future__ import annotations

import asyncio

from enrich import _plain
from llm import SONNET, LLM
from models import Lead, OutreachDraft, Source, Stakeholder

CONCURRENCY = 3

MOTIONS = {
    "call_now": (
        "This account looks open: we found no incumbent protective film "
        "partner, or a durability gap in what they publish. Write directly. "
        "Name the specific gap. Ask for a short technical conversation."
    ),
    "displacement": (
        "Strong fit, but a competitor most likely holds this account. Do not "
        "push for a meeting and do not imply urgency. Lead on one concrete "
        "technical difference and offer information, not a call. The goal is "
        "to be remembered at their next materials review."
    ),
    "low_priority": (
        "Weak fit. Keep it short, general, and low-commitment. No specific "
        "technical claims."
    ),
    "ignore": "Do not write to this lead.",
}

WRITE_SYSTEM = """You write first-touch outreach for DuPont Tedlar's Graphics \
& Signage team.

Tedlar is a PVF protective overlaminate for printed graphics that live \
outdoors. It sells on UV and weather resistance, chemical and graffiti \
resistance, and long outdoor service life, and it is specified into the \
product lines of companies that manufacture graphic films, print media, and \
outdoor fabrics.

You will be given everything known about one company and one person, and the \
sales motion to use.

Rules:

Every factual claim about the recipient's company must come from the \
evidence given to you. If it is not in the evidence, you cannot say it. Do \
not describe their products, markets, size, or plans from general knowledge \
about their industry.

No invented specifics. No made-up mutual connections, no invented case \
studies, no numbers you were not given, no claims about what Tedlar did for \
"a similar manufacturer".

Under 120 words. Plain sentences. No exclamation marks, no "I hope this \
finds you well", no "I noticed you're doing amazing work", no em dashes.

Open with the specific thing that made this company worth writing to. One \
sentence on why Tedlar is relevant to that specific thing. One low-friction \
ask.

Reply with a JSON object and nothing else:

{
  "subject": "under 60 characters, specific, no hype",
  "body": "the message, with a greeting line and a sign-off",
  "hook": "the one fact the personalization rests on",
  "claims": ["each factual claim you made about their company, one per string"]
}

claims is the important field. List every statement you made about the \
recipient's company as a separate string. Be exhaustive and honest: this \
list is checked against the evidence, and an unlisted claim found later is \
treated as a failure of the whole draft."""

CHECK_SYSTEM = """You verify outreach emails against source evidence, for a \
sales team that will send them.

You are given an evidence bundle about a company and a draft email. For each \
factual claim the email makes about the recipient's company, decide whether \
the evidence supports it.

Supported means the evidence states it or directly implies it. Not \
supported means the evidence is silent, or says something different, or the \
claim is more specific than the evidence warrants. "They make outdoor \
signage material" is not support for "your fleet graphics line".

Claims about Tedlar itself, and ordinary courtesy, are not your concern. \
Only claims about the recipient's company.

Be strict. A false positive here reaches a real prospect.

Reply with a JSON object and nothing else:

{
  "unsupported": ["each claim the evidence does not support, quoted"],
  "verdict": "pass" or "flag"
}"""


def _evidence(lead: Lead) -> str:
    """Everything the writer is allowed to use, with sources attached."""
    c = lead.company
    rows = [f"COMPANY: {c.name}"]

    for label, s in (("website", c.website), ("hq city", c.hq_city),
                     ("hq country", c.hq_country), ("revenue", c.revenue_usd),
                     ("revenue band", c.revenue_band), ("employees", c.employees),
                     ("employee band", c.employees_band)):
        if s:
            rows.append(f"  {label}: {s.value}  [{s.source.url}]")

    if c.served_regions:
        rows.append(f"  markets served: {', '.join(r.value for r in c.served_regions)}")
    for s in c.product_lines:
        rows.append(f"  product line: {s.value}  [{s.source.url}]")
    for s in c.recent_signals:
        rows.append(f"  recent activity: {s.value}  [{s.source.url}]")

    for a in c.appearances:
        booth = f", booth {a.booth}" if a.booth else ""
        rows.append(f"  exhibiting at: {a.event_slug}{booth}")

    rows.append("\nWHY THIS COMPANY SCORED WELL:")
    for comp in sorted(lead.qualification.components, key=lambda x: -x.points)[:4]:
        if comp.raw > 0:
            rows.append(f"  {comp.name}: {comp.rationale}")
    if lead.leverage:
        for comp in sorted(lead.leverage.components, key=lambda x: -x.points)[:3]:
            if comp.raw > 0:
                rows.append(f"  {comp.name}: {comp.rationale}")
    return "\n".join(rows)


async def draft_one(llm: LLM, lead: Lead,
                    person: Stakeholder | None) -> OutreachDraft | None:
    if lead.quadrant in ("ignore", "disqualified"):
        return None

    who = (f"{person.full_name}, {person.title}" if person
           else "an unnamed decision maker in product development")
    evidence = _evidence(lead)

    written = await llm.json_call(
        stage="outreach",
        system=WRITE_SYSTEM,
        prompt=(f"{evidence}\n\nRECIPIENT: {who}\n\n"
                f"SALES MOTION: {MOTIONS[lead.quadrant]}\n\nWrite the message."),
        model=SONNET,
        max_tokens=1200,
    )
    if not isinstance(written, dict):
        return None

    subject = _plain(written.get("subject"))[:90]
    body = _plain(written.get("body"))
    if not subject or not body:
        return None

    claims = [_plain(c) for c in written.get("claims", []) if _plain(c)]

    checked = await llm.json_call(
        stage="verify",
        system=CHECK_SYSTEM,
        prompt=(f"{evidence}\n\n{'=' * 60}\n\nDRAFT SUBJECT: {subject}\n\n"
                f"DRAFT BODY:\n{body}\n\nCLAIMS THE WRITER LISTED:\n"
                + "\n".join(f"  {c}" for c in claims)),
        model=SONNET,
        max_tokens=800,
    )

    unsupported: list[str] = []
    if isinstance(checked, dict):
        rows = checked.get("unsupported")
        if isinstance(rows, list):
            unsupported = [_plain(r)[:200] for r in rows if _plain(r)]
    else:
        # A verifier that did not answer is not a pass. Unverified drafts
        # go to a human, because the alternative is sending on the writer's
        # own assurance, which is the thing this stage exists to prevent.
        unsupported = ["verification did not complete"]

    supporting: list[Source] = []
    for s in lead.company.evidence[:8]:
        supporting.append(s.source)

    return OutreachDraft(
        subject=subject,
        body=body,
        hook=_plain(written.get("hook"))[:200],
        supporting=supporting,
        unverified_claims=unsupported,
    )


async def draft_all(llm: LLM, leads: list[Lead]) -> list[OutreachDraft | None]:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(lead: Lead) -> OutreachDraft | None:
        async with sem:
            try:
                person = lead.stakeholders[0] if lead.stakeholders else None
                return await draft_one(llm, lead, person)
            except Exception:
                return None

    return await asyncio.gather(*(one(l) for l in leads))
