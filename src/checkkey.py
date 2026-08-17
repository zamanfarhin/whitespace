"""
One cheap call to find out whether the API is usable before spending.

Exists because a run of 120 companies failed 240 times, cost nothing, and
reported no reason. Ten seconds of checking beats ten minutes of a
progress bar advancing toward zero results.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv  # noqa: E402

import anthropic  # noqa: E402
from llm import HAIKU  # noqa: E402


async def main() -> int:
    load_dotenv()
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("no ANTHROPIC_API_KEY found. is .env in the project root?")
        return 1
    print(f"key loaded: {key[:12]}...{key[-4:]} ({len(key)} chars)")

    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        resp = await client.messages.create(
            model=HAIKU, max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
    except anthropic.APIStatusError as exc:
        print(f"\nAPI returned HTTP {exc.status_code}")
        print(f"  {str(getattr(exc, 'message', '') or exc)[:300]}")
        return 1
    except Exception as exc:
        print(f"\n{type(exc).__name__}: {exc}")
        return 1

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    print(f"plain call works: {text!r} "
          f"({resp.usage.input_tokens} in, {resp.usage.output_tokens} out)")

    # Web search is billed separately from tokens and can be unavailable
    # even when plain calls succeed, so it gets its own check.
    try:
        resp = await client.messages.create(
            model=HAIKU, max_tokens=200,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
            messages=[{"role": "user",
                       "content": "Search for Arlon Graphics and name one product."}],
        )
    except anthropic.APIStatusError as exc:
        print(f"\nweb search failed: HTTP {exc.status_code}")
        print(f"  {str(getattr(exc, 'message', '') or exc)[:300]}")
        print("\n  the pipeline needs this tool. that is what to fix.")
        return 1

    used = any(b.type != "text" for b in resp.content)
    print(f"web search works: tool invoked = {used}")
    print("\nall good, run the pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
