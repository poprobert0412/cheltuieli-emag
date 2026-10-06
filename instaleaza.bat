@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Pregătirea programului pe Windows. O cheamă porneste.bat la fiecare pornire: prima dată durează cam un minut,
rem apoi o secundă, fiindcă nu reface nimic din ce e deja gata. Nu trebuie instalat Python.
rem 1) descarcă uv, instalatorul de Python, în versiunea din instalare\versiuni.txt și îl folosește doar dacă amprenta
rem    SHA-256 a arhivei se potrivește cu cea scrisă acolo; o arhivă rămasă cu altă amprentă se descarcă o dată din nou;
rem    după dezarhivare șterge arhivele uv din .uv\descarcari;
rem 2) creează .venv cu Python-ul fixat și instalează requirements.txt, din nou doar când se schimbă cerințele;
rem 3) dacă nu găsește Edge sau Chrome, descarcă o singură dată Chromium-ul lui Playwright.
rem Folosește doar unelte din Windows 10/11 (curl.exe, tar.exe, certutil.exe din System32). Nu cere drepturi de
rem administrator și nu scrie în afara acestui folder: tot ce descarcă stă în .uv\ și .venv\.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete. Mesajele de eroare nu conțin
rem paranteze sau & | < >, fiindcă se afișează prin variabile.
title Pregătire Cheltuieli eMAG
set "NO_PAUSE="
if /i "%~1"=="--fara-pauza" set "NO_PAUSE=1"
rem Lungimea maximă a căii acestui folder. Windows nu încarcă un fișier .pyd dacă calea lui întreagă are 260 de caractere sau mai multe,
rem iar cel mai lung .pyd încărcat din .venv are 63 de caractere după rădăcina folderului (greenlet, măsurat la 5 oct. 2026).
rem 259 (maximul) - 63 - 6 (marjă pentru nume viitoare) = 190.
set "MAX_FOLDER_PATH=190"
set "SYS=%SystemRoot%\System32"
set "FAIL="
set "LUCRU="

if not exist "requirements.txt" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou porneste.bat din folderul extras, nu din interiorul ZIP-ului.
  echo.
  if not defined NO_PAUSE pause
  exit /b 1
)
call ".\instalare\mediu.bat"

call set "PREA_LUNG=%%CD:~%MAX_FOLDER_PATH%,1%%"
if defined PREA_LUNG set "FAIL=calea acestui folder e prea lungă, peste %MAX_FOLDER_PATH% de caractere. Windows nu poate porni programele dacă o cale întreagă ajunge la 260 de caractere. Mută folderul programului mai aproape de rădăcina discului, de exemplu în C:\cheltuieli-emag, și pornește din nou de acolo."

rem Versiunile fixate: UV_VERSION, PYTHON_VERSION și amprentele SHA256_* din instalare\versiuni.txt.
if not defined FAIL for /f "usebackq eol=# tokens=1,* delims==" %%a in ("instalare\versiuni.txt") do set "%%a=%%b"
if not defined FAIL if not defined UV_VERSION set "FAIL=lipsește instalare\versiuni.txt sau e incomplet. Extrage din nou tot folderul programului din ZIP."

set "ARH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "ARH=%PROCESSOR_ARCHITEW6432%"
set "UV_TINTA="
if /i "%ARH%"=="AMD64" set "UV_TINTA=x86_64-pc-windows-msvc"
if /i "%ARH%"=="AMD64" set "UV_AMPRENTA=%SHA256_WINDOWS_X64%"
if /i "%ARH%"=="ARM64" set "UV_TINTA=aarch64-pc-windows-msvc"
if /i "%ARH%"=="ARM64" set "UV_AMPRENTA=%SHA256_WINDOWS_ARM64%"
if not defined FAIL if not defined UV_TINTA set "FAIL=procesorul acestui calculator, %ARH%, nu e suportat. Programul merge pe Windows de 64 de biți, x64 sau ARM64."

