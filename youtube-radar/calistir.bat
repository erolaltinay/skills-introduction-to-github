@echo off
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
echo YouTube Nis Radari baslatiliyor...
set /p KONU="Konu (bos birakirsan genel tarama): "
if "%KONU%"=="" (%PY% radar.py) else (%PY% radar.py --konu "%KONU%")
echo.
pause
