@echo off
title Skantha WMS - Production Server
chcp 65001 > nul
cls
echo ======================================================================
echo  Launching Skantha WMS Enterprise Production Server (Waitress WSGI)
echo ======================================================================
echo.
python run_production.py
pause
