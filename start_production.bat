@echo off
title Skantha WMS - Production Server
chcp 65001 > nul
cd /d "%~dp0"
cls
echo ======================================================================
echo  Launching Skantha WMS Enterprise Production Server (Waitress WSGI)
echo ======================================================================
echo.
rem Python 3.14 is the version this installation is tested with; fall back to any Python 3.
py -3.14 --version > nul 2>&1
if not errorlevel 1 (
    py -3.14 run_production.py
    goto :done
)
py -3 --version > nul 2>&1
if not errorlevel 1 (
    echo Python 3.14 not found - using the newest Python 3 instead.
    py -3 run_production.py
    goto :done
)
echo Python 3 was not found. Install Python 3.14 from https://www.python.org/downloads/
:done
pause
