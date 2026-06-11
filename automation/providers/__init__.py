"""
automation.providers — external data-source adapters behind narrow interfaces.

  options_provider — OptionsProvider protocol + YFinanceOptionsProvider (options chain → options_chain).

Keeping the vendor SDK behind an adapter means rate-limit/backoff and row-shaping live in one place,
and swapping the source (e.g. yfinance → Polygon/Tradier) is a config change.
"""
