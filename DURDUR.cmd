@echo off
cd /d "%~dp0"
if not exist .runtime mkdir .runtime
echo stop>.runtime\stop-request
echo Yerel baslatma aracina durdurma istegi gonderildi.
echo Docker kullaniyorsan: docker compose stop
