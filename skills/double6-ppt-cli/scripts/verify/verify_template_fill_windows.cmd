@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 verify_template_fill.py %*) || (python verify_template_fill.py %*)
echo.
pause
