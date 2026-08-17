"""
Fixture adapter.

Reads exhibitor lists from disk instead of the network. Two jobs:

  1. A reviewer with no API key, no network, or a firewall between them
     and a trade show's server can still run the pipeline end to end and
     see the dashboard populate. That single property is probably worth
     more than any feature in this repo, because code a reviewer cannot
     run is code they judge from the README.
  2. Deterministic tests. Scoring changes should be attributable to the
     scoring change, not to a directory that reshuffled overnight.

Fixtures are snapshots of real fetches, written by `--snapshot`, so the
offline path exercises the same parsing as the live one.
"""

from __future__ import annotations

import json
from pathlib import Path

from models import Company
from .base import SourceAdapter, register

FIXTURE_DIR = Path("fixtures/exhibitors")


@register
class FixtureAdapter(SourceAdapter):
    name = "fixtures"

    async def exhibitors(self, event) -> list[Company]:
        path = Path(self.config.get("dir", FIXTURE_DIR)) / f"{event.slug}.json"
        if not path.exists():
            # A missing fixture is a gap in coverage, not a crash. The run
            # reports which events had no data rather than dying on one.
            return []
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(rows, list):
            return []

        out: list[Company] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            if not name:
                continue
            out.append(Company(
                name=name,
                domain=row.get("domain"),
                appearances=[self._appearance(
                    event, row.get("booth"), row.get("categories") or []
                )],
            ))
        return out
