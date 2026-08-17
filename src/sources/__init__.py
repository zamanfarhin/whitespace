"""Source adapters. Importing this module registers every adapter."""

from .base import SourceAdapter, build, canonical_name, merge, register  # noqa: F401
from . import fixtures, mapyourshow, messe_frankfurt  # noqa: F401

__all__ = ["SourceAdapter", "build", "canonical_name", "merge", "register"]
