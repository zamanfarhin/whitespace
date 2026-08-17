"""
The fetch layer.

Every adapter goes through this instead of calling httpx directly, which
buys three things that matter for a pipeline meant to be rerun:

  1. A disk cache keyed on the URL. The second run of the pipeline costs
     nothing and takes seconds, which is what makes iterating on the
     scoring rubric tolerable.
  2. Per-host rate limiting, so we don't hammer a trade show's server.
  3. Retries with backoff on the failures worth retrying, and immediate
     give-up on the ones that aren't. A 404 will still be a 404 in four
     seconds.

Failures are recorded, not raised. One dead exhibitor page should cost us
one event, not the whole run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

CACHE_DIR = Path(".cache/http")
DEFAULT_TIMEOUT = 25.0
RETRY_ON = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4

USER_AGENT = (
    "TedlarLeadBot/0.1 (case study prototype; contact via repo README)"
)


@dataclass
class Response:
    url: str
    status: int
    text: str
    from_cache: bool = False
    content: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> object | None:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return None


@dataclass
class FetchFailure:
    url: str
    status: int | None
    reason: str


class RateLimiter:
    """One token bucket per host. Cheap, and enough for this scale."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str, per_sec: float) -> None:
        if per_sec <= 0:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        gap = 1.0 / per_sec
        async with lock:
            elapsed = time.monotonic() - self._last.get(host, 0.0)
            if elapsed < gap:
                await asyncio.sleep(gap - elapsed)
            self._last[host] = time.monotonic()


@dataclass
class Fetcher:
    cache_dir: Path = CACHE_DIR
    use_cache: bool = True
    concurrency: int = 6
    failures: list[FetchFailure] = field(default_factory=list)
    cache_hits: int = 0
    network_calls: int = 0

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._limiter = RateLimiter()
        self._sem = asyncio.Semaphore(self.concurrency)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Fetcher:
        self._client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        host = urlparse(url).netloc.replace(":", "_") or "unknown"
        return self.cache_dir / host / f"{digest}.json"

    def _read_cache(self, url: str) -> Response | None:
        path = self._cache_path(url)
        if not (self.use_cache and path.exists()):
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt cache entry should be a miss, not a crash.
            return None
        raw = path.with_suffix(".bin")
        return Response(
            url=url, status=blob["status"], text=blob["text"], from_cache=True,
            content=raw.read_bytes() if raw.exists() else b"",
        )

    def _write_cache(self, resp: Response) -> None:
        path = self._cache_path(resp.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"url": resp.url, "status": resp.status, "text": resp.text}
        path.write_text(json.dumps(payload), encoding="utf-8")
        # Binary bodies (the PDF exports) live beside the metadata rather
        # than getting base64'd into it.
        if resp.content:
            path.with_suffix(".bin").write_bytes(resp.content)

    async def get(
        self,
        url: str,
        *,
        rate_limit: float = 2.0,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        binary: bool = False,
    ) -> Response | None:
        """
        Fetch a URL. Returns None on permanent failure and records why.

        Callers check for None. Nothing here raises, because a single bad
        page inside a 400-company crawl is expected, not exceptional.
        """
        full = str(httpx.URL(url, params=params)) if params else url

        cached = self._read_cache(full)
        if cached is not None:
            self.cache_hits += 1
            return cached

        assert self._client is not None, "use Fetcher inside an async with block"
        host = urlparse(full).netloc

        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._limiter.wait(host, rate_limit)
            async with self._sem:
                try:
                    self.network_calls += 1
                    raw = await self._client.get(full, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt == MAX_ATTEMPTS:
                        self.failures.append(FetchFailure(full, None, type(exc).__name__))
                        return None
                    await self._backoff(attempt)
                    continue

            if raw.status_code in RETRY_ON and attempt < MAX_ATTEMPTS:
                # Honour Retry-After when the server bothers to send one.
                await self._backoff(attempt, raw.headers.get("Retry-After"))
                continue

            resp = Response(
                url=full, status=raw.status_code,
                text="" if binary else raw.text,
                content=raw.content if binary else b"",
            )
            if resp.ok:
                self._write_cache(resp)
                return resp

            self.failures.append(FetchFailure(full, raw.status_code, "http error"))
            return None

        return None

    @staticmethod
    async def _backoff(attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                await asyncio.sleep(min(float(retry_after), 30.0))
                return
            except ValueError:
                pass
        # Jitter matters here: several adapters hit the same host at once
        # and lockstep retries just recreate the burst that caused the 429.
        delay = min(2 ** (attempt - 1), 8) * (0.6 + random.random() * 0.8)
        await asyncio.sleep(delay)
