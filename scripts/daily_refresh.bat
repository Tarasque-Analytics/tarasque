@echo off
REM ============================================================================
REM  daily_refresh.bat — nightly Tarasque refresh
REM ============================================================================
REM  Runs (in order):
REM    1. data refresh        (Alpaca OHLCV continuation + FRED)
REM    2. Alpaca vsurfd       (today's IV grid added to vsurfd parquet)
REM    3. daily_forecast      (predict today + SHAP + y_true backfill)
REM    4. rebuild_aggregates  (stitch per-ticker files → all_predictions.csv)
REM    5. mz_overlay          (calibrate → all_predictions_cal.csv)
REM    6. export_for_webapp   (CSV bundle + Supabase append-only push)
REM
REM  All output goes to logs\daily_YYYY-MM-DD.log so failures are debuggable.
REM
REM  To run manually: scripts\daily_refresh.bat
REM  Scheduled via:    scripts\register_daily_task.ps1
REM ============================================================================

cd /d "%~dp0\.."

REM Build a sortable date stamp (YYYY-MM-DD) regardless of locale
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set DT=%%I
set STAMP=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%
set LOGFILE=logs\daily_%STAMP%.log

if not exist logs mkdir logs

echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Tarasque daily refresh — %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

REM ── 1. Data refresh (Alpaca + FRED continuation) ─────────────────────────────
echo. >> "%LOGFILE%"
echo [STEP 1/4] refresh_data >> "%LOGFILE%"
python -u -m model.pipeline --mode refresh_data >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [WARN] refresh_data exited with errorlevel — continuing >> "%LOGFILE%"
)

REM ── 2. Alpaca vsurfd splice (today's IV grid) ────────────────────────────────
echo. >> "%LOGFILE%"
echo [STEP 2/4] fetch_alpaca_vsurfd >> "%LOGFILE%"
python -u -m model.pipeline.scripts.fetch_alpaca_vsurfd >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [WARN] fetch_alpaca_vsurfd exited with errorlevel — continuing >> "%LOGFILE%"
)

REM ── 3. Daily forecast (predict + SHAP for all 93 tickers) ────────────────────
echo. >> "%LOGFILE%"
echo [STEP 3/6] daily_forecast >> "%LOGFILE%"
python -u -m model.pipeline.daily_forecast --skip-refresh >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] daily_forecast failed — aborting daily run >> "%LOGFILE%"
    exit /b 1
)

REM ── 4. Rebuild aggregates so today's per-ticker rows land in all_predictions ─
REM Without this, the exporter reads stale all_predictions_cal.csv and the
REM new daily forecast row never reaches Supabase.
echo. >> "%LOGFILE%"
echo [STEP 4/6] rebuild_aggregates >> "%LOGFILE%"
python -u -m model.pipeline.scripts.rebuild_aggregates >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] rebuild_aggregates failed — aborting daily run >> "%LOGFILE%"
    exit /b 1
)

REM ── 5. MZ overlay → produces calibrated all_predictions_cal.csv ─────────────
echo. >> "%LOGFILE%"
echo [STEP 5/6] mz_overlay >> "%LOGFILE%"
python -u -m model.pipeline.analysis.mz_overlay >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] mz_overlay failed — aborting daily run >> "%LOGFILE%"
    exit /b 1
)

REM ── 6. Export to webapp bundle (CSV + Supabase push) ────────────────────────
echo. >> "%LOGFILE%"
echo [STEP 6/6] export_for_webapp >> "%LOGFILE%"
REM --append-only: only push rows newer than the latest date already in
REM volatility_history (per security). Cheap, idempotent. The weekly job
REM does a full --push-to-supabase (no append-only) to backfill y_true.
python -u -m model.pipeline.export_for_webapp --all --push-to-supabase --append-only >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [WARN] export_for_webapp exited with errorlevel >> "%LOGFILE%"
)

echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Daily refresh complete — %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
