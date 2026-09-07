@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM One build. Onefile console exe + icon. First run unpacks data next to the exe.

where py >nul 2>&1
if %ERRORLEVEL%==0 (set PY=py -3) else (set PY=python)

echo Installing PyInstaller + pygame + numpy...
%PY% -m pip install -q --upgrade pip pyinstaller pygame numpy
if errorlevel 1 exit /b 1

if exist build rmdir /s /q build
if exist dist\RPS_Game.exe del /q dist\RPS_Game.exe

echo Compiling...
%PY% -m PyInstaller --noconfirm --clean --onefile --console ^
  --name RPS_Game ^
  --icon rps.ico ^
  --add-data "rps.ico;." ^
  --add-data "README.md;." ^
  --add-data "arena;arena" ^
  --add-data "strategies;strategies" ^
  --add-data "maths;maths" ^
  --add-data "optimizer;optimizer" ^
  --add-data "config.py;." ^
  --hidden-import pygame ^
  --hidden-import numpy ^
  --hidden-import strategies.playbook ^
  --hidden-import strategies.balance ^
  --hidden-import optimizer.engine ^
  --hidden-import optimizer.motion ^
  --hidden-import optimizer.mcts ^
  --hidden-import optimizer.logger ^
  --hidden-import app_paths ^
  --collect-all pygame ^
  game.py

if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)

echo.
echo Built: dist\RPS_Game.exe
echo Live:   dist\RPS_Game.exe
echo Learn:  dist\RPS_Game.exe /learn
echo Empty folder: drop the exe in, first run unpacks strategies arena optimizer *.md
endlocal
exit /b 0
