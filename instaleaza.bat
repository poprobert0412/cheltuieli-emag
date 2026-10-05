@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Instalare, o singură dată: creează mediul izolat .venv în acest folder și instalează în el
rem doar pachetele din requirements.txt, apoi verifică dacă se pot importa.
rem Nu modifică nimic în afara acestui folder: nu scrie în Registry, în AppData sau în folderul personal.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
title Instalare Cheltuieli eMAG
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
rem Argumentul --fara-pauza (îl pune porneste.bat) sare peste pause și peste mesajul „Ce urmează”: scriptul care îl cheamă continuă singur.
set "NO_PAUSE="
if /i "%~1"=="--fara-pauza" set "NO_PAUSE=1"
rem Lungimea maximă a căii acestui folder. Windows nu încarcă un fișier .pyd dacă calea lui întreagă are 260 de caractere sau mai multe,
rem iar cel mai lung .pyd încărcat din .venv are 63 de caractere după rădăcina folderului (greenlet, măsurat la 5 oct. 2026).
rem 259 (maximul) - 63 - 6 (marjă pentru nume viitoare, de ex. cp315t) = 190.
set "MAX_FOLDER_PATH=190"

if not exist "requirements.txt" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou instaleaza.bat din folderul extras, nu din interiorul ZIP-ului.
  echo.
  if not defined NO_PAUSE pause
  exit /b 1
)

echo.
echo === Instalare Cheltuieli eMAG ===
echo.
echo Caut Python 3.10 sau mai nou...

set "PYTHON_CMD="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 3)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 3)" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo.
  echo EROARE: nu am găsit Python 3.10 sau mai nou ^(sau cel instalat e prea vechi^).
  echo.
  echo Ce faci:
  echo   1. Deschide https://www.python.org/downloads/ și descarcă ultima versiune de Python 3.
  echo   2. Pornește instalatorul și BIFEAZĂ căsuța Add python.exe to PATH, jos, înainte de Install Now.
  echo   3. Când se termină, închide această fereastră și dă din nou dublu-clic pe instaleaza.bat.
  echo.
  if not defined NO_PAUSE pause
  exit /b 1
)
%PYTHON_CMD% --version
%PYTHON_CMD% -c "import os; raise SystemExit(0 if len(os.getcwd()) <= %MAX_FOLDER_PATH% else 4)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo EROARE: calea acestui folder e prea lungă ^(peste %MAX_FOLDER_PATH% de caractere^).
  echo Windows nu poate porni programele instalate dacă o cale întreagă ajunge la 260 de caractere.
  echo Ce faci: mută folderul programului mai aproape de rădăcina discului, de exemplu în C:\cheltuieli-emag,
  echo apoi dă din nou dublu-clic pe instaleaza.bat din folderul nou.
  echo.
  if not defined NO_PAUSE pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  echo Mediul .venv există deja, îl reutilizez.
) else (
  echo Creez mediul izolat .venv în acest folder...
  %PYTHON_CMD% -m venv ".venv"
  if errorlevel 1 (
    echo.
    echo EROARE: nu am putut crea mediul .venv. Verifică mesajul de mai sus.
    echo Dacă folderul acesta e într-un loc protejat, mută folderul programului pe Desktop sau în Documente.
    echo.
    if not defined NO_PAUSE pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 3)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo EROARE: mediul .venv e stricat sau a fost făcut cu un Python mai vechi de 3.10.
  echo Șterge folderul .venv din Explorer ^(clic dreapta, Delete^) și rulează din nou instaleaza.bat.
  echo.
  if not defined NO_PAUSE pause
  exit /b 1
)

echo.
echo Instalez pachetele din requirements.txt. Au nevoie de internet; durează 1-3 minute...
rem --no-cache-dir: pip nu scrie memoria lui în AppData; --only-binary: doar pachete gata făcute, fără cod de instalare rulat local.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements.txt
if errorlevel 1 (
  echo.
  echo EROARE: instalarea pachetelor a eșuat. Citește mesajul de mai sus.
  echo Cauze frecvente: fără internet, un antivirus sau firewall care blochează pypi.org,
  echo sau o versiune de Python foarte nouă, pentru care pachetele nu au încă fișiere gata făcute.
  echo Programul a fost testat cu Python 3.13 și 3.14. Rezolvă cauza și rulează din nou instaleaza.bat.
  echo.
  if not defined NO_PAUSE pause
  exit /b 1
)

echo.
echo Verific pachetele instalate...
".venv\Scripts\python.exe" -c "import playwright, bs4, lxml.etree, greenlet, pyee, soupsieve, typing_extensions"
if errorlevel 1 (
  echo.
  echo EROARE: pachetele s-au instalat, dar nu pot fi încărcate. Rulează din nou instaleaza.bat.
  echo Dacă eroarea se repetă, șterge folderul .venv din Explorer și rulează instaleaza.bat încă o dată.
  echo.
  if not defined NO_PAUSE pause
  exit /b 1
)

echo.
echo ================================================================
echo  Instalarea s-a terminat cu succes.
echo ================================================================
echo.
if not defined NO_PAUSE (
  echo Ce urmează:
  echo   1. login.bat   - o singură dată: te loghezi în contul tău eMAG, în fereastra care se deschide.
  echo   2. ruleaza.bat - calculează cât ai cheltuit; raportul se deschide singur în browser.
  echo.
  echo Vrei să vezi mai întâi cum arată? demo.bat folosește comenzi inventate, fără login.
  echo.
)
if not defined NO_PAUSE pause
exit /b 0
