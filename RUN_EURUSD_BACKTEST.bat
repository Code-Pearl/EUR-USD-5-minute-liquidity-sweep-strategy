@echo off
title EURUSD Liquidity Sweep Backtest
cd /d "%~dp0"
echo ==========================================
echo EURUSD 5-minute Liquidity Sweep Backtest
echo ==========================================
echo.
py -3 "%~dp0eurusd_liquidity_backtest.py"
if errorlevel 1 (
  echo.
  echo Backtest stopped with an error. See message above.
)
echo.
pause
