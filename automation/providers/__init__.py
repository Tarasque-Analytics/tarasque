"""
automation.providers — external service adapters behind narrow interfaces.

  market_data — MarketDataProvider protocol + AlpacaProvider (stock bars + options chain). PLAN §4.3, §5.
  llm         — LLMProvider protocol + ClaudeProvider + a registry, so AI overviews are
                model/provider-agnostic. PLAN §8.

Keeping vendor SDKs behind these adapters means rate-limit/backoff (market data) and prompt/workflow
specifics (LLM) live in one place, and swapping a provider is a registry/config change.
"""
