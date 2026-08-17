"""
MapYourShow adapter.

Covers ISA Sign Expo and PRINTING United, and by extension the several
hundred other North American trade shows on the same platform.

Getting data out of MapYourShow is less obvious than it looks. Both the
exhibitor gallery and the alphabetical listing are Angular front ends: the
HTML that comes back is a template full of {{placeholders}} with no company
names in it at all. Scraping either one returns nothing, quietly.

What does work is the print export at
/8_0/exhibitor/exhibitor-list.cfm?export=pdf, which is server-rendered and
contains every exhibitor with its booth number. Verified against a show
with ~1,700 exhibitors. It is also the most stable route on offer, because
it exists for people who want to print the floor guide and therefore has no
reason to change when the front end gets rebuilt.

Three paths, tried in order:

  1. PDF export. Complete, server-rendered, stable.
  2. JSON search endpoint. Richer (product categories) but the parameter
     shape is undocumented and varies by show configuration.
  3. Alphabetical HTML listing. Almost certainly empty, kept because it
     costs one request and would start working if they ever server-render
     that page again.
"""

from __future__ import annotations

import io
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from models import Company
from .base import SourceAdapter, register

PDF_PATH = "/8_0/exhibitor/exhibitor-list.cfm"
JSON_PATH = "/8_0/ajax/remote-proxy.cfm"
ALPHA_PATH = "/8_0/explore/exhibitor-alphalist.cfm"
PAGE_SIZE = 100
MAX_PAGES = 40

EXHIBITOR_HREF = re.compile(r"/8_0/exhibitor/exhibitor-details\.cfm\?exhid=", re.I)

# Booth codes sit at the end of the line: "3M SU239". Alphanumeric with an
# optional hall-letter prefix. A company can hold several, and the export
# wraps long booth lists onto their own lines, sometimes leaving a trailing
# comma behind. Both halves of that have to be handled or the next
# company's name gets glued onto the previous one's.
BOOTH = r"(?:[A-Z]{0,3}\d{2,6})"
BOOTH_TAIL = re.compile(rf"\s+({BOOTH}(?:\s*,\s*{BOOTH})*)\s*,?\s*$")
BOOTH_ONLY = re.compile(rf"^{BOOTH}(?:\s*,\s*{BOOTH})*\s*,?\s*$")
HEADER = re.compile(r"^(exhibitor listing|.*\bas of\b\s*\d|name\s+booth)", re.I)


@register
class MapYourShowAdapter(SourceAdapter):
    name = "mapyourshow"

    async def exhibitors(self, event) -> list[Company]:
        host = self._host(event)
        if not host:
            return []

        for path in (self._via_pdf, self._via_json, self._via_alphalist):
            found = await path(event, host)
            if found:
                return found
        return []

    @staticmethod
    def _host(event) -> str | None:
        if getattr(event, "host", None):
            return event.host
        if event.directory_url:
            return urlparse(str(event.directory_url.value)).netloc or None
        return None

    async def _via_pdf(self, event, host: str) -> list[Company]:
        resp = await self.fetcher.get(
            f"https://{host}{PDF_PATH}",
            rate_limit=self.rate_limit,
            params={"export": "pdf"},
            binary=True,
        )
        if resp is None or not resp.content:
            return []
        text = self._pdf_text(resp.content)
        return self._parse_export(text, event) if text else []

    @staticmethod
    def _pdf_text(blob: bytes) -> str:
        try:
            import pdfplumber
        except ImportError:
            return ""
        try:
            with pdfplumber.open(io.BytesIO(blob)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            # A malformed PDF is a dead path, not a dead run. Fall through
            # to the JSON endpoint.
            return ""

    def _parse_export(self, text: str, event) -> list[Company]:
        """
        Turn "Company Name  BOOTH" lines into companies.

        Long names wrap, so a line with no booth code is either a
        continuation of the previous name or a page header. Continuations
        get stitched back on.
        """
        out: list[Company] = []
        pending = ""

        def emit(name: str, booth: str) -> None:
            if len(name.strip()) >= 2:
                out.append(Company(
                    name=name.strip(),
                    appearances=[self._appearance(event, booth or None)],
                ))

        for raw in text.splitlines():
            line = raw.strip()
            if not line or HEADER.match(line):
                pending = ""
                continue

            if BOOTH_ONLY.match(line):
                booth = re.sub(r"[\s,]+$", "", re.sub(r"\s+", "", line))
                if pending:
                    # Name was on its own line, booths follow beneath it.
                    emit(pending, booth)
                    pending = ""
                elif out and out[-1].appearances:
                    # Continuation of the previous company's booth list.
                    prev = out[-1].appearances[0]
                    prev.booth = f"{prev.booth},{booth}" if prev.booth else booth
                continue

            match = BOOTH_TAIL.search(line)
            if match is None:
                # Name wrapped. Hold it and wait for the rest.
                pending = f"{pending} {line}".strip()
                continue

            emit(pending + " " + line[: match.start()],
                 re.sub(r"[\s,]+$", "", re.sub(r"\s+", "", match.group(1))))
            pending = ""

        return out

    async def _via_json(self, event, host: str) -> list[Company]:
        out: list[Company] = []
        for page in range(1, MAX_PAGES + 1):
            resp = await self.fetcher.get(
                f"https://{host}{JSON_PATH}",
                rate_limit=self.rate_limit,
                params={"action": "search", "searchtype": "exhibitor",
                        "start": str((page - 1) * PAGE_SIZE), "rows": str(PAGE_SIZE)},
                headers={"X-Requested-With": "XMLHttpRequest",
                         "Accept": "application/json"},
            )
            if resp is None:
                break
            batch = self._parse_json(resp.json(), event)
            out.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return out

    def _parse_json(self, payload, event) -> list[Company]:
        """
        Walk the payload for anything name-shaped.

        Pinning an exact key path is how this breaks silently when a show
        ships a different config, so we search the tree instead.
        """
        if not isinstance(payload, (dict, list)):
            return []

        records: list[dict] = []

        def walk(node) -> None:
            if isinstance(node, dict):
                if any(k in node for k in ("exhname", "exhibitorName", "name")):
                    records.append(node)
                    return
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(payload)

        out = []
        for rec in records:
            name = (rec.get("exhname") or rec.get("exhibitorName")
                    or rec.get("name") or "").strip()
            if not name:
                continue
            cats = rec.get("categories") or rec.get("productcategories") or []
            if isinstance(cats, str):
                cats = [c.strip() for c in cats.split(",") if c.strip()]
            out.append(Company(
                name=name,
                domain=rec.get("website") or rec.get("exhurl") or None,
                appearances=[self._appearance(
                    event,
                    str(rec.get("boothnumber") or rec.get("booth") or "").strip() or None,
                    list(cats)[:12],
                )],
            ))
        return out

    async def _via_alphalist(self, event, host: str) -> list[Company]:
        resp = await self.fetcher.get(f"https://{host}{ALPHA_PATH}",
                                      rate_limit=self.rate_limit)
        if resp is None:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        out = []
        for link in soup.find_all("a", href=EXHIBITOR_HREF):
            name = link.get_text(strip=True)
            # The template row ships literal placeholder text.
            if not name or "EXHNAME" in name:
                continue
            out.append(Company(name=name, appearances=[self._appearance(event)]))
        return out
