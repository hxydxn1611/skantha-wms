@echo off
title Skantha WMS - Production Server
chcp 65001 > nul
cls
echo ======================================================================
echo  Launching Skantha WMS Enterprise Production Server (Waitress WSGI)
echo ======================================================================
echo.
py -3.12 run_production.py
if errorlevel 1 (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" run_production.py
)
pause
