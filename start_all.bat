@echo off
echo ================================================
echo   Starting F.R.I.D.A.I. - All Services
echo ================================================

echo Starting Cloudflare tunnel...
start "" /B "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel run fridai

echo Starting FRIDAI Brain (Flask backend)...
start "" /B cmd /c "cd /d C:\Users\Owner\VoiceClaude && C:\Python314\python.exe app.py"

echo Waiting for backend to initialize...
timeout /t 5 /nobreak >nul

echo Starting Discord Bot (Python 3.12)...
start "" /B cmd /c "cd /d C:\Users\Owner\VoiceClaude && C:\Users\Owner\VoiceClaude\discord_venv\Scripts\python.exe discord_bot.py"

echo ================================================
echo   F.R.I.D.A.I. is now running!
echo ================================================
echo.
echo Services:
echo   - Flask backend: http://localhost:5000
echo   - Public URL: https://fridai.fridai.me
echo   - Discord bot: Online
echo.
echo You can close this window - FRIDAI will keep running.
echo To stop: Open Task Manager and end python.exe processes
echo ================================================
pause
