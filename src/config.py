"""Loads config/events.yaml and config/icp.yaml into typed objects."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from models import Event, Method, Region, Source, Sourced

CONFIG_DIR = Path("config")


def _sourced_date(value, url: str | None) -> Sourced[date] | None:
    if value is None:
        return None
    return Sourced(value=value, source=Source(url=url, method=Method.ORGANIZER))


def load_events(path: Path | None = None) -> tuple[list[Event], dict]:
    blob = yaml.safe_load((path or CONFIG_DIR / "events.yaml").read_text(encoding="utf-8"))
    adapters = blob.get("adapters", {})

    events: list[Event] = []
    for raw in blob.get("events", []):
        url = raw.get("directory_url")
        event = Event(
            slug=raw["slug"],
            name=raw["name"],
            organizer=raw.get("organizer"),
            region=Region(raw["region"]),
            city=raw.get("city"),
            country=raw.get("country"),
            starts_on=_sourced_date(raw.get("starts_on"), url),
            ends_on=_sourced_date(raw.get("ends_on"), url),
            directory_url=(Sourced(value=url, source=Source(url=url, method=Method.ORGANIZER))
                           if url else None),
            adapter=raw["adapter"],
        )
        # Carried through for adapters that need it, not part of the model.
        object.__setattr__(event, "host", raw.get("host"))
        object.__setattr__(event, "weight_note", raw.get("weight_note"))
        events.append(event)
    return events, adapters


def load_icp(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_DIR / "icp.yaml").read_text(encoding="utf-8"))
