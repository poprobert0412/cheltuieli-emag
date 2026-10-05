@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Aplicația cu un singur buton: dacă lipsește mediul .venv, îl instalează singur (instaleaza.bat), apoi pornește serverul
rem local, doar pe acest calculator, și deschide pagina aplicației în browser. Se oprește cu Ctrl+C sau din pagină.
rem Nu modifică nimic în afara acestui folder: datele rămân în iesiri, logs și .profil_browser.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
rem Fără blocuri imbricate cu «exit /b» urmate de alte comenzi: pe unele versiuni de Windows codul de ieșire se pierde (devine 0).
rem Instalatorul se cheamă cu cale explicită (.\): unde Windows nu mai caută în folderul curent, «call instaleaza.bat» nu ar fi găsit.
title Cheltuieli eMAG
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "INSTALL_FAILED="

if not exist "ruleaza.py" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou porneste.bat din folderul extras, nu din interiorul ZIP-ului.
  echo.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" if not exist "instaleaza.bat" (
  echo.
  echo EROARE: programul nu e instalat și nu găsesc instaleaza.bat lângă acest script.
  echo Extrage din nou tot folderul programului din ZIP, apoi rulează din nou porneste.bat.
  echo.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Prima pornire: instalez ce lipsește. Se face o singură dată, durează 1-3 minute și are nevoie de internet.
  echo.
  call ".\instaleaza.bat" --fara-pauza
  if errorlevel 1 set "INSTALL_FAILED=1"
)
if defined INSTALL_FAILED (
  echo.
  echo Instalarea nu s-a terminat. Citește mesajul de mai sus, rezolvă cauza și dă din nou dublu-clic pe porneste.bat.
  echo.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo EROARE: după instalare tot nu găsesc mediul .venv. Rulează instaleaza.bat și citește mesajele lui.
  echo.
  pause
  exit /b 1
)

echo.
echo Pornesc aplicația. Pagina se deschide în browser; lasă această fereastră deschisă cât o folosești.
echo.
".venv\Scripts\python.exe" ruleaza.py --aplicatie
set "COD=%ERRORLEVEL%"

echo.
if "%COD%"=="0" (
  echo Aplicația s-a oprit. Rezultatele rămân în folderul iesiri.
) else (
  echo Aplicația s-a oprit cu o eroare. Citește mesajul de mai sus; jurnalul complet e în folderul logs.
)
echo.
pause
exit /b %COD%
