@echo off
rem Daily BossBandit job (Task Scheduler runs this). Logs go to data\daily.log
cd /d "%~dp0.."
if not exist data mkdir data
echo ==== %date% %time% ==== >> data\daily.log
rem Twitch changes things often; keeping yt-dlp fresh prevents most download failures.
.venv\Scripts\python.exe -m pip install --upgrade --quiet yt-dlp >> data\daily.log 2>&1
.venv\Scripts\bossbandit.exe run >> data\daily.log 2>&1
