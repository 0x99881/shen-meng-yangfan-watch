@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist config.json (
  echo 找不到 config.json，请先复制 config.example.json 并完成配置。
  pause
  exit /b 1
)
python app.py
pause
