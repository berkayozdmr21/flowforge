@echo off
setlocal
cd /d "%~dp0"
docker compose up -d --build
if errorlevel 1 goto failed
echo Servisler baslatildi. Tarayicida http://127.0.0.1:9030 adresini ac.
echo Durdurmak icin: docker compose stop
pause
exit /b 0
:failed
echo Docker Desktop calisiyor olmali. Hata metnini kontrol et.
pause
exit /b 1
