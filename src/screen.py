"""
Cheap triage, run before anything that costs money.

Sourcing returns everyone who booked a booth. At PRINTING United that is
821 companies, and most of them sell printers, inks, software, or staffing
services. Enriching all of them would mean roughly 821 web lookups and 821
model calls to discover that most were never candidates.

So the name gets screened first. It is a weak signal on its own, which is
the point: this does not decide who qualifies, it decides who is worth
paying to look at. Three buckets:

  strong    name states an ICP-relevant product line -> enrich first
  excluded  name states a disqualifying category     -> skip, with a reason
  unknown   name says nothing either way             -> enrich if budget allows

`unknown` is the honest bucket and it is usually the biggest one. A company
called "Aberdeen Fabrics" is legible; one called "A4" is not, and pretending
otherwise would throw away real leads. Nothing is deleted here, only
ordered, and the exclusion reason travels with the record so a rep can see
why a company never got looked at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from models import Company

# Product vocabulary that maps to something a protective overlaminate goes
# on. Ordered roughly by how specific the term is.
POSITIVE = {
    3.0: (r"overlaminat", r"protective film", r"pressure.?sensitive",
          r"\bpvf\b", r"weatherab", r"\bwrap film"),
    2.0: (r"\bfilms?\b", r"\blaminat", r"\bvinyl\b", r"\bsubstrat",
          r"\badhesiv", r"\bcoating", r"graphic film"),
    1.5: (r"\bgraphics?\b", r"\bwraps?\b", r"\bawning", r"\bbanner",
          r"\bsignage\b", r"\bdisplay film"),
    1.0: (r"\bfabric", r"\btextile", r"\bmedia\b", r"\bpolymer",
          r"\bsigns?\b", r"\bcanvas\b", r"\bmesh\b"),
}

# Categories with no surface for a film. These are hard excludes rather
# than negative weights, because "we sell printers" is a different answer
# from "we might be small".
EXCLUDE = {
    "equipment": (r"\bprinters?\b", r"\bpress(es)?\b", r"\bcutters?\b",
                  r"\brouters?\b", r"\blaser\b", r"\bengrav", r"\bplotter",
                  r"\bmachin", r"\bequipment\b", r"\bCNC\b", r"\bembroider"),
    "consumable": (r"\binks?\b", r"\btoner", r"\bcartridge", r"\bdye\b"),
    "software": (r"\bsoftware\b", r"\bERP\b", r"\bSaaS\b", r"\bworkflow\b",
                 r"\bweb.?to.?print", r"\bRIP\b", r"\banalytics\b"),
    "electronics": (r"\bLED\b", r"\bdigital signage\b", r"\bscreens?\b",
                    r"\bmonitors?\b", r"\bkiosk", r"\bprojector"),
    "services": (r"\bBPO\b", r"\bstaffing\b", r"\brecruit", r"\bconsult",
                 r"\binsurance\b", r"\bfinanc", r"\blogistics\b",
                 r"\bshipping\b", r"\btravel\b"),
    "media_org": (r"\bassociation\b", r"\bmagazine\b", r"\bjournal\b",
                  r"\bpublish", r"\buniversity\b", r"\binstitute\b",
                  r"\bcouncil\b", r"\bsociety\b", r"\bmedia group\b",
                  r"\bnews\b", r"\bexpo\b", r"\bpavilion\b",
                  r"\balliance\b", r"\bfederation\b", r"\bguild\b",
                  r"\bchamber\b", r"\bconsortium\b"),
}

# Terms that flip an otherwise positive read. "Print Media Group" is a
# publisher; "Wide Format Media" is a manufacturer. Word order carries the
# meaning and a bag of keywords loses it.
AMBIGUOUS = (
    (re.compile(r"media (group|inc|llc)\b.*\b(publish|news)", re.I), "media_org"),
)


class Bucket(str, Enum):
    STRONG = "strong"
    UNKNOWN = "unknown"
    EXCLUDED = "excluded"


@dataclass
class Screened:
    company: Company
    bucket: Bucket
    signal: float = 0.0
    matched: list[str] = field(default_factory=list)
    reason: str | None = None

    @property
    def name(self) -> str:
        return self.company.name


def _hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    """Return the matched text, not the pattern. Reasons get read by humans."""
    out = []
    for pattern in patterns:
        found = re.search(pattern, text, re.I)
        if found:
            out.append(found.group(0))
    return out


def screen_one(company: Company) -> Screened:
    # Booth categories, when the source gave us any, are far better signal
    # than the company name. Most sources do not, hence the fallback.
    cats = " ".join(c for a in company.appearances for c in a.categories)
    text = f"{company.name} {cats}".strip()

    for category, patterns in EXCLUDE.items():
        found = _hits(text, patterns)
        if found:
            return Screened(company, Bucket.EXCLUDED, reason=f"{category}: {found[0]}")

    for pattern, category in AMBIGUOUS:
        if pattern.search(text):
            return Screened(company, Bucket.EXCLUDED, reason=f"{category}: ambiguous name")

    signal, matched = 0.0, []
    for weight, patterns in POSITIVE.items():
        found = _hits(text, patterns)
        if found:
            signal += weight * len(found)
            matched.extend(found)

    if signal >= 1.5:
        return Screened(company, Bucket.STRONG, signal, matched)
    return Screened(company, Bucket.UNKNOWN, signal, matched)


def screen_all(companies: list[Company]) -> list[Screened]:
    """
    Screen and order. Strong first by signal, then unknown, then excluded.

    Ordering matters more than the buckets do: the enrichment stage walks
    this list until it hits its budget, so a better sort directly means
    more qualified leads per dollar.
    """
    results = [screen_one(c) for c in companies]
    rank = {Bucket.STRONG: 0, Bucket.UNKNOWN: 1, Bucket.EXCLUDED: 2}
    results.sort(key=lambda s: (
        rank[s.bucket],
        -s.signal,
        # Within a bucket, companies seen at more than one show first.
        -len(s.company.appearances),
        s.name.lower(),
    ))
    return results


def budget(results: list[Screened], limit: int) -> list[Screened]:
    """Everything strong, then fill the remainder from unknown."""
    strong = [s for s in results if s.bucket is Bucket.STRONG]
    unknown = [s for s in results if s.bucket is Bucket.UNKNOWN]
    return (strong + unknown)[:limit] if limit > 0 else strong + unknown
