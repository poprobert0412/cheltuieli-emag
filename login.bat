@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Login, o singură dată: deschide browserul, te loghezi tu manual în eMAG, iar sesiunea rămâne
rem salvată local în .profil_browser. Parola și codul 2FA nu trec prin acest program.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
rem Rândul care pornește Python e ULTIMUL din fișier și are pe el tot ce urmează (decis 5 oct. 2026, D13): o actualizare
rem poate înlocui acest fișier cât rulează Python, iar cmd l-ar citi mai departe de la o poziție greșită. Mesajul final și
rem pauza sunt în instalare\dupa_rulare.bat; «call exit /b» păstrează codul exact. Detalii în porneste.bat.
title Login eMAG
rem Variabilele comune (unde stau Python-ul, pachetele și browserul descărcate): instalare\mediu.bat.
call ".\instalare\mediu.bat"

if not exist "ruleaza.py" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou login.bat din folderul extras, nu din interiorul ZIP-ului.
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
echo Se deschide o fereastră de browser. Loghează-te în contul tău eMAG: parola și codul 2FA le introduci tu.
echo Poți închide fereastra după ce apare mesajul de încheiere.
echo.
".venv\Scripts\python.exe" ruleaza.py --doar-login & call ".\instalare\dupa_rulare.bat" login %%ERRORLEVEL%% & call exit /b %%ERRORLEVEL%%
