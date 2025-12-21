@echo off
title FRIDAI Server
cd /d C:\Users\Owner\VoiceClaude

echo Starting F.R.I.D.A.I...
echo.

:: Start FRIDAI Flask server
start "FRIDAI" /min python app.py

:: Wait for Flask to start
timeout /t 5 /nobreak > nul

:: Start Cloudflare Tunnel (permanent)
start "Cloudflare Tunnel" /min "C:\Program Files (x86)\cloudflared\cloudflared.exe" --config "C:\Users\Owner\.cloudflared\config.yml" tunnel run fridai

echo ========================================
echo   F.R.I.D.A.I. is running!
echo ========================================
echo.
echo   Local:  http://localhost:5000
echo   Public: https://fridai.fridai.me
echo.
echo   (This window will close in 5 seconds)
timeout /t 5