rem 1) uv, exact în versiunea fixată: se descarcă doar dacă lipsește sau are altă versiune.
set "UV=%CD%\.uv\bin\uv.exe"
set "UV_ACTUAL="
if not defined FAIL if exist "%UV%" for /f "usebackq tokens=2" %%v in (`"%UV%" --version 2^>nul`) do set "UV_ACTUAL=%%v"
set "NEED_UV="
if not defined FAIL if not "%UV_ACTUAL%"=="%UV_VERSION%" set "NEED_UV=1"
rem Arhiva păstrată are și versiunea lui uv în nume: una rămasă de la alt UV_VERSION, de exemplu după o actualizare a
rem programului, nu e luată drept cea nouă și nu dă o alarmă falsă de amprentă (decis 6 oct. 2026, N12).
set "UV_ARHIVA=%CD%\.uv\descarcari\uv-%UV_VERSION%-%UV_TINTA%.zip"
if defined NEED_UV echo.
if defined NEED_UV echo Prima pornire: descarc uv %UV_VERSION%, instalatorul de Python, o singură dată...
if defined NEED_UV set "LUCRU=1"
if defined NEED_UV if not exist "%CD%\.uv\descarcari" mkdir "%CD%\.uv\descarcari"
if defined NEED_UV if not exist "%CD%\.uv\bin" mkdir "%CD%\.uv\bin"
rem O arhivă rămasă de la o pornire anterioară, de exemplu o descărcare întreruptă, care nu are amprenta oficială se șterge
rem și se descarcă o singură dată din nou; abia o arhivă proaspăt descărcată cu altă amprentă oprește pregătirea (N12).
set "GASIT="
if defined NEED_UV if not defined FAIL if exist "%UV_ARHIVA%" for /f "skip=1 tokens=*" %%h in ('%SYS%\certutil.exe -hashfile "%UV_ARHIVA%" SHA256') do if not defined GASIT set "GASIT=%%h"
if defined GASIT set "GASIT=%GASIT: =%"
if defined NEED_UV if not defined FAIL if exist "%UV_ARHIVA%" if /i not "%GASIT%"=="%UV_AMPRENTA%" del /q "%UV_ARHIVA%"
if defined NEED_UV if not defined FAIL if not exist "%UV_ARHIVA%" %SYS%\curl.exe --proto =https --tlsv1.2 -fsSL --retry 3 -o "%UV_ARHIVA%" "https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/uv-%UV_TINTA%.zip"
if defined NEED_UV if not defined FAIL if not exist "%UV_ARHIVA%" set "FAIL=nu am putut descărca uv. Verifică legătura la internet, sau dacă un antivirus ori firewall blochează github.com, și pornește din nou."
set "GASIT="
if defined NEED_UV if not defined FAIL for /f "skip=1 tokens=*" %%h in ('%SYS%\certutil.exe -hashfile "%UV_ARHIVA%" SHA256') do if not defined GASIT set "GASIT=%%h"
if defined GASIT set "GASIT=%GASIT: =%"
rem O arhivă care nu are exact amprenta oficială se șterge și nu se folosește: poate fi stricată la descărcare sau modificată.
if defined NEED_UV if not defined FAIL if /i not "%GASIT%"=="%UV_AMPRENTA%" del /q "%UV_ARHIVA%"
if defined NEED_UV if not defined FAIL if /i not "%GASIT%"=="%UV_AMPRENTA%" set "FAIL=arhiva uv descărcată nu are amprenta SHA-256 așteptată. Am șters-o și NU o folosesc. Încearcă din nou mai târziu; dacă se repetă, deschide o problemă pe GitHub, fără date personale."
set "UV_DEZARHIVAT="
if defined NEED_UV if not defined FAIL %SYS%\tar.exe -xf "%UV_ARHIVA%" -C "%CD%\.uv\bin" uv.exe && set "UV_DEZARHIVAT=1"
if defined NEED_UV if not defined FAIL if not exist "%UV%" set "FAIL=nu am putut dezarhiva uv. Un antivirus poate bloca fișierul .uv\bin\uv.exe; verifică-l și pornește din nou."
rem După o dezarhivare reușită nu mai e nevoie de nicio arhivă uv: se șterg toate uv-* din .uv\descarcari, și cea tocmai
rem folosită, și cele rămase de la alte versiuni (decis 6 oct. 2026, P9). del cu tipar șterge doar fișiere, nu foldere, și nu
rem intră în legături; ce nu se poate șterge acum rămâne, fără să oprească pregătirea.
if defined UV_DEZARHIVAT if not defined FAIL del /q "%CD%\.uv\descarcari\uv-*"

rem 2) .venv cu Python-ul fixat, creat din nou doar dacă lipsește, e stricat (de exemplu după mutarea folderului) sau are alt
rem    Python decât PYTHON_VERSION, comparat ca major.minor: o versiune nouă a programului poate trece la alt Python
rem    (decis 5 oct. 2026, D15). Versiunea fixată ajunge la Python ca argument, nu lipită în codul lui.
set "PY=%CD%\.venv\Scripts\python.exe"
set "VENV_BUN="
if not defined FAIL if exist "%PY%" "%PY%" -c "import sys, playwright, bs4, lxml.etree; raise SystemExit('.'.join(map(str, sys.version_info[:2])) != '.'.join(sys.argv[1].split('.')[:2]))" %PYTHON_VERSION% >nul 2>&1 && set "VENV_BUN=1"
if not defined FAIL if not defined VENV_BUN echo.
if not defined FAIL if not defined VENV_BUN echo Pregătesc Python %PYTHON_VERSION% și pachetele programului. Prima dată durează cam un minut și are nevoie de internet...
if not defined FAIL if not defined VENV_BUN set "LUCRU=1"
set "VENV_FACUT="
if not defined FAIL if not defined VENV_BUN "%UV%" venv --quiet --clear --python %PYTHON_VERSION% "%CD%\.venv" && set "VENV_FACUT=1"
if not defined FAIL if not defined VENV_BUN if not defined VENV_FACUT set "FAIL=nu am putut pregăti Python %PYTHON_VERSION%. Verifică legătura la internet și pornește din nou."
if not defined FAIL if not defined VENV_BUN if exist "%CD%\.venv\cerinte.sha256" del /q "%CD%\.venv\cerinte.sha256"

