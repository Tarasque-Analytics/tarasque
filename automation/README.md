# automation

Data tooling for the tarasque DB — the only component that **writes** to Supabase (via a secret-key
client). Ships an options-chain import and a securities/universe sync; the broader nightly pipeline is
designed but not yet built.

**👉 Full context, design, decisions, and gotchas: [CLAUDE.md](CLAUDE.md).**

Quickstart (from the repo root):

```bash
pip install -r automation/requirements.txt
cp .env.example .env                                              # SUPABASE_URL + SUPABASE_SECRET_KEY

python -m automation.tools.fetch_options --tickers AAPL --dry-run # options chain (no DB writes)
python -m automation.tools.sync_sp500                             # preview S&P 500 securities sync
python -m pytest automation/tests                                 # tests
```
