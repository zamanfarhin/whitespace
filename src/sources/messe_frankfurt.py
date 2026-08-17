"""
Messe Frankfurt adapter.

Covers the five Media Expo editions in India, and in principle any other
Messe Frankfurt fair, since they run one exhibitor-search product across
their portfolio. Same property that makes the MapYourShow adapter worth
writing: one file, many events.

Their search page is server-rendered enough to parse but paginates through
a query parameter, and the markup differs slightly between fair skins. So
this leans on structure that is stable across skins (links into the
exhibitor detail path) rather than on class names, which are not.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from models import Company
from .base import SourceAdapter, looks_like_exhibitors, register

DETAIL_HREF = re.compile(r"/exhibitor-search[^\"']*?/[\w\-]+\.html$", re.I)
FALLBACK_HREF = re.compile(r"/(exhibitor|aussteller)[\w\-/]*\.html$", re.I)
MAX_PAGES = 30
BOOTH = re.compile(r"\b(?:hall|booth|stand)\s*[:\-]?\s*([\w\.\-/]+)", re.I)


@register
class MesseFrankfurtAdapter(SourceAdapter):
    name = "messe_frankfurt"

    async def exhibitors(self, event) -> list[Company]:
        if not event.directory_url:
            return []
        base = str(event.directory_url.value)
        seen: set[str] = set()
        out: list[Company] = []

        for page in range(1, MAX_PAGES + 1):
            params = {"page": str(page)} if page > 1 else None
            resp = await self.fetcher.get(base, rate_limit=self.rate_limit, params=params)
            if resp is None:
                break

            batch = self._parse(resp.text, base, event, seen)
            if not batch:
                # Either we ran off the end of the results or the markup
                # changed. Either way there is nothing more to gain here.
                break
            out.extend(batch)

        # Messe Frankfurt renders its exhibitor search client-side, so this
        # path currently returns the site menu rather than companies. The
        # gate catches that and reports a coverage gap instead of letting
        # navigation links into the dataset.
        reason = looks_like_exhibitors(out)
        if reason:
            self.last_gap = reason
            return []
        return out

    def _parse(self, html: str, base: str, event, seen: set[str]) -> list[Company]:
        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(base).netloc

        links = soup.find_all("a", href=DETAIL_HREF)
        if not links:
            links = [
                a for a in soup.find_all("a", href=FALLBACK_HREF)
                if a.get_text(strip=True)
            ]

        out: list[Company] = []
        for link in links:
            name = link.get_text(" ", strip=True)
            if not name or len(name) > 120:
                continue

            href = urljoin(base, link["href"])
            # Only follow links that stay on this fair's own domain.
            if urlparse(href).netloc != host or href in seen:
                continue
            seen.add(href)

            booth = None
            parent = link.find_parent(["li", "article", "tr", "div"])
            if parent is not None:
                match = BOOTH.search(parent.get_text(" ", strip=True))
                if match:
                    booth = match.group(1)

            out.append(Company(
                name=name,
                appearances=[self._appearance(event, booth)],
            ))
        return out
