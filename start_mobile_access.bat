@echo off
title Skantha WMS - Mobile & Remote HTTPS Access
chcp 65001 > nul
cls
echo ======================================================================
echo  Launching Skantha WMS Mobile & Remote HTTPS Tunnel (Waitress + SSL)
echo ======================================================================
echo.
python run_mobile_access.py
pause
