@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stress_pipeline_onboarding_alerts.ps1" %*
