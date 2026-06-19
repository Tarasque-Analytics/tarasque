"""Fundamentals — EDGAR XBRL ingest + RAFI divergence pipeline.

Builds a per-firm "economic footprint" composite (rev_ps + ocf_ps + book_ps +
dps, equal-weighted, indexed to a canonical base date) and the price/RAFI
divergence series that powers the Macro Economic-Footprint Valuation Layer.

Layers (each one a separate module):
  edgar_xbrl       — SEC Company Facts API client (rate-limited, retry, cache)
  xbrl_extract     — tag selection + ASC606 stitching + restatement handling
  ttm_smooth       — TTM construction (Q4 = FY − Q1+Q2+Q3) + 20Q smoothing
  composite        — canonical-base indexing + RAFI equal-weight composite
  divergence       — price-spine as-of join + divergence series + break flags

Source: EDGAR XBRL only. Coverage starts ~2009 (mandate). Canonical base date
for the composite is 2014-01-02 (5yr pre-history requirement against the
XBRL-mandate start of 2009).
"""
