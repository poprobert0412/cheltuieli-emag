@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Login, o singură dată: deschide browserul, te loghezi tu manual în eMAG, iar sesiunea rămâne
rem salvată local în .profil_browser. Parola și codul 2FA nu trec prin acest program.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
title Login eMAG
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"

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
  echo Programul nu este instalat încă. Rulează mai întâi instaleaza.bat, apoi încearcă din nou.
  echo.
  pause
  exit /b 1
)

echo.
echo Se deschide o fereastră de browser. Loghează-te în contul tău eMAG: parola și codul 2FA le introduci tu.
echo Poți închide fereastra după ce apare mesajul de încheiere.
echo.
".venv\Scripts\python.exe" ruleaza.py --doar-login
set "COD=%ERRORLEVEL%"

echo.
if "%COD%"=="0" (
  echo Gata: sesiunea ta eMAG e salvată pe acest calculator, în folderul .profil_browser.
  echo Tratează acel folder ca pe o parolă: nu îl trimite nimănui.
  echo Pasul următor: ruleaza.bat
) else (
  echo Login-ul nu s-a încheiat cu succes. Citește mesajul de mai sus, apoi rulează din nou login.bat.
)
echo.
pause
exit /b %COD%
