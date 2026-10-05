@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Șterge sesiunea eMAG salvată pe acest calculator, adică folderul .profil_browser.
rem Programul cere o confirmare înainte să șteargă; după ștergere trebuie să rulezi din nou login.bat.
rem Ștergerea o face programul Python, nu acest script, care nu are voie să șteargă nimic.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
title Șterge sesiunea eMAG
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"

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
  echo Programul nu este instalat încă. Rulează mai întâi instaleaza.bat, apoi încearcă din nou.
  echo.
  pause
  exit /b 1
)

echo.
echo Urmează să ștergi sesiunea ta eMAG salvată pe acest calculator.
echo După aceea va trebui să te loghezi din nou, cu login.bat. Comenzile și rapoartele din iesiri nu se șterg.
echo.
".venv\Scripts\python.exe" ruleaza.py --sterge-sesiunea
set "COD=%ERRORLEVEL%"

echo.
if not "%COD%"=="0" (
  echo Sesiunea nu a fost ștearsă sau comanda s-a oprit cu o eroare. Citește mesajul de mai sus.
)
echo.
pause
exit /b %COD%
