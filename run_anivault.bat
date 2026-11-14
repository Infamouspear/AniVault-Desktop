@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
python -c "import importlib.util; assert all(importlib.util.find_spec(m) for m in ('vlc', 'PySide6', 'pypdfium2', 'rarfile', 'PIL'))" >nul 2>&1 || pip install -r requirements.txt
python main.py
if errorlevel 1 pause
