@echo off
rem Double-click to open Blender Fox Transfer (needs Python from python.org)
cd /d "%~dp0"
where py >nul 2>nul && (py blender_fox_transfer.py %*) || (python blender_fox_transfer.py %*)
if errorlevel 1 pause
