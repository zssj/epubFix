@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

where pythonw.exe >nul 2>nul
if errorlevel 1 (
    python -m epubfix.gui
    if errorlevel 1 pause
) else (
    start "" pythonw.exe -m epubfix.gui
)
endlocal
