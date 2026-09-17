@echo off
chcp 65001 > nul
title Meen Yaarifni Aktar - Public Link
cd /d "%~dp0"
set PYTHONUTF8=1

where py > nul 2>&1
if %errorlevel%==0 goto runpy

where python > nul 2>&1
if %errorlevel%==0 goto runpython

echo.
echo   Python is not installed on this PC.
echo   Download it from https://www.python.org/downloads/
echo.
pause
exit /b

:runpy
py -3 share.py
goto done

:runpython
python share.py

:done
echo.
pause
