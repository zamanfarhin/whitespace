"""
The model client.

Everything that costs money goes through here, for three reasons:

  1. A running cost ledger. The results section of the writeup needs a real
     number for cost per qualified lead, and that number has to come from
     counted tokens rather than an estimate made afterwards.
  2. One place that knows how to get JSON out of a model reliably. Models
     wrap JSON in prose and fences given the chance; the prompt discourages
     it and the parser assumes it happened anyway.
  3. Retries on the failures worth retrying. Overload and rate limit
     responses are transient. A malformed request is not.

Model choice is per call site, not global. Cheap extraction runs on Haiku,
judgement runs on Sonnet, and mixing them deliberately is most of why this
pipeline costs single-digit dollars instead of triple.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5"

# USD per million tokens, (input, output). Kept here so the ledger reports
# real money rather than token counts nobody can interpret.
PRICES = {
    HAIKU: (1.00, 5.00),
    SONNET: (3.00, 15.00),
}

MAX_ATTEMPTS = 4
FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)

CACHE_DIR = Path(".cache/llm")


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    """Raised when a run hits its spend ceiling. Stops work immediately."""


@dataclass
class Ledger:
    calls: int = 0
    failures: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    by_stage: dict[str, float] = field(default_factory=dict)
    #: Why calls failed, counted by reason. An earlier version recorded
    #: only that 240 calls had failed, which is the least useful possible
    #: thing to know at the moment a run collapses.
    errors: dict[str, int] = field(default_factory=dict)

    def note_error(self, reason: str) -> None:
        self.failures += 1
        key = reason[:90]
        self.errors[key] = self.errors.get(key, 0) + 1

    def record(self, model: str, stage: str, tokens_in: int, tokens_out: int) -> None:
        rate_in, rate_out = PRICES.get(model, (0.0, 0.0))
        spend = (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000
        self.calls += 1
        self.input_tokens += tokens_in
        self.output_tokens += tokens_out
        self.cost_usd += spend
        self.by_stage[stage] = round(self.by_stage.get(stage, 0.0) + spend, 6)

    def summary(self) -> str:
        parts = ", ".join(f"{k} ${v:.3f}" for k, v in sorted(self.by_stage.items()))
        cached = f", {self.cache_hits} from cache" if self.cache_hits else ""
        line = (f"{self.calls} calls{cached}, {self.failures} failed, "
                f"${self.cost_usd:.3f} total ({parts})")
        if self.errors:
            top = sorted(self.errors.items(), key=lambda kv: -kv[1])[:3]
            line += "\n  failure reasons: " + "; ".join(f"{k} (x{v})" for k, v in top)
        return line


class LLM:
    """
    Client with a response cache on disk.

    The cache is not an optimisation, it is the difference between an
    afternoon of iteration costing four dollars and costing forty. Every
    stage after enrichment reads the same companies, and every bug fix
    means running the pipeline again; without this, each rerun repays for
    work already done. Learned by paying for a run of 120 enrichments that
    died on the last step and returned nothing.

    Keyed on everything that could change the answer: model, system prompt,
    user prompt, and tool config. Change a prompt and the cache misses,
    which is correct. Delete .cache/llm to force fresh results.
    """

    def __init__(self, ledger: Ledger | None = None, use_cache: bool = True,
                 max_spend: float = 0.0) -> None:
        self.use_cache = use_cache
        #: Hard ceiling in USD for this process. Checked before every call,
        #: so the worst case is one call's overshoot rather than a run that
        #: keeps going until the balance is gone.
        self.max_spend = max_spend
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env, "
                "paste your key, and make sure python-dotenv loaded it."
            )
        self.client = anthropic.AsyncAnthropic(api_key=key)
        self.ledger = ledger or Ledger()

    async def json_call(
        self,
        *,
        stage: str,
        prompt: str,
        system: str,
        model: str = HAIKU,
        max_tokens: int = 2000,
        tools: list[dict] | None = None,
        retry_on_garbage: bool = True,
    ) -> object | None:
        """
        Ask for JSON and get JSON back, or None.

        Returns None rather than raising: one company whose response came
        back malformed should cost that company, not the run. The caller
        records the gap.

        A response that arrives fine but will not parse gets one more try.
        That is usually a truncated object rather than a broken prompt, and
        one extra cheap call is worth more than losing a good company.
        """
        key = self._cache_key(model, system, prompt, tools)
        parsed = await self._json_once(stage, prompt, system, model, max_tokens, tools)
        if parsed is not None:
            return parsed

        self._invalidate(key)
        if not retry_on_garbage:
            return None

        retry_prompt = prompt + "\n\nReturn only the JSON object, nothing else. Keep every rationale under 15 words so the object fits."
        parsed = await self._json_once(stage, retry_prompt, system, model,
                                       max_tokens, tools)
        if parsed is None:
            self._invalidate(self._cache_key(model, system, retry_prompt, tools))
        return parsed

    async def _json_once(self, stage, prompt, system, model, max_tokens, tools):
        text = await self._call(stage=stage, prompt=prompt, system=system,
                                model=model, max_tokens=max_tokens, tools=tools)
        if text is None:
            return None

        cleaned = FENCE.sub("", text.strip())
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Models sometimes prepend a sentence before the object. Take the
        # outermost bracketed span and try once more before giving up.
        start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1),
                    default=-1)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if start == -1 or end <= start:
            self.ledger.note_error("response had no JSON in it")
            return None
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            self.ledger.note_error("JSON present but malformed")
            return None

    @staticmethod
    def _fatal(detail: str) -> bool:
        """
        Some 400s mean every subsequent call will fail the same way.

        Running out of credit is the obvious one: retrying 119 more times
        wastes minutes to learn what the first response already said. Stop
        the run and tell the user, rather than reporting 240 anonymous
        failures at the end.
        """
        low = detail.lower()
        return any(t in low for t in
                   ("credit balance", "billing", "quota", "insufficient",
                    "not allowed", "permission", "disabled"))

    @staticmethod
    def _cache_key(model: str, system: str, prompt: str,
                   tools: list[dict] | None) -> str:
        blob = json.dumps([model, system, prompt, tools or []], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def _read_cache(self, key: str) -> str | None:
        path = CACHE_DIR / f"{key}.json"
        if not (self.use_cache and path.exists()):
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["text"]
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def _invalidate(self, key: str) -> None:
        """
        Drop a cached response that turned out to be unusable.

        The cache sits below the JSON parser and cannot tell a good answer
        from a truncated one. Without this, a response that got cut off
        mid-object is cached and replays as garbage on every future run,
        so raising the token ceiling would fix nothing.
        """
        try:
            (CACHE_DIR / f"{key}.json").unlink(missing_ok=True)
        except OSError:
            pass

    def _write_cache(self, key: str, text: str) -> None:
        try:
            (CACHE_DIR / f"{key}.json").write_text(
                json.dumps({"text": text}), encoding="utf-8")
        except OSError:
            pass

    async def _call(
        self, *, stage: str, prompt: str, system: str, model: str,
        max_tokens: int, tools: list[dict] | None,
    ) -> str | None:
        key = self._cache_key(model, system, prompt, tools)
        hit = self._read_cache(key)
        if hit is not None:
            self.ledger.cache_hits += 1
            return hit

        # Checked here rather than in the caller: this is the only line in
        # the codebase that can spend money.
        if self.max_spend and self.ledger.cost_usd >= self.max_spend:
            raise BudgetExceeded(
                f"stopped at ${self.ledger.cost_usd:.2f}, ceiling was "
                f"${self.max_spend:.2f}. work already done is cached and free "
                f"to replay; raise --max-spend to continue.")

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            kwargs["tools"] = tools

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await self.client.messages.create(**kwargs)
            except (anthropic.RateLimitError, anthropic.InternalServerError,
                    anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
                if attempt == MAX_ATTEMPTS:
                    self.ledger.note_error(f"{type(exc).__name__} after "
                                           f"{MAX_ATTEMPTS} attempts")
                    return None
                await asyncio.sleep(min(2 ** (attempt - 1), 16) * (0.6 + random.random()))
                continue
            except anthropic.APIStatusError as exc:
                # 400s do not get better on retry. Fail this one and move on,
                # but say what the API actually objected to.
                if exc.status_code == 401:
                    raise LLMError("API key rejected. Check ANTHROPIC_API_KEY in .env.")
                detail = str(getattr(exc, "message", "") or exc)[:120]
                if exc.status_code in (400, 402, 403) and self._fatal(detail):
                    raise LLMError(f"API returned {exc.status_code}: {detail}")
                self.ledger.note_error(f"HTTP {exc.status_code}: {detail}")
                return None
            except Exception as exc:
                self.ledger.note_error(f"{type(exc).__name__}: {exc}"[:90])
                return None

            usage = resp.usage
            self.ledger.record(model, stage, usage.input_tokens, usage.output_tokens)

            # With tools enabled the reply is a mix of blocks; only the text
            # ones carry the answer.
            text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            if text:
                self._write_cache(key, text)
            return text

        return None
