@echo off
setlocal
title MedBox - demarrage de la demo
cd /d "%~dp0"
echo.
echo  MedBox : controle de la machine, puis lancement.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\preflight.ps1" -Bundle "%~dp0."
if errorlevel 1 goto :probleme
echo.
echo  Controle passe. Lancement dans 5 secondes.
rem ping, not timeout: timeout refuses to run without a console for input.
ping -n 6 127.0.0.1 >nul
start "" "%~dp0MedBox.exe"
echo.
echo  MedBox demarre : la page vaisseau s'ouvre dans le navigateur, la puce "assistant"
echo  passe a "pret" en moins d'une minute. Cette fenetre se ferme toute seule.
ping -n 13 127.0.0.1 >nul
exit /b 0

:probleme
echo.
echo  Le controle a trouve un probleme : lis les lignes ECHEC ci-dessus, corrige, puis
echo  relance ce fichier. Memoire vive : fermer Chrome, WhatsApp, Spotify, le VPN, et
echo  quitter Ollama dans la barre systeme (icone pres de l'horloge, clic droit, Quit).
echo.
pause
exit /b 1
