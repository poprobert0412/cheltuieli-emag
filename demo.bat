@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Demonstrația: același raport ca la o rulare reală, dar cu comenzi INVENTATE. Fără login, fără
rem cont eMAG, fără nicio citire de pe eMAG: ideal ca să vezi cum arată programul înainte să îl folosești.
rem Rescrie și interfata\assets\demo-data.js, cu același conținut la fiecare rulare.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
title Demonstrație Cheltuieli eMAG
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"

if not exist "ruleaza.py" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou demo.bat din folderul extras, nu din interiorul ZIP-ului.
  echo.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Programul nu este instalat încă. Rulează mai întâi instaleaza.bat, apoi încearcă din nou.
  echo.
  pause
  exit /b 1
)

echo.
echo Demonstrație cu comenzi inventate: nu se citește nimic din contul tău eMAG.
echo.
".venv\Scripts\python.exe" ruleaza.py --demo --deschide
set "COD=%ERRORLEVEL%"

echo.
if "%COD%"=="0" (
  echo Gata. Raportul demonstrativ s-a deschis în browser; fișierele lui sunt în folderul iesiri.
) else (
  echo Demonstrația s-a oprit cu o eroare. Citește mesajul de mai sus; jurnalul complet e în folderul logs.
)
echo.
pause
exit /b %COD%
