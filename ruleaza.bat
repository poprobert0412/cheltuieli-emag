@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Rularea completă: citește comenzile și retururile din contul tău eMAG, calculează cât ai
rem cheltuit efectiv și deschide raportul. Rezultatele apar în iesiri\, jurnalul în logs\.
rem Opțiunile din linia de comandă se transmit mai departe, de exemplu: ruleaza.bat --prag 1000
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
title Cheltuieli eMAG
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"

if not exist "ruleaza.py" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou ruleaza.bat din folderul extras, nu din interiorul ZIP-ului.
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
echo Pornesc calculul. Se deschide browserul; dacă nu ești logat, rulează întâi login.bat.
echo Citirea comenzilor poate dura câteva minute: nu închide fereastra.
echo.
".venv\Scripts\python.exe" ruleaza.py --deschide %*
set "COD=%ERRORLEVEL%"

echo.
if "%COD%"=="0" (
  echo Gata. Raportul s-a deschis în browser; toate fișierele rulării sunt în folderul iesiri.
) else (
  echo Rularea s-a oprit cu o eroare. Citește mesajul de mai sus; jurnalul complet e în folderul logs.
)
echo.
pause
exit /b %COD%
