@echo off
title YTBOT backend
cd /d "%~dp0"

REM 1) Put your Vercel site address here (no trailing slash):
set ALLOWED_ORIGIN=https://ytbotpro.vercel.app

REM 2) Install packages (first run takes a minute)
pip install -r requirements.txt

REM 3) Open the public tunnel in a second window
start "Cloudflare Tunnel" cmd /k cloudflared tunnel --url http://localhost:5000

REM 4) Start the backend
python app.py
pause
