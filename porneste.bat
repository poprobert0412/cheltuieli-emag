@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem Pornește programul pe Windows: dublu-clic pe acest fișier. Nu trebuie instalat Python.
rem Întâi termină o actualizare întreruptă, dacă a rămas una, apoi pregătește ce lipsește (instaleaza.bat: uv, Python, pachete,
rem browser; prima dată cam un minut, apoi o secundă), apoi pornește aplicația locală, doar pe acest calculator, și deschide
rem pagina ei în browser. Se oprește cu Ctrl+C sau din pagină.
rem Argumentele, dacă le dai, merg direct la ruleaza.py, de exemplu: porneste.bat --demo
rem Nu modifică nimic în afara acestui folder: datele rămân în iesiri, logs și .profil_browser, iar ce descarcă în .uv și .venv.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
rem Fără blocuri imbricate cu «exit /b» urmate de alte comenzi: pe unele versiuni de Windows codul de ieșire se pierde (devine 0).
rem Instalatorul se cheamă cu cale explicită (.\): unde Windows nu mai caută în folderul curent, «call instaleaza.bat» nu ar fi găsit.
rem ORDINEA, contract pentru versiunile instalate (decis 6 oct. 2026, P1): 1) recuperarea unei actualizări întrerupte, 2) pregătirea,
rem 3) programul. Cu .actualizare\jurnal.json și Python-ul din .venv, recuperarea rulează cu el (python -m emag_spend.update_recovery,
rem doar biblioteca standard) ÎNAINTEA lui instaleaza.bat, care altfel ar citi instalare\versiuni.txt și requirements.txt dintr-un
rem arbore amestecat (vechi + nou) și ar putea opri pornirea, de exemplu fără internet, înainte ca recuperarea să apuce să ruleze.
rem Fără .venv merge întâi pregătirea, iar recuperarea o face ruleaza.py. La codul 1 al recuperării lansatorul se oprește cu mesaj;
rem la orice alt cod pornește din nou porneste.bat, de la început (recuperarea poate să-l fi înlocuit, D13), o singură dată: cel
rem repornit primește semnul CHELTUIELI_EMAG_DUPA_RECUPERARE și nu mai încearcă recuperarea (un jurnal care nu se poate șterge
rem n-o reia la nesfârșit; o mai încearcă oricum ruleaza.py).
rem Rândurile care pornesc Python au pe ele tot ce urmează după Python (decis 5 oct. 2026, D12 și D13): cmd citește un .bat pe
rem bucăți, după poziție, iar o actualizare din aplicație sau o recuperare înlocuiește acest fișier cât rulează Python; un rând citit
rem după aceea ar veni din fișierul nou, de la o poziție greșită. Pe rândul programului, ULTIMUL din fișier: mesajul final și pauza
rem (instalare\dupa_rulare.bat), apoi, la codul 75 (settings.EXIT_CODE_RESTART: programul s-a actualizat), porneste.bat NOU,
rem citit de la început, care reface pregătirea; la final «call exit /b» cu codul exact (un «exit /b» simplu ar ieși cu 0).
title Cheltuieli eMAG
set "INSTALL_FAILED="
set "RECUPERARE_ESUATA="
rem Semnul pus de rândul recuperării pentru porneste.bat repornit imediat după ea; se golește aici, ca să nu ajungă la program.
set "DUPA_RECUPERARE=%CHELTUIELI_EMAG_DUPA_RECUPERARE%"
set "CHELTUIELI_EMAG_DUPA_RECUPERARE="

if not exist "ruleaza.py" (
  echo.
  echo EROARE: nu găsesc fișierele programului lângă acest script.
  echo Dacă ai descărcat un ZIP: clic dreapta pe el, alege Extract All - Extrage tot,
  echo apoi rulează din nou porneste.bat din folderul extras, nu din interiorul ZIP-ului.
  echo.
  pause
  exit /b 1
)
if not exist "instaleaza.bat" (
  echo.
  echo EROARE: nu găsesc instaleaza.bat lângă acest script.
  echo Extrage din nou tot folderul programului din ZIP, apoi rulează din nou porneste.bat.
  echo.
  pause
  exit /b 1
)
rem Mediul (Python fără __pycache__, cu UTF-8, uv și Playwright în .uv) se încarcă o dată, înaintea recuperării; instaleaza.bat
rem are setlocal propriu, deci nu îl schimbă pentru program.
call ".\instalare\mediu.bat"

rem 1) Recuperarea (P1), pe un singur rând: totul după Python stă aici, iar cmd nu mai citește nimic din fișier după ea.
if not defined DUPA_RECUPERARE if exist ".actualizare\jurnal.json" if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -m emag_spend.update_recovery & (if errorlevel 1 if not errorlevel 2 set "RECUPERARE_ESUATA=1") & (if defined RECUPERARE_ESUATA echo. & echo Pornirea s-a oprit: actualizarea întreruptă nu a putut fi desfăcută. Citește mesajul de mai sus, rezolvă cauza și dă din nou dublu-clic pe porneste.bat. & echo. & pause) & (if not defined RECUPERARE_ESUATA set "CHELTUIELI_EMAG_DUPA_RECUPERARE=1" & call ".\porneste.bat" %*) & call exit /b %%ERRORLEVEL%%

rem 2) Pregătirea.
call ".\instaleaza.bat" --fara-pauza
if errorlevel 1 set "INSTALL_FAILED=1"
if defined INSTALL_FAILED (
  echo.
  echo Pregătirea nu s-a terminat. Citește mesajul de mai sus, rezolvă cauza și dă din nou dublu-clic pe porneste.bat.
  echo.
  pause
  exit /b 1
)

rem 3) Programul. Fără argumente pornește aplicația; cu argumente le dă neschimbate lui ruleaza.py.
set "ARGUMENTE=--aplicatie"
if not "%~1"=="" set ARGUMENTE=%*
echo.
if "%~1"=="" echo Pornesc aplicația. Pagina se deschide în browser; lasă această fereastră deschisă cât o folosești.
echo.
".venv\Scripts\python.exe" ruleaza.py %ARGUMENTE% & call ".\instalare\dupa_rulare.bat" porneste %%ERRORLEVEL%% & (if errorlevel 75 if not errorlevel 76 call ".\porneste.bat" %*) & call exit /b %%ERRORLEVEL%%
