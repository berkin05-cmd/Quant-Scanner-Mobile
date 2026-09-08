@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py") || (set "PY=python")
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :ERR
echo.
echo Quant Scanner sunucusu baslatiliyor...
echo Telefon ve bilgisayar ayni Wi-Fi'da olmali.
echo Bu pencere acik kalacak.
%PY% -m uvicorn server:app --host 0.0.0.0 --port 8000
exit /b 0
:ERR
echo Paket kurulumu basarisiz.
pause
