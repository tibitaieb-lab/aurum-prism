@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Suivez README.md pour installer Python 3.12 et les dependances dans .venv.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -I -B "%~dp0tools\demo.py"
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "%~dp0reports\public-demo\review.html"