rem Pachetele se instalează din nou doar când s-a schimbat requirements.txt: amprenta lui se ține în .venv\cerinte.sha256.
rem --only-binary: doar pachete gata făcute, deci niciun cod de instalare (setup.py) de pe internet nu rulează pe calculator.
set "CERINTE="
if not defined FAIL for /f "skip=1 tokens=*" %%h in ('%SYS%\certutil.exe -hashfile "%CD%\requirements.txt" SHA256') do if not defined CERINTE set "CERINTE=%%h"
if defined CERINTE set "CERINTE=%CERINTE: =%"
set "INSTALAT="
if not defined FAIL if exist "%CD%\.venv\cerinte.sha256" set /p INSTALAT=<"%CD%\.venv\cerinte.sha256"
set "PIP_OK="
if not defined FAIL if /i not "%INSTALAT%"=="%CERINTE%" set "LUCRU=1"
if not defined FAIL if /i not "%INSTALAT%"=="%CERINTE%" "%UV%" pip install --quiet --only-binary :all: --python "%PY%" -r "%CD%\requirements.txt" && set "PIP_OK=1"
if not defined FAIL if /i not "%INSTALAT%"=="%CERINTE%" if not defined PIP_OK set "FAIL=instalarea pachetelor a eșuat. Cauze frecvente: fără internet sau un antivirus ori firewall care blochează pypi.org. Rezolvă cauza și pornește din nou."
if not defined FAIL if /i not "%INSTALAT%"=="%CERINTE%" "%PY%" -c "import playwright, bs4, lxml.etree, greenlet, pyee, soupsieve, typing_extensions" >nul 2>&1 || set "FAIL=pachetele s-au instalat, dar nu pot fi încărcate. Șterge folderul .venv și pornește din nou."
if not defined FAIL if /i not "%INSTALAT%"=="%CERINTE%" >"%CD%\.venv\cerinte.sha256" echo %CERINTE%

rem 3) Un browser pe care programul îl poate controla: Edge sau Chrome, altfel Chromium descărcat o singură dată în .uv\browsere.
if not defined FAIL if not exist "%CD%\.uv\browser.ok" "%PY%" -m emag_spend.browser_check && type nul >"%CD%\.uv\browser.ok"
if not defined FAIL if not exist "%CD%\.uv\browser.ok" set "LUCRU=1"
if not defined FAIL if not exist "%CD%\.uv\browser.ok" echo Descarc o singură dată Chromium pentru program, aproximativ 150 MB...
if not defined FAIL if not exist "%CD%\.uv\browser.ok" "%PY%" -m playwright install chromium && "%PY%" -m emag_spend.browser_check && type nul >"%CD%\.uv\browser.ok"
rem Lipsa browserului nu oprește pornirea: demonstrația și rapoartele vechi merg și fără; citirea contului spune atunci ce lipsește.
if not defined FAIL if not exist "%CD%\.uv\browser.ok" echo.
if not defined FAIL if not exist "%CD%\.uv\browser.ok" echo ATENȚIE: nu pot porni niciun browser, deci programul nu va putea citi contul eMAG; demonstrația merge.
if not defined FAIL if not exist "%CD%\.uv\browser.ok" echo Ce faci: instalează Microsoft Edge sau Google Chrome și pornește din nou.

if defined FAIL echo.
if defined FAIL echo EROARE: %FAIL%
if defined FAIL echo.
if defined FAIL if not defined NO_PAUSE pause
if defined FAIL exit /b 1

if defined LUCRU echo.
if defined LUCRU echo Pregătirea s-a terminat: programul e gata.
if not defined NO_PAUSE echo.
if not defined NO_PAUSE echo Ce urmează: dublu-clic pe porneste.bat. Vrei doar să vezi cum arată? demo.bat folosește comenzi inventate, fără login.
if not defined NO_PAUSE echo.
if not defined NO_PAUSE pause
exit /b 0
