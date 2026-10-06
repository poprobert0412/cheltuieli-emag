@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Demonstrația: același raport ca la o rulare reală, dar cu comenzi INVENTATE. Fără login, fără
rem cont eMAG, fără nicio citire de pe eMAG: ideal ca să vezi cum arată programul înainte să îl folosești.
rem Rescrie și interfata\assets\demo-data.js, cu același conținut la fiecare rulare.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
rem Rândul care pornește Python e ULTIMUL din fișier și are pe el tot ce urmează (decis 5 oct. 2026, D13): o actualizare
rem poate înlocui acest fișier cât rulează Python, iar cmd l-ar citi mai departe de la o poziție greșită. Mesajul final și
rem pauza sunt în instalare\dupa_rulare.bat; «call exit /b» păstrează codul exact. Detalii în porneste.bat.
title Demonstrație Cheltuieli eMAG
rem Variabilele comune (unde stau Python-ul, pachetele și browserul descărcate): instalare\mediu.bat.
call ".\instalare\mediu.bat"

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
  echo Programul nu este pregătit încă. Dă mai întâi dublu-clic pe porneste.bat: pregătește singur tot ce lipsește.
  echo.
  pause
  exit /b 1
)

echo.
echo Demonstrație cu comenzi inventate: nu se citește nimic din contul tău eMAG.
echo.
".venv\Scripts\python.exe" ruleaza.py --demo --deschide & call ".\instalare\dupa_rulare.bat" demo %%ERRORLEVEL%% & call exit /b %%ERRORLEVEL%%
