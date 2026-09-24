@echo off
setlocal
title MedBox - station locale (garder cette fenetre ouverte pendant la demo)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\demarrer.ps1"
if errorlevel 1 (
  echo.
  echo  MedBox ne s'est pas lance : lis les lignes ci-dessus, puis relance ce fichier.
  echo.
  pause
)
