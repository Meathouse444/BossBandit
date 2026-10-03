@echo off
rem Double-click to run BossBandit right now and open today's posting kit.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m pip install --upgrade --quiet yt-dlp
.venv\Scripts\bossbandit.exe doctor
if errorlevel 1 goto end
.venv\Scripts\bossbandit.exe run
.venv\Scripts\bossbandit.exe open
:end
pause
