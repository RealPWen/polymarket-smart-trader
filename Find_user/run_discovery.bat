@echo off
title Polymarket Smart Trader Discovery
echoStrings
echo ========================================================
echo       Polymarket Smart Trader Discovery System
echo ========================================================
echo.

echo [1/3] Setting up environment...
cd /d "%~dp0"

echo [2/3] Starting Pipeline (Fast Mode)...
echo       - Fetching Top 1000 Traders (OVERALL / ALL)
echo       - Analyzing candidates...
echo.

python run_pipeline.py --max-traders 1000 --preset default

echo.
echo [3/3] Done! Results are in the 'output' folder.
echo.
pause
