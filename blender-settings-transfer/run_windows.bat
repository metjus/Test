@echo off
rem Double-click to open Blender Settings Transfer (needs Python from python.org)
cd /d "%~dp0"
where py >nul 2>nul && (py blender_settings_transfer.py %*) || (python blender_settings_transfer.py %*)
if errorlevel 1 pause
