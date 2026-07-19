@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_cloud_profile_e2e.ps1" %*
