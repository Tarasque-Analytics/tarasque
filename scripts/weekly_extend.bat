@echo off
REM ============================================================================
REM  weekly_extend.bat — weekly WFA retrain + prediction extension
REM ============================================================================
REM  Uses 20-BD cadence (cadence_experiment --step-days 20) to retrain through
REM  the extension period — matches backtest WFA cadence, validated by Phase 2
REM  cadence experiments (2026-05-26) as the right production setting.
REM
REM  Pipeline order:
REM    1. refresh_data                — latest OHLCV / IV / FRED
REM    2. cadence_experiment step_20  — retrain every 20 BD across extension
REM    3. merge_cadence_to_canonical  — splice into per-ticker prediction files
REM    4. rebuild_aggregates          — stitch into all_predictions.csv
REM    5. mz_overlay                  — calibrated all_predictions_cal.csv
REM    6. export_for_webapp           — CSV bundle + full Supabase re-push
REM
REM  Runs Sunday 2 AM. ~3-4 hour total runtime (mostly step 2, the retrains).
REM ============================================================================

cd /d "%~dp0\.."

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set DT=%%I
set STAMP=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%
set LOGFILE=logs\weekly_extend_%STAMP%.log

if not exist logs mkdir logs

echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Tarasque weekly extend — %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

REM ── 1. Data refresh first so we have latest OHLCV ────────────────────────────
echo. >> "%LOGFILE%"
echo [STEP 1/6] refresh_data >> "%LOGFILE%"
python -u -m model.pipeline --mode refresh_data >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [WARN] refresh_data exited with errorlevel — continuing >> "%LOGFILE%"
)

REM ── 2. Cadence experiment: retrain every 20 BD across extension window ──────
REM Replaces the old single-retrain extend_predictions. Writes per-ticker
REM outputs to results/cadence_experiment/step_20/ — they get spliced into
REM canonical files in step 3. ~80% of weekly runtime is here.
echo. >> "%LOGFILE%"
echo [STEP 2/6] cadence_experiment (step_days=20, full corpus) >> "%LOGFILE%"
python -u -m model.pipeline.scripts.cadence_experiment --mode fixed --step-days 20 >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] cadence_experiment failed — aborting weekly run >> "%LOGFILE%"
    exit /b 1
)

REM ── 3. Splice cadence output into canonical per-ticker prediction files ─────
echo. >> "%LOGFILE%"
echo [STEP 3/6] merge_cadence_to_canonical >> "%LOGFILE%"
python -u -m model.pipeline.scripts.merge_cadence_to_canonical --step-days 20 >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] merge_cadence_to_canonical failed — aborting weekly run >> "%LOGFILE%"
    exit /b 1
)

REM ── 4. Rebuild aggregates so all_predictions.csv reflects the new dates ─────
echo. >> "%LOGFILE%"
echo [STEP 4/6] rebuild_aggregates >> "%LOGFILE%"
python -u -m model.pipeline.scripts.rebuild_aggregates >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] rebuild_aggregates failed — aborting weekly run >> "%LOGFILE%"
    exit /b 1
)

REM ── 5. Re-run MZ overlay so the calibration is current ─────────────────────
echo. >> "%LOGFILE%"
echo [STEP 5/6] mz_overlay >> "%LOGFILE%"
python -u -m model.pipeline.analysis.mz_overlay >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] mz_overlay failed — aborting weekly run >> "%LOGFILE%"
    exit /b 1
)

REM ── 6. Final webapp export (full Supabase push — NOT append-only) ──────────
REM Weekly does a full re-push (idempotent UPSERT) so y_true backfills on
REM stale rows make it to the DB. Daily uses --append-only; weekly does not.
echo. >> "%LOGFILE%"
echo [STEP 6/6] export_for_webapp --all --push-to-supabase >> "%LOGFILE%" 2>&1
python -u -m model.pipeline.export_for_webapp --all --push-to-supabase >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [WARN] export_for_webapp exited with errorlevel >> "%LOGFILE%"
)

echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Weekly extend complete — %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
