@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Rularea completă: citește comenzile și retururile din contul tău eMAG, calculează cât ai
rem cheltuit efectiv și deschide raportul. Rezultatele apar în iesiri\, jurnalul în logs\.
rem Opțiunile din linia de comandă se transmit mai departe, de exemplu: ruleaza.bat --prag 1000
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
rem Rândul care pornește Python e ULTIMUL din fișier și are pe el tot ce urmează (decis 5 oct. 2026, D13): o actualizare
rem poate înlocui acest fișier cât rulează Python, iar cmd l-ar citi mai departe de la o poziție greșită. Mesajul final și
rem pauza sunt în instalare\dupa_rulare.bat; «call exit /b» păstrează codul exact. Detalii în porneste.bat.
title Cheltuieli eMAG
rem Variabilele comune (unde stau Python-ul, pachetele și browserul descărcate): instalare\mediu.bat.
call ".\instalare\mediu.bat"

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
  echo Programul nu este pregătit încă. Dă mai întâi dublu-clic pe porneste.bat: pregătește singur tot ce lipsește.
  echo.
  pause
  exit /b 1
)

echo.
echo Pornesc calculul. Se deschide browserul; dacă nu ești logat, rulează întâi login.bat.
echo Citirea comenzilor poate dura câteva minute: nu închide fereastra.
echo.
".venv\Scripts\python.exe" ruleaza.py --deschide %* & call ".\instalare\dupa_rulare.bat" ruleaza %%ERRORLEVEL%% & call exit /b %%ERRORLEVEL%%
