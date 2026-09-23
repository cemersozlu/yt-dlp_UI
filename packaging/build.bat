@echo off
cd /d "%~dp0\.."

echo Installing required packages...
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo Building exe...
python -m PyInstaller --noconfirm --clean --windowed --onefile --name "yt-dlp_UI" ^
  --distpath "dist" --workpath "build\pyinstaller" --specpath "packaging" ^
  --icon "..\web\assets\icon.ico" ^
  --add-data "..\web;web" ^
  --collect-all webview ^
  --hidden-import flask ^
  --hidden-import werkzeug ^
  --hidden-import jinja2 ^
  --hidden-import server ^
  --paths "..\app" ^
  app\main.py

echo.
if exist "dist\yt-dlp_UI.exe" (
  echo OK: dist\yt-dlp_UI.exe
) else (
  echo ERROR: exe was not created.
)
pause