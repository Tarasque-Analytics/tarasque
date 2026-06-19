"""
edgar_xbrl.py — SEC EDGAR XBRL Company Facts API client.

The SEC publishes every filer's full XBRL fact history at one endpoint per CIK:
    https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit-zero-padded}.json

One call returns every tag the company ever filed across every period — a JSON
blob ~1-10 MB per firm. We pull it once per firm, cache to disk, and refresh
only when new filings land (typically quarterly).

SEC requirements:
  - User-Agent header MUST be set with org + contact email
  - Rate limit: SEC asks for <=10 requests/second sustained
  - No auth, no API key

We pull at ~5 req/sec to stay comfortably under the ceiling.

Cache layout:
  data_cache/sec_xbrl/CIK<10-digit>.json   raw API response, per company
  data_cache/sec_xbrl/_meta.json           {cik: {last_fetched, n_facts}}

Cache hygiene:
  - cached_get(cik) returns the cached blob if fresh (default: <24h old)
  - force=True re-fetches and overwrites
  - refresh_if_stale(cik, days=1) is the daily-refresh entry point
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import requests
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = REPO_ROOT / 'data_cache' / 'sec_xbrl'
META_PATH = CACHE_DIR / '_meta.json'

# SEC's stated ceiling is 10 req/s; we throttle to 5 to be safe + leave room
# for concurrent pulls from other pipelines.
MIN_INTERVAL_SECONDS = 0.2

# Default cache TTL: 24 hours. XBRL data only changes when a new filing lands,
# which is at most ~quarterly per firm, but we refresh daily to catch 8-K
# amendments / restatements promptly.
DEFAULT_CACHE_TTL_HOURS = 24

# Default User-Agent. SEC blocks requests without one. Override via env:
#   SEC_USER_AGENT="Volarbear Analytics <email>"
DEFAULT_UA = 'Tarasque Research leoharrisondipietro@gmail.com'


_ENV_PATH = REPO_ROOT / 'model' / '.env'
load_dotenv(dotenv_path=_ENV_PATH)


class EdgarXbrlError(RuntimeError):
    """Raised on non-recoverable API or cache errors."""


class EdgarXbrlClient:
    """Rate-limited cached client for SEC EDGAR Company Facts.

    Usage:
        client = EdgarXbrlClient()
        facts = client.company_facts(cik=93410)   # CVX
        # → dict with structure {'cik': ..., 'entityName': ..., 'facts': {...}}
    """

    BASE_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'

    def __init__(self, user_agent: Optional[str] = None,
                 cache_dir: Optional[Path] = None,
                 min_interval_seconds: float = MIN_INTERVAL_SECONDS):
        self.user_agent = user_agent or os.getenv('SEC_USER_AGENT', DEFAULT_UA)
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = float(min_interval_seconds)
        self._last_request_ts = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': self.user_agent,
            'Accept-Encoding': 'gzip, deflate',
        })

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    def _cache_path(self, cik: int) -> Path:
        return self.cache_dir / f'CIK{cik:010d}.json'

    def _is_fresh(self, path: Path, ttl_hours: float) -> bool:
        if not path.exists():
            return False
        age_sec = time.time() - path.stat().st_mtime
        return age_sec < ttl_hours * 3600

    def fetch(self, cik: int, max_retries: int = 3) -> Dict:
        """Hit the SEC API and return parsed JSON. Throttled + retried."""
        url = self.BASE_URL.format(cik=cik)
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            self._throttle()
            try:
                r = self._session.get(url, timeout=30)
                if r.status_code == 404:
                    raise EdgarXbrlError(f'CIK {cik}: no XBRL facts on EDGAR (404).')
                if r.status_code == 429:
                    # Rate-limited — back off harder
                    backoff = (attempt + 1) * 5.0
                    time.sleep(backoff)
                    last_exc = EdgarXbrlError(f'CIK {cik}: rate-limited (429).')
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as e:
                last_exc = e
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 2.0)
        raise EdgarXbrlError(f'CIK {cik}: fetch failed after {max_retries} attempts: {last_exc}')

    def cached_get(self, cik: int, force: bool = False,
                   ttl_hours: float = DEFAULT_CACHE_TTL_HOURS) -> Dict:
        """Return the company facts blob, from cache if fresh, else fetched."""
        path = self._cache_path(cik)
        if not force and self._is_fresh(path, ttl_hours):
            try:
                with path.open(encoding='utf-8') as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass  # cache corrupt; fall through to fetch
        blob = self.fetch(cik)
        # Write atomically
        tmp = path.with_suffix('.json.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(blob, f)
        tmp.replace(path)
        self._update_meta(cik, blob)
        return blob

    def refresh_if_stale(self, cik: int, days: float = 1.0) -> Dict:
        """Convenience for daily-refresh jobs: re-pull only if cache > `days` old."""
        return self.cached_get(cik, ttl_hours=days * 24)

    def _update_meta(self, cik: int, blob: Dict):
        meta = {}
        if META_PATH.exists():
            try:
                with META_PATH.open(encoding='utf-8') as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                meta = {}
        facts = blob.get('facts', {})
        n_facts = sum(len(t) for taxonomy in facts.values() for t in taxonomy.values())
        meta[str(cik)] = {
            'entity_name': blob.get('entityName'),
            'last_fetched': datetime.now(timezone.utc).isoformat(),
            'n_unique_tags': sum(len(taxonomy) for taxonomy in facts.values()),
            'n_facts_total': n_facts,
        }
        tmp = META_PATH.with_suffix('.json.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        tmp.replace(META_PATH)


def company_facts(cik: int, force: bool = False) -> Dict:
    """Module-level convenience: lazy singleton client, cached fetch."""
    global _CLIENT
    try:
        client = _CLIENT
    except NameError:
        client = None
    if client is None:
        client = EdgarXbrlClient()
        globals()['_CLIENT'] = client
    return client.cached_get(cik, force=force)


if __name__ == '__main__':
    # Smoke: pull CVX (CIK 93410) and report cache status.
    import sys
    cik = int(sys.argv[1]) if len(sys.argv) > 1 else 93410
    print(f'Fetching CIK {cik}...')
    client = EdgarXbrlClient()
    blob = client.cached_get(cik, force=False)
    print(f'  entity: {blob.get("entityName")}')
    facts = blob.get('facts', {})
    print(f'  taxonomies: {list(facts.keys())}')
    if 'us-gaap' in facts:
        print(f'  us-gaap tags: {len(facts["us-gaap"])}')
    if 'dei' in facts:
        print(f'  dei tags: {len(facts["dei"])}')
