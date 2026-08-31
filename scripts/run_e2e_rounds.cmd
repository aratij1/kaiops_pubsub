@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_e2e_rounds.ps1" %*
