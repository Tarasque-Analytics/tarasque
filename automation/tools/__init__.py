"""automation.tools — small standalone runners that reuse the pipeline's building blocks.

These exist to unblock/validate individual pieces without the full orchestrator. Each is a thin CLI
over the same core modules the pipeline stages use, so behavior matches what the scheduled run does.
"""
