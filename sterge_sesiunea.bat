@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Șterge sesiunea eMAG salvată pe acest calculator, adică folderul .profil_browser.
rem Programul cere o confirmare înainte să șteargă; după ștergere trebuie să rulezi din nou login.bat.
rem Ștergerea o face programul Python, nu acest script, care nu are voie să șteargă nimic.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
rem Rândul care pornește Python e ULTIMUL din fișier și are pe el tot ce urmează (decis 5 oct. 2026, D13): o actualizare
rem poate înlocui acest fișier cât rulează Python, iar cmd l-ar citi mai departe de la o poziție greșită. Mesajul final și
rem pauza sunt în instalare\dupa_rulare.bat; «call exit /b» păstrează codul exact. Detalii în porneste.bat.
title Șterge sesiunea eMAG
rem Variabilele comune (unde stau Python-ul, pachetele și browserul descărcate): instalare\mediu.bat.
call ".\instalare\mediu.bat"

if not exist "ruleaza.py" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou sterge_sesiunea.bat din folderul extras, nu din interiorul ZIP-ului.
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
echo Urmează să ștergi sesiunea ta eMAG salvată pe acest calculator.
echo După aceea va trebui să te loghezi din nou, cu login.bat. Comenzile și rapoartele din iesiri nu se șterg.
echo.
".venv\Scripts\python.exe" ruleaza.py --sterge-sesiunea & call ".\instalare\dupa_rulare.bat" sterge_sesiunea %%ERRORLEVEL%% & call exit /b %%ERRORLEVEL%%
