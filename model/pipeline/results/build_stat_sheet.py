"""
build_stat_sheet.py — Full 94-ticker stat sheet for all completed backtest results.
Outputs: v4_stat_sheet_full.csv  +  console summary
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from scipy import stats
from pathlib import Path

results_dir = Path('model/pipeline/results')

# All tickers with predictions
tickers = [
    'AAPL','ABBV','ABT','ADBE','AEP','AMAT','AMD','AMGN','AMT','AMZN',
    'APD','AVGO','AXP','BA','BAC','BLK','BMY','C','CAT','CCI',
    'CL','CMCSA','COP','COST','CRM','CSCO','CVS','CVX','D','DE',
    'DIS','DOW','DUK','EOG','EQIX','F','FCX','FDX','GE','GILD',
    'GM','GOOGL','GS','HD','HON','IBM','INTC','JNJ','JPM','KO',
    'LIN','LLY','LMT','LOW','MCD','META','MMM','MO','MRK','MS',
    'MSFT','MU','NEE','NEM','NFLX','NKE','NOC','NVDA','ORCL','OXY',
    'PEP','PFE','PG','PLD','PM','QCOM','RTX','SBUX','SCHW','SLB',
    'SO','SPG','T','TGT','TMO','TSLA','TXN','UNH','UPS','USB',
    'VZ','WFC','WMT','XOM',
]

# Corporate action flags (for annotation)
flagged = {'GE': 'breakup', 'META': 'ticker<2013', 'RTX': 'merger2020', 'GOOGL': 'class-split2014'}

sectors = {
    'AAPL':'Tech','MSFT':'Tech','NVDA':'Tech','AVGO':'Tech','TXN':'Tech',
    'INTC':'Tech','QCOM':'Tech','IBM':'Tech','ADBE':'Tech','CRM':'Tech',
    'AMAT':'Tech','AMD':'Tech','ORCL':'Tech','CSCO':'Tech',
    'AMZN':'Consumer Disc','HD':'Consumer Disc','NKE':'Consumer Disc','TSLA':'Consumer Disc',
    'LOW':'Consumer Disc','TGT':'Consumer Disc',
    'DIS':'Comm','NFLX':'Comm','CMCSA':'Comm','T':'Comm','GOOGL':'Comm',
    'META':'Comm','VZ':'Comm',
    'JPM':'Financials','GS':'Financials','MS':'Financials','BAC':'Financials',
    'WFC':'Financials','C':'Financials','SCHW':'Financials','AXP':'Financials',
    'BLK':'Financials','USB':'Financials','SPG':'REIT','PLD':'REIT',
    'XOM':'Energy','CVX':'Energy','COP':'Energy','EOG':'Energy','SLB':'Energy',
    'OXY':'Energy','CCI':'Energy',
    'JNJ':'Health Care','UNH':'Health Care','LLY':'Health Care','MRK':'Health Care',
    'ABT':'Health Care','GILD':'Health Care','BMY':'Health Care','PFE':'Health Care',
    'ABBV':'Health Care','TMO':'Health Care','AMGN':'Health Care','CVS':'Health Care',
    'PG':'Staples','KO':'Staples','PEP':'Staples','WMT':'Staples','COST':'Staples',
    'PM':'Staples','MCD':'Staples','SBUX':'Staples','MO':'Staples','CL':'Staples',
    'NEE':'Utilities','DUK':'Utilities','D':'Utilities','SO':'Utilities','AEP':'Utilities',
    'CAT':'Industrials','HON':'Industrials','GE':'Industrials','LMT':'Industrials',
    'DE':'Industrials','MMM':'Industrials','FDX':'Industrials','BA':'Industrials',
    'NOC':'Industrials','UPS':'Industrials','RTX':'Industrials',
    'NEM':'Materials','FCX':'Materials','APD':'Materials','LIN':'Materials',
    'DOW':'Materials',
    'AMT':'REIT','EQIX':'REIT','CCI':'REIT',
}

def qlike(y_true, y_pred):
    """QLIKE loss: mean(y_pred/y_true - log(y_pred/y_true) - 1)"""
    ratio = y_pred / y_true
    return np.mean(ratio - np.log(ratio) - 1)

rows = []
for t in tickers:
    for h in [21, 63, 126]:
        fpath = results_dir / f'predictions_{t}_H{h}.csv'
        if not fpath.exists():
            continue
        try:
            df = pd.read_csv(fpath).dropna(subset=['y_true', 'y_pred'])
            df = df.sort_values('date')
            if len(df) < 100:
                continue

            y_true = df['y_true'].values
            y_pred = df['y_pred'].values

            # MZ regression: y_true = alpha + beta * y_pred
            sl, ic, r, p, se = stats.linregress(y_pred, y_true)

            rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
            mae  = np.mean(np.abs(y_true - y_pred))
            r2   = r ** 2

            # QLIKE in log-vol space (predictions are log-vol)
            ql = qlike(np.exp(y_true), np.exp(y_pred))

            # Hit rate: sign of (y_true - prev_y_true) == sign of (y_pred - prev_y_pred)
            if len(df) > 1:
                dy_true = np.diff(y_true)
                dy_pred = np.diff(y_pred)
                hit_rate = np.mean(np.sign(dy_true) == np.sign(dy_pred))
            else:
                hit_rate = np.nan

            n_obs = len(df)
            flag = flagged.get(t, '')

            rows.append({
                'ticker': t,
                'sector': sectors.get(t, 'Other'),
                'horizon': h,
                'alpha': round(ic, 5),
                'beta': round(sl, 4),
                'r2': round(r2, 4),
                'rmse': round(rmse, 6),
                'mae': round(mae, 6),
                'qlike': round(ql, 6),
                'hit_rate': round(hit_rate, 4),
                'n_obs': n_obs,
                'flag': flag,
            })
        except Exception as e:
            print(f'  [WARN] {t} H{h}: {e}')

df_out = pd.DataFrame(rows)
df_out.to_csv(results_dir / 'v4_stat_sheet_full.csv', index=False)
print(f'Saved {len(df_out)} rows to v4_stat_sheet_full.csv')

# ── Summary by horizon ──────────────────────────────────────────────────────
print()
print('=' * 95)
print('FULL PORTFOLIO SUMMARY  (94 tickers, v4 backtest)')
print('=' * 95)

for h in [21, 63, 126]:
    sub = df_out[(df_out.horizon == h) & (df_out.flag == '')]
    sub_all = df_out[df_out.horizon == h]
    well_cal = ((sub.beta >= 0.85) & (sub.beta <= 1.15)).sum()
    print(f'\nH={h:3d}  ({len(sub)} clean tickers, {len(sub_all)} total)')
    print(f'  Beta  : mean={sub.beta.mean():.3f}  median={sub.beta.median():.3f}  std={sub.beta.std():.3f}  '
          f'in [0.85,1.15]={well_cal}/{len(sub)} ({well_cal/len(sub)*100:.0f}%)')
    print(f'  Alpha : mean={sub.alpha.mean():.4f}  median={sub.alpha.median():.4f}')
    print(f'  R2    : mean={sub.r2.mean():.3f}  median={sub.r2.median():.3f}  '
          f'min={sub.r2.min():.3f}  max={sub.r2.max():.3f}')
    print(f'  RMSE  : mean={sub.rmse.mean():.5f}  median={sub.rmse.median():.5f}')
    print(f'  QLIKE : mean={sub.qlike.mean():.5f}  median={sub.qlike.median():.5f}')
    print(f'  HitRt : mean={sub.hit_rate.mean():.3f}  median={sub.hit_rate.median():.3f}')

# ── By sector (H=21 clean only) ─────────────────────────────────────────────
print()
print('=' * 95)
print('SECTOR SUMMARY  H=21 (clean tickers only)')
print('=' * 95)
print(f'{"Sector":<18} {"N":>3}  {"Beta_mean":>10}  {"Beta_med":>9}  {"R2_mean":>8}  {"Well-cal":>10}')
print('-' * 95)
sub21 = df_out[(df_out.horizon == 21) & (df_out.flag == '')]
for sect in sorted(sub21.sector.unique()):
    s = sub21[sub21.sector == sect]
    wc = ((s.beta >= 0.85) & (s.beta <= 1.15)).sum()
    print(f'{sect:<18} {len(s):>3}  {s.beta.mean():>10.3f}  {s.beta.median():>9.3f}  '
          f'{s.r2.mean():>8.3f}  {wc}/{len(s)} ({wc/len(s)*100:.0f}%)')

# ── Full per-ticker table ────────────────────────────────────────────────────
print()
print('=' * 110)
print('PER-TICKER DETAIL  (sorted by sector, ticker)')
print('=' * 110)
print(f'{"Ticker":<7} {"Sector":<16} {"H":>4}  {"Alpha":>8}  {"Beta":>7}  {"R2":>6}  '
      f'{"RMSE":>8}  {"QLIKE":>8}  {"HitRt":>7}  {"N":>5}  {"Flag"}')
print('-' * 110)
for _, r in df_out.sort_values(['sector','ticker','horizon']).iterrows():
    flag_str = f'  [{r.flag}]' if r.flag else ''
    print(f'{r.ticker:<7} {r.sector:<16} {r.horizon:>4}  {r.alpha:>8.4f}  {r.beta:>7.4f}  '
          f'{r.r2:>6.3f}  {r.rmse:>8.5f}  {r.qlike:>8.5f}  {r.hit_rate:>7.3f}  {r.n_obs:>5}{flag_str}')
